"""FastAPI app for the Dyson supply-chain risk decision-support web app.

Run from the repository root:

    .venv/bin/uvicorn webapp.backend.main:app --reload --port 8000

The evidence database is loaded once at startup (`load_database()`), and one
read-only Neo4j driver is shared by all requests. If webapp/frontend/dist
exists (after `vite build`), it is served at `/`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from supplier_risk_engine.engine import describe_database
from supplier_risk_engine.loader import LoadedDatabase, load_database

from .config import FRONTEND_DIST
from .graph_api import graph_router, home_router
from .neo4j_client import ReadOnlyNeo4j


def create_app(
    *, neo4j_client: ReadOnlyNeo4j | None = None, evidence_db: LoadedDatabase | None = None
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_client = neo4j_client is None
        app.state.neo4j = neo4j_client or ReadOnlyNeo4j()
        app.state.evidence_db = evidence_db or load_database()
        try:
            yield
        finally:
            if owns_client:
                app.state.neo4j.close()

    app = FastAPI(title="Dyson supply-chain risk", version="0.1.0", lifespan=lifespan)
    app.include_router(home_router)
    app.include_router(graph_router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, Any]:
        app.state.neo4j.verify()
        db = describe_database(app.state.evidence_db.index)
        return {
            "status": "ok",
            "neo4j": "connected",
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
