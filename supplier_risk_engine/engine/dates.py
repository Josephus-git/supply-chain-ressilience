"""Dated retrieval (plan sections 5.2 and 5.3).

`event_window_days` is a retrieval setting. Nothing here treats it, or a
search window, as the duration of an event.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .models import DateScope
from .reference import DATE_FAMILY, STUDY_END, STUDY_START

UNDATED_REASON = "undated candidate: as_of_date within search_window"
OPEN_EFFECTIVE_END = "no end date recorded; continued force not verified"

# (start field, end field) for each date family.
FAMILY_FIELDS = {
    "event_interval": ("event_start", "event_end"),
    "observation_point": ("observation_date", None),
    "observation_start": ("observation_start", "observation_end"),
    "effective_interval": ("effective_from", "effective_to"),
}

_DATED_REASONS = {
    "event_interval": (
        "dated: as_of_date within event_start to event_end (or event_start), "
        "each extended by event_window_days"
    ),
    "observation_point": "dated: as_of_date within event_window_days of observation_date",
    "observation_start": (
        "dated: as_of_date within observation_start to observation_end (or "
        "observation_start), each extended by event_window_days"
    ),
    "effective_interval": (
        "dated: as_of_date within effective_from to effective_to, each "
        "extended by event_window_days"
    ),
}


def in_study_window(as_of: date) -> bool:
    return STUDY_START <= as_of <= STUDY_END


def _iso(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def date_scope(
    risk_type: str, record: dict[str, Any], as_of: date, window_days: int
) -> DateScope | None:
    """Return the record's date scope if it is in scope on `as_of`, else None."""
    family = DATE_FAMILY[risk_type]
    start_field, end_field = FAMILY_FIELDS[family]
    stored = {start_field: record.get(start_field)}
    if end_field is not None:
        stored[end_field] = record.get(end_field)

    start = _iso(record.get(start_field))
    if start is None:
        return _undated(family, record, as_of, stored)

    window = timedelta(days=window_days)
    open_end = None
    end = _iso(record.get(end_field)) if end_field else None
    if end is None:
        if family == "effective_interval":
            end = STUDY_END
            open_end = OPEN_EFFECTIVE_END
        else:
            end = start

    if not _overlaps_study(start, end):
        return None
    if not (start - window <= as_of <= end + window):
        return None
    return DateScope(
        date_family=family,
        date_status="dated",
        in_scope_reason=_DATED_REASONS[family],
        dates=stored,
        open_end=open_end,
    )


def _undated(
    family: str, record: dict[str, Any], as_of: date, stored: dict[str, Any]
) -> DateScope | None:
    """A record without its date field is only an undated candidate, and only
    when its stored search window contains as_of (no event window applied)."""
    sw = record.get("search_window") or {}
    sw_start, sw_end = _iso(sw.get("start")), _iso(sw.get("end"))
    if sw_start is None or sw_end is None:
        return None
    if not _overlaps_study(sw_start, sw_end):
        return None
    if not (sw_start <= as_of <= sw_end):
        return None
    return DateScope(
        date_family=family,
        date_status="undated_candidate",
        in_scope_reason=UNDATED_REASON,
        dates=stored,
    )


def _overlaps_study(start: date, end: date) -> bool:
    return start <= STUDY_END and end >= STUDY_START
