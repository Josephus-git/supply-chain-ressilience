"""Risk Assessment endpoints.

    POST /api/assess          run one assessment; Server-Sent Events, one per step
    GET  /api/runs            stored assessment runs, newest first (summaries; ?mode=)
    GET  /api/runs/{run_id}   one stored run with its full trace

Only one assessment runs at a time (API credit safety): a second request
while one is running gets 409.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from ..ask.llm import cypher_llm
from ..config import STUDY_END, STUDY_START
from ..runs_store import list_runs, load_run, valid_run_id
from .assess import MAX_ITEMS, assess, evidence_view
from .llm import report_llm

assess_router = APIRouter(prefix="/api", tags=["assess"])

_running = asyncio.Lock()


class ItemIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    source: Literal["catalogue", "typed"] = "typed"
    product_id: str | None = Field(None, max_length=40)


class AssessRequest(BaseModel):
    mode: Literal["parts", "describe"]
    items: list[ItemIn] = Field(default_factory=list, max_length=MAX_ITEMS)
    goal: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=1000)
    as_of_date: date
    date_mode: Literal["chosen", "random"] = "chosen"
    rerun_of: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "AssessRequest":
        if not STUDY_START <= self.as_of_date <= STUDY_END:
            raise ValueError(f"as_of_date must be inside the study window {STUDY_START} to {STUDY_END}")
        if self.mode == "parts":
            self.items = [i for i in self.items if i.text.strip()]
            if not self.items:
                raise ValueError("Add at least one item to the parts list.")
        else:
            if not (self.description or "").strip() or len(self.description.strip()) < 3:
                raise ValueError("Describe what you need in at least 3 characters.")
        if self.rerun_of is not None and not valid_run_id(self.rerun_of):
            raise ValueError("rerun_of is not a run id")
        return self


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@assess_router.post("/assess")
async def run_assessment(body: AssessRequest, request: Request) -> StreamingResponse:
    if _running.locked():
        raise HTTPException(409, "An assessment is already running. Wait for it to finish.")
    state = request.app.state
    if body.mode == "describe":
        items = [{"text": body.description.strip(), "source": "typed", "product_id": None}]
    else:
        items = [{"text": i.text.strip(), "source": i.source, "product_id": i.product_id} for i in body.items]
    c_llm = getattr(state, "assess_cypher_llm", None) or cypher_llm()
    r_llm = getattr(state, "assess_report_llm", None) or report_llm()
    view = evidence_view(state.evidence_db, state.assess_cache)

    async def stream() -> AsyncIterator[str]:
        async with _running:
            async for event in assess(
                mode=body.mode,
                items=items,
                goal=body.goal,
                as_of=body.as_of_date,
                date_mode=body.date_mode,
                rerun_of=body.rerun_of,
                client=state.neo4j,
                db=state.evidence_db,
                view=view,
                cypher_llm=c_llm,
                report_llm=r_llm,
                runs_dir=state.assess_runs_dir,
                embedder=getattr(state, "assess_embedder", None),
            ):
                yield _sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _summary_text(report: dict[str, Any]) -> str | None:
    """History line: the shared summary, else the item answers joined."""
    shared = ((report.get("summary") or {}).get("text") or "").strip()
    if shared:
        return shared
    answers = [((i.get("answer") or {}).get("text") or "").strip() for i in report.get("items") or []]
    return " · ".join(a for a in answers if a) or None


def _summary(run: dict[str, Any]) -> dict[str, Any]:
    items = run.get("items") or []
    report = (run.get("report") or {}).get("parsed") or {}
    return {
        "run_id": run["run_id"],
        "mode": run.get("mode"),
        "status": run.get("status"),
        "started_at": run.get("started_at"),
        "as_of_date": run.get("as_of_date"),
        "date_mode": run.get("date_mode"),
        "rerun_of": run.get("rerun_of"),
        "item_count": len(items),
        "first_items": [i.get("text") for i in items[:3]],
        "goal": run.get("goal"),
        "summary": _summary_text(report),
        "tokens": (run.get("usage") or {}).get("total_tokens"),
        "models": run.get("models"),
    }


@assess_router.get("/runs")
def assess_runs(
    request: Request,
    mode: Literal["parts", "describe"] | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    runs = [_summary(r) for r in list_runs(request.app.state.assess_runs_dir, 500)]
    if mode:
        runs = [r for r in runs if r["mode"] == mode]
    return {"runs": runs[:limit]}


@assess_router.get("/runs/{run_id}")
def assess_run(run_id: str, request: Request) -> dict[str, Any]:
    run = load_run(request.app.state.assess_runs_dir, run_id)
    if run is None:
        raise HTTPException(404, f"No stored assessment run {run_id!r}")
    return run
