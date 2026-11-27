"""Evaluation batch runner: runs the fixed evaluation inputs through the app's own
pipelines and stores each run with an `eval` block (EVALUATION_PLAN §2.9, §2.11).

    .venv/bin/python -m evaluation.run_batch --arm M1 --set main --dry-run
    .venv/bin/python -m evaluation.run_batch --arm M1 --set main --limit 5
    .venv/bin/python -m evaluation.run_batch --arm M2 --set ask_gold --only q01,q02

Sets (inputs are fixed files in evaluation/):
    main          the 20 in-scope queries of assess_sample.csv, once per arm (repeat 0)
    out_of_scope  the 8 out-of-scope queries (o01-o08), once per arm
    stability     c02, c03, s04, s08, repeats 1-3 per arm (the main run is repeat 0; Q7)
    graph_off     the 20 in-scope queries with the D11 switch on; M1 only (D2)
    ask_gold      the 35 Ask the Graph gold questions; the gold query's rows are stored too

Arms (§2.11; METHODOLOGY_NOTES M1-M3). The same model plays both LLM roles:
    M1  openai     gpt-5.2
    M2  deepseek   deepseek-flash (DeepSeek-V4.1-Flash), open weights, through DeepSeek's API; thinking mode off
    M3  anthropic  claude-sonnet-5-5
Parts-list candidates always use the OpenAI embedding model (R26), whatever the arm.

Output: runs/evaluation/assess/, runs/evaluation/ask/ and runs/evaluation/manifest.csv.

Rules:
- A run is never repeated to get a better answer (§2.5). A (set, query, arm, repeat)
  already in the manifest is skipped, whatever its status, so the batch can be resumed
  across days.
- Exception: a run that failed because the service could not be used (bad key, rate
  limit, connection refused, provider overloaded; see INFRA_ERRORS) says nothing about
  the model. It is kept and listed with `infra_error`, the batch stops, and the next
  invocation runs it again. A rejected request (BadRequestError, HTTP 400) is treated the
  same way: the model produced nothing, and the cause is usually a setting to fix first.
- A run stopped with Ctrl-C is neither saved nor listed (the runner saves a run only once
  it has finished), so it runs again next time.
- The working tree must be clean (runs/ aside) unless --allow-dirty, so every run can be
  traced to a commit. The commit and the dirty flag are stored either way.
- Nothing here changes what an LLM sees: the pipelines are called exactly as the app
  calls them.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

from webapp.backend.config import (
    CANDIDATE_MIN_SCORE, CANDIDATE_TOP_K, CYPHER_MAX_TOKENS, CYPHER_TIMEOUT_S, EMBEDDING_MODEL,
    LLM_MAX_RETRIES, REPO_ROOT, REPORT_MAX_TOKENS, REPORT_TIMEOUT_S, RUNS_DIR,
)
from webapp.backend.llm_factory import model_kwargs
from webapp.backend.runs_store import now_iso, save_run

EVAL_DIR = Path(__file__).resolve().parent
SAMPLE = EVAL_DIR / "assess_sample.csv"
GOLD = EVAL_DIR / "ask_gold_set.csv"
OUT_DIR = RUNS_DIR / "evaluation"

SETS = ("main", "out_of_scope", "stability", "graph_off", "ask_gold")
STABILITY_QUERIES = ("c02", "c03", "s04", "s08")
STABILITY_REPEATS = (1, 2, 3)

MANIFEST_COLUMNS = [
    "run_id", "file", "set", "query_id", "arm", "graph_off", "repeat", "commit", "dirty", "models",
    "as_of_date", "date_mode", "status", "total_tokens", "infra_error", "finished_at",
]

# Exception class names (the start of a run's `error`) that mean the service could not
# be used. These say nothing about the model, so such runs are run again later.
INFRA_ERRORS = (
    "AuthenticationError", "PermissionDeniedError", "RateLimitError", "APIConnectionError",
    "NotFoundError", "InternalServerError", "OverloadedError", "ServiceUnavailableError",
    "ConnectError", "ConnectionError", "ConnectionRefusedError", "ServiceUnavailable", "BadRequestError",
)


@dataclass(frozen=True)
class Arm:
    name: str
    provider: str
    model: str
    key_env: str | None


def arm_for(name: str) -> Arm:
    if name == "M1":
        return Arm("M1", "openai", "gpt-5.2", "OPENAI_API_KEY")
    if name == "M2":
        return Arm("M2", "deepseek", "deepseek-flash", "DEEPSEEK_API_KEY")
    if name == "M3":
        return Arm("M3", "anthropic", "claude-sonnet-5-5", "ANTHROPIC_API_KEY")
    raise SystemExit(f"Unknown arm {name!r}: use M1, M2 or M3")


# ------------------------------------------------------------------------------ the plan


@dataclass
class Job:
    set: str
    query_id: str
    repeat: int
    graph_off: bool = False
    items: list[dict[str, Any]] = field(default_factory=list)  # assess
    goal: str | None = None
    as_of_date: str | None = None
    date_mode: str | None = None
    gold: dict[str, str] | None = None  # ask_gold

    @property
    def kind(self) -> str:
        return "ask" if self.set == "ask_gold" else "assess"


def read_sample(path: Path = SAMPLE) -> dict[str, dict[str, Any]]:
    """query_id -> {set, goal, as_of_date, date_mode, items}, in file order."""
    queries: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            q = queries.setdefault(row["query_id"], {
                "set": row["set"], "goal": row["goal"], "as_of_date": row["as_of_date"],
                "date_mode": row["date_mode"], "items": [],
            })
            for key in ("set", "goal", "as_of_date", "date_mode"):
                if q[key] != row[key]:
                    raise ValueError(f"{row['query_id']}: rows disagree on {key}")
            q["items"].append({
                "n": int(row["n"]),
                "text": row["item_text"],
                "source": row["source"],
                "product_id": row["product_id"] or None,
            })
    for qid, q in queries.items():
        q["items"].sort(key=lambda it: it["n"])
        if [it["n"] for it in q["items"]] != list(range(1, len(q["items"]) + 1)):
            raise ValueError(f"{qid}: item numbers must run 1..n")
    return queries


def read_gold(path: Path = GOLD) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _assess_job(set_name: str, qid: str, q: dict[str, Any], repeat: int = 0, graph_off: bool = False) -> Job:
    items = [{k: it[k] for k in ("text", "source", "product_id")} for it in q["items"]]
    return Job(set_name, qid, repeat, graph_off, items, q["goal"], q["as_of_date"], q["date_mode"])


def plan_jobs(set_name: str, sample: dict[str, dict[str, Any]], gold: list[dict[str, str]]) -> list[Job]:
    if set_name == "ask_gold":
        return [Job("ask_gold", g["id"], 0, gold=g) for g in gold]
    if set_name in ("main", "out_of_scope"):
        return [_assess_job(set_name, qid, q) for qid, q in sample.items() if q["set"] == set_name]
    if set_name == "stability":
        missing = [qid for qid in STABILITY_QUERIES if qid not in sample]
        if missing:
            raise ValueError(f"stability queries missing from the sample: {missing}")
        return [_assess_job("stability", qid, sample[qid], r) for qid in STABILITY_QUERIES for r in STABILITY_REPEATS]
    if set_name == "graph_off":
        return [_assess_job("graph_off", qid, q, graph_off=True) for qid, q in sample.items() if q["set"] == "main"]
    raise ValueError(f"unknown set {set_name!r}")


# ------------------------------------------------------------------------------ manifest


def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def done_keys(rows: list[dict[str, str]]) -> set[tuple[str, str, str, int]]:
    """Runs that count: every listed run except those stopped by an infrastructure error."""
    return {(r["set"], r["query_id"], r["arm"], int(r["repeat"])) for r in rows if not r.get("infra_error")}


def append_manifest(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.is_file()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in MANIFEST_COLUMNS})


def infra_error(run: dict[str, Any]) -> str:
    err = run.get("error") or ""
    name = err.split(":", 1)[0].strip()
    return name if name in INFRA_ERRORS else ""


# ------------------------------------------------------------------------------ provenance


def git_state(root: Path = REPO_ROOT) -> tuple[str, bool]:
    """HEAD commit and whether tracked or new files differ from it (runs/ is ignored)."""
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", ".", ":(exclude)runs"], cwd=root, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    return commit, bool(status.strip())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _temperature(llm: Any) -> Any:
    return getattr(llm, "temperature", None)


def eval_block(
    job: Job, arm: Arm, *, commit: str, dirty: bool, input_file: Path, input_sha: str,
    cypher_llm: Any, report_llm: Any, served: list[str],
) -> dict[str, Any]:
    extra = model_kwargs(arm.provider, max_tokens=0, timeout=0).get("extra_body")
    block: dict[str, Any] = {
        "set": job.set,
        "query_id": job.query_id,
        "arm": arm.name,
        "repeat": job.repeat,
        "graph_off": job.graph_off,
        "commit": commit,
        "dirty": dirty,
        "provider": arm.provider,
        "model_requested": arm.model,
        "models_served": served,  # model names the provider reported in its replies
        "request_extra": extra,  # sent with every request, e.g. DeepSeek's thinking switch
        "temperature": {
            "cypher": _temperature(cypher_llm),
            "report": _temperature(report_llm) if job.kind == "assess" else None,
            "note": "not set by the app: each model runs at its provider default (None = default)",
        },
        "limits": {
            "cypher_max_tokens": CYPHER_MAX_TOKENS, "cypher_timeout_s": CYPHER_TIMEOUT_S,
            "report_max_tokens": REPORT_MAX_TOKENS, "report_timeout_s": REPORT_TIMEOUT_S,
            "max_retries": LLM_MAX_RETRIES,
        },
        "input_file": str(input_file.relative_to(REPO_ROOT)) if input_file.is_relative_to(REPO_ROOT) else str(input_file),
        "input_sha256": input_sha,
        "runner": "evaluation.run_batch",
        "recorded_at": now_iso(),
    }
    if job.kind == "assess":
        block["retrieval"] = {"embedding_model": EMBEDDING_MODEL, "top_k": CANDIDATE_TOP_K, "min_score": CANDIDATE_MIN_SCORE}
    return block


# ------------------------------------------------------------------------------ one run


def gold_result(client: Any, gold: dict[str, str]) -> dict[str, Any]:
    """The gold query's rows, through the same read-only check as Ask (check_gold_set)."""
    from webapp.backend.ask.pipeline import check_cypher, run_query

    cypher = (gold.get("reference_cypher") or "").strip()
    out: dict[str, Any] = {k: gold.get(k) for k in ("id", "template", "question", "reference_cypher", "compare", "status")}
    if not cypher:
        out["result"] = None
        return out
    if gold.get("compare") == "refusal":
        # Proof query for an unanswerable question: shows the graph has no such data.
        res = run_query(client, cypher)
    else:
        check = check_cypher(client, cypher)
        out["check"] = check.to_dict()
        res = run_query(client, check.cypher) if check.ok else {"ok": False, "error": " ".join(check.problems)}
    res = {k: v for k, v in res.items() if k != "graph"}  # rows are what is compared
    out["result"] = res
    return out


