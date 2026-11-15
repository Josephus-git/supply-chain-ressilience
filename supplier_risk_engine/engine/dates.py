"""Dated retrieval (plan sections 5.2 and 5.3).

`event_window_days` is a retrieval setting. Nothing here treats it, or a
search window, as the duration of an event.

No look-ahead (phase 6): a record is in scope only from the date it became
known (`known_from`), and the window extends only past its end, never before
its start. A record that becomes known after its end (or after its search
window) stays in scope for the window from `known_from`, so a late report is
still seen once it is public.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .models import DateScope
from .reference import DATE_FAMILY, STUDY_END, STUDY_START

UNDATED_REASON = (
    "undated candidate: as_of_date within search_window and on or after known_from"
)
UNDATED_LATE_REASON = (
    "undated candidate: known after search_window ended; as_of_date within "
    "event_window_days of known_from"
)
DATED_LATE_REASON = (
    "dated: known after its end date; as_of_date from known_from to known_from "
    "plus event_window_days"
)
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
        "dated: as_of_date from known_from to event_end (or event_start) "
        "plus event_window_days"
    ),
    "observation_point": (
        "dated: as_of_date from known_from to observation_date plus event_window_days"
    ),
    "observation_start": (
        "dated: as_of_date from known_from to observation_end (or "
        "observation_start) plus event_window_days"
    ),
    "effective_interval": (
        "dated: as_of_date from known_from to effective_to plus event_window_days"
    ),
}

# How known_from was set (plan section 5.2, rules 1 to 3).
KNOWN_FROM_STORED = "stored_known_from"
KNOWN_FROM_START = "start_date"
KNOWN_FROM_PUBLISHED = "source_published_at"


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
    known = known_from(record, start_field)
    if known is None:
        return None
    if as_of < known[0]:
        return None
    if start is None:
        return _undated(family, record, as_of, window_days, stored, known)

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
    reported_late = known[0] > end
    if as_of > max(end, known[0]) + window:
        return None
    return DateScope(
        date_family=family,
        date_status="dated",
        in_scope_reason=DATED_LATE_REASON if reported_late else _DATED_REASONS[family],
        dates=stored,
        known_from=known[0].isoformat(),
        known_from_rule=known[1],
        open_end=open_end,
    )


def known_from(record: dict[str, Any], start_field: str) -> tuple[date, str] | None:
    """The date the record became known, and the rule that set it.

    Rule 3 first: a stored `known_from` (announced in advance, or disclosed
    later) overrides the others. Otherwise rule 1, the family's start date (a
    sudden event is known as it happens, whatever the report date), then
    rule 2, `source.published_at`.
    Returns None when none is usable, so the record is never in scope.
    """
    stored = _iso(record.get("known_from"))
    if stored is not None:
        return stored, KNOWN_FROM_STORED
    start = _iso(record.get(start_field))
    if start is not None:
        return start, KNOWN_FROM_START
    published = _iso((record.get("source") or {}).get("published_at"))
    if published is not None:
        return published, KNOWN_FROM_PUBLISHED
    return None


def _undated(
    family: str,
    record: dict[str, Any],
    as_of: date,
    window_days: int,
    stored: dict[str, Any],
    known: tuple[date, str],
) -> DateScope | None:
    """A record without its date field is only an undated candidate, and only
    when its stored search window contains as_of (no event window applied).
    If it became known after the search window ended, it is a candidate for
    event_window_days from known_from instead. The caller has already checked
    that it is known by as_of."""
    sw = record.get("search_window") or {}
    sw_start, sw_end = _iso(sw.get("start")), _iso(sw.get("end"))
    if sw_start is None or sw_end is None:
        return None
    if not _overlaps_study(sw_start, sw_end):
        return None
    if known[0] > sw_end:
        if as_of > known[0] + timedelta(days=window_days):
            return None
        reason = UNDATED_LATE_REASON
    elif sw_start <= as_of <= sw_end:
        reason = UNDATED_REASON
    else:
        return None
    return DateScope(
        date_family=family,
        date_status="undated_candidate",
        in_scope_reason=reason,
        dates=stored,
        known_from=known[0].isoformat(),
        known_from_rule=known[1],
    )


def _overlaps_study(start: date, end: date) -> bool:
    return start <= STUDY_END and end >= STUDY_START
