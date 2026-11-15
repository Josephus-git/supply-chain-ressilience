"""Phase 5 CLI: the four commands, exit codes, and the gold-set batch run."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from supplier_risk_engine import cli
from supplier_risk_engine.engine import lookup_suppliers
from supplier_risk_engine.loader import load_database

from .helpers import EXAMPLES_DIR, load_gold, load_payload

PAYLOAD_DIR = EXAMPLES_DIR / "payloads"
EXPECTED = EXAMPLES_DIR / "expected_ids.json"


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Commands(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_query_matches_direct_call(self):
        rel = load_gold()["fixtures"][0]["payload"]
        code, out, _ = run_cli("query", str(EXAMPLES_DIR / rel))
        self.assertEqual(code, cli.EXIT_OK)
        direct = lookup_suppliers(load_payload(rel), load_database().index)
        self.assertEqual(json.loads(out), direct)

    def test_query_out_file(self):
        target = self.tmp / "sub" / "r.json"
        code, out, _ = run_cli("query", str(sorted(PAYLOAD_DIR.glob("*.json"))[0]), "--out", str(target))
        self.assertEqual((code, out), (cli.EXIT_OK, ""))
        self.assertEqual(json.loads(target.read_text())["status"], "completed")

    def test_query_rejected_payload(self):
        bad = self.tmp / "bad.json"
        bad.write_text("{}")
        code, out, err = run_cli("query", str(bad))
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertEqual(json.loads(out)["status"], "rejected")
        self.assertIn("rejected: as_of_date", err)

    def test_query_file_errors(self):
        broken = self.tmp / "broken.json"
        broken.write_text("{nope")
        for path in (broken, self.tmp / "missing.json"):
            with self.subTest(path=path.name):
                code, _, err = run_cli("query", str(path))
                self.assertEqual(code, cli.EXIT_ERROR)
                self.assertIn("error:", err)

    def test_evidence(self):
        code, out, _ = run_cli("evidence", "CYBER-CLAIM-2026-001")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(json.loads(out)["risk_type"], "cyberattack")
        code, out, _ = run_cli("evidence", "NOPE-001")
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertEqual(json.loads(out)["status"], "not_found")

    def test_describe(self):
        code, out, _ = run_cli("describe")
        self.assertEqual(code, cli.EXIT_OK)
        d = json.loads(out)
        self.assertEqual(d["record_count"], 97)
        self.assertEqual(d["data_snapshot_id"], load_database().snapshot_id)
        self.assertEqual(len(d["database"]["files"]), 18)

    def test_bad_database_dir(self):
        code, _, err = run_cli("--database", str(self.tmp / "nope"), "describe")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("could not be loaded", err)


class RunAll(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_gold_batch_passes(self):
        out_dir = self.tmp / "out"
        code, _, err = run_cli("run-all", str(PAYLOAD_DIR), "--out", str(out_dir),
                               "--expected", str(EXPECTED))
        self.assertEqual(code, cli.EXIT_OK, err)
        summary = json.loads((out_dir / cli.SUMMARY_NAME).read_text())
        gold = summary["gold"]
        self.assertEqual((gold["fixtures_compared"], gold["fixtures_passed"]), (37, 37))
        self.assertEqual((gold["missed_ids"], gold["unexpected_ids"]), (0, 0))
        self.assertEqual((gold["recall"], gold["precision"]), (1.0, 1.0))
        self.assertEqual(gold["payloads_without_fixture"], [])
        self.assertEqual(gold["fixtures_without_payload"], [])
        self.assertEqual(len(list(out_dir.glob("*.json"))), 38)  # 37 results + summary

    def test_batch_without_gold(self):
        code, _, _ = run_cli("run-all", str(PAYLOAD_DIR), "--out", str(self.tmp / "o"))
        self.assertEqual(code, cli.EXIT_OK)
        summary = json.loads((self.tmp / "o" / cli.SUMMARY_NAME).read_text())
        self.assertNotIn("gold", summary)
        self.assertEqual(summary["completed"], 37)

    def test_gold_mismatch_reported(self):
        gold = load_gold()
        first = gold["fixtures"][0]
        dropped = first["expected_ids"][0]
        first["expected_ids"] = first["expected_ids"][1:] + ["NOT-RETURNED-001"]
        for fixture in gold["fixtures"]:
            fixture["payload"] = str(EXAMPLES_DIR / fixture["payload"])
        expected = self.tmp / "expected.json"
        expected.write_text(json.dumps(gold))
        code, _, err = run_cli("run-all", str(PAYLOAD_DIR), "--out", str(self.tmp / "o"),
                               "--expected", str(expected))
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("FAIL", err)
        run = json.loads((self.tmp / "o" / cli.SUMMARY_NAME).read_text())["runs"][0]
        self.assertEqual(run["gold"]["missed"], ["NOT-RETURNED-001"])
        self.assertEqual(run["gold"]["unexpected"], [dropped])

    def test_rejected_payload_in_batch(self):
        payloads = self.tmp / "p"
        payloads.mkdir()
        (payloads / "bad.json").write_text("{}")
        code, _, _ = run_cli("run-all", str(payloads), "--out", str(self.tmp / "o"))
        self.assertEqual(code, cli.EXIT_FAILED)
        summary = json.loads((self.tmp / "o" / cli.SUMMARY_NAME).read_text())
        self.assertEqual(summary["rejected"], ["bad.json"])

    def test_usage_errors(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        for argv in (
            ("run-all", str(self.tmp / "nope"), "--out", str(self.tmp / "o")),
            ("run-all", str(empty), "--out", str(self.tmp / "o")),
            ("run-all", str(PAYLOAD_DIR), "--out", str(PAYLOAD_DIR)),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv)[0], cli.EXIT_ERROR)


if __name__ == "__main__":
    unittest.main()