async def run_job(
    job: Job, arm: Arm, *, client: Any, db: Any, view: Any, cypher_llm: Any, report_llm: Any,
    embedder: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """One run through the app's pipeline. Returns the finished run (not yet saved)."""
    run: dict[str, Any] | None = None
    if job.kind == "ask":
        from webapp.backend.ask.pipeline import ask

        async for ev in ask(job.gold["question"], client=client, llm=cypher_llm, model_name=arm.model, runs_dir=None):
            if ev["event"] == "done":
                run = ev["run"]
        assert run is not None
        run["gold"] = await asyncio.to_thread(gold_result, client, job.gold)
        return run

    from webapp.backend.pipeline.assess import assess

    async for ev in assess(
        mode="parts",
        items=job.items,
        goal=job.goal,
        as_of=date.fromisoformat(job.as_of_date),
        date_mode=job.date_mode,
        rerun_of=None,
        client=client,
        db=db,
        view=view,
        cypher_llm=cypher_llm,
        report_llm=report_llm,
        runs_dir=None,
        cypher_model=arm.model,
        report_model=arm.model,
        graph_off=job.graph_off,
        embedder=embedder,
    ):
        if ev["event"] == "done":
            run = ev["run"]
    assert run is not None
    return run


def manifest_row(run: dict[str, Any], path: Path, job: Job, arm: Arm, commit: str, dirty: bool, out_dir: Path) -> dict[str, Any]:
    models = run.get("models") or {"cypher": run.get("model")}
    return {
        "run_id": run["run_id"],
        "file": str(path.relative_to(out_dir)),
        "set": job.set,
        "query_id": job.query_id,
        "arm": arm.name,
        "graph_off": int(job.graph_off),
        "repeat": job.repeat,
        "commit": commit,
        "dirty": int(dirty),
        "models": ";".join(f"{k}={v}" for k, v in models.items() if v),
        "as_of_date": job.as_of_date or "",
        "date_mode": job.date_mode or "",
        "status": run.get("status"),
        "total_tokens": (run.get("usage") or {}).get("total_tokens", ""),
        "infra_error": infra_error(run),
        "finished_at": run.get("finished_at"),
    }


async def run_batch(
    jobs: list[Job], arm: Arm, *, out_dir: Path, client: Any, db: Any, view: Any, cypher_llm: Any, report_llm: Any,
    commit: str, dirty: bool, embedder: Callable[[str], Any] | None = None,
    limit: int | None = None, token_budget: int | None = None, log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run the jobs not yet in the manifest, in order. Returns a small summary."""
    manifest = out_dir / "manifest.csv"
    done = done_keys(read_manifest(manifest))
    todo = [j for j in jobs if (j.set, j.query_id, arm.name, j.repeat) not in done]
    if limit is not None:
        todo = todo[:limit]
    hashes = {"assess": (SAMPLE, sha256(SAMPLE)), "ask": (GOLD, sha256(GOLD))}
    summary = {"planned": len(jobs), "skipped": len(jobs) - len([j for j in jobs if (j.set, j.query_id, arm.name, j.repeat) not in done]),
               "ran": 0, "tokens": 0, "stopped": None, "runs": []}
    for i, job in enumerate(todo, start=1):
        if token_budget is not None and summary["tokens"] >= token_budget:
            summary["stopped"] = f"token budget {token_budget} reached"
            break
        started = time.perf_counter()
        run = await run_job(job, arm, client=client, db=db, view=view, cypher_llm=cypher_llm, report_llm=report_llm, embedder=embedder)
        input_file, input_sha = hashes[job.kind]
        served = sorted(((run.get("usage") or {}).get("by_model") or {}).keys())
        run["eval"] = eval_block(
            job, arm, commit=commit, dirty=dirty, input_file=input_file, input_sha=input_sha,
            cypher_llm=cypher_llm, report_llm=report_llm, served=served,
        )
        path = save_run(out_dir / job.kind, run)
        row = manifest_row(run, path, job, arm, commit, dirty, out_dir)
        append_manifest(manifest, row)
        tokens = int(row["total_tokens"] or 0)
        summary["ran"] += 1
        summary["tokens"] += tokens
        summary["runs"].append(row)
        log(f"[{i}/{len(todo)}] {job.set} {job.query_id} r{job.repeat} {arm.name}: {row['status']}, "
            f"{tokens} tokens, {time.perf_counter() - started:.0f} s -> {row['file']}")
        if row["infra_error"]:
            summary["stopped"] = f"{row['infra_error']}: {run.get('error')}"
            log(f"Stopped: the service could not be used ({summary['stopped'][:300]}). "
                "The run is listed with infra_error and will run again next time.")
            break
    return summary


# ------------------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", required=True, choices=["M1", "M2", "M3"])
    ap.add_argument("--set", required=True, choices=SETS, dest="set_name")
    ap.add_argument("--only", help="comma-separated query or gold ids")
    ap.add_argument("--limit", type=int, help="run at most this many new runs")
    ap.add_argument("--token-budget", type=int, help="stop before a new run once this batch has used this many tokens")
    ap.add_argument("--dry-run", action="store_true", help="list what would run; call nothing")
    ap.add_argument("--allow-dirty", action="store_true", help="run with uncommitted changes (recorded as dirty)")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    arm = arm_for(args.arm)
    if args.set_name == "graph_off" and arm.name != "M1":
        raise SystemExit("graph_off (D2) is run with M1 only (EVALUATION_PLAN §2.10)")
    jobs = plan_jobs(args.set_name, read_sample(), read_gold())
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        unknown = wanted - {j.query_id for j in jobs}
        if unknown:
            raise SystemExit(f"not in set {args.set_name}: {sorted(unknown)}")
        jobs = [j for j in jobs if j.query_id in wanted]

    done = done_keys(read_manifest(args.out / "manifest.csv"))
    todo = [j for j in jobs if (j.set, j.query_id, arm.name, j.repeat) not in done]
    if args.limit is not None:
        todo = todo[: args.limit]
    commit, dirty = git_state()
    print(f"{arm.name} ({arm.provider} {arm.model}) · set {args.set_name}: {len(jobs)} planned, "
          f"{len(jobs) - len([j for j in jobs if (j.set, j.query_id, arm.name, j.repeat) not in done])} already in the manifest, "
          f"{len(todo)} to run · commit {commit[:10]}{' (dirty)' if dirty else ''}")
    if args.dry_run:
        for j in todo:
            extra = f" {j.as_of_date} {j.date_mode} {len(j.items)} item(s)" if j.kind == "assess" else f" {j.gold['template']}"
            print(f"  {j.set} {j.query_id} r{j.repeat}{' graph_off' if j.graph_off else ''}{extra}")
        return 0
    if not todo:
        return 0
    if dirty and not args.allow_dirty:
        raise SystemExit("The working tree has uncommitted changes. Commit first, or pass --allow-dirty (recorded in every run).")

    needs_openai = any(j.kind == "assess" and not j.graph_off for j in todo)  # R26 embeddings
    for env in {arm.key_env, "OPENAI_API_KEY" if needs_openai else None} - {None}:
        if not os.getenv(env):
            raise SystemExit(f"{env} is not set in .env")

    from supplier_risk_engine.loader import load_database
    from webapp.backend.ask.llm import make_cypher_llm
    from webapp.backend.evidence_api import EvidenceView
    from webapp.backend.neo4j_client import ReadOnlyNeo4j
    from webapp.backend.pipeline.llm import make_report_llm

    client = ReadOnlyNeo4j()
    client.verify()
    db = load_database()
    try:
        summary = asyncio.run(run_batch(
            jobs, arm, out_dir=args.out, client=client, db=db, view=EvidenceView(db),
            cypher_llm=make_cypher_llm(arm.model, arm.provider), report_llm=make_report_llm(arm.model, arm.provider),
            commit=commit, dirty=dirty, limit=args.limit, token_budget=args.token_budget,
        ))
    except KeyboardInterrupt:
        print("Interrupted: the unfinished run was not saved or listed; it runs again next time.")
        return 130
    finally:
        client.close()
    print(f"Done: {summary['ran']} run(s), {summary['tokens']} tokens."
          + (f" Stopped early: {summary['stopped'][:300]}" if summary["stopped"] else ""))
    return 1 if summary["stopped"] and "budget" not in summary["stopped"] else 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    raise SystemExit(main())
