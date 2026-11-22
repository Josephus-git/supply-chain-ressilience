"""lookup_evidence: the risk engine, called with a fixed as_of_date.

- One `lookup_suppliers` call per candidate supplier (one payload each, so two
  supplier nodes whose names normalise alike can never collide).
- Country-level lookups (R4, R4a): the engine has no country-only operation,
  so the app sends a payload whose only real key is the country (a
  placeholder supplier name that matches no record, the country's currency,
  no ports, carriers or vessels). The engine's own rules then decide which
  records link by country alone, with the same date rules as every lookup.
  Countries come from the question text (`mentioned`) or from the Cypher LLM's
  labelled suggestions (`suggested`).

The engine stays deterministic; nothing here calls an LLM.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from supplier_risk_engine.engine import lookup_suppliers
from supplier_risk_engine.engine.normalise import normalise_text
from supplier_risk_engine.engine.reference import COUNTRY_NAMES, ISO_COUNTRY_CODES
from supplier_risk_engine.loader import LoadedDatabase

from ..evidence_api import EvidenceView
from .profiles import CURRENCY, EVENT_WINDOW_DAYS, IMPORTING_COUNTRY, SCHEMA_VERSION, engine_payload

# Country names too ambiguous to detect in free text ("tell us ...").
_AMBIGUOUS_NAMES = {"us", "u s"}
COUNTRY_PLACEHOLDER = "Country-level lookup {code} (no supplier)"


def mentioned_countries(*texts: str) -> list[str]:
    """ISO codes of countries named in the texts (whole words, engine's name table)."""
    blob = f" {normalise_text(' '.join(t for t in texts if t))} "
    first: dict[str, int] = {}
    for name, code in COUNTRY_NAMES.items():
        if name in _AMBIGUOUS_NAMES:
            continue
        m = re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", blob)
        if m and m.start() < first.get(code, len(blob)):
            first[code] = m.start()
    return sorted(first, key=first.get)


def country_payload(code: str, as_of: date, *, query: str) -> dict[str, Any] | None:
    currency = CURRENCY.get(code)
    if code not in ISO_COUNTRY_CODES or currency is None:
        return None
    name = COUNTRY_PLACEHOLDER.format(code=code)
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of_date": as_of.isoformat(),
        "event_window_days": EVENT_WINDOW_DAYS,
        "request_context": {"bom_line_id": f"COUNTRY-{code}", "component_query": query[:200], "importing_country": IMPORTING_COUNTRY},
        "suppliers": [{"supplier_id": f"country:{code}", "supplier_name": name, "country": code, "parent_companies": [name], "currency": currency}],
    }


def _compact_link(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": report["evidence_id"],
        "risk_type": report["risk_type"],
        "link_basis": report["link_basis"],
        "link_strength": report["link_strength"],
        "matched_values": report.get("matched_values") or [],
        "date_status": report.get("date_status"),
        "in_scope_reason": report.get("in_scope_reason"),
        "labels": report.get("labels") or [],
        "approximated": report.get("approximated", False),
    }


def record_brief(view: EvidenceView, evidence_id: str) -> dict[str, Any] | None:
    s = view.by_id.get(evidence_id)
    if s is None:
        return None
    d = s["dates"]
    return {
        "evidence_id": evidence_id,
        "risk_type": s["risk_type"],
        "risk_label": s["risk_label"],
        "title": s["title"],
        "description": s["description"],
        "start": d.get("start"),
        "end": d.get("end"),
        "date_family": d.get("family"),
        "verification_status": s["verification_status"],
        "limitations": s["limitations"],
        "measures": s["measures"],
        "countries": [c["code"] for c in s["countries"]],
        "publisher": s["source"]["publisher"],
    }


def lookup_evidence(
    db: LoadedDatabase,
    view: EvidenceView,
    profiles: dict[str, dict[str, Any]],
    as_of: date,
    *,
    query: str,
    countries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Engine results per supplier and per country, plus a brief of every linked record.

    `countries` is a list of `{"code", "basis": "mentioned"|"suggested", "reason"}`.
    """
    by_supplier: dict[str, Any] = {}
    for n, (sid, profile) in enumerate(sorted(profiles.items()), start=1):
        payload = engine_payload(profile, as_of, line_id=f"ASSESS-S{n:02d}", query=query)
        result = lookup_suppliers(payload, db.index)
        reports = result["suppliers"][0]["linked_reports"] if result["status"] == "completed" else []
        by_supplier[sid] = {
            "payload": payload,
            "status": result["status"],
            "errors": result.get("errors"),
            "links": [_compact_link(r) for r in reports],
            "result": result,
        }

    by_country: dict[str, Any] = {}
    skipped: list[dict[str, Any]] = []
    for c in countries:
        code = c["code"]
        if code in by_country:
            continue
        payload = country_payload(code, as_of, query=query)
        if payload is None:
            skipped.append({**c, "reason_skipped": "No currency in the app's table for this country, so no engine payload can be built."})
            continue
        result = lookup_suppliers(payload, db.index)
        reports = result["suppliers"][0]["linked_reports"] if result["status"] == "completed" else []
        by_country[code] = {
            **c,
            "payload": payload,
            "status": result["status"],
            "errors": result.get("errors"),
            "links": [_compact_link(r) for r in reports],
            "result": result,
        }

    ids = {link["evidence_id"] for part in (*by_supplier.values(), *by_country.values()) for link in part["links"]}
    records = {eid: brief for eid in sorted(ids) if (brief := record_brief(view, eid)) is not None}
    return {
        "as_of_date": as_of.isoformat(),
        "event_window_days": EVENT_WINDOW_DAYS,
        "by_supplier": by_supplier,
        "by_country": by_country,
        "countries_skipped": skipped,
        "records": records,
        "snapshot_id": db.index.snapshot_id,
    }
