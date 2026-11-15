"""Matching rules for each risk type (plan sections 4, 5.1 and 7), on
synthetic records so every rule is tested in isolation from the real data."""

import unittest

from supplier_risk_engine.engine.lookup import APPROXIMATED_LABEL
from supplier_risk_engine.engine.match import COUNTRY_WIDE_LABEL

from .helpers import record, reports, run, supplier

SUPPLIER = "Acme Widgets Sdn Bhd"
PARENT = "Acme Holdings Ltd"


def basis(report):
    return report["link_basis"], report["link_strength"]


def is_country_only(report):
    return any(label.startswith("country-only link") for label in report["labels"])


class CompanyNames(unittest.TestCase):
    RT = "labour_disruption"

    def one(self, name, s=None, **fields):
        rec = record("R", reported_organisation=name, country_code="SG", **fields)
        return reports({self.RT: [rec]}, s or supplier()).get("R")

    def test_exact_after_normalisation(self):
        r = self.one("ACME WIDGETS SDN. BHD.")
        self.assertEqual(basis(r), ("company_name", "strong"))
        self.assertEqual(r["matched_values"], ["ACME WIDGETS SDN. BHD."])
        self.assertFalse(is_country_only(r))

    def test_near_miss_does_not_link(self):
        self.assertIsNone(self.one("Acme Widgets Philippines Inc"))
        self.assertIsNone(self.one("Acme"))

    def test_role_text_removed(self):
        self.assertEqual(basis(self.one("Acme Widgets (contract manufacturer)")),
                         ("company_name", "strong"))

    def test_parent_links_down_to_supplier(self):
        r = self.one("Acme Holdings")
        self.assertEqual(basis(r), ("parent_company_name", "strong"))
        link = r["links"][0]
        self.assertEqual(link["input_value"], PARENT)

    def test_every_parent_level_is_matched(self):
        s = supplier(parent_companies=["Acme Regional Pte Ltd", PARENT])
        self.assertEqual(basis(self.one("Acme Regional", s)), ("parent_company_name", "strong"))
        self.assertEqual(basis(self.one("Acme Holdings", s)), ("parent_company_name", "strong"))

    def test_parent_link_one_direction_only(self):
        # The payload's supplier is the parent. A report about its subsidiary
        # does not link upward.
        parent = supplier(supplier_name=PARENT, parent_companies=[PARENT])
        self.assertIsNone(self.one("Acme Widgets Sdn Bhd", parent))

    def test_parent_equal_to_own_name_reported_once(self):
        s = supplier(parent_companies=[SUPPLIER])
        r = self.one("Acme Widgets", s)
        self.assertEqual([l["link_basis"] for l in r["links"]], ["company_name"])


class ListValuedCompanyFields(unittest.TestCase):
    def test_product_quality_split_with_role_text(self):
        rec = record("Q", reported_supplier="Other Co (importer); Acme Widgets (manufacturer)",
                     country_code="US")
        r = reports({"product_quality_compliance": [rec]}, supplier())["Q"]
        self.assertEqual(basis(r), ("company_name", "strong"))
        self.assertEqual(r["matched_values"], ["Acme Widgets"])

    def test_concentration_list_and_unnamed(self):
        rec = record("C", reported_entities_or_routes=["(unnamed) supplier", "Acme Widgets; Beta Ltd"],
                     observation_start="2025-06-01", observation_end="2025-06-30", countries=[])
        r = reports({"supplier_or_route_concentration": [rec]}, supplier())["C"]
        self.assertEqual(basis(r), ("company_name", "strong"))

        only_unnamed = record("C2", reported_entities_or_routes="(unnamed)",
                              observation_start="2025-06-01", observation_end="2025-06-30",
                              countries=[])
        s = supplier(supplier_name="Unnamed", parent_companies=["Unnamed"])
        self.assertEqual(reports({"supplier_or_route_concentration": [only_unnamed]}, s), {})


