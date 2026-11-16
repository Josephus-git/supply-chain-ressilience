"""The LLM behind Ask the Graph.

`cypher_llm` writes the Cypher and the answer. It is separate from the Risk
Assessment `report_llm` so the two can use different models
(`ASK_CYPHER_MODEL` and `REPORT_MODEL` in .env, both defaulting to gpt-5.2).
It is built on first use, so the app starts (and the tests run) without an
OpenAI key.
"""

from __future__ import annotations

from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from ..config import ASK_CYPHER_MODEL


@lru_cache(maxsize=1)
def cypher_llm() -> BaseChatModel:
    return init_chat_model(ASK_CYPHER_MODEL, model_provider="openai")
