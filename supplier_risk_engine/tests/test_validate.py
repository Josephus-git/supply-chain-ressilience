"""Payload validation (plan section 6.3)."""

import unittest

from supplier_risk_engine.engine import EngineValidationError, lookup_suppliers, parse_request

from .helpers import payload, supplier


def codes(p):
    """(field, code) pairs for a rejected payload."""
    result = lookup_suppliers(p, {})
    assert result["status"] == "rejected", result
    return {(e["field"], e["code"]) for e in result["errors"]}


class Accepted(unittest.TestCase):
    def test_minimal_payload(self):
        request, errors, _ = parse_request(payload())
        self.assertEqual(errors, [])
        self.assertEqual(request.suppliers[0].country, "MY")

    def test_country_name_and_lowercase_currency_converted(self):
        request, errors, _ = parse_request(payload(supplier(country="Malaysia", currency="myr")))
        self.assertEqual(errors, [])
        self.assertEqual(request.suppliers[0].country, "MY")
        self.assertEqual(request.suppliers[0].currency, "MYR")

    def test_unknown_keys_warn_but_do_not_reject(self):
        p = payload(supplier(extra="x"), surprise=1)
        result = lookup_suppliers(p, {})
        self.assertEqual(result["status"], "completed")
        fields = {w["field"] for w in result["warnings"]}
        self.assertEqual(fields, {"surprise", "suppliers[0].extra"})

    def test_zero_window_allowed(self):
        self.assertEqual(parse_request(payload(event_window_days=0))[1], [])


class Rejected(unittest.TestCase):
    def test_as_of_date(self):
        p = payload()
        del p["as_of_date"]
        self.assertIn(("as_of_date", "missing"), codes(p))
        for bad in ("2025/06/15", "2025-02-30", 20250615, "June 2025"):
            with self.subTest(bad=bad):
                self.assertIn(("as_of_date", "invalid_date"), codes(payload(as_of_date=bad)))

    def test_event_window_days(self):
        p = payload()
        del p["event_window_days"]
        self.assertIn(("event_window_days", "missing"), codes(p))
        self.assertIn(("event_window_days", "negative"), codes(payload(event_window_days=-1)))
        for bad in (1.5, "14", True):
            with self.subTest(bad=bad):
                self.assertIn(("event_window_days", "invalid_type"),
                              codes(payload(event_window_days=bad)))

    def test_suppliers_missing_or_empty(self):
        self.assertIn(("suppliers", "empty"), codes(payload(suppliers=[])))
        p = payload()
        del p["suppliers"]
        self.assertIn(("suppliers", "missing"), codes(p))

    def test_required_supplier_fields(self):
        for key in ("supplier_name", "country", "parent_companies", "currency"):
            with self.subTest(key=key):
                s = supplier()
                del s[key]
                self.assertIn((f"suppliers[0].{key}", "missing"), codes(payload(s)))

    def test_parent_companies_empty_list(self):
        self.assertIn(("suppliers[0].parent_companies", "empty"),
                      codes(payload(supplier(parent_companies=[]))))

    def test_unknown_country(self):
        self.assertIn(("suppliers[0].country", "unknown_country"),
                      codes(payload(supplier(country="Atlantis"))))
        self.assertIn(("suppliers[0].country", "unknown_country"),
                      codes(payload(supplier(country="XX"))))

    def test_duplicate_supplier_after_normalisation(self):
        a = supplier(supplier_name="Acme Widgets Sdn Bhd")
        b = supplier(supplier_name="ACME WIDGETS", country="Malaysia")
        self.assertIn(("suppliers[1]", "duplicate_supplier"), codes(payload(a, b)))

    def test_same_name_different_country_is_not_duplicate(self):
        a = supplier()
        b = supplier(country="PH")
        self.assertEqual(parse_request(payload(a, b))[1], [])

    def test_empty_or_whitespace_names(self):
        cases = {
            "supplier_name": (supplier(supplier_name="  "), "suppliers[0].supplier_name"),
            "parent": (supplier(parent_companies=[" "]), "suppliers[0].parent_companies[0]"),
            "vessel": (supplier(vessels=[{"name": ""}]), "suppliers[0].vessels[0].name"),
            "carrier": (supplier(carriers=[{"name": " "}]), "suppliers[0].carriers[0].name"),
            "port": (supplier(exit_ports=[{"name": "\t"}]), "suppliers[0].exit_ports[0].name"),
        }
        for label, (s, field) in cases.items():
            with self.subTest(label=label):
                self.assertIn((field, "empty"), codes(payload(s)))

    def test_importing_country(self):
        p = payload()
        del p["request_context"]["importing_country"]
        self.assertIn(("request_context.importing_country", "missing"), codes(p))
        p = payload()
        del p["request_context"]
        self.assertIn(("request_context", "missing"), codes(p))

    def test_unknown_currency(self):
        self.assertIn(("suppliers[0].currency", "unknown_currency"),
                      codes(payload(supplier(currency="XYZ"))))

    def test_non_digit_hs_code(self):
        for bad in ("8507.60", 850760, "85A760", ""):
            with self.subTest(bad=bad):
                self.assertIn(("suppliers[0].hs_codes[0].code", "invalid_hs_code"),
                              codes(payload(supplier(hs_codes=[{"code": bad}]))))

    def test_shipments_count(self):
        for bad in (-1, 2.5, "3", True):
            with self.subTest(bad=bad):
                s = supplier(buyers=[{"name": "Dyson", "shipments": bad}])
                self.assertIn(("suppliers[0].buyers[0].shipments", "invalid_count"), codes(payload(s)))

    def test_invalid_coast_and_port_country(self):
        s = supplier(entry_ports=[{"name": "Los Angeles", "coast": "north"}])
        self.assertIn(("suppliers[0].entry_ports[0].coast", "invalid_coast"), codes(payload(s)))
        s = supplier(exit_ports=[{"name": "Penang", "country": "Atlantis"}])
        self.assertIn(("suppliers[0].exit_ports[0].country", "unknown_country"), codes(payload(s)))

    def test_not_an_object(self):
        self.assertIn(("$", "invalid_type"), codes([]))

    def test_all_errors_collected_in_one_pass(self):
        p = payload(supplier(currency="XYZ", country="Atlantis"), event_window_days=-3)
        found = codes(p)
        self.assertTrue({("event_window_days", "negative"),
                         ("suppliers[0].currency", "unknown_currency"),
                         ("suppliers[0].country", "unknown_country")} <= found)

    def test_rejected_result_shape(self):
        result = lookup_suppliers(payload(event_window_days=-1), {})
        self.assertEqual(set(result), {"schema_version", "status", "engine_version",
                                       "data_snapshot_id", "study_window", "errors"})

    def test_raise_on_error(self):
        with self.assertRaises(EngineValidationError) as ctx:
            parse_request(payload(event_window_days=-1), raise_on_error=True)
        self.assertEqual(ctx.exception.errors[0].field, "event_window_days")


if __name__ == "__main__":
    unittest.main()