class CountryOnlyLinks(unittest.TestCase):
    """Each type that allows country-only links, with its own country field."""

    CASES = {
        "supplier_operational_disruption": {"reported_supplier": "Other", "country_code": "MY"},
        "cyberattack": {"reported_organisation": "Other", "country_code": "MY"},
        "supplier_financial_distress": {"reported_supplier": "Other", "country_code": "MY",
                                        "observation_date": "2025-06-15"},
        "product_quality_compliance": {"reported_supplier": "Other", "country_code": "MY"},
        "labour_disruption": {"reported_organisation": "Other", "country_code": "MY"},
        "natural_hazards": {"location": {"label": "Somewhere", "country_code": "MY"}},
        "route_chokepoint_disruption": {"countries": [{"country_code": "MY"}], "trade_lanes": []},
        "goods_in_transit_loss_theft_or_damage": {"reported_carrier": "Other", "country_code": "MY"},
        "government_restrictions": {"reported_organisation": "", "affected_countries": [{"country_code": "MY"}],
                                    "issuing_country_code": "US", "effective_from": "2025-01-01"},
        "border_customs_delays": {"border_or_customs_location": "Somewhere", "country_code": "MY"},
        "geopolitical_conflict": {"affected_countries": [{"country_code": "MY"}]},
        "input_material_shortage": {"reported_supplier": "Other", "affected_countries": [{"country_code": "MY"}]},
        "energy_or_transport_cost_increase": {"affected_countries": [{"country_code": "MY"}],
                                              "observation_start": "2025-06-01",
                                              "observation_end": "2025-06-30"},
        "supplier_or_route_concentration": {"reported_entities_or_routes": "Other",
                                            "countries": [{"country_code": "MY"}],
                                            "observation_start": "2025-06-01",
                                            "observation_end": "2025-06-30"},
    }

    def test_country_match_links_weak_and_labelled(self):
        for risk_type, fields in self.CASES.items():
            with self.subTest(risk_type=risk_type):
                r = reports({risk_type: [record("X", **fields)]}, supplier()).get("X")
                self.assertIsNotNone(r)
                self.assertEqual(basis(r), ("country_code", "weak"))
                self.assertTrue(is_country_only(r))

    def test_other_country_does_not_link(self):
        for risk_type, fields in self.CASES.items():
            with self.subTest(risk_type=risk_type):
                self.assertEqual(reports({risk_type: [record("X", **fields)]},
                                         supplier(country="PH")), {})

    def test_government_restriction_issuing_country(self):
        rec = record("G", reported_organisation="", affected_countries=[],
                     issuing_country_code="MY", effective_from="2025-01-01")
        self.assertEqual(basis(reports({"government_restrictions": [rec]}, supplier())["G"]),
                         ("country_code", "weak"))

    def test_name_beats_country_and_both_are_kept(self):
        rec = record("L", reported_organisation="Acme Widgets", country_code="MY")
        r = reports({"labour_disruption": [rec]}, supplier())["L"]
        self.assertEqual(basis(r), ("company_name", "strong"))
        self.assertEqual([l["link_basis"] for l in r["links"]], ["company_name", "country_code"])
        self.assertFalse(is_country_only(r))


