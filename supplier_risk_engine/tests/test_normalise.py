"""Normalisation (plan section 5.1)."""

import csv
import unittest
from pathlib import Path

from supplier_risk_engine.engine.normalise import (
    contains_whole_words,
    country_to_code,
    hs_codes_match,
    is_generic_port_name,
    normalise_name,
    normalise_port_name,
    split_name_list,
)


class NameNormalisation(unittest.TestCase):
    def test_case_whitespace_and_trim(self):
        self.assertEqual(normalise_name("  NEXPERIA   inc. "), "nexperia")

    def test_legal_suffixes_removed_repeatedly(self):
        for raw in ("Acme Sdn Bhd", "Acme Pte. Ltd.", "Acme Berhad", "Acme GmbH",
                    "Acme Plc", "Acme L.L.C.", "Acme Co., Ltd.", "Acme Corp"):
            with self.subTest(raw=raw):
                self.assertEqual(normalise_name(raw), "acme")

    def test_suffix_only_removed_at_end(self):
        self.assertEqual(normalise_name("Inc Holdings"), "inc holdings")

    def test_name_made_of_suffixes_keeps_last_token(self):
        self.assertEqual(normalise_name("Co Ltd"), "co")

    def test_bracketed_role_text_removed(self):
        self.assertEqual(normalise_name("Maersk (charterer)"), "maersk")
        self.assertEqual(normalise_name("Maersk [operator]"), "maersk")

    def test_dots_and_apostrophes_deleted_other_punctuation_is_space(self):
        self.assertEqual(normalise_name("V.S. Industry Berhad"), "vs industry")
        self.assertEqual(normalise_name("O'Neil-Smith & Sons"), "oneil smith sons")

    def test_unicode_casefold(self):
        self.assertEqual(normalise_name("STRASSE GMBH"), normalise_name("straße GmbH"))

    def test_exact_and_near_miss(self):
        # Decision 2: equality after normalisation only.
        self.assertEqual(normalise_name("Nexperia"), normalise_name("Nexperia Inc."))
        self.assertNotEqual(normalise_name("Nexperia"), normalise_name("Nexperia Philippines Inc."))


class ListValuedFields(unittest.TestCase):
    def test_split_on_semicolon_and_comma(self):
        self.assertEqual(split_name_list("A Corp; B Ltd, C Inc"), ["A Corp", "B Ltd", "C Inc"])

    def test_unnamed_entries_ignored(self):
        self.assertEqual(split_name_list("A Corp; (unnamed); B Ltd (Unnamed)"), ["A Corp"])

    def test_comma_inside_brackets_does_not_split(self):
        self.assertEqual(split_name_list("A Corp (importer, US); B Ltd"),
                         ["A Corp (importer, US)", "B Ltd"])

    def test_empty_entries_dropped(self):
        self.assertEqual(split_name_list("A;;  ; B"), ["A", "B"])


class Countries(unittest.TestCase):
    def test_codes_any_case(self):
        self.assertEqual(country_to_code("my"), "MY")
        self.assertEqual(country_to_code(" US "), "US")

    def test_names_converted(self):
        self.assertEqual(country_to_code("Malaysia"), "MY")
        self.assertEqual(country_to_code("People's Republic of China"), "CN")
        self.assertEqual(country_to_code("the Philippines"), "PH")
        self.assertEqual(country_to_code("United States of America"), "US")

    def test_unknown_name_or_code(self):
        self.assertIsNone(country_to_code("Atlantis"))
        self.assertIsNone(country_to_code("XX"))

    def test_graph_country_names_convert_to_their_stored_codes(self):
        """Decision 4 (plan section 5.4): every name/code pair in the CSVs
        the graph is loaded from must agree with the name table."""
        csv_dir = Path(__file__).resolve().parents[2] / "data" / "processed"
        paths = sorted(csv_dir.glob("*_shipments_clean.csv"))
        if not paths:
            self.skipTest(f"no graph CSVs in {csv_dir}")
        pairs = set()
        for path in paths:
            with path.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    for name_col, code_col in (
                        ("supplier_country", "supplier_country_code"),
                        ("buyer_country", "buyer_country_code"),
                    ):
                        if row.get(name_col):
                            pairs.add((row[name_col], row[code_col]))
        self.assertTrue(pairs)
        for name, code in sorted(pairs):
            with self.subTest(name=name):
                self.assertEqual(country_to_code(name), code)
                self.assertEqual(country_to_code(code), code)


class Ports(unittest.TestCase):
    def test_trailing_state_tag_dropped(self):
        self.assertEqual(normalise_port_name("Long Beach, Ca"), "long beach")

    def test_generic_names(self):
        self.assertTrue(is_generic_port_name("port"))
        self.assertTrue(is_generic_port_name("port of the harbour"))
        self.assertTrue(is_generic_port_name(""))
        self.assertFalse(is_generic_port_name("port klang"))

    def test_whole_word_containment(self):
        self.assertTrue(contains_whole_words("congestion at port of long beach terminals", "long beach"))
        self.assertFalse(contains_whole_words("penangport", "penang"))
        self.assertFalse(contains_whole_words("anything", ""))


class HsCodes(unittest.TestCase):
    def test_prefix_either_way(self):
        self.assertTrue(hs_codes_match("850760", "8507.60.00"))
        self.assertTrue(hs_codes_match("85076000", "850760"))

    def test_minimum_six_digits(self):
        self.assertFalse(hs_codes_match("8507", "8507.60.00"))
        self.assertFalse(hs_codes_match("850760", "8507"))

    def test_different_codes(self):
        self.assertFalse(hs_codes_match("850811", "8507.60.00"))


if __name__ == "__main__":
    unittest.main()
