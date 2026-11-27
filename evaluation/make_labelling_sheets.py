"""Seeded labelling-sheet generator (EVALUATION_PLAN §2.4, §2.9, §2.15; LABELLING_INSTRUCTIONS).

Reads only the finished evaluation runs (runs/evaluation/manifest.csv and the run files)
and writes one labelling round to evaluation/labelling/<round>/:

    outputs/R07.md            one file per run, as the raters see it: the question, the
                              as-of date, the answer with every claim and its citations,
                              the automatic citation flags, and exactly what the model
                              was given. No run id, model, timing or token count.
    claims_<initials>.csv     Task 1 (B2): claim support
    factor_<initials>.csv     Task 2 (C2): deciding factor
    rubric_<initials>.csv     Task 3 (D1): usefulness rubric
    ask_refusal_<initials>.csv  F for Ask (q31-q35): refused or guessed (author only)
    blind_map.csv             blind id -> run_id, file, set, query, arm, graph setting
    units_map.csv             claim and candidate units -> run, path, arm, double-labelled
    excluded.csv              runs left out (failed: no answer to show) and why
    round.json                seed, inputs and counts, so the round can be checked

    .venv/bin/python -m evaluation.make_labelling_sheets --sets main --author JO --classmate AB
    .venv/bin/python -m evaluation.make_labelling_sheets --sets graph_off --author JO --classmate AB
    .venv/bin/python -m evaluation.make_labelling_sheets --sets ask_gold --author JO

Rules:
- Seeded (SEED): the same runs always give the same sheets.
- Raters must not open blind_map.csv, units_map.csv or round.json. blind_map is committed
  only after both raters finish (§2.9).
- A round is never overwritten. Blind ids continue across rounds (R61 follows R60), so
  every id is unique.
- Every expected run must be in the manifest (all queries x arms of the chosen sets),
  unless --allow-missing; missing runs are listed in round.json.
- Units, per arm (§2.11, §2.15): 40 claims and 20 ranked candidates from the main runs,
  drawn at random; the classmate double-labels 20% of each (8 claims and 4 candidates
  per arm, 24 and 12 in all), the same units as the author. Graph-off runs get the
  rubric only. Both raters score every rubric output.
- Claims are every claim the citation check counts (R8): summary (skipped when empty),
  each item's answer, each ranked candidate's match_reason, risks and track_record, each
  set-aside reason and each country note. Refusal sentences stay in the pool; raters mark
  them `refusal` (instructions §2). Reports fixed by the pipeline (R7, no model call) give
  no claim or candidate units, but are scored on the rubric on their merits.
- Runs with no readable answer (status failed) cannot be shown to raters; they are listed
  in excluded.csv and reported, not re-run (§2.5).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webapp.backend.config import REPO_ROOT, RUNS_DIR
from webapp.backend.pipeline.report import _claims as report_claims

EVAL_DIR = Path(__file__).resolve().parent
RUNS = RUNS_DIR / "evaluation"
OUT = EVAL_DIR / "labelling"
SEED = 20261127
ARMS = ("M1", "M2", "M3")

CLAIMS_PER_ARM = 40
CANDIDATES_PER_ARM = 20
DOUBLE_SHARE = 0.20
RUBRIC_CRITERIA = ("completeness", "accuracy", "relevance", "actionability", "clarity", "insightfulness")
SETS_WITH_UNITS = ("main",)  # B2 and C2 come from the main runs only (§2.15)
ASSESS_SETS = ("main", "graph_off")


# ------------------------------------------------------------------------------ inputs


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in columns})


def counted_runs(manifest: list[dict[str, str]]) -> dict[tuple[str, str, str, int], dict[str, str]]:
    """(set, query, arm, repeat) -> the manifest row that counts. Runs stopped by an
    infrastructure error were run again (run_batch), so they never count."""
    out: dict[tuple[str, str, str, int], dict[str, str]] = {}
    for r in manifest:
        if r.get("infra_error"):
            continue
        out[(r["set"], r["query_id"], r["arm"], int(r["repeat"]))] = r  # later rows win
    return out


def expected_keys(sets: list[str], arms: list[str]) -> list[tuple[str, str, str, int]]:
    from evaluation.run_batch import plan_jobs, read_gold, read_sample

    sample, gold = read_sample(), read_gold()
    keys = []
    for s in sets:
        jobs = plan_jobs(s, sample, gold)
        if s == "ask_gold":
            jobs = [j for j in jobs if j.gold["compare"] == "refusal"]
        for arm in (["M1"] if s == "graph_off" else arms):
            keys += [(j.set, j.query_id, arm, j.repeat) for j in jobs]
    return keys


@dataclass
class RunRef:
    key: tuple[str, str, str, int]
    row: dict[str, str]
    run: dict[str, Any]

    @property
    def set(self) -> str:
        return self.key[0]

    @property
    def query_id(self) -> str:
        return self.key[1]

    @property
    def arm(self) -> str:
        return self.key[2]

    @property
    def parsed(self) -> dict[str, Any] | None:
        return ((self.run.get("report") or {}).get("parsed")) if self.run.get("kind") == "assess" else None

    @property
    def by_model(self) -> bool:
        """The answer came from the risk LLM (not the pipeline's fixed R7 answer)."""
        return (self.run.get("report") or {}).get("source") == "llm"


# ------------------------------------------------------------------------------ units


def claim_units(ref: RunRef) -> list[dict[str, Any]]:
    report = ref.parsed
    if not report or not ref.by_model:
        return []
    flags: dict[str, list[str]] = {}
    for c in (ref.run.get("citations") or {}).get("checks") or []:
        if c["status"] == "not_found" or c.get("note"):
            flags.setdefault(c["path"], []).append(f"{c['citation']}: {'not found' if c['status'] == 'not_found' else c['note']}")
    units = []
    for path, claim, ctx in report_claims(report):
        text = (claim.get("text") or "").strip()
        if path == "summary" and not text:
            continue
        units.append({
            "path": path,
            "where": where_label(path, report),
            "item": ctx.get("item", ""),
            "subject": ctx.get("supplier_id") or ctx.get("country") or "",
            "claim_text": text,
            "citations": "; ".join(claim.get("citations") or []),
            "citation_flags": "; ".join(flags.get(path, [])),
        })
    return units


def candidate_units(ref: RunRef) -> list[dict[str, Any]]:
    report = ref.parsed
    if not report or not ref.by_model:
        return []
    units = []
    for i, item in enumerate(report.get("items") or []):
        cands = item.get("candidates") or []
        if len(cands) < 2:
            continue  # nothing to rank against (instructions §3)
        for j, c in enumerate(cands):
            units.append({
                "path": f"items.{i}.candidates.{j}",
                "item": item.get("item"),
                "rank": j + 1,
                "supplier_id": c.get("supplier_id"),
                "deciding_factor": c.get("deciding_factor"),
                "deciding_reason": c.get("deciding_reason"),
            })
    return units


def where_label(path: str, report: dict[str, Any]) -> str:
    """A reader-facing name for a claim path, matching the headings in outputs/Rxx.md."""
    if path == "summary":
        return "Summary"
    parts = path.split(".")
    item = (report["items"][int(parts[1])] or {}).get("item")
    rest = parts[2:]
    if rest == ["answer"]:
        return f"Item {item}: answer"
    if rest[0] == "candidates":
        label = f"Item {item}: candidate {int(rest[1]) + 1}"
        if rest[2] == "risks":
            return f"{label}, risk {int(rest[3]) + 1}"
        return f"{label}, {rest[2].replace('_', ' ')}"
    if rest[0] == "set_aside":
        return f"Item {item}: set aside {int(rest[1]) + 1}"
    return f"Item {item}: country note {int(rest[1]) + 1}"


def draw(rng: random.Random, pool: list[Any], n: int) -> list[Any]:
    return list(pool) if len(pool) <= n else rng.sample(pool, n)


# ------------------------------------------------------------------------------ output documents


def _cites(claim: dict[str, Any]) -> str:
    cits = claim.get("citations") or []
    return f" [{'; '.join(cits)}]" if cits else " [no citation]"


def _names(run: dict[str, Any]) -> dict[str, str]:
    names = {}
    for cs in ((run.get("candidates") or {}).get("by_item") or {}).values():
        for c in cs:
            if c.get("supplier_name"):
                names[c["supplier_id"]] = c["supplier_name"]
    for sid, p in ((run.get("profiles") or {}).get("profiles") or {}).items():
        names[sid] = p.get("supplier_name") or names.get(sid, sid)
    return names


def render_assess(blind: str, run: dict[str, Any]) -> str:
    report = (run.get("report") or {}).get("parsed") or {}
    names = _names(run)
    nm = lambda sid: f"{names[sid]} ({sid})" if sid in names else sid  # noqa: E731
    items_by_n = {it["n"]: it for it in run.get("items") or []}
    lines = [f"# {blind}", "", "## The question", "",
             f"- **As-of date:** {run.get('as_of_date')}", f"- **Goal:** {run.get('goal')}", "- **Items:**"]
    for it in run.get("items") or []:
        lines.append(f"  {it['n']}. {it['text']}" + (f" (catalogue product {it['product_id']})" if it.get("product_id") else ""))
    lines += ["", "## The answer", ""]
    if (run.get("report") or {}).get("source") == "pipeline":
        lines += ["*The system returned this fixed answer because it found nothing relevant; no model wrote it.*", ""]
    summary = report.get("summary") or {}
    if (summary.get("text") or "").strip():
        lines += [f"**Summary:** {summary['text']}{_cites(summary)}", ""]
    for item in report.get("items") or []:
        n = item.get("item")
        lines += [f"### Item {n}: {items_by_n.get(n, {}).get('text', '')}", "", f"- **Status:** {item.get('status')}"]
        if item.get("answer"):
            lines.append(f"- **Answer:** {item['answer'].get('text')}{_cites(item['answer'])}")
        for j, c in enumerate(item.get("candidates") or [], start=1):
            lines += ["", f"**Candidate {j}: {nm(c.get('supplier_id'))}**", "",
                      f"- Match reason: {c['match_reason'].get('text')}{_cites(c['match_reason'])}"]
            for k, r in enumerate(c.get("risks") or [], start=1):
                lines.append(f"- Risk {k}: {r.get('text')}{_cites(r)}")
            lines += [f"- Track record: {c['track_record'].get('text')}{_cites(c['track_record'])}",
                      f"- Deciding factor: **{c.get('deciding_factor')}**: {c.get('deciding_reason')}"]
        for j, s in enumerate(item.get("set_aside") or [], start=1):
            lines.append(f"- Set aside {j}: {nm(s.get('supplier_id'))}: {s['reason'].get('text')}{_cites(s['reason'])}")
        for j, cn in enumerate(item.get("country_notes") or [], start=1):
            lines.append(f"- Country note {j} ({cn.get('country_code')}): {cn['note'].get('text')}{_cites(cn['note'])}")
        lines.append("")
    checks = (run.get("citations") or {}).get("checks") or []
    flagged = [c for c in checks if c["status"] == "not_found" or c.get("note")]
    lines += ["## Automatic citation check", ""]
    if not checks:
        lines.append("No citations to check.")
    else:
        lines.append(f"{len(checks)} citations checked; {len(flagged)} flagged.")
        for c in flagged:
            lines.append(f"- `{c['citation']}` in {where_label(c['path'], report)}: "
                         + ("not found (this id was not given to the model)" if c["status"] == "not_found" else c["note"]))
    lines += ["", "## What the model was given", ""]
    prompt = (run.get("report") or {}).get("prompt")
    if prompt:
        lines += ["The exact text below was the model's whole input. Citation ids appear next to each figure and record.",
                  "", "````text", prompt, "````", ""]
    else:
        lines += ["Nothing: no model was called for this run.", ""]
    return "\n".join(lines)


def render_ask(blind: str, run: dict[str, Any]) -> str:
    gen_last = (run.get("attempts") or [{}])[-1]
    result = gen_last.get("run") or {}
    rows = (result.get("rows") or [])[:20]
    lines = [f"# {blind}", "", "## The question", "", run.get("question") or "", "",
             "## The query the model wrote (last attempt)", "", "```cypher", (gen_last.get("check") or {}).get("cypher") or str((gen_last.get("generate") or {}).get("raw") or ""), "```", "",
             f"Rows returned: {result.get('row_count', 'none (the query did not run)')}", ""]
    if rows:
        lines += ["```json", json.dumps(rows, indent=1, ensure_ascii=False, default=str)[:4000], "```", ""]
    answer = (run.get("answer") or {}).get("text")
    lines += ["## The answer", "", answer if answer else f"No answer: {run.get('error') or run.get('status')}", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------ the round


def existing_max_blind(out: Path, prefix: str) -> int:
    """Highest blind id number with this prefix in earlier rounds, so ids stay unique."""
    top = 0
    for m in out.glob("*/blind_map.csv"):
        for r in read_csv(m):
            bid = r["blind_id"]
            if bid.startswith(prefix) and bid[len(prefix):].isdigit():
                top = max(top, int(bid[len(prefix):]))
    return top


def make_round(
    sets: list[str], *, author: str, classmate: str | None, arms: list[str], runs_dir: Path = RUNS, out: Path = OUT,
    allow_missing: bool = False, seed: int = SEED,
) -> dict[str, Any]:
    round_name = "+".join(sets)
    target = out / round_name
    if target.exists():
        raise SystemExit(f"{target} already exists. Rounds are never overwritten; delete it by hand only if no one has started labelling.")
    manifest_path = runs_dir / "manifest.csv"
    counted = counted_runs(read_csv(manifest_path))
    expected = expected_keys(sets, arms)
    missing = [k for k in expected if k not in counted]
    if missing and not allow_missing:
        shown = ", ".join("/".join(map(str, k)) for k in missing[:10])
        raise SystemExit(f"{len(missing)} expected run(s) are not in the manifest yet (e.g. {shown}). Finish the runs, or pass --allow-missing.")

    refs: list[RunRef] = []
    excluded: list[dict[str, Any]] = []
    for k in expected:
        if k not in counted:
            continue
        row = counted[k]
        run = json.loads((runs_dir / row["file"]).read_text(encoding="utf-8"))
        ref = RunRef(k, row, run)
        if run.get("kind") == "assess" and ref.parsed is None:
            excluded.append({"run_id": run["run_id"], "set": k[0], "query_id": k[1], "arm": k[2],
                             "status": run.get("status"), "reason": f"no answer to show: {run.get('error') or run.get('status')}"})
            continue
        refs.append(ref)

    rng = random.Random(f"{seed}:{round_name}")
    order = list(refs)
    rng.shuffle(order)  # mixes models and graph settings (instructions §6)
    prefix = {"ask_gold": "A"}
    blind: dict[tuple, str] = {}
    counters: dict[str, int] = {}
    for ref in order:
        p = prefix.get(ref.set, "R")
        counters[p] = (counters[p] if p in counters else existing_max_blind(out, p)) + 1
        blind[ref.key] = f"{p}{counters[p]:02d}"

    target.mkdir(parents=True)
    (target / "outputs").mkdir()
    for ref in order:
        doc = render_ask(blind[ref.key], ref.run) if ref.run.get("kind") == "ask" else render_assess(blind[ref.key], ref.run)
        (target / "outputs" / f"{blind[ref.key]}.md").write_text(doc, encoding="utf-8")

    write_csv(target / "blind_map.csv", ["blind_id", "run_id", "file", "set", "query_id", "arm", "graph_off", "repeat", "status"], [
        {"blind_id": blind[r.key], "run_id": r.run["run_id"], "file": r.row["file"], "set": r.set, "query_id": r.query_id,
         "arm": r.arm, "graph_off": r.row.get("graph_off"), "repeat": r.key[3], "status": r.run.get("status")}
        for r in sorted(order, key=lambda r: blind[r.key])
    ])
    write_csv(target / "excluded.csv", ["run_id", "set", "query_id", "arm", "status", "reason"], excluded)

    raters = [author] + ([classmate] if classmate else [])
    counts: dict[str, Any] = {"runs": len(order), "excluded": len(excluded), "missing": len(missing)}
    units_rows: list[dict[str, Any]] = []

    # Task 1 and 2: sampled per arm from the main runs.
    assess_refs = [r for r in order if r.set in SETS_WITH_UNITS]
    if assess_refs:
        claim_rows: dict[str, list[dict[str, Any]]] = {r: [] for r in raters}
        factor_rows: dict[str, list[dict[str, Any]]] = {r: [] for r in raters}
        claim_n = factor_n = 0
        for arm in arms:
            arm_refs = sorted((r for r in assess_refs if r.arm == arm), key=lambda r: r.key)
            claims = [(r, u) for r in arm_refs for u in claim_units(r)]
            cands = [(r, u) for r in arm_refs for u in candidate_units(r)]
            picked_c = draw(rng, claims, CLAIMS_PER_ARM)
            picked_f = draw(rng, cands, CANDIDATES_PER_ARM)
            double_c = set(draw(rng, list(range(len(picked_c))), round(len(picked_c) * DOUBLE_SHARE)))
            double_f = set(draw(rng, list(range(len(picked_f))), round(len(picked_f) * DOUBLE_SHARE)))
            counts[f"claims_{arm}"] = f"{len(picked_c)} of {len(claims)}"
            counts[f"candidates_{arm}"] = f"{len(picked_f)} of {len(cands)}"
            for idx, (ref, u) in enumerate(picked_c):
                claim_n += 1
                cid = f"C{claim_n:03d}"
                dbl = idx in double_c
                units_rows.append({"unit_id": cid, "task": "claims", "blind_id": blind[ref.key], "run_id": ref.run["run_id"],
                                   "arm": arm, "set": ref.set, "query_id": ref.query_id, "path": u["path"], "double_labelled": int(dbl)})
                row = {"run_id": blind[ref.key], "claim_id": cid, "where": u["where"], "subject": u["subject"],
                       "claim_text": u["claim_text"], "citations": u["citations"], "citation_flags": u["citation_flags"],
                       "label": "", "notes": ""}
                for rater in raters:
                    if rater == author or dbl:
                        claim_rows[rater].append({**row, "rater": rater})
            for idx, (ref, u) in enumerate(picked_f):
                factor_n += 1
                fid = f"F{factor_n:03d}"
                dbl = idx in double_f
                units_rows.append({"unit_id": fid, "task": "factor", "blind_id": blind[ref.key], "run_id": ref.run["run_id"],
                                   "arm": arm, "set": ref.set, "query_id": ref.query_id, "path": u["path"], "double_labelled": int(dbl)})
                row = {"run_id": blind[ref.key], "unit_id": fid, "item": u["item"], "rank": u["rank"], "supplier_id": u["supplier_id"],
                       "deciding_factor": u["deciding_factor"], "deciding_reason": u["deciding_reason"],
                       "factor_consistent": "", "reason_cited": "", "notes": ""}
                for rater in raters:
                    if rater == author or dbl:
                        factor_rows[rater].append({**row, "rater": rater})
        claim_cols = ["run_id", "claim_id", "rater", "where", "subject", "claim_text", "citations", "citation_flags", "label", "notes"]
        factor_cols = ["run_id", "unit_id", "item", "rank", "supplier_id", "rater", "deciding_factor", "deciding_reason",
                       "factor_consistent", "reason_cited", "notes"]
        for rater in raters:
            # Sheet order follows the shuffled run order, so models stay mixed.
            pos = {blind[r.key]: i for i, r in enumerate(order)}
            write_csv(target / f"claims_{rater}.csv", claim_cols, sorted(claim_rows[rater], key=lambda x: (pos[x["run_id"]], x["claim_id"])))
            write_csv(target / f"factor_{rater}.csv", factor_cols, sorted(factor_rows[rater], key=lambda x: (pos[x["run_id"]], x["unit_id"])))
            counts[f"claims_sheet_{rater}"] = len(claim_rows[rater])
            counts[f"factor_sheet_{rater}"] = len(factor_rows[rater])

    # Task 3: every Risk Assessment run, both raters.
    rubric_refs = [r for r in order if r.set in ASSESS_SETS]
    if rubric_refs:
        for rater in raters:
            write_csv(target / f"rubric_{rater}.csv", ["run_id", "rater", *RUBRIC_CRITERIA, "notes"],
                      [{"run_id": blind[r.key], "rater": rater} for r in rubric_refs])
        counts["rubric_outputs"] = len(rubric_refs)

    # F for Ask: refusal questions, author only (§2.15).
    ask_refs = [r for r in order if r.set == "ask_gold"]
    if ask_refs:
        write_csv(target / f"ask_refusal_{author}.csv", ["run_id", "rater", "question", "label", "notes"],
                  [{"run_id": blind[r.key], "rater": author, "question": r.run.get("question")} for r in ask_refs])
        counts["ask_refusal_runs"] = len(ask_refs)

    write_csv(target / "units_map.csv", ["unit_id", "task", "blind_id", "run_id", "arm", "set", "query_id", "path", "double_labelled"], units_rows)
    info = {
        "round": round_name, "sets": sets, "arms": arms, "seed": seed, "author": author, "classmate": classmate,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "counts": counts, "missing": ["/".join(map(str, k)) for k in missing],
        "rules": {"claims_per_arm": CLAIMS_PER_ARM, "candidates_per_arm": CANDIDATES_PER_ARM, "double_share": DOUBLE_SHARE,
                  "double_labelled_drawn": "per arm, from that arm's sampled units"},
    }
    (target / "round.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sets", required=True, help="comma-separated: main, graph_off, ask_gold")
    ap.add_argument("--author", required=True, help="the author's initials (used in sheet file names)")
    ap.add_argument("--classmate", help="the classmate's initials (not used for ask_gold)")
    ap.add_argument("--arms", default=",".join(ARMS), help="arms to include (default M1,M2,M3)")
    ap.add_argument("--allow-missing", action="store_true", help="make the round even if some expected runs are missing")
    args = ap.parse_args(argv)
    sets = [s.strip() for s in args.sets.split(",") if s.strip()]
    bad = [s for s in sets if s not in ("main", "graph_off", "ask_gold")]
    if bad:
        raise SystemExit(f"unknown set(s): {bad}")
    if "ask_gold" in sets and len(sets) > 1:
        raise SystemExit("make the ask_gold round on its own")
    for name in (args.author, args.classmate):
        if name is not None and not name.isalnum():
            raise SystemExit("initials must be letters or digits only")
    if any(s in ("main", "graph_off") for s in sets) and not args.classmate:
        raise SystemExit("--classmate is required for main and graph_off rounds")
    info = make_round(sets, author=args.author, classmate=args.classmate, arms=[a.strip() for a in args.arms.split(",")],
                      allow_missing=args.allow_missing)
    print(json.dumps({k: info[k] for k in ("round", "counts", "missing")}, indent=2))
    print(f"Written to {OUT / info['round']}. Raters must not open blind_map.csv, units_map.csv or round.json.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    raise SystemExit(main())
