"""One place that builds every chat model, so all arms get the same controls (C1).

`init_chat_model` passes keyword arguments straight to the provider class, and the
names differ: ChatOllama has no `max_tokens`, `timeout` or `max_retries` fields and
silently ignores them. So the output cap, the timeout and the context window are
mapped per provider here:

    openai:            max_tokens, timeout, max_retries (one retry at most)
    deepseek:          the same, plus thinking mode switched off (see below)
    anthropic:         the same, plus thinking switched off (see below)
    ollama:            num_predict (= max_tokens), client timeout, num_ctx; no retry
                       (a local server; a failed call is recorded as it is)

DeepSeek (M2 in METHODOLOGY_NOTES): thinking mode is on by default, and in thinking
mode the API rejects a forced, named tool choice with a 400 error. LangChain's
structured output (`with_structured_output`, method "function_calling") forces exactly
that, so every risk-LLM call would fail. Thinking is switched off, which also matches
M1: gpt-5.2 runs with no reasoning tokens at its default.

Claude (M3, claude-sonnet-5-5): thinking is adaptive by default; the author chose to
switch it off (27 Nov) so all three arms run without reasoning. On Sonnet 5.5,
`{"type": "disabled"}` returns a 400; off is `{"type": "between_tools"}`. Sonnet 5.5 also
rejects a forced tool choice with a 400, so its structured output uses LangChain's
"json_schema" method (Anthropic structured outputs, `output_config.format`), which is
schema-enforced like M1's OpenAI default. `structured()` picks the method; every other
provider keeps its LangChain default, unchanged.

Temperature is never set: each model runs at its provider default (Q7), and the
evaluation records that.
"""

from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from .config import LLM_MAX_RETRIES, OLLAMA_NUM_CTX

# Sent with every DeepSeek or Claude request (see the module docstring).
DEEPSEEK_EXTRA_BODY = {"thinking": {"type": "disabled"}}
ANTHROPIC_THINKING = {"type": "between_tools"}


def model_kwargs(provider: str, *, max_tokens: int, timeout: float, stream_usage: bool = False) -> dict[str, Any]:
    if provider == "ollama":
        return {"num_predict": max_tokens, "num_ctx": OLLAMA_NUM_CTX, "client_kwargs": {"timeout": timeout}}
    kwargs: dict[str, Any] = {"max_tokens": max_tokens, "timeout": timeout, "max_retries": LLM_MAX_RETRIES}
    if stream_usage:
        kwargs["stream_usage"] = True
    if provider == "deepseek":
        kwargs["extra_body"] = DEEPSEEK_EXTRA_BODY
    if provider == "anthropic":
        kwargs["thinking"] = ANTHROPIC_THINKING
    return kwargs


def structured_method(llm: Any) -> str | None:
    """The structured-output method to request, or None for LangChain's default."""
    return "json_schema" if type(llm).__name__ == "ChatAnthropic" else None


def structured(llm: Any, schema: type) -> Any:
    """`llm.with_structured_output(schema, include_raw=True)`, with the method Claude needs."""
    method = structured_method(llm)
    if method is None:
        return llm.with_structured_output(schema, include_raw=True)
    return llm.with_structured_output(schema, include_raw=True, method=method)


def build_chat_model(model: str, provider: str, *, max_tokens: int, timeout: float, stream_usage: bool = False) -> BaseChatModel:
    return init_chat_model(
        model, model_provider=provider, **model_kwargs(provider, max_tokens=max_tokens, timeout=timeout, stream_usage=stream_usage)
    )
