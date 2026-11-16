"""Ask the Graph endpoints.

    GET  /api/ask/examples        example question chips (reference Cypher is not sent)
    POST /api/ask                 run one question; Server-Sent Events, one per step
    GET  /api/ask/runs            stored runs, newest first (summaries)
    GET  /api/ask/runs/{run_id}   one stored run with its full trace
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..runs_store import list_runs, load_run
from .llm import cypher_llm
from .pipeline import ask, load_examples

ask_router = APIRouter(prefix="/api/ask", tags=["ask"])


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


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
    llm = getattr(state, "ask_llm", None) or cypher_llm()

    async def stream() -> AsyncIterator[str]:
        async for event in ask(question, client=state.neo4j, llm=llm, runs_dir=state.ask_runs_dir):
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
        "started_at": run.get("started_at"),
        "attempts": len(run.get("attempts") or []),
        "row_count": (used or {}).get("run", {}).get("row_count"),
    }


@ask_router.get("/runs")
def ask_runs(request: Request, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    return {"runs": [_summary(r) for r in list_runs(request.app.state.ask_runs_dir, limit)]}


@ask_router.get("/runs/{run_id}")
def ask_run(run_id: str, request: Request) -> dict[str, Any]:
    run = load_run(request.app.state.ask_runs_dir, run_id)
    if run is None:
        raise HTTPException(404, f"No stored Ask the Graph run {run_id!r}")
    return run