class Ports(unittest.TestCase):
    RT = "port_disruption"

    def port_supplier(self, **port):
        entry = {"name": "Penang", "code": "55701", "country": "MY", "shipments": 3}
        entry.update(port)
        return supplier(country="CN", exit_ports=[entry])

    def test_tier1_code(self):
        rec = record("P", reported_port="Somewhere else", country_code="MY", port_ids=["55701"])
        r = reports({self.RT: [rec]}, self.port_supplier())["P"]
        self.assertEqual(basis(r), ("port_code", "strong"))
        self.assertEqual(r["matched_exposure"][0]["shipments"], 3)  # echoed unchanged

    def test_tier2_name_whole_word(self):
        rec = record("P", reported_port="Congestion at Port of Penang terminals", country_code="MY")
        r = reports({self.RT: [rec]}, self.port_supplier())["P"]
        self.assertEqual(basis(r), ("port_name", "medium"))
        # Name hit stops the tiers for that port: no port_country link as well.
        self.assertEqual([l["link_basis"] for l in r["links"]], ["port_name"])

    def test_tier2_state_tag_dropped(self):
        rec = record("P", reported_port="Long Beach container terminal", country_code="XX")
        s = supplier(entry_ports=[{"name": "Long Beach, Ca", "country": "US"}])
        self.assertEqual(basis(reports({self.RT: [rec]}, s)["P"]), ("port_name", "medium"))

    def test_tier2_not_a_substring_of_a_word(self):
        rec = record("P", reported_port="Penangport", country_code="SG")
        self.assertEqual(reports({self.RT: [rec]}, self.port_supplier()), {})

    def test_generic_port_name_never_matches(self):
        rec = record("P", reported_port="Port terminal closure", country_code="SG")
        self.assertEqual(reports({self.RT: [rec]}, self.port_supplier(name="Port")), {})

    def test_tier3_country(self):
        rec = record("P", reported_port="Port Klang", country_code="MY")
        r = reports({self.RT: [rec]}, self.port_supplier())["P"]
        self.assertEqual(basis(r), ("port_country", "weak"))
        self.assertTrue(is_country_only(r))

    def test_port_without_country_skips_tier3(self):
        rec = record("P", reported_port="Port Klang", country_code="MY")
        self.assertEqual(reports({self.RT: [rec]}, self.port_supplier(country=None)), {})

    def test_port_disruption_never_links_on_supplier_country(self):
        rec = record("P", reported_port="Port Klang", country_code="MY")
        self.assertEqual(reports({self.RT: [rec]}, supplier(country="MY")), {})

    def test_natural_hazard_port_name_and_country(self):
        rec = record("H", location={"label": "Flooding", "affected_area": "Penang state",
                                    "country_code": "MY"})
        r = reports({"natural_hazards": [rec]}, self.port_supplier())["H"]
        self.assertEqual(basis(r), ("port_name", "medium"))
        self.assertEqual(r["links"][0]["record_field"], "location.affected_area")

        rec2 = record("H2", location={"label": "Flooding", "country_code": "MY"})
        self.assertEqual(basis(reports({"natural_hazards": [rec2]}, self.port_supplier())["H2"]),
                         ("port_country", "weak"))

    def test_border_customs_port_name(self):
        rec = record("B", border_or_customs_location="Penang customs office", country_code="SG")
        r = reports({"border_customs_delays": [rec]}, self.port_supplier())["B"]
        self.assertEqual(basis(r), ("port_name", "medium"))


class CarriersAndVessels(unittest.TestCase):
    RT = "carrier_vessel_disruption"

    def test_vessel_strong(self):
        rec = record("V", reported_vessel="KYPARISSIA", reported_carrier=None, country_code="MY")
        r = reports({self.RT: [rec]}, supplier(vessels=[{"name": "Kyparissia", "shipments": 2}]))["V"]
        self.assertEqual(basis(r), ("vessel_name", "strong"))
        self.assertEqual(r["matched_exposure"], [{"name": "Kyparissia", "shipments": 2}])

    def test_carrier_medium_role_text_removed(self):
        rec = record("V", reported_vessel="Other", reported_carrier="Maersk (charterer)", country_code="MY")
        r = reports({self.RT: [rec]}, supplier(carriers=[{"name": "Maersk", "code": "MAEU"}]))["V"]
        self.assertEqual(basis(r), ("carrier_name", "medium"))

    def test_carrier_near_miss(self):
        rec = record("V", reported_vessel="Other", reported_carrier="Maersk (charterer)", country_code="MY")
        self.assertEqual(reports({self.RT: [rec]}, supplier(carriers=[{"name": "Maersk Line"}])), {})

    def test_never_linked_by_country(self):
        rec = record("V", reported_vessel="Other", reported_carrier="Other", country_code="MY")
        s = supplier(country="MY", exit_ports=[{"name": "Port Klang", "country": "MY"}])
        self.assertEqual(reports({self.RT: [rec]}, s), {})

    def test_goods_in_transit_carrier_list(self):
        rec = record("T", reported_carrier="Alpha Freight; Beta Logistics (forwarder)", country_code="US")
        r = reports({"goods_in_transit_loss_theft_or_damage": [rec]},
                    supplier(carriers=[{"name": "Beta Logistics Pte Ltd"}]))["T"]
        self.assertEqual(basis(r), ("carrier_name", "medium"))


