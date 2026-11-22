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

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from ..config import ASK_CYPHER_MODEL, CYPHER_MAX_TOKENS, CYPHER_TIMEOUT_S, LLM_MAX_RETRIES


@lru_cache(maxsize=1)
def cypher_llm() -> BaseChatModel:
    return init_chat_model(
        ASK_CYPHER_MODEL,
        model_provider="openai",
        max_tokens=CYPHER_MAX_TOKENS,
        timeout=CYPHER_TIMEOUT_S,
        max_retries=LLM_MAX_RETRIES,
        stream_usage=True,
    )
