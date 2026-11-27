"""The LLM behind Ask the Graph (and the Cypher step of Risk Assessment).

`cypher_llm` writes the Cypher and the Ask answer. It is separate from the
Risk Assessment `report_llm` (pipeline/llm.py) so the two can use different
models (`ASK_CYPHER_MODEL` and `REPORT_MODEL` in .env, both defaulting to
gpt-5.2). It is built on first use, so the app starts (and the tests run)
without an OpenAI key.

Cost controls (C1 in METHODOLOGY_NOTES.md): an output-token cap, a timeout and
at most one retry. `stream_usage=True` makes streamed answers report their
token usage too, so every run can record it (C2).
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from ..config import ASK_CYPHER_MODEL, ASK_CYPHER_PROVIDER, CYPHER_MAX_TOKENS, CYPHER_TIMEOUT_S
from ..llm_factory import build_chat_model


def make_cypher_llm(model: str, provider: str) -> BaseChatModel:
    """The Cypher LLM for any arm (the evaluation runner builds M1-M3 with this)."""
    return build_chat_model(model, provider, max_tokens=CYPHER_MAX_TOKENS, timeout=CYPHER_TIMEOUT_S, stream_usage=True)


@lru_cache(maxsize=1)
def cypher_llm() -> BaseChatModel:
    return make_cypher_llm(ASK_CYPHER_MODEL, ASK_CYPHER_PROVIDER)
