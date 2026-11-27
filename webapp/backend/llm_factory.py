"""One place that builds every chat model, so all arms get the same controls (C1).

`init_chat_model` passes keyword arguments straight to the provider class, and the
names differ: ChatOllama has no `max_tokens`, `timeout` or `max_retries` fields and
silently ignores them. So the output cap, the timeout and the context window are
mapped per provider here:

    openai, anthropic: max_tokens, timeout, max_retries (one retry at most)
    deepseek:          the same, plus thinking mode switched off (see below)
    ollama:            num_predict (= max_tokens), client timeout, num_ctx; no retry
                       (a local server; a failed call is recorded as it is)

DeepSeek (M2 in METHODOLOGY_NOTES): thinking mode is on by default, and in thinking
mode the API rejects a forced, named tool choice with a 400 error. LangChain's
structured output (`with_structured_output`, method "function_calling") forces exactly
that, so every risk-LLM call would fail. Thinking is switched off, which also matches
M1 and M3: gpt-5.2 runs with no reasoning tokens at its default, and Claude does not
think unless asked.

Temperature is never set: each model runs at its provider default (Q7), and the
evaluation records that.
"""

from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from .config import LLM_MAX_RETRIES, OLLAMA_NUM_CTX

# Sent with every DeepSeek request (see the module docstring).
DEEPSEEK_EXTRA_BODY = {"thinking": {"type": "disabled"}}


def model_kwargs(provider: str, *, max_tokens: int, timeout: float, stream_usage: bool = False) -> dict[str, Any]:
    if provider == "ollama":
        return {"num_predict": max_tokens, "num_ctx": OLLAMA_NUM_CTX, "client_kwargs": {"timeout": timeout}}
    kwargs: dict[str, Any] = {"max_tokens": max_tokens, "timeout": timeout, "max_retries": LLM_MAX_RETRIES}
    if stream_usage:
        kwargs["stream_usage"] = True
    if provider == "deepseek":
        kwargs["extra_body"] = DEEPSEEK_EXTRA_BODY
    return kwargs


def build_chat_model(model: str, provider: str, *, max_tokens: int, timeout: float, stream_usage: bool = False) -> BaseChatModel:
    return init_chat_model(
        model, model_provider=provider, **model_kwargs(provider, max_tokens=max_tokens, timeout=timeout, stream_usage=stream_usage)
    )
