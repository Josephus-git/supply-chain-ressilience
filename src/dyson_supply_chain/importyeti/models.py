"""Models and validation for documented ImportYeti PowerQuery responses."""

from dataclasses import dataclass, field
from typing import Any


class ResponseFormatError(ValueError):
    """Raised when an API response does not match the documented envelope."""


@dataclass(frozen=True)
class BOLPage:
    records: list[dict[str, Any]]
    total_count: int
    raw: dict[str, Any]
    request_cost: float | int | None = None
    credits_remaining: float | int | None = None

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "BOLPage":
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ResponseFormatError("Expected PowerQuery data.data to be a list")
        total = data.get("totalCount")
        if not isinstance(total, int) or total < 0:
            raise ResponseFormatError("Expected non-negative integer data.totalCount")
        records = [row for row in data["data"] if isinstance(row, dict)]
        return cls(records, total, payload, payload.get("requestCost"), payload.get("creditsRemaining"))


def validate_record(record: dict[str, Any]) -> list[str]:
    """Return missing/invalid required-field messages without discarding a row."""
    errors: list[str] = []
    if not isinstance(record.get("bol_number"), str) or not record["bol_number"].strip():
        errors.append("missing bol_number")
    if "arrival_date" not in record:
        errors.append("missing arrival_date")
    return errors


@dataclass
class ExtractionStats:
    retrieved: int = 0
    retained: int = 0
    rejected: int = 0
    deduplicated: int = 0
    pages: int = 0
    errors: list[str] = field(default_factory=list)

