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
PRODUCT_CATEGORIES_PATH = REFERENCE_DIR / "product_categories.json"
RUNS_DIR = REPO_ROOT / "runs"
FRONTEND_DIST = REPO_ROOT / "webapp" / "frontend" / "dist"

# Study window: one source of truth, the evidence engine.
from supplier_risk_engine.engine.reference import STUDY_END, STUDY_START  # noqa: E402,F401

# Vector search: same model and index as the (deleted) rag/update_embeddings.py.
EMBEDDING_MODEL = "text-embedding-3-small"
VECTOR_INDEX = "embedding"
CHAT_MODEL = "gpt-5.2"
# R26/R27 (METHODOLOGY_NOTES.md): parts-list candidates come from vector search.
# Fixed values, not read from .env, so every evaluation run uses the same settings.
CANDIDATE_TOP_K = 3
CANDIDATE_MIN_SCORE = 0.69  # R27, chosen 27 Nov 2026 from evaluation/calibrate_embedding_threshold.py

load_dotenv(REPO_ROOT / ".env")

# Ask the Graph has its own Cypher-writing model; Risk Assessment will use REPORT_MODEL.
ASK_CYPHER_MODEL = os.getenv("ASK_CYPHER_MODEL") or CHAT_MODEL
REPORT_MODEL = os.getenv("REPORT_MODEL") or CHAT_MODEL
# LangChain provider for each model (e.g. "openai", "anthropic", "deepseek", "ollama"). Changing a
# model's provider is a methodology change: see METHODOLOGY_NOTES.md (M1-M3).
ASK_CYPHER_PROVIDER = os.getenv("ASK_CYPHER_PROVIDER") or "openai"
REPORT_PROVIDER = os.getenv("REPORT_PROVIDER") or "openai"
# D11 no-graph baseline. "1" makes Risk Assessment skip the Cypher LLM and graph profiles by default.
ASSESS_GRAPH_OFF = (os.getenv("ASSESS_GRAPH_OFF") or "").strip() == "1"
ASK_RUNS_DIR = RUNS_DIR / "ask"
ASSESS_RUNS_DIR = RUNS_DIR / "assess"
# Batch runs (evaluation/run_batch.py): each folder holds ask/, assess/ and manifest.csv.
# "pilot" holds trial runs made before the evaluation, kept apart from its results.
BATCH_RUN_ROOTS = {"evaluation": RUNS_DIR / "evaluation", "pilot": RUNS_DIR / "pilot"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name) or default)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


# API credit safety (C1, C2 in METHODOLOGY_NOTES.md). Every LLM call has an
# output cap (reasoning tokens included), a timeout and one retry at most.
CYPHER_MAX_TOKENS = _int_env("CYPHER_MAX_TOKENS", 6_000)
CYPHER_TIMEOUT_S = _float_env("CYPHER_TIMEOUT_S", 120)
REPORT_MAX_TOKENS = _int_env("REPORT_MAX_TOKENS", 16_000)
REPORT_TIMEOUT_S = _float_env("REPORT_TIMEOUT_S", 300)
LLM_MAX_RETRIES = 1
# Ollama context window in tokens (only used when a provider is "ollama"). Ollama's default
# is smaller than a risk-LLM prompt plus its output, and it drops the start of a prompt
# that does not fit, so it is set explicitly.
OLLAMA_NUM_CTX = _int_env("OLLAMA_NUM_CTX", 16_384)
# The OpenAI free-token allowance per day, and the share at which the app warns.
DAILY_FREE_TOKENS = _int_env("DAILY_FREE_TOKENS", 250_000)
TOKEN_WARN_FRACTION = _float_env("TOKEN_WARN_FRACTION", 0.8)


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
