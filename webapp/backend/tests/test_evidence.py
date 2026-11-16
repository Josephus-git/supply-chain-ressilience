"""Evidence Library endpoints (phase 4). No Neo4j or OpenAI needed: the graph
supplier list comes from a fake client, and the records are the real stored
database (109 records, 18 risk types).

    .venv/bin/python -m unittest webapp.backend.tests.test_evidence
"""

from __future__ import annotations

import unittest
from collections import Counter

from fastapi.testclient import TestClient

from supplier_risk_engine.loader import load_database
from webapp.backend.main import create_app

DB = load_database()


class FakeNeo4j:
    """Supplier nodes as `_graph_suppliers` reads them."""

    rows = [
        {"id": "VS-MY", "name": "VS Industry Berhad", "company": "Vs Industrial Berhad", "country": "MY"},
        {"id": "KINPO-PH", "name": "Kinpo Electronics", "company": "Kinpo Electronics Philippines", "country": "PH"},
        {"id": "HIP-TW", "name": "Hi P", "company": "Hi P Philippines Technology Corpora", "country": "TW"},
    ]

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def read(self, *args, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Neo4j down")
        return list(self.rows)

    def verify(self):
        pass

    def close(self):
        pass


class EvidenceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.neo4j = FakeNeo4j()
        cls.http = TestClient(create_app(neo4j_client=cls.neo4j, evidence_db=DB))
        cls.http.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.http.__exit__(None, None, None)

    def get(self, url: str, status: int = 200, **params) -> dict:
        r = self.http.get(url, params=params)
        self.assertEqual(r.status_code, status, r.text[:300])
        return r.json()

    def ids(self, **params) -> list[str]:
        return sorted(r["evidence_id"] for r in self.get("/api/evidence", **params)["records"])

    # ------------------------------------------------------------- no filters

    def test_unfiltered_returns_all_records(self):
        body = self.get("/api/evidence")
        self.assertEqual(body["total"], 109)
        self.assertEqual(body["count"], 109)
        self.assertEqual(len({r["evidence_id"] for r in body["records"]}), 109)
        self.assertEqual(body["data_snapshot_id"], DB.snapshot_id)

    def test_facet_counts_match_db(self):
        facets = self.get("/api/evidence")["facets"]
        expected = {rt: len(records) for rt, records in DB.records.items()}
        got = {f["value"]: f["count"] for f in facets["risk_type"]}
        self.assertEqual(len(got), 18)
        self.assertEqual(got, expected)
        self.assertEqual(sum(got.values()), DB.record_count)

        # Country facet: each record counted once per distinct code it carries.
        records = self.get("/api/evidence")["records"]
        counts = Counter(c["code"] for r in records for c in r["countries"])
        self.assertEqual({f["value"]: f["count"] for f in facets["country"]}, dict(counts))
        self.assertEqual(counts["ID"], 1)

    def test_facets_ignore_their_own_filter(self):
        facets = self.get("/api/evidence", risk_type="labour_disruption")["facets"]
        types = {f["value"]: f["count"] for f in facets["risk_type"]}
        self.assertEqual(types["port_disruption"], len(DB.records["port_disruption"]))
        countries = {f["value"]: f["count"] for f in facets["country"]}
        self.assertEqual(countries, {"PH": 1, "US": 3})

    # ---------------------------------------------------------------- filters

    def test_risk_type_filter(self):
        self.assertEqual(
            self.ids(risk_type="labour_disruption"),
            [
                "LABOUR-2025-PH-NEXPERIA-001",
                "LABOUR-2026-US-AXLE-001",
                "LABOUR-2026-US-PACKAGING-001",
                "LABOUR-2026-US-WAREHOUSE-001",
            ],
        )
        both = self.ids(risk_type="labour_disruption,cyberattack")
        self.assertEqual(len(both), 5)
        self.assertIn("CYBER-CLAIM-2026-001", both)
        self.get("/api/evidence", 400, risk_type="not_a_type")

    def test_country_filter(self):
        self.assertEqual(self.ids(country="ID"), ["TRANSIT-2026-STRAIT-001"])
        self.assertEqual(self.ids(country="id"), ["TRANSIT-2026-STRAIT-001"])
        self.assertEqual(
            self.ids(risk_type="tariffs_and_duties", country="TW"),
            ["TARIFF-2025-US-TW-RECIPROCAL", "TARIFF-2026-US-TW-FORCED-LABOR-301"],
        )
        # Trade-lane origins count: the Suez diversion lists CN, TW, MY, SG, PH -> US.
        self.assertIn("ROUTE-2025-SUEZ-001", self.ids(country="PH"))

    def test_date_overlap_filter(self):
        self.assertEqual(
            self.ids(date_from="2025-03-01", date_to="2025-03-10"),
            [
                "CONCENTRATION-2025-MALACCA-OIL-001",  # observation 2025-01-01..06-30
                "CONCENTRATION-2025-MY-VS-001",  # observation 2024-08-01..2025-07-31
                "FX-2025-2026-USD-CNY-001",
                "FX-2025-2026-USD-MYR-001",
                "FX-2025-2026-USD-PHP-001",
                "FX-2025-2026-USD-SGD-001",
                "FX-2025-2026-USD-TWD-001",
                "FX-2025-DYSON-QUALITATIVE-001",  # undated: search window 2025
                "LABOUR-2025-PH-NEXPERIA-001",  # event 03-05..03-08
                "MATERIAL-2025-MY-PE-001",  # undated: search window 02-01..03-24
                "RESTRICT-2025-CN-001",  # effective from 02-04, open-ended
                "RESTRICT-2025-US-001",  # effective from 01-16, open-ended
                "TARIFF-2025-US-CN-OPIOID-10A",  # effective 02-04..03-03
                "TARIFF-2025-US-CN-OPIOID-20",  # effective from 03-04
            ],
        )
        # A single-day event (no end date) counts as that day only.
        self.assertIn("QUALITY-2025-US-POOL-001", self.ids(date_from="2025-03-20", date_to="2025-03-20"))
        self.assertNotIn("QUALITY-2025-US-POOL-001", self.ids(date_from="2025-03-21", date_to="2025-03-31"))

    def test_open_effective_interval_runs_to_study_end(self):
        open_ended = ["RESTRICT-2025-CN-001", "RESTRICT-2025-CN-002", "RESTRICT-2025-MY-001",
                      "RESTRICT-2025-SG-001", "RESTRICT-2025-US-001"]
        self.assertEqual(self.ids(risk_type="government_restrictions", date_from="2026-09-30"), open_ended)
        self.assertEqual(self.ids(risk_type="government_restrictions", date_from="2026-10-01"), [])
        record = self.get("/api/evidence/RESTRICT-2025-CN-001")["summary"]["dates"]
        self.assertEqual(record["family"], "effective_interval")
        self.assertIsNone(record["end"])
        self.assertEqual(record["filter_range"]["end"], "2026-09-30")
        self.assertTrue(record["open_end"])

    def test_text_filter(self):
        self.assertEqual(self.ids(q="ragasa"), ["HAZARD-2025-CN-RAGASA-001", "PORT-2025-CN-RAGASA-001"])
        self.assertEqual(self.ids(q="Wan Hai"), ["VESSEL-2025-CN-001"])  # reported carrier
        self.assertEqual(
            self.ids(q="v.s. industry"),
            ["CONCENTRATION-2025-MY-VS-001", "FINANCE-2026-MY-VS-001", "FINANCE-2026-MY-VS-002",
             "FINANCE-2026-MY-VS-003", "OPERATIONS-2026-PH-VS-001"],
        )
        publisher = DB.index.by_id["PORT-2025-CN-RAGASA-001"][1]["source"]["publisher"]
        self.assertIn("PORT-2025-CN-RAGASA-001", self.ids(q=publisher))

    def test_filters_combine(self):
        self.assertEqual(self.ids(q="ragasa", risk_type="port_disruption"), ["PORT-2025-CN-RAGASA-001"])
        self.assertEqual(self.ids(q="ragasa", date_from="2025-09-23", date_to="2025-09-30"),
                         ["HAZARD-2025-CN-RAGASA-001"])

    def test_bad_dates(self):
        self.get("/api/evidence", 400, date_from="yesterday")
        self.get("/api/evidence", 400, date_from="2026-01-02", date_to="2026-01-01")

    # ----------------------------------------------------------------- detail

    def test_detail_returns_record(self):
        body = self.get("/api/evidence/PORT-2025-CN-RAGASA-001")
        stored = DB.index.by_id["PORT-2025-CN-RAGASA-001"][1]
        self.assertEqual(body["record"], stored)
        self.assertEqual(body["summary"]["risk_type"], "port_disruption")
        self.assertEqual(body["summary"]["dates"]["start"], "2025-09-22")
        self.assertEqual([r["evidence_id"] for r in body["related"]], ["HAZARD-2025-CN-RAGASA-001"])

    def test_unknown_id_is_404(self):
        self.get("/api/evidence/NOT-A-RECORD", 404)

    def test_every_related_id_resolves(self):
        for _, record in DB.index.records:
            for other in record.get("related_evidence_ids") or []:
                with self.subTest(source=record["evidence_id"], related=other):
                    self.assertIn(other, DB.index.by_id)
                    body = self.get(f"/api/evidence/{other}")
                    self.assertEqual(body["summary"]["evidence_id"], other)

    def test_every_record_has_a_summary(self):
        for r in self.get("/api/evidence")["records"]:
            with self.subTest(r["evidence_id"]):
                self.assertTrue(r["title"])
                self.assertIn(r["dates"]["family"], {"event_interval", "observation_point",
                                                    "observation_start", "effective_interval"})
                self.assertIsNotNone(r["dates"]["filter_range"])

    # ------------------------------------------------------------- graph link

    def test_graph_link_by_supplier_country(self):
        detail = self.get("/api/evidence/CONCENTRATION-2025-MY-VS-001")
        self.assertEqual([s["id"] for s in detail["graph_suppliers"]], ["supplier:VS-MY"])
        self.assertEqual(detail["summary"]["graph_supplier_ids"], ["supplier:VS-MY"])
        # US (the import side of every tariff) never links; the origin country does.
        tw = self.get("/api/evidence/TARIFF-2025-US-TW-RECIPROCAL")
        self.assertEqual([s["id"] for s in tw["graph_suppliers"]], ["supplier:HIP-TW"])
        us = self.get("/api/evidence/LABOUR-2026-US-AXLE-001")
        self.assertEqual(us["graph_suppliers"], [])

    def test_works_without_neo4j(self):
        with TestClient(create_app(neo4j_client=FakeNeo4j(fail=True), evidence_db=DB)) as http:
            body = http.get("/api/evidence").json()
            self.assertEqual(body["count"], 109)
            self.assertTrue(body["graph_error"])
            self.assertEqual(body["graph_suppliers_by_country"], {})
            self.assertEqual(http.get("/api/evidence/PORT-2025-CN-RAGASA-001").status_code, 200)


if __name__ == "__main__":
    unittest.main()
