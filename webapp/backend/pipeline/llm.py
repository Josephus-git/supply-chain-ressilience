"""The risk LLM (`report_llm`) for Risk Assessment.

Separate from the Cypher LLM (`ask.llm.cypher_llm`, also used for the
candidate step) so the two can use different models. Built on first use, so
the app starts and the tests run without an OpenAI key. Cost controls (C1):
output-token cap (reasoning included), timeout, one retry at most.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from ..config import REPORT_MAX_TOKENS, REPORT_MODEL, REPORT_PROVIDER, REPORT_TIMEOUT_S
from ..llm_factory import build_chat_model


def make_report_llm(model: str, provider: str) -> BaseChatModel:
    """The risk LLM for any arm (the evaluation runner builds M1-M3 with this)."""
    return build_chat_model(model, provider, max_tokens=REPORT_MAX_TOKENS, timeout=REPORT_TIMEOUT_S)


@lru_cache(maxsize=1)
def report_llm() -> BaseChatModel:
    return make_report_llm(REPORT_MODEL, REPORT_PROVIDER)