class TradeLanes(unittest.TestCase):
    RT = "route_chokepoint_disruption"
    LANE = {"origin_country_codes": ["MY", "CN"], "destination_country_code": "US",
            "destination_coast": "east_gulf"}

    def rec(self, approximated=True):
        fields = {"countries": [], "trade_lanes": [dict(self.LANE)]}
        if approximated:
            fields["approximations"] = [{"field": "trade_lanes", "basis": "Analyst approximation"}]
        return record("R", **fields)

    def lane_supplier(self, coast="east_gulf", country="MY"):
        return supplier(country=country, entry_ports=[{"name": "Savannah, Ga", "coast": coast}])

    def test_lane_links_weak_and_labelled_approximated(self):
        r = reports({self.RT: [self.rec()]}, self.lane_supplier())["R"]
        self.assertEqual(basis(r), ("trade_lane", "weak"))
        self.assertTrue(r["approximated"])
        self.assertIn(APPROXIMATED_LABEL, r["labels"])
        self.assertEqual(r["links"][0]["approximation_basis"], "Analyst approximation")

    def test_lane_needs_origin_destination_and_coast(self):
        self.assertEqual(reports({self.RT: [self.rec()]}, self.lane_supplier(country="PH")), {})
        self.assertEqual(reports({self.RT: [self.rec()]}, self.lane_supplier(coast="west")), {})
        self.assertEqual(reports({self.RT: [self.rec()]}, self.lane_supplier(),
                                 request_context={"importing_country": "CA"}), {})

    def test_no_coast_no_lane_link(self):
        s = supplier(entry_ports=[{"name": "Savannah, Ga"}])
        self.assertEqual(reports({self.RT: [self.rec()]}, s), {})

    def test_approximated_country_is_weak(self):
        rec = record("H", countries=[{"country_code": "MY"}], trade_lanes=[],
                     approximations=[{"field": "countries", "basis": "Analyst approximation"}])
        r = reports({self.RT: [rec]}, supplier())["H"]
        self.assertEqual(basis(r), ("country_code", "weak"))
        self.assertTrue(r["approximated"])


class Tariffs(unittest.TestCase):
    RT = "tariffs_and_duties"

    def rec(self, origin="MY", importing="US", code=None):
        return record("T", origin_country_code=origin, importing_country_code=importing,
                      product_classification={"code": code} if code else None,
                      effective_from="2025-04-01", effective_to=None)

    def test_country_pair_without_code(self):
        r = reports({self.RT: [self.rec()]}, supplier())["T"]
        self.assertEqual(basis(r), ("country_code", "weak"))
        self.assertIn(COUNTRY_WIDE_LABEL, r["labels"])
        self.assertEqual(r["open_end"], "no end date recorded; continued force not verified")

    def test_both_countries_required(self):
        self.assertEqual(reports({self.RT: [self.rec(origin="CN")]}, supplier()), {})
        self.assertEqual(reports({self.RT: [self.rec(importing="CA")]}, supplier()), {})

    def test_null_origin_matches_on_importing_country(self):
        r = reports({self.RT: [self.rec(origin=None)]}, supplier(country="PH"))["T"]
        self.assertEqual(basis(r), ("importing_country", "weak"))

    def test_coded_record_needs_hs_prefix(self):
        recs = {self.RT: [self.rec(code="8507.60.00")]}
        r = reports(recs, supplier(hs_codes=[{"code": "850760", "shipments": 4}]))["T"]
        self.assertEqual(basis(r), ("hs_code", "medium"))
        self.assertNotIn(COUNTRY_WIDE_LABEL, r["labels"])
        self.assertEqual(reports(recs, supplier(hs_codes=[{"code": "850811"}])), {})
        self.assertEqual(reports(recs, supplier(hs_codes=[{"code": "8507"}])), {})
        self.assertEqual(reports(recs, supplier()), {})


