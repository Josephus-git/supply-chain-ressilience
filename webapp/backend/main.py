"""FastAPI app for the Dyson supply-chain risk decision-support web app.

Run from the repository root:

    .venv/bin/uvicorn webapp.backend.main:app --reload --port 8000

The evidence database is loaded once at startup (`load_database()`), and one
read-only Neo4j driver is shared by all requests. If webapp/frontend/dist
exists (after `vite build`), it is served at `/`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from supplier_risk_engine.engine import describe_database
from supplier_risk_engine.loader import LoadedDatabase, load_database

from .ask.api import ask_router
from .config import ASK_RUNS_DIR, FRONTEND_DIST
from .evidence_api import evidence_router
from .graph_api import graph_router, home_router
from .neo4j_client import ReadOnlyNeo4j


def create_app(
    *,
    neo4j_client: ReadOnlyNeo4j | None = None,
    evidence_db: LoadedDatabase | None = None,
    ask_llm: Any = None,
    ask_runs_dir: Path | None = None,
) -> FastAPI:
    """`ask_llm` and `ask_runs_dir` let tests swap in a fake chat model and a temp folder."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_client = neo4j_client is None
        app.state.neo4j = neo4j_client or ReadOnlyNeo4j()
        app.state.evidence_db = evidence_db or load_database()
        app.state.ask_llm = ask_llm  # None: build cypher_llm() on first question
        app.state.ask_runs_dir = ask_runs_dir or ASK_RUNS_DIR
        try:
            yield
        finally:
            if owns_client:
                app.state.neo4j.close()

    app = FastAPI(title="Dyson supply-chain risk", version="0.1.0", lifespan=lifespan)
    app.include_router(home_router)
    app.include_router(graph_router)
    app.include_router(ask_router)
    app.include_router(evidence_router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, Any]:
        """Two independent parts: the Neo4j knowledge graph, and the evidence
        engine (local JSON files loaded at startup, no Neo4j)."""
        neo4j_error = None
        try:
            app.state.neo4j.verify()
        except Exception as e:  # report it; the evidence engine still works
            neo4j_error = str(e)
        db = describe_database(app.state.evidence_db.index)
        return {
            "status": "ok" if neo4j_error is None else "degraded",
            "neo4j": "connected" if neo4j_error is None else "unavailable",
            "neo4j_error": neo4j_error,
            "evidence_records": db["record_count"],
            "evidence_snapshot_id": db["data_snapshot_id"],
            "engine_version": db["engine_version"],
            "warnings": list(app.state.evidence_db.warnings),
        }

    if FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404, "Not Found")
            candidate = (FRONTEND_DIST / path).resolve()
            if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
