"""Run History and the model picker.

    GET /api/models    the model arms (M1-M3) and whether each has a key; never the key
    GET /api/history   every saved run, summarised by the automatic measures of the
                       evaluation plan, in two groups:
                         pilot       trial runs before the evaluation: runs made by hand
                                     in the web app (runs/assess/, runs/ask/; made_by
                                     "app") and with the runner (runs/pilot/; "runner")
                         evaluation  runs/evaluation/ (the evaluation runs)
                       `current_pipeline` is false for Risk Assessment parts-list runs
                       saved before candidate retrieval by embeddings (R26, 27 Nov).

The summaries hold only what the run files already record (EVALUATION_PLAN §2.2):
status, refusals forced by the pipeline (R7) versus by the model, citation checks
(B1: verified share; C1: not found, wrong scope, uncited claims), ranked candidates,
tokens and calls. Human labels (B2, C2, D1) are not shown: they come from the
labelling sheets. For batch folders only the runs that count are listed: runs stopped
by a service failure were run again (run_batch), so they are left out.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from .arms import arm_of_models, describe
from .config import BATCH_RUN_ROOTS

history_router = APIRouter(prefix="/api", tags=["history"])

_cache: dict[Path, tuple[float, dict[str, Any]]] = {}


@history_router.get("/models")
def models() -> dict[str, Any]:
    return describe()


def _assess_summary(run: dict[str, Any]) -> dict[str, Any]:
    report = run.get("report") or {}
    parsed = report.get("parsed") or {}
    cit = run.get("citations") or {}
    items = run.get("items") or []
    goal = run.get("goal")
    return {
        "title": items[0]["text"] if run.get("mode") == "describe" and items else ", ".join(i.get("text", "") for i in items),
        "goal": goal,
        "items": [i.get("text") for i in items],
        "mode": run.get("mode"),
        "as_of_date": run.get("as_of_date"),
        "answered_by": report.get("source"),
        "item_status": [i.get("status") for i in parsed.get("items") or []],
        "ranked": [len(i.get("candidates") or []) for i in parsed.get("items") or []],
        "citations": {
            "total": cit.get("total", 0),
            "verified": cit.get("verified", 0),
            "not_found": cit.get("not_found", 0),
            "with_note": cit.get("with_note", 0),
            "uncited": len(cit.get("uncited_claims") or []),
        } if cit else None,
        "graph_off": bool(run.get("graph_off")),
        "model": ((run.get("models") or {}).get("report")),
    }


def _ask_summary(run: dict[str, Any]) -> dict[str, Any]:
    used = next((a for a in reversed(run.get("attempts") or []) if (a.get("run") or {}).get("ok")), None)
    gold = run.get("gold") or {}
    return {
        "title": run.get("question"),
        "rows": ((used or {}).get("run") or {}).get("row_count"),
        "attempts": len(run.get("attempts") or []),
        "gold_compare": gold.get("compare"),
        "gold_rows": ((gold.get("result") or {}).get("row_count")),
        "model": run.get("model"),
    }


def summarise(run: dict[str, Any], source: str) -> dict[str, Any]:
    ev = run.get("eval") or {}
    usage = run.get("usage") or {}
    kind = run.get("kind") or ("ask" if "question" in run else "assess")
    body = _ask_summary(run) if kind == "ask" else _assess_summary(run)
    served = sorted((usage.get("by_model") or {}).keys())
    made_by = "app" if source == "app" else "runner"
    current = kind == "ask" or run.get("mode") == "describe" or "retrieval" in run
    return {
        "run_id": run["run_id"],
        "kind": kind,
        "source": "pilot" if source == "app" else source,
        "made_by": made_by,
        "current_pipeline": current,
        "started_at": run.get("started_at"),
        "status": run.get("status"),
        "error": run.get("error"),
        "arm": run.get("arm") or ev.get("arm") or arm_of_models(body.get("model"), *served),
        "models_served": served,
        "set": ev.get("set"),
        "query_id": ev.get("query_id"),
        "repeat": ev.get("repeat"),
        "tokens": usage.get("total_tokens"),
        "calls": usage.get("calls"),
        **body,
    }


def _summary_of(path: Path, source: str) -> dict[str, Any] | None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mtime and hit[1]["made_by"] == ("app" if source == "app" else "runner"):
        return hit[1]
    try:
        s = summarise(json.loads(path.read_text(encoding="utf-8")), source)
    except (OSError, json.JSONDecodeError, KeyError):
        return None
    _cache[path] = (mtime, s)
    return s


def _batch_files(root: Path) -> list[Path]:
    manifest = root / "manifest.csv"
    if not manifest.is_file():
        return []
    counted: dict[tuple[str, ...], str] = {}
    with manifest.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("infra_error"):
                continue
            counted[(r["set"], r["query_id"], r["arm"], r["repeat"])] = r["file"]  # later rows win
    return [root / f for f in counted.values()]


def all_runs(app_dirs: list[Path], batch_roots: dict[str, Path]) -> list[dict[str, Any]]:
    out = []
    for d in app_dirs:
        if d.is_dir():
            out += [s for p in d.glob("*.json") if (s := _summary_of(p, "app"))]
    for source, root in batch_roots.items():
        out += [s for p in _batch_files(root) if (s := _summary_of(p, source))]
    return sorted(out, key=lambda s: s.get("started_at") or "", reverse=True)


@history_router.get("/history")
def history(request: Request) -> dict[str, Any]:
    state = request.app.state
    roots = getattr(state, "batch_run_roots", None) or BATCH_RUN_ROOTS
    runs = all_runs([state.assess_runs_dir, state.ask_runs_dir], roots)
    return {"runs": runs, "arms": describe()["arms"]}
