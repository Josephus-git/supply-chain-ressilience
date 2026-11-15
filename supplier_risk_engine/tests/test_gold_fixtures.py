"""The 42 fixture payloads against the gold set (plan section 10), plus the
stored database through all three operations."""

import copy
import json
import unittest

from supplier_risk_engine.engine import (
    ENGINE_VERSION,
    build_index,
    describe_database,
    get_evidence,
    lookup_suppliers,
)

from .helpers import load_database, load_gold, load_payload


class GoldFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gold = load_gold()
        cls.records = load_database()
        cls.index = build_index(cls.records)

    def test_fixture_count(self):
        self.assertEqual(len(self.gold["fixtures"]), 42)

    def test_each_fixture_returns_exactly_its_expected_ids(self):
        for fixture in self.gold["fixtures"]:
            with self.subTest(fixture=fixture["fixture"]):
                result = lookup_suppliers(load_payload(fixture["payload"]), self.index)
                self.assertEqual(result["status"], "completed", result.get("errors"))
                got = {r["evidence_id"] for r in result["suppliers"][0]["linked_reports"]}
                expected = set(fixture["expected_ids"])
                self.assertEqual(
                    got, expected,
                    f"missed {sorted(expected - got)}, unexpected {sorted(got - expected)}",
                )

    def test_each_fixture_link_detail(self):
        for fixture in self.gold["fixtures"]:
            result = lookup_suppliers(load_payload(fixture["payload"]), self.index)
            by_id = {r["evidence_id"]: r for r in result["suppliers"][0]["linked_reports"]}
            for eid, exp in fixture["expected_links"].items():
                with self.subTest(fixture=fixture["fixture"], evidence_id=eid):
                    r = by_id[eid]
                    self.assertEqual(r["link_basis"], exp["link_basis"])
                    self.assertEqual(r["link_strength"], exp["link_strength"])
                    self.assertEqual(sorted(r["matched_values"]), sorted(exp["matched_values"]))
                    self.assertEqual(r["known_from"], exp["known_from"])
                    self.assertEqual(r["known_from_rule"], exp["known_from_rule"])
                    self.assertLessEqual(r["known_from"], fixture["as_of_date"])
                    if exp["in_scope"] == "dated":
                        self.assertEqual(r["date_status"], "dated")
                    else:
                        self.assertEqual(r["date_status"], "undated_candidate")
                        self.assertEqual(r["in_scope_reason"], exp["in_scope"])

    def test_expected_exclusions_are_not_returned(self):
        for fixture in self.gold["fixtures"]:
            result = lookup_suppliers(load_payload(fixture["payload"]), self.index)
            got = {r["evidence_id"] for r in result["suppliers"][0]["linked_reports"]}
            for eid in fixture.get("expected_exclusions") or {}:
                with self.subTest(fixture=fixture["fixture"], evidence_id=eid):
                    self.assertNotIn(eid, got)

    def test_stored_limitations_returned_unchanged(self):
        fixture = self.gold["fixtures"][0]
        result = lookup_suppliers(load_payload(fixture["payload"]), self.index)
        for r in result["suppliers"][0]["linked_reports"]:
            with self.subTest(evidence_id=r["evidence_id"]):
                stored = self.index.by_id[r["evidence_id"]][1]
                self.assertEqual(r["limitations"], stored["limitations"])
                self.assertEqual(r["verification_status"], stored["verification_status"])


