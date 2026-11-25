"""Risk Assessment as a plain async generator.

    find_candidates (Cypher LLM: generate -> check -> run, one retry)
    -> build_profiles (fixed Cypher, as_of_date filter)
    -> lookup_evidence (risk engine, fixed as_of_date; country lookups)
    -> write_report (risk LLM, structured output, no tools)
    -> check_citations (flag only)

`assess()` yields one event per step so FastAPI can stream them as
Server-Sent Events; the finished timeline is layer 3 of the page ("How this
answer was reached"). The run is saved to runs/assess/.

Event shapes (all JSON objects with an `event` key):
    {"event": "run",  "run": {...header...}}
    {"event": "step", "step": <name>, "attempt": n|None, "status": "running"|"done"|"failed", "data": {...}}
    {"event": "done", "run": {...full run...}}
    {"event": "error", "message": "...", "step": <name>|None}

The LLMs never choose the date (R12); the Cypher LLM writes only the
candidate-finding query.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from langchain_core.language_models import BaseChatModel
from supplier_risk_engine.loader import LoadedDatabase

from ..ask.pipeline import check_cypher, run_query, schema_text
from ..config import ASK_CYPHER_MODEL, ASSESS_GRAPH_OFF, ASSESS_RUNS_DIR, REPORT_MODEL
from ..evidence_api import EvidenceView
from ..neo4j_client import ReadOnlyNeo4j
from ..runs_store import new_run_id, now_iso, save_run
from ..usage import message_usage
from .evidence import lookup_evidence, mentioned_countries
from .profiles import build_profiles, match_products
from .prompts import (
    CANDIDATE_EXAMPLE, CANDIDATE_RETRY, INSUFFICIENT, AssessmentReport, CandidateQuery, candidate_prompt, report_prompt,
)
from .report import check_citations, fixed_insufficient_report, has_support, report_inputs

MAX_ITEMS = 20
MAX_ATTEMPTS = 2
DEFAULT_GOAL = "Assess supplier risk for these items."
REQUIRED_COLUMNS = ("item", "supplier_id")

Event = dict[str, Any]
Mode = Literal["parts", "describe"]


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def request_text(mode: Mode, items: list[dict[str, Any]], goal: str) -> str:
    if mode == "describe":
        return f"Describe mode. Item 1 (the buyer's description): {items[0]['text']}"
    lines = [f"Parts list ({len(items)} items). Goal: {goal}"]
    for it in items:
        extra = f"  [catalogue product_id: {it['product_id']}]" if it.get("product_id") else ""
        lines.append(f"{it['n']}. {it['text']}{extra}")
    return "\n".join(lines)


def _dump_model(obj: Any) -> Any:
    if obj is None:
        return None
    return obj.model_dump() if hasattr(obj, "model_dump") else obj


def _raw_text(raw: Any) -> Any:
    """What the model actually returned (content or tool-call arguments)."""
    if raw is None:
        return None
    calls = getattr(raw, "tool_calls", None)
    if calls:
        return [{"name": c.get("name"), "args": c.get("args")} for c in calls]
    return getattr(raw, "content", raw)


async def generate_candidates(
    llm: BaseChatModel, request: str, previous: dict[str, Any] | None, *, usage: dict[str, Any]
) -> dict[str, Any]:
    feedback = CANDIDATE_RETRY.format(**previous) if previous else ""
    values = {"request": request, "example": CANDIDATE_EXAMPLE, "schema": schema_text(), "feedback": feedback}
    prompt_text = candidate_prompt.format(**values)
    started = time.perf_counter()
    out = await (candidate_prompt | llm.with_structured_output(CandidateQuery, include_raw=True)).ainvoke(values)
    message_usage(usage, out.get("raw"))
    parsed: CandidateQuery | None = out.get("parsed")
    return {
        "prompt": prompt_text,
        "feedback": previous,
        "raw": _raw_text(out.get("raw")),
        "parsing_error": str(out["parsing_error"]) if out.get("parsing_error") else None,
        "cypher": parsed.cypher if parsed else "",
        "suggested_countries": [s.model_dump() for s in parsed.suggested_countries] if parsed else [],
        "interpretation": parsed.interpretation if parsed else None,
        "elapsed_ms": _ms(started),
    }


def _candidate_problem(gen: dict[str, Any], check: Any, result: dict[str, Any] | None) -> str | None:
    if gen.get("parsing_error"):
        return f"The reply was not in the required format: {gen['parsing_error'][:300]}"
    if not check.ok:
        return " ".join(check.problems)
    if result is None:
        return None
    if not result["ok"]:
        return f"The query failed: {result['error']}"
    missing = [c for c in REQUIRED_COLUMNS if c not in (result.get("columns") or [])]
    if result["row_count"] and missing:
        return f"The rows lack the required columns {', '.join(missing)}. Return item, supplier_id and product_id first."
    if result["row_count"] == 0:
        return (
            "The query ran but returned no rows. Product descriptions are noisy: match shorter lower-case "
            "keywords and synonyms with toLower(...) CONTAINS, on product_description and hs_code_description."
        )
    return None


def candidates_from_rows(rows: list[dict[str, Any]], n_items: int) -> dict[int, list[dict[str, Any]]]:
    """item number -> candidate suppliers, each with the product ids the query matched."""
    out: dict[int, dict[str, dict[str, Any]]] = {}
    for r in rows:
        try:
            n = int(r.get("item"))
        except (TypeError, ValueError):
            continue
        sid = r.get("supplier_id")
        if not isinstance(sid, str) or not 1 <= n <= n_items:
            continue
        sid = sid.removeprefix("supplier:")
        c = out.setdefault(n, {}).setdefault(sid, {"supplier_id": sid, "supplier_name": r.get("supplier_name"), "product_ids": []})
        pid = r.get("product_id")
        if isinstance(pid, str) and pid not in c["product_ids"]:
            c["product_ids"].append(pid)
    return {n: list(cs.values()) for n, cs in out.items()}


def _run_status(report: dict[str, Any]) -> str:
    statuses = [i.get("status") for i in report.get("items") or []]
    if "answered" in statuses:
        return "answered"
    if "country_level" in statuses:
        return "country_level"
    return "insufficient_data"


def evidence_view(db: LoadedDatabase, cache: dict[str, Any] | None = None) -> EvidenceView:
    if cache is not None:
        view = cache.get("view")
        if view is None or view.db is not db:
            view = cache["view"] = EvidenceView(db)
        return view
    return EvidenceView(db)


async def assess(
    *,
    mode: Mode,
    items: list[dict[str, Any]],
    goal: str | None,
    as_of: date,
    date_mode: Literal["chosen", "random"],
    rerun_of: str | None,
    client: ReadOnlyNeo4j,
    db: LoadedDatabase,
    view: EvidenceView,
    cypher_llm: BaseChatModel,
    report_llm: BaseChatModel,
    runs_dir: Path | None = ASSESS_RUNS_DIR,
    cypher_model: str = ASK_CYPHER_MODEL,
    report_model: str = REPORT_MODEL,
    graph_off: bool = ASSESS_GRAPH_OFF,
) -> AsyncIterator[Event]:
    """`graph_off=True` is the D11 no-graph baseline: no Cypher LLM, no graph profiles or
    matches. Countries come only from the request text, and the risk LLM sees only
    country-level engine evidence (the R4 path)."""
    items = [{**it, "n": i} for i, it in enumerate(items[:MAX_ITEMS], start=1)]
    goal = (goal or "").strip() or (None if mode == "describe" else DEFAULT_GOAL)
    run: dict[str, Any] = {
        "run_id": new_run_id("assess"),
        "kind": "assess",
        "mode": mode,
        "items": items,
        "goal": goal,
        "as_of_date": as_of.isoformat(),
        "date_mode": date_mode,
        "rerun_of": rerun_of,
        "models": {"cypher": cypher_model, "report": report_model},
        "graph_off": graph_off,
        "started_at": now_iso(),
        "finished_at": None,
        "status": "running",
        "attempts": [],
        "candidates": None,
        "profiles": None,
        "evidence": None,
        "report": None,
        "citations": None,
        "usage": None,
        "error": None,
        "failed_step": None,
    }
    header_keys = ("run_id", "kind", "mode", "items", "goal", "as_of_date", "date_mode", "rerun_of", "models", "graph_off", "started_at")
    yield {"event": "run", "run": {k: run[k] for k in header_keys}}

    usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0, "by_model": {}}
    calls = 0
    step = None
    request = request_text(mode, items, goal or "")
    query_text = items[0]["text"] if mode == "describe" else "; ".join(it["text"] for it in items)

    try:
        # ---------------------------------------------------------------- 1. find candidates
        previous: dict[str, Any] | None = None
        final: dict[str, Any] | None = None
        for n in range(1, (0 if graph_off else MAX_ATTEMPTS) + 1):
            attempt: dict[str, Any] = {"attempt": n, "generate": None, "check": None, "run": None, "problem": None}
            run["attempts"].append(attempt)

            step = "generate_cypher"
            yield {"event": "step", "step": step, "attempt": n, "status": "running", "data": {"retry_of": previous}}
            calls += 1
            gen = await generate_candidates(cypher_llm, request, previous, usage=usage)
            attempt["generate"] = gen
            yield {"event": "step", "step": step, "attempt": n, "status": "failed" if gen["parsing_error"] else "done", "data": gen}

            step = "check_cypher"
            yield {"event": "step", "step": step, "attempt": n, "status": "running", "data": {}}
            started = time.perf_counter()
            check = await asyncio.to_thread(check_cypher, client, gen["cypher"])
            attempt["check"] = {**check.to_dict(), "elapsed_ms": _ms(started)}
            yield {"event": "step", "step": step, "attempt": n, "status": "done" if check.ok else "failed", "data": attempt["check"]}

            result = None
            if check.ok and not gen["parsing_error"]:
                step = "run_query"
                yield {"event": "step", "step": step, "attempt": n, "status": "running", "data": {"cypher": check.cypher}}
                result = await asyncio.to_thread(run_query, client, check.cypher)
                attempt["run"] = result
                yield {"event": "step", "step": step, "attempt": n, "status": "done" if result["ok"] else "failed", "data": result}
                if result["ok"]:
                    final = {"cypher": check.cypher, "result": result, "generate": gen}

            problem = _candidate_problem(gen, check, result)
            attempt["problem"] = problem
            if problem is None:
                break
            previous = {"cypher": check.cypher or gen["cypher"], "problem": problem}

        # The labelled suggestions of the attempt that was used (or the last one).
        used_gen = (final or {}).get("generate") or (run["attempts"][-1]["generate"] if run["attempts"] else None) or {}
        rows = (final or {}).get("result", {}).get("rows") or []
        cand = candidates_from_rows(rows, len(items))

        # ---------------------------------------------------------------- 2. build profiles
        step = "build_profiles"
        yield {"event": "step", "step": step, "attempt": None, "status": "running", "data": {}}
        started = time.perf_counter()
        queries: list[dict[str, Any]] = []
        if graph_off:
            # D11: no graph profiles or matches are built; no Neo4j query runs in this step.
            built = {"profiles": {}, "inactive": [], "unknown": []}
            pairs: list[dict[str, Any]] = []
            matched: list[dict[str, Any]] = []
        else:
            supplier_ids = sorted({c["supplier_id"] for cs in cand.values() for c in cs})
            built = await asyncio.to_thread(build_profiles, client, supplier_ids, as_of, log=queries)
            pairs = [{"item": n, "supplier_id": c["supplier_id"], "product_id": pid} for n, cs in cand.items() for c in cs for pid in c["product_ids"]]
            matched = await asyncio.to_thread(match_products, client, pairs, as_of, log=queries)
        by_pair: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for m in matched:
            by_pair.setdefault((m["item"], m["supplier_id"]), []).append(m)
        for n, cs in cand.items():
            for c in cs:
                c["products"] = sorted(by_pair.get((n, c["supplier_id"]), []), key=lambda m: -m["shipments"])
                c["active"] = c["supplier_id"] in built["profiles"]
        matched_keys = {(m["item"], m["supplier_id"], m["product_id"]) for m in matched}
        after_date = [p for p in pairs if (p["item"], p["supplier_id"], p["product_id"]) not in matched_keys]
        run["candidates"] = {"by_item": {str(k): v for k, v in cand.items()}, "after_as_of": after_date}
        run["profiles"] = {
            "profiles": built["profiles"],
            "inactive": built["inactive"],
            "unknown": built["unknown"],
            "queries": queries,
            "elapsed_ms": _ms(started),
        }
        yield {"event": "step", "step": step, "attempt": None, "status": "done", "data": {"candidates": run["candidates"], **run["profiles"]}}

        # ---------------------------------------------------------------- 3. lookup evidence
        step = "lookup_evidence"
        yield {"event": "step", "step": step, "attempt": None, "status": "running", "data": {}}
        started = time.perf_counter()
        countries: list[dict[str, Any]] = []
        for code in mentioned_countries(goal or "", *(it["text"] for it in items)):
            countries.append({"code": code, "basis": "mentioned", "reason": "Named in the request."})
        for s in used_gen.get("suggested_countries") or []:
            code = str(s.get("code", "")).strip().upper()
            if len(code) == 2 and code not in {c["code"] for c in countries}:
                countries.append({"code": code, "basis": "suggested", "reason": s.get("reason")})
        ev = await asyncio.to_thread(
            lookup_evidence, db, view, built["profiles"], as_of, query=query_text, countries=countries
        )
        ev["elapsed_ms"] = _ms(started)
        run["evidence"] = ev
        yield {"event": "step", "step": step, "attempt": None, "status": "done", "data": ev}

        # ---------------------------------------------------------------- 4. write report
        step = "write_report"
        inputs = report_inputs(items=items, candidates=cand, profiles=built["profiles"], inactive=built["inactive"], evidence=ev)
        if not has_support(cand, built["profiles"], ev):
            # R7: nothing relevant from the graph or the engine; the LLM is not called.
            report = fixed_insufficient_report(items)
            run["report"] = {"source": "pipeline", "reason": "Neither the graph nor the risk engine returned anything relevant (R7).", "prompt": None, "raw": None, "parsed": report, "parsing_error": None, "elapsed_ms": 0}
            yield {"event": "step", "step": step, "attempt": None, "status": "done", "data": run["report"]}
        else:
            values = {
                "as_of_date": as_of.isoformat(),
                "goal": goal or items[0]["text"],
                "mode": "parts list" if mode == "parts" else "free-text description",
                "insufficient": INSUFFICIENT,
                **inputs["sections"],
            }
            prompt_text = report_prompt.format(**values)
            yield {"event": "step", "step": step, "attempt": None, "status": "running", "data": {"prompt": prompt_text}}
            started = time.perf_counter()
            calls += 1
            out = await (report_prompt | report_llm.with_structured_output(AssessmentReport, include_raw=True)).ainvoke(values)
            message_usage(usage, out.get("raw"))
            parsed = _dump_model(out.get("parsed"))
            run["report"] = {
                "source": "llm",
                "prompt": prompt_text,
                "raw": _raw_text(out.get("raw")),
                "parsed": parsed,
                "parsing_error": str(out["parsing_error"]) if out.get("parsing_error") else None,
                "elapsed_ms": _ms(started),
            }
            if parsed is None:
                yield {"event": "step", "step": step, "attempt": None, "status": "failed", "data": run["report"]}
                raise ValueError(f"The risk LLM's reply could not be read: {run['report']['parsing_error']}")
            yield {"event": "step", "step": step, "attempt": None, "status": "done", "data": run["report"]}

        # ---------------------------------------------------------------- 5. check citations
        step = "check_citations"
        yield {"event": "step", "step": step, "attempt": None, "status": "running", "data": {}}
        run["citations"] = check_citations(run["report"]["parsed"], inputs["citations"], ev)
        run["citations"]["given"] = sorted(inputs["citations"])
        yield {"event": "step", "step": step, "attempt": None, "status": "done", "data": run["citations"]}
        run["status"] = _run_status(run["report"]["parsed"])
        step = None
    except asyncio.CancelledError:
        run["status"] = "cancelled"
        run["failed_step"] = step
        raise
    except Exception as e:  # LLM/network/Neo4j failures: report and keep the trace
        run["status"] = "failed"
        run["failed_step"] = step
        run["error"] = f"{type(e).__name__}: {e}"
        yield {"event": "error", "message": run["error"], "step": step}
    finally:
        run["finished_at"] = now_iso()
        run["usage"] = {**usage, "calls": calls}
        if runs_dir is not None:
            save_run(runs_dir, run)
    yield {"event": "done", "run": run}
