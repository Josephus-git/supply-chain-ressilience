"""Dated retrieval and the study window (plan sections 5.2 and 5.3)."""

import unittest
from datetime import date

from supplier_risk_engine.engine.dates import (
    KNOWN_FROM_PUBLISHED,
    KNOWN_FROM_START,
    KNOWN_FROM_STORED,
    OPEN_EFFECTIVE_END,
    UNDATED_REASON,
    date_scope,
)

from .helpers import record, reports, run, supplier

D = date.fromisoformat


def scope(risk_type, rec, as_of, window=0):
    return date_scope(risk_type, rec, D(as_of), window)


class EventInterval(unittest.TestCase):
    RT = "labour_disruption"

    def setUp(self):
        self.rec = record("E", event_start="2025-06-10", event_end="2025-06-20")

    def test_boundaries_without_window(self):
        self.assertIsNotNone(scope(self.RT, self.rec, "2025-06-10"))  # on start
        self.assertIsNotNone(scope(self.RT, self.rec, "2025-06-20"))  # on end
        self.assertIsNone(scope(self.RT, self.rec, "2025-06-09"))     # one day before
        self.assertIsNone(scope(self.RT, self.rec, "2025-06-21"))     # one day after

    def test_boundaries_with_window(self):
        # The window looks back only: it extends past the end, never before the start.
        self.assertIsNone(scope(self.RT, self.rec, "2025-06-03", 7))
        self.assertIsNone(scope(self.RT, self.rec, "2025-06-09", 7))
        self.assertIsNotNone(scope(self.RT, self.rec, "2025-06-10", 7))
        self.assertIsNotNone(scope(self.RT, self.rec, "2025-06-27", 7))
        self.assertIsNone(scope(self.RT, self.rec, "2025-06-28", 7))

    def test_open_end_equals_start(self):
        rec = record("E", event_start="2025-06-10", event_end=None)
        self.assertIsNotNone(scope(self.RT, rec, "2025-06-10"))
        self.assertIsNone(scope(self.RT, rec, "2025-06-11"))
        self.assertIsNotNone(scope(self.RT, rec, "2025-06-13", 3))
        self.assertIsNone(scope(self.RT, rec, "2025-06-14", 3))
        self.assertIsNone(scope(self.RT, rec, "2025-06-10").open_end)

    def test_dated_status_and_stored_dates(self):
        s = scope(self.RT, self.rec, "2025-06-15")
        self.assertEqual(s.date_status, "dated")
        self.assertEqual(s.date_family, "event_interval")
        self.assertEqual(s.dates, {"event_start": "2025-06-10", "event_end": "2025-06-20"})
        self.assertIsNone(s.open_end)


class ObservationPoint(unittest.TestCase):
    RT = "supplier_financial_distress"

    def test_window_around_observation_date(self):
        rec = record("F", observation_date="2025-06-10")
        del rec["event_start"], rec["event_end"]
        self.assertIsNotNone(scope(self.RT, rec, "2025-06-10"))
        self.assertIsNone(scope(self.RT, rec, "2025-06-11"))
        self.assertIsNone(scope(self.RT, rec, "2025-06-05", 5))  # before: not yet known
        self.assertIsNone(scope(self.RT, rec, "2025-06-09", 5))
        self.assertIsNotNone(scope(self.RT, rec, "2025-06-15", 5))
        self.assertIsNone(scope(self.RT, rec, "2025-06-16", 5))


class ObservationStart(unittest.TestCase):
    RT = "energy_or_transport_cost_increase"

    def test_interval_and_open_end(self):
        rec = record("C", observation_start="2025-03-01", observation_end="2025-03-31")
        self.assertIsNotNone(scope(self.RT, rec, "2025-03-31"))
        self.assertIsNone(scope(self.RT, rec, "2025-04-01"))
        self.assertIsNotNone(scope(self.RT, rec, "2025-04-01", 1))

        open_rec = record("C2", observation_start="2025-03-01", observation_end=None)
        self.assertIsNotNone(scope(self.RT, open_rec, "2025-03-01"))
        self.assertIsNone(scope(self.RT, open_rec, "2025-03-02"))
        self.assertIsNone(scope(self.RT, open_rec, "2025-03-01").open_end)


