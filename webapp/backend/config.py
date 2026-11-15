"""Settings for the web app backend, read once from the repository's .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parents[1]
REFERENCE_DIR = BACKEND_DIR / "reference"
LOCATIONS_PATH = REFERENCE_DIR / "locations.json"
RUNS_DIR = REPO_ROOT / "runs"
FRONTEND_DIST = REPO_ROOT / "webapp" / "frontend" / "dist"

# Study window: one source of truth, the evidence engine.
from supplier_risk_engine.engine.reference import STUDY_END, STUDY_START  # noqa: E402,F401

# Vector search: same model and index as the (deleted) rag/update_embeddings.py.
EMBEDDING_MODEL = "text-embedding-3-small"
VECTOR_INDEX = "embedding"
CHAT_MODEL = "gpt-5.2"

load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Neo4jSettings:
    uri: str
    username: str
    password: str
    database: str | None


def neo4j_settings() -> Neo4jSettings:
    missing = [k for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD") if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing Neo4j settings in .env: {', '.join(missing)}")
    return Neo4jSettings(
        uri=os.environ["NEO4J_URI"],
        username=os.environ["NEO4J_USERNAME"],
        password=os.environ["NEO4J_PASSWORD"],
        database=os.getenv("NEO4J_DATABASE") or None,
    )