class Currency(unittest.TestCase):
    RT = "currency_fluctuations"

    def rec(self, **fields):
        base = {"reported_organisation": None, "quote_currency": "MYR", "base_currency": "USD",
                "country_code": "MY", "observation_start": "2025-06-01", "observation_end": "2025-06-30"}
        base.update(fields)
        return record("FX", **base)

    def test_quote_or_base_currency(self):
        self.assertEqual(basis(reports({self.RT: [self.rec()]}, supplier())["FX"]), ("currency", "medium"))
        recs = {self.RT: [self.rec(quote_currency="USD", base_currency="MYR")]}
        self.assertEqual(basis(reports(recs, supplier())["FX"]), ("currency", "medium"))
        self.assertEqual(reports({self.RT: [self.rec()]}, supplier(currency="PHP")), {})

    def test_country_never_links(self):
        recs = {self.RT: [self.rec(quote_currency=None, base_currency=None)]}
        self.assertEqual(reports(recs, supplier(country="MY")), {})

    def test_buyer_name(self):
        recs = {self.RT: [self.rec(reported_organisation="Dyson", quote_currency=None, base_currency=None,
                                   approximations=[{"field": "country_code",
                                                    "basis": "Informational only; not used."}])]}
        r = reports(recs, supplier(buyers=[{"name": "Dyson Inc", "shipments": 31}]))["FX"]
        self.assertEqual(basis(r), ("buyer_name", "strong"))
        self.assertEqual(r["matched_exposure"], [{"name": "Dyson Inc", "shipments": 31}])
        self.assertFalse(r["approximated"])

    def test_informational_approximation_never_links(self):
        rec = record("L", reported_organisation="Other", country_code="MY",
                     approximations=[{"field": "country_code", "basis": "Informational only."}])
        self.assertEqual(reports({"labour_disruption": [rec]}, supplier()), {})


class IncidentGroups(unittest.TestCase):
    def test_related_ids_two_way_and_not_pulled_in(self):
        a = record("A", reported_organisation="Acme Widgets", country_code="SG",
                   related_evidence_ids=["B"])
        b = record("B", reported_organisation="Unrelated", country_code="SG")
        result = reports({"labour_disruption": [a, b]}, supplier())
        self.assertEqual(set(result), {"A"})  # B does not link on its own
        self.assertEqual(result["A"]["related_evidence_ids"], ["B"])
        self.assertEqual(result["A"]["incident_group_id"], "A")

    def test_group_reported_when_several_members_link(self):
        a = record("A", reported_organisation="Acme Widgets", country_code="SG")
        b = record("B", reported_organisation="Acme Widgets", country_code="SG",
                   related_evidence_ids=["A"])
        c = record("C", reported_organisation="Other", country_code="SG",
                   related_evidence_ids=["B"])
        out = run({"labour_disruption": [a, b, c]}, supplier())["suppliers"][0]
        self.assertEqual(out["linked_report_count"], 2)
        self.assertEqual(out["distinct_incident_count"], 1)
        self.assertEqual(out["incident_groups"], [{"incident_group_id": "A",
                                                   "linked_evidence_ids": ["A", "B"],
                                                   "unlinked_member_ids": ["C"]}])


if __name__ == "__main__":
    unittest.main()
