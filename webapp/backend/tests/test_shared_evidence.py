"""R22: identical links shared by every supplier are listed once under SHARED EVIDENCE.

No Neo4j or LLM needed.

    .venv/bin/python -m unittest discover -s webapp/backend/tests -t .
"""

from __future__ import annotations

import json
import unittest

from webapp.backend.pipeline.report import check_citations, report_inputs


def _profile(name: str) -> dict:
    return {
        "supplier_name": name,
        "footprint_window": {"shipments": 3, "first_arrival": "2025-01-01", "last_arrival": "2025-06-01"},
        "country": "MY",
        "parent_companies": [name],
        "exit_ports": [],
        "carriers": [],
    }


def _link(eid: str, basis: str, values: list[str]) -> dict:
    return {"evidence_id": eid, "risk_type": "tariff", "link_basis": basis, "link_strength": "weak",
            "matched_values": values, "date_status": "dated"}


TARIFF = _link("TARIFF-US", "importing_country", ["US"])
EVIDENCE = {
    "by_supplier": {
        "a": {"links": [TARIFF, _link("PORT-MY", "port_country", ["MY"])]},
        "b": {"links": [TARIFF]},
    },
    "by_country": {},
    "records": {},
}


class SharedEvidenceTests(unittest.TestCase):
    def _inputs(self, profiles):
        return report_inputs(items=[{"n": 1, "text": "fan"}], candidates={}, profiles=profiles, inactive=[], evidence=EVIDENCE)

    def test_shared_link_listed_once(self):
        out = self._inputs({"a": _profile("A"), "b": _profile("B")})
        self.assertEqual(out["shared_evidence"], ["TARIFF-US"])
        suppliers = json.loads(out["sections"]["suppliers"])
        a, b = suppliers
        self.assertEqual([l["evidence_id"] for l in a["evidence_links"]], ["PORT-MY"])
        self.assertEqual(b["evidence_links"], "none beyond SHARED EVIDENCE")
        self.assertEqual(out["sections"]["suppliers"].count("TARIFF-US"), 0)
        self.assertEqual(json.loads(out["sections"]["shared"])[0]["evidence_id"], "TARIFF-US")

    def test_single_supplier_not_hoisted(self):
        out = self._inputs({"a": _profile("A")})
        self.assertEqual(out["shared_evidence"], [])
        self.assertEqual(out["sections"]["shared"], "(none)")

    def test_citation_scope_unchanged(self):
        report = {"summary": {}, "items": [{"item": 1, "candidates": [{"supplier_id": "b", "risks": [{"text": "x", "citations": ["TARIFF-US"]}]}]}]}
        res = check_citations(report, {"TARIFF-US": {"kind": "evidence"}}, EVIDENCE)
        self.assertEqual(res["verified"], 1)
        self.assertEqual(res["with_note"], 0)


if __name__ == "__main__":
    unittest.main()
