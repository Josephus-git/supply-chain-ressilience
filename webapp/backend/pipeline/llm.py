"""The risk LLM (`report_llm`) for Risk Assessment.

Separate from the Cypher LLM (`ask.llm.cypher_llm`, also used for the
candidate step) so the two can use different models. Built on first use, so
the app starts and the tests run without an OpenAI key. Cost controls (C1):
output-token cap (reasoning included), timeout, one retry at most.
"""

from __future__ import annotations

from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from ..config import LLM_MAX_RETRIES, REPORT_MAX_TOKENS, REPORT_MODEL, REPORT_TIMEOUT_S


@lru_cache(maxsize=1)
def report_llm() -> BaseChatModel:
    return init_chat_model(
        REPORT_MODEL,
        model_provider="openai",
        max_tokens=REPORT_MAX_TOKENS,
        timeout=REPORT_TIMEOUT_S,
        max_retries=LLM_MAX_RETRIES,
    )
