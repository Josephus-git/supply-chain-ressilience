"""Shared builders for the tests.

`load_database` returns the stored records through the real loader
(supplier_risk_engine.loader), so manifest checks run on every test load.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from supplier_risk_engine import loader
from supplier_risk_engine.engine import lookup_suppliers

PACKAGE_DIR = Path(__file__).resolve().parent.parent
DATABASE_DIR = PACKAGE_DIR / "risk_evidence" / "database"
EXAMPLES_DIR = PACKAGE_DIR / "examples"


def load_database() -> dict[str, list[dict[str, Any]]]:
    return loader.load_database(DATABASE_DIR).records


def load_gold() -> dict[str, Any]:
    return json.loads((EXAMPLES_DIR / "expected_ids.json").read_text(encoding="utf-8"))


def load_payload(relative: str) -> dict[str, Any]:
    return json.loads((EXAMPLES_DIR / relative).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Synthetic payloads and records


def supplier(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "supplier_id": "S-TEST",
        "supplier_name": "Acme Widgets Sdn Bhd",
        "country": "MY",
        "parent_companies": ["Acme Holdings Ltd"],
        "currency": "MYR",
    }
    base.update(overrides)
    return base


def payload(*suppliers: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": "1.1",
        "as_of_date": "2025-06-15",
        "event_window_days": 0,
        "request_context": {
            "bom_line_id": "TEST-L1",
            "component_query": "test component",
            "importing_country": "US",
        },
        "suppliers": list(suppliers) or [supplier()],
    }
    base.update(overrides)
    return base


SEARCH_WINDOW = {"start": "2025-01-01", "end": "2026-09-30"}


def record(evidence_id: str, **fields: Any) -> dict[str, Any]:
    """A minimal stored record. Defaults give an event interval covering
    2025-06-01 to 2025-06-30, which all `event_interval` types read."""
    base: dict[str, Any] = {
        "evidence_id": evidence_id,
        "event_start": "2025-06-01",
        "event_end": "2025-06-30",
        "related_evidence_ids": [],
        "verification_status": "test",
        "limitations": ["test record"],
        "search_window": dict(SEARCH_WINDOW),
    }
    base.update(fields)
    return base


def run(records: dict[str, list[dict[str, Any]]], *suppliers: dict[str, Any], **overrides: Any):
    """Run a lookup and return the full result dict."""
    return lookup_suppliers(payload(*suppliers, **overrides), copy.deepcopy(records))


def reports(records, *suppliers, **overrides) -> dict[str, dict[str, Any]]:
    """Linked reports for the first supplier, keyed by evidence_id."""
    result = run(records, *suppliers, **overrides)
    assert result["status"] == "completed", result.get("errors")
    return {r["evidence_id"]: r for r in result["suppliers"][0]["linked_reports"]}