class EffectiveInterval(unittest.TestCase):
    RT = "tariffs_and_duties"

    def test_closed_interval_boundaries(self):
        rec = record("T", effective_from="2025-04-01", effective_to="2025-11-09")
        self.assertIsNotNone(scope(self.RT, rec, "2025-04-01"))
        self.assertIsNotNone(scope(self.RT, rec, "2025-11-09"))
        self.assertIsNone(scope(self.RT, rec, "2025-03-31"))
        self.assertIsNone(scope(self.RT, rec, "2025-11-10"))
        # The window extends the end (gold-set interpretation effective_to_window_applies).
        self.assertIsNotNone(scope(self.RT, rec, "2025-11-21", 14))
        self.assertIsNone(scope(self.RT, rec, "2025-11-24", 14))
        # ...but never the start.
        self.assertIsNone(scope(self.RT, rec, "2025-03-31", 14))

    def test_open_end_runs_to_study_end_and_is_labelled(self):
        rec = record("T", effective_from="2025-04-01", effective_to=None)
        s = scope(self.RT, rec, "2026-09-30")
        self.assertIsNotNone(s)
        self.assertEqual(s.open_end, OPEN_EFFECTIVE_END)
        self.assertEqual(s.dates, {"effective_from": "2025-04-01", "effective_to": None})


class UndatedCandidates(unittest.TestCase):
    RT = "cyberattack"

    def rec(self):
        return record("U", event_start=None, event_end=None,
                      search_window={"start": "2026-09-07", "end": "2026-10-05"})

    def test_inside_search_window(self):
        s = scope(self.RT, self.rec(), "2026-09-07")
        self.assertEqual(s.date_status, "undated_candidate")
        self.assertEqual(s.in_scope_reason, UNDATED_REASON)
        self.assertIsNotNone(scope(self.RT, self.rec(), "2026-09-30"))

    def test_window_days_not_applied_to_search_window(self):
        self.assertIsNone(scope(self.RT, self.rec(), "2026-09-06"))
        self.assertIsNone(scope(self.RT, self.rec(), "2026-09-06", 30))

    def test_no_search_window(self):
        rec = self.rec()
        rec["search_window"] = None
        self.assertIsNone(scope(self.RT, rec, "2026-09-10"))

    def test_invalid_stored_date_treated_as_undated(self):
        rec = self.rec()
        rec["event_start"] = "not-a-date"
        self.assertEqual(scope(self.RT, rec, "2026-09-10").date_status, "undated_candidate")


