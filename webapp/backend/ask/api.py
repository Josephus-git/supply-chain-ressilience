"""Ask the Graph endpoints.

    GET  /api/ask/examples        example question chips (reference Cypher is not sent)
    POST /api/ask                 run one question; Server-Sent Events, one per step
    GET  /api/ask/runs            stored runs, newest first (summaries)
    GET  /api/ask/runs/{run_id}   one stored run with its full trace
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..arms import arm_for, available, llms_for
from ..config import ASK_CYPHER_MODEL, BATCH_RUN_ROOTS
from ..runs_store import find_run, list_runs
from .llm import cypher_llm
from .pipeline import ask, load_examples

ask_router = APIRouter(prefix="/api/ask", tags=["ask"])


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    arm: Literal["M1", "M2", "M3"] | None = None


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@ask_router.get("/examples")
def ask_examples() -> dict[str, Any]:
    return {"questions": [{k: q[k] for k in ("id", "question", "angle")} for q in load_examples()]}


@ask_router.post("")
async def ask_question(body: AskRequest, request: Request) -> StreamingResponse:
    question = body.question.strip()
    if len(question) < 3:
        raise HTTPException(422, "Ask a question of at least 3 characters.")
    state = request.app.state
    llm = getattr(state, "ask_llm", None)
    model_name = ASK_CYPHER_MODEL
    if body.arm and llm is None:  # a test fake takes precedence
        arm = arm_for(body.arm)
        if not available(arm):
            raise HTTPException(422, f"{arm.label} ({arm.name}) has no API key in .env ({arm.key_env}).")
        llm, model_name = llms_for(arm.name)[0], arm.model
    llm = llm or cypher_llm()

    async def stream() -> AsyncIterator[str]:
        async for event in ask(question, client=state.neo4j, llm=llm, model_name=model_name, runs_dir=state.ask_runs_dir, arm=body.arm):
            yield _sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _summary(run: dict[str, Any]) -> dict[str, Any]:
    used = next((a for a in reversed(run.get("attempts") or []) if (a.get("run") or {}).get("ok")), None)
    return {
        "run_id": run["run_id"],
        "question": run.get("question"),
        "status": run.get("status"),
        "model": run.get("model"),
        "arm": run.get("arm"),
        "started_at": run.get("started_at"),
        "attempts": len(run.get("attempts") or []),
        "row_count": (used or {}).get("run", {}).get("row_count"),
    }


@ask_router.get("/runs")
def ask_runs(request: Request, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    return {"runs": [_summary(r) for r in list_runs(request.app.state.ask_runs_dir, limit)]}


@ask_router.get("/runs/{run_id}")
def ask_run(run_id: str, request: Request) -> dict[str, Any]:
    dirs = [request.app.state.ask_runs_dir, *(root / "ask" for root in BATCH_RUN_ROOTS.values())]
    run = find_run(dirs, run_id)
    if run is None:
        raise HTTPException(404, f"No stored Ask the Graph run {run_id!r}")
    return run