class StoredKnownFrom(unittest.TestCase):
    """Phase 6 data checks (plan section 5.2)."""

    @classmethod
    def setUpClass(cls):
        cls.records = load_database()

    def test_every_record_has_a_known_from_basis(self):
        from supplier_risk_engine.engine.dates import FAMILY_FIELDS, known_from
        from supplier_risk_engine.engine.reference import DATE_FAMILY

        for risk_type, recs in self.records.items():
            start_field = FAMILY_FIELDS[DATE_FAMILY[risk_type]][0]
            for rec in recs:
                with self.subTest(evidence_id=rec["evidence_id"]):
                    self.assertIsNotNone(known_from(rec, start_field))

    def test_stored_known_from_has_its_basis_in_approximations(self):
        for recs in self.records.values():
            for rec in recs:
                if "known_from" not in rec:
                    continue
                with self.subTest(evidence_id=rec["evidence_id"]):
                    entries = [a for a in rec.get("approximations") or []
                               if a.get("field") == "known_from"]
                    self.assertEqual(len(entries), 1)
                    self.assertEqual(entries[0]["value"], rec["known_from"])
                    self.assertTrue(entries[0]["basis"])


class Determinism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gold = load_gold()
        cls.records = load_database()

    def test_repeated_runs_identical(self):
        for fixture in self.gold["fixtures"]:
            with self.subTest(fixture=fixture["fixture"]):
                p = load_payload(fixture["payload"])
                first = json.dumps(lookup_suppliers(p, self.records), sort_keys=True)
                second = json.dumps(lookup_suppliers(copy.deepcopy(p), build_index(self.records)),
                                    sort_keys=True)
                self.assertEqual(first, second)

    def test_record_order_does_not_change_output(self):
        shuffled = {rt: list(reversed(recs)) for rt, recs in reversed(list(self.records.items()))}
        p = load_payload(self.gold["fixtures"][0]["payload"])
        self.assertEqual(json.dumps(lookup_suppliers(p, self.records), sort_keys=True),
                         json.dumps(lookup_suppliers(p, shuffled), sort_keys=True))

    def test_inputs_not_modified(self):
        records = load_database()
        before = json.dumps(records, sort_keys=True)
        p = load_payload(self.gold["fixtures"][0]["payload"])
        p_before = json.dumps(p, sort_keys=True)
        lookup_suppliers(p, records)
        self.assertEqual(json.dumps(records, sort_keys=True), before)
        self.assertEqual(json.dumps(p, sort_keys=True), p_before)


class Operations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(load_database())

    def test_describe_database(self):
        d = describe_database(self.index)
        self.assertEqual(d["record_count"], 109)
        self.assertEqual(len(d["risk_types"]), 18)
        self.assertEqual(d["study_window"], {"start": "2025-01-01", "end": "2026-09-30"})
        self.assertEqual(d["engine_version"], ENGINE_VERSION)
        self.assertEqual(d["unknown_risk_types"], [])
        counts = {r["risk_type"]: r["records"] for r in d["risk_types"]}
        self.assertEqual(counts["tariffs_and_duties"], 15)
        self.assertEqual(counts["goods_in_transit_loss_theft_or_damage"], 8)

    def test_get_evidence_found(self):
        e = get_evidence("CYBER-CLAIM-2026-001", self.index)
        self.assertEqual(e["status"], "found")
        self.assertEqual(e["risk_type"], "cyberattack")
        self.assertEqual(e["record"], self.index.by_id["CYBER-CLAIM-2026-001"][1])

    def test_get_evidence_not_found(self):
        for bad in ("NOPE-001", None, 42):
            with self.subTest(bad=bad):
                self.assertEqual(get_evidence(bad, self.index)["status"], "not_found")

    def test_snapshot_id_stable_and_in_results(self):
        again = build_index(load_database())
        self.assertEqual(self.index.snapshot_id, again.snapshot_id)
        self.assertEqual(build_index(load_database(), data_snapshot_id="snap-1").snapshot_id, "snap-1")

    def test_duplicate_evidence_id_rejected(self):
        with self.assertRaises(ValueError):
            build_index({"labour_disruption": [{"evidence_id": "X"}, {"evidence_id": "X"}]})

    def test_unknown_risk_type_ignored_with_warning(self):
        from .helpers import payload
        records = {"mystery": [{"evidence_id": "M"}]}
        result = lookup_suppliers(payload(), records)
        self.assertEqual([w["code"] for w in result["warnings"]], ["unknown_risk_type"])


if __name__ == "__main__":
    unittest.main()