class KnownFrom(unittest.TestCase):
    """Plan section 5.2: nothing is in scope before the date it became known."""

    def test_rule_start_date_even_if_reported_later(self):
        rec = record("H", event_start="2025-06-10", event_end=None,
                     source={"published_at": "2025-06-20"})
        s = scope("natural_hazards", rec, "2025-06-10")
        self.assertEqual((s.known_from, s.known_from_rule), ("2025-06-10", KNOWN_FROM_START))

    def test_stored_known_from_announced_in_advance(self):
        rec = record("T", effective_from="2025-08-07", effective_to="2026-02-23",
                     known_from="2025-07-31")
        self.assertIsNone(scope("tariffs_and_duties", rec, "2025-07-30", 14))
        s = scope("tariffs_and_duties", rec, "2025-07-31")
        self.assertEqual((s.known_from, s.known_from_rule), ("2025-07-31", KNOWN_FROM_STORED))

    def test_stored_known_from_disclosed_later(self):
        rec = record("C", observation_start="2024-08-01", observation_end="2025-07-31",
                     known_from="2025-11-28")
        rt = "supplier_or_route_concentration"
        self.assertIsNone(scope(rt, rec, "2025-03-01"))        # inside the period, not yet reported
        self.assertIsNone(scope(rt, rec, "2025-11-27", 400))
        s = scope(rt, rec, "2025-11-28", 120)
        self.assertEqual((s.known_from, s.known_from_rule), ("2025-11-28", KNOWN_FROM_STORED))
        self.assertIsNone(scope(rt, rec, "2025-11-29", 120))  # window from the end still applies

    def test_undated_known_from_published_at(self):
        rec = record("U", event_start=None, event_end=None,
                     search_window={"start": "2026-06-11", "end": "2026-07-09"},
                     source={"published_at": "2026-06-25"})
        self.assertIsNone(scope("border_customs_delays", rec, "2026-06-24"))
        s = scope("border_customs_delays", rec, "2026-06-25")
        self.assertEqual(s.date_status, "undated_candidate")
        self.assertEqual((s.known_from, s.known_from_rule), ("2026-06-25", KNOWN_FROM_PUBLISHED))

    def test_undated_stored_known_from_overrides_published_at(self):
        rec = record("U", event_start=None, event_end=None, known_from="2026-06-20",
                     search_window={"start": "2026-06-11", "end": "2026-07-09"},
                     source={"published_at": "2026-06-25"})
        self.assertEqual(scope("border_customs_delays", rec, "2026-06-20").known_from_rule,
                         KNOWN_FROM_STORED)

    def test_no_basis_never_in_scope(self):
        rec = record("U", event_start=None, event_end=None, source={"published_at": None},
                     search_window={"start": "2026-06-11", "end": "2026-07-09"})
        self.assertIsNone(scope("border_customs_delays", rec, "2026-06-20"))

    def test_invalid_stored_known_from_falls_back(self):
        rec = record("E", event_start="2025-06-10", event_end=None, known_from="soon")
        self.assertEqual(scope("labour_disruption", rec, "2025-06-10").known_from_rule,
                         KNOWN_FROM_START)

    def test_report_states_known_from_and_rule(self):
        records = {"labour_disruption": [record("L", reported_organisation="Acme Widgets")]}
        r = reports(records, supplier(), as_of_date="2025-06-15")["L"]
        self.assertEqual((r["known_from"], r["known_from_rule"]), ("2025-06-01", KNOWN_FROM_START))


class StudyWindow(unittest.TestCase):
    RT = "labour_disruption"

    def test_record_wholly_outside_study_window_never_in_scope(self):
        rec = record("OLD", event_start="2024-11-01", event_end="2024-12-01")
        self.assertIsNone(scope(self.RT, rec, "2025-01-01", 60))

    def test_record_overlapping_study_start_is_in_scope(self):
        rec = record("OVR", event_start="2024-08-01", event_end="2025-07-31")
        s = scope(self.RT, rec, "2025-01-01")
        self.assertEqual(s.dates["event_start"], "2024-08-01")  # returned as stored

    def test_as_of_outside_study_window_returns_nothing_and_no_warning(self):
        records = {self.RT: [record("L", reported_organisation="Acme Widgets",
                                    event_start="2024-12-01", event_end="2025-01-31")]}
        for as_of in ("2024-12-31", "2026-10-01"):
            with self.subTest(as_of=as_of):
                result = run(records, as_of_date=as_of, event_window_days=60)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["suppliers"][0]["linked_reports"], [])
                self.assertEqual(result["warnings"], [])

    def test_study_boundaries_are_inclusive(self):
        records = {self.RT: [record("L", reported_organisation="Acme Widgets",
                                    event_start="2024-12-01", event_end="2026-12-01")]}
        for as_of in ("2025-01-01", "2026-09-30"):
            with self.subTest(as_of=as_of):
                self.assertIn("L", reports(records, supplier(), as_of_date=as_of))


if __name__ == "__main__":
    unittest.main()
