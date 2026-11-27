"""The model arms of the evaluation (EVALUATION_PLAN §2.11; METHODOLOGY_NOTES M1-M3).

One list, used by the web app (the model picker on Risk Assessment and Ask the Graph)
and by the evaluation runner, so both build each arm the same way: through
`make_cypher_llm` / `make_report_llm`, with the controls in `llm_factory.py`.
The same model plays both LLM roles in an arm.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from langchain_core.language_models import BaseChatModel


@dataclass(frozen=True)
class Arm:
    name: str
    provider: str
    model: str
    key_env: str | None
    label: str = ""
    note: str = ""


ARMS: dict[str, Arm] = {
    "M1": Arm("M1", "openai", "gpt-5.2", "OPENAI_API_KEY", "OpenAI gpt-5.2", "Baseline: the model the app was built with."),
    "M2": Arm("M2", "deepseek", "deepseek-flash", "DEEPSEEK_API_KEY", "DeepSeek V4.1 Flash",
              "Open-weight model through DeepSeek's API; thinking off."),
    "M3": Arm("M3", "anthropic", "claude-sonnet-5-5", "ANTHROPIC_API_KEY", "Claude Sonnet 5.5",
              "Anthropic's API; thinking off; JSON-schema structured output."),
}
DEFAULT_ARM = "M1"


def arm_for(name: str) -> Arm:
    try:
        return ARMS[name]
    except KeyError:
        raise ValueError(f"Unknown arm {name!r}: use {', '.join(ARMS)}") from None


def available(arm: Arm) -> bool:
    return not arm.key_env or bool(os.getenv(arm.key_env))


def describe() -> dict[str, Any]:
    """For the model picker: every arm and whether its key is set (never the key itself)."""
    return {
        "default": DEFAULT_ARM,
        "arms": [{**{k: v for k, v in asdict(a).items() if k != "key_env"}, "available": available(a)} for a in ARMS.values()],
    }


@lru_cache(maxsize=None)
def llms_for(name: str) -> tuple[BaseChatModel, BaseChatModel]:
    """(Cypher LLM, risk LLM) for an arm, built once per process."""
    from .ask.llm import make_cypher_llm
    from .pipeline.llm import make_report_llm

    arm = arm_for(name)
    return make_cypher_llm(arm.model, arm.provider), make_report_llm(arm.model, arm.provider)


def arm_of_models(*names: str | None) -> str | None:
    """Best guess of the arm behind runs saved without one (before the picker existed)."""
    for n in names:
        n = (n or "").lower()
        for arm in ARMS.values():
            if n and (n == arm.model or n.startswith(arm.model)):
                return arm.name
        if n.startswith("deepseek"):
            return "M2"
        if n.startswith("claude"):
            return "M3"
        if n.startswith("gpt"):
            return "M1"
    return None
