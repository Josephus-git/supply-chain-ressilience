"""Token usage and the OpenAI service check (API credit safety, C2).

Every Ask and Assess run stores its LangChain `usage_metadata` totals under
`usage` in its run JSON. `tokens_today` sums them for the current UTC day, so
the header can warn near the free daily allowance. It warns; it never blocks.
Assumption to check: the free-token day resets at 00:00 UTC.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.callbacks import UsageMetadataCallbackHandler

from .config import DAILY_FREE_TOKENS, TOKEN_WARN_FRACTION


def usage_totals(handler: UsageMetadataCallbackHandler) -> dict[str, Any]:
    """Sum a callback handler's per-model usage into one record."""
    total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0, "calls": 0}
    by_model: dict[str, Any] = {}
    for model, u in (handler.usage_metadata or {}).items():
        reasoning = (u.get("output_token_details") or {}).get("reasoning", 0) or 0
        by_model[model] = {k: u.get(k, 0) for k in ("input_tokens", "output_tokens", "total_tokens")} | {"reasoning_tokens": reasoning}
        for k in ("input_tokens", "output_tokens", "total_tokens"):
            total[k] += u.get(k, 0) or 0
        total["reasoning_tokens"] += reasoning
    total["by_model"] = by_model
    return total


def message_usage(totals: dict[str, Any], message: Any) -> None:
    """Add one AIMessage's `usage_metadata` to `totals` (in place).

    Structured-output calls return the raw message (`include_raw=True`), so
    Risk Assessment reads usage from it directly.
    """
    u = getattr(message, "usage_metadata", None) or {}
    if not u:
        return
    model = (getattr(message, "response_metadata", None) or {}).get("model_name") or "unknown"
    reasoning = (u.get("output_token_details") or {}).get("reasoning", 0) or 0
    m = totals.setdefault("by_model", {}).setdefault(model, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0})
    for k in ("input_tokens", "output_tokens", "total_tokens"):
        totals[k] = (totals.get(k) or 0) + (u.get(k) or 0)
        m[k] += u.get(k) or 0
    totals["reasoning_tokens"] = (totals.get("reasoning_tokens") or 0) + reasoning
    m["reasoning_tokens"] += reasoning


def add_usage(into: dict[str, Any], more: dict[str, Any]) -> dict[str, Any]:
    out = dict(into)
    for k in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens", "calls"):
        out[k] = (into.get(k) or 0) + (more.get(k) or 0)
    return out


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def tokens_today(*dirs: Path) -> dict[str, Any]:
    """Tokens used today (UTC) by stored runs in `dirs`, against the free allowance."""
    day = _today_utc()
    used, runs = 0, 0
    for d in dirs:
        if not d or not d.is_dir():
            continue
        for path in d.glob("*.json"):
            # Run ids embed the UTC start time: <kind>-YYYYMMDDTHHMMSSZ-xxxxxx
            stamp = path.stem.split("-")[1] if path.stem.count("-") >= 2 else ""
            if stamp[:8] != day.replace("-", ""):
                continue
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            used += int(((run.get("usage") or {}).get("total_tokens")) or 0)
            runs += 1
    warn_at = int(DAILY_FREE_TOKENS * TOKEN_WARN_FRACTION)
    level = "over" if used >= DAILY_FREE_TOKENS else "warn" if used >= warn_at else "ok"
    return {
        "day_utc": day,
        "used": used,
        "runs": runs,
        "limit": DAILY_FREE_TOKENS,
        "warn_at": warn_at,
        "level": level,
        "note": "Free daily allowance; assumed to reset at 00:00 UTC. Warning only, runs are not blocked.",
    }


_OPENAI_CACHE: dict[str, Any] = {"at": 0.0, "value": None}
OPENAI_CHECK_TTL_S = 300


def openai_status(force: bool = False) -> dict[str, Any]:
    """Key present and API reachable, checked by listing models (spends no tokens).

    Cached for five minutes so the header's health poll does not call OpenAI
    every minute.
    """
    now = time.monotonic()
    if not force and _OPENAI_CACHE["value"] is not None and now - _OPENAI_CACHE["at"] < OPENAI_CHECK_TTL_S:
        return _OPENAI_CACHE["value"]
    if not os.getenv("OPENAI_API_KEY"):
        value = {"status": "no_key", "error": "OPENAI_API_KEY is not set in .env"}
    else:
        try:
            from openai import OpenAI

            OpenAI(timeout=10, max_retries=0).models.list()
            value = {"status": "reachable", "error": None}
        except Exception as e:  # report it; the rest of the app still works
            value = {"status": "unreachable", "error": f"{type(e).__name__}: {str(e)[:300]}"}
    value["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _OPENAI_CACHE.update(at=now, value=value)
    return value
