"""Payload validation (plan section 6.3).

`parse_request` returns either a `LookupRequest` or a list of structured
`ValidationError`s. It collects every error it can find rather than stopping
at the first, so a caller can fix a payload in one pass.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .models import (
    EngineValidationError,
    ExposureEntry,
    LookupRequest,
    Notice,
    RequestContext,
    Supplier,
    ValidationError,
)
from .normalise import country_to_code, normalise_name
from .reference import COASTS, ISO_CURRENCY_CODES

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TOP_LEVEL_KEYS = {
    "schema_version",
    "as_of_date",
    "event_window_days",
    "request_context",
    "suppliers",
}
CONTEXT_KEYS = {"bom_line_id", "component_query", "importing_country"}
SUPPLIER_KEYS = {
    "supplier_id",
    "supplier_name",
    "country",
    "parent_companies",
    "currency",
    "hs_codes",
    "exit_ports",
    "entry_ports",
    "carriers",
    "vessels",
    "buyers",
    "footprint_window",
}
LIST_KEYS = ("hs_codes", "exit_ports", "entry_ports", "carriers", "vessels", "buyers")


class _Collector:
    def __init__(self) -> None:
        self.errors: list[ValidationError] = []
        self.warnings: list[Notice] = []

    def error(self, field: str, code: str, message: str) -> None:
        self.errors.append(ValidationError(field, code, message))

    def warn(self, field: str, code: str, message: str) -> None:
        self.warnings.append(Notice(code=code, message=message, field=field))


def parse_request(
    payload: Any, *, raise_on_error: bool = False
) -> tuple[LookupRequest | None, list[ValidationError], list[Notice]]:
    """Validate a payload and build a typed request.

    Returns (request, errors, warnings). `request` is None when there are
    errors. With `raise_on_error=True`, errors raise `EngineValidationError`.
    """
    c = _Collector()
    request = _parse(payload, c)
    if c.errors:
        if raise_on_error:
            raise EngineValidationError(c.errors)
        return None, c.errors, c.warnings
    return request, [], c.warnings


def _parse(payload: Any, c: _Collector) -> LookupRequest | None:
    if not isinstance(payload, dict):
        c.error("$", "invalid_type", "The payload must be a JSON object.")
        return None
    _warn_unknown(payload, TOP_LEVEL_KEYS, "", c)

    as_of = _parse_date(payload, "as_of_date", c)
    window = _parse_window(payload, c)
    context = _parse_context(payload, c)
    suppliers = _parse_suppliers(payload, c)

    schema_version = payload.get("schema_version")
    if schema_version is not None and not isinstance(schema_version, str):
        c.error("schema_version", "invalid_type", "schema_version must be a string.")

    if c.errors:
        return None
    assert as_of is not None and window is not None and context is not None
    return LookupRequest(
        as_of_date=as_of,
        event_window_days=window,
        request_context=context,
        suppliers=tuple(suppliers),
        schema_version=schema_version,
    )


def _warn_unknown(obj: dict, allowed: set[str], prefix: str, c: _Collector) -> None:
    for key in sorted(set(obj) - allowed):
        path = f"{prefix}.{key}" if prefix else key
        c.warn(path, "unknown_key", f"Unknown key '{key}' was ignored.")


def _parse_date(obj: dict, key: str, c: _Collector) -> date | None:
    if key not in obj or obj[key] is None:
        c.error(key, "missing", f"{key} is required (ISO date, YYYY-MM-DD).")
        return None
    value = obj[key]
    if not isinstance(value, str) or not _ISO_DATE.match(value):
        c.error(key, "invalid_date", f"{key} must be an ISO date string, YYYY-MM-DD.")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        c.error(key, "invalid_date", f"{key} '{value}' is not a valid calendar date.")
        return None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_window(payload: dict, c: _Collector) -> int | None:
    if "event_window_days" not in payload or payload["event_window_days"] is None:
        c.error("event_window_days", "missing", "event_window_days is required.")
        return None
    value = payload["event_window_days"]
    if not _is_int(value):
        c.error(
            "event_window_days",
            "invalid_type",
            "event_window_days must be a non-negative integer.",
        )
        return None
    if value < 0:
        c.error("event_window_days", "negative", "event_window_days must not be negative.")
        return None
    return value


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _parse_country(value: Any, field: str, c: _Collector) -> str | None:
    if value is None:
        c.error(field, "missing", f"{field} is required.")
        return None
    if not _nonempty_str(value):
        c.error(field, "empty", f"{field} must be a non-empty country code or name.")
        return None
    code = country_to_code(value)
    if code is None:
        c.error(
            field,
            "unknown_country",
            f"'{value}' is not an ISO 3166-1 alpha-2 code or a country name in "
            "the reviewed mapping table.",
        )
    return code


def _parse_context(payload: dict, c: _Collector) -> RequestContext | None:
    ctx = payload.get("request_context")
    if ctx is None:
        c.error("request_context", "missing", "request_context is required.")
        return None
    if not isinstance(ctx, dict):
        c.error("request_context", "invalid_type", "request_context must be an object.")
        return None
    _warn_unknown(ctx, CONTEXT_KEYS, "request_context", c)
    importing = _parse_country(
        ctx.get("importing_country"), "request_context.importing_country", c
    )
    if importing is None:
        return None
    return RequestContext(
        importing_country=importing,
        bom_line_id=ctx.get("bom_line_id"),
        component_query=ctx.get("component_query"),
    )


def _parse_suppliers(payload: dict, c: _Collector) -> list[Supplier]:
    raw = payload.get("suppliers")
    if raw is None:
        c.error("suppliers", "missing", "suppliers is required.")
        return []
    if not isinstance(raw, list):
        c.error("suppliers", "invalid_type", "suppliers must be an array.")
        return []
    if not raw:
        c.error("suppliers", "empty", "suppliers must contain at least one supplier.")
        return []

    suppliers: list[Supplier] = []
    seen: dict[tuple[str, str], int] = {}
    for i, entry in enumerate(raw):
        supplier = _parse_supplier(entry, f"suppliers[{i}]", c)
        if supplier is None:
            continue
        key = (normalise_name(supplier.supplier_name), supplier.country)
        if key in seen:
            c.error(
                f"suppliers[{i}]",
                "duplicate_supplier",
                f"Same normalised name and country as suppliers[{seen[key]}].",
            )
        else:
            seen[key] = i
        suppliers.append(supplier)
    return suppliers


def _parse_supplier(entry: Any, path: str, c: _Collector) -> Supplier | None:
    if not isinstance(entry, dict):
        c.error(path, "invalid_type", "Each supplier must be an object.")
        return None
    _warn_unknown(entry, SUPPLIER_KEYS, path, c)
    before = len(c.errors)

    name = entry.get("supplier_name")
    if name is None:
        c.error(f"{path}.supplier_name", "missing", "supplier_name is required.")
    elif not _nonempty_str(name):
        c.error(f"{path}.supplier_name", "empty", "supplier_name must be a non-empty string.")

    country = _parse_country(entry.get("country"), f"{path}.country", c)

    parents = entry.get("parent_companies")
    parent_list: list[str] = []
    if parents is None:
        c.error(
            f"{path}.parent_companies",
            "missing",
            "parent_companies is required. Pass the supplier's own name if it "
            "has no parent.",
        )
    elif not isinstance(parents, list) or not parents:
        c.error(
            f"{path}.parent_companies",
            "empty",
            "parent_companies must be a non-empty list of names.",
        )
    else:
        for j, parent in enumerate(parents):
            if not _nonempty_str(parent):
                c.error(
                    f"{path}.parent_companies[{j}]",
                    "empty",
                    "Parent names must be non-empty strings.",
                )
            else:
                parent_list.append(parent)

    currency = entry.get("currency")
    if currency is None:
        c.error(f"{path}.currency", "missing", "currency is required (ISO 4217).")
    elif not isinstance(currency, str) or currency.strip().upper() not in ISO_CURRENCY_CODES:
        c.error(f"{path}.currency", "unknown_currency", f"'{currency}' is not an ISO 4217 code.")

    lists = {key: _parse_list(entry, key, path, c) for key in LIST_KEYS}

    if len(c.errors) > before:
        return None
    return Supplier(
        supplier_id=entry.get("supplier_id"),
        supplier_name=name,
        country=country,  # type: ignore[arg-type]
        parent_companies=tuple(parent_list),
        currency=currency.strip().upper(),
        **lists,
    )


def _parse_list(entry: dict, key: str, path: str, c: _Collector) -> tuple[ExposureEntry, ...]:
    raw = entry.get(key)
    if raw is None:
        return ()
    field = f"{path}.{key}"
    if not isinstance(raw, list):
        c.error(field, "invalid_type", f"{key} must be an array.")
        return ()
    out: list[ExposureEntry] = []
    for j, item in enumerate(raw):
        parsed = _parse_entry(item, key, f"{field}[{j}]", c)
        if parsed is not None:
            out.append(parsed)
    return tuple(out)


def _parse_entry(item: Any, key: str, path: str, c: _Collector) -> ExposureEntry | None:
    if not isinstance(item, dict):
        c.error(path, "invalid_type", "Each entry must be an object.")
        return None
    ok = True

    shipments = item.get("shipments")
    if shipments is not None and (not _is_int(shipments) or shipments < 0):
        c.error(f"{path}.shipments", "invalid_count", "shipments must be a non-negative integer.")
        ok = False

    name = code = country = coast = None
    if key == "hs_codes":
        code = item.get("code")
        if not isinstance(code, str) or not code.strip() or not code.strip().isdigit():
            c.error(
                f"{path}.code",
                "invalid_hs_code",
                "HS codes must be strings of digits (keep leading zeros).",
            )
            ok = False
        else:
            code = code.strip()
    else:
        name = item.get("name")
        if not _nonempty_str(name):
            c.error(f"{path}.name", "empty", "name must be a non-empty string.")
            ok = False
        raw_code = item.get("code")
        if raw_code is not None:
            if not _nonempty_str(raw_code):
                c.error(f"{path}.code", "empty", "code, when given, must be a non-empty string.")
                ok = False
            else:
                code = raw_code.strip()
        if key in ("exit_ports", "entry_ports"):
            if item.get("country") is not None:
                country = _parse_country(item.get("country"), f"{path}.country", c)
                ok = ok and country is not None
            coast = item.get("coast")
            if coast is not None and coast not in COASTS:
                c.error(
                    f"{path}.coast",
                    "invalid_coast",
                    f"coast must be one of {sorted(COASTS)}.",
                )
                ok = False

    if not ok:
        return None
    return ExposureEntry(
        name=name,
        code=code,
        country=country,
        coast=coast,
        shipments=shipments,
        raw=dict(item),
    )
