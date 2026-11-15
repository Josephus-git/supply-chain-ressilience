"""Phase 5 loader: reading the database, manifest checks, snapshot ID."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from supplier_risk_engine.engine import describe_database
from supplier_risk_engine.loader import (
    DEFAULT_DATABASE_DIR,
    DatabaseError,
    compute_snapshot_id,
    load_database,
)

from .helpers import record


def _write(path: Path, data) -> str:
    raw = json.dumps(data, indent=2).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _manifest(files: dict[str, str], snapshot_id=None) -> dict:
    return {
        "schema_version": "1.0",
        "records": [
            {"snapshot_id": snapshot_id, "files": [{"path": name, "sha256": digest}]}
            for name, digest in files.items()
        ],
    }


class RealDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = load_database()

    def test_counts(self):
        self.assertEqual(self.db.record_count, 109)
        self.assertEqual(len(self.db.records), 18)
        self.assertEqual(describe_database(self.db.index)["record_count"], 109)

    def test_manifest_hashes_verified_without_warnings(self):
        self.assertEqual(self.db.warnings, ())
        self.assertEqual(len(self.db.file_hashes), 18)

    def test_snapshot_id_computed_and_used_by_engine(self):
        self.assertEqual(self.db.snapshot_source, "computed")
        self.assertTrue(self.db.snapshot_id.startswith("db-sha256:"))
        self.assertEqual(self.db.snapshot_id, compute_snapshot_id(self.db.file_hashes))
        self.assertEqual(self.db.index.snapshot_id, self.db.snapshot_id)
        self.assertEqual(load_database().snapshot_id, self.db.snapshot_id)

    def test_default_path(self):
        self.assertEqual(self.db.path, DEFAULT_DATABASE_DIR)


class SyntheticDatabase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.hashes = {
            "labour_disruption.json": _write(
                self.dir / "labour_disruption.json",
                {"risk_type": "labour_disruption", "records": [record("L-1")]},
            ),
            "cyberattack.json": _write(
                self.dir / "cyberattack.json",
                {"risk_type": "cyberattack", "records": [record("C-1"), record("C-2")]},
            ),
        }

    def write_manifest(self, files=None, snapshot_id=None):
        _write(self.dir / "manifest.json", _manifest(files or self.hashes, snapshot_id))

    def test_loads(self):
        self.write_manifest()
        db = load_database(self.dir)
        self.assertEqual(sorted(db.records), ["cyberattack", "labour_disruption"])
        self.assertEqual(db.record_count, 3)
        self.assertEqual(db.warnings, ())

    def test_file_name_must_match_risk_type(self):
        _write(self.dir / "labour.json", {"risk_type": "natural_hazards", "records": []})
        with self.assertRaises(DatabaseError) as ctx:
            load_database(self.dir, verify=False)
        self.assertIn("does not match the file name", ctx.exception.problems[0])

    def test_manifest_snapshot_id_used_when_set(self):
        self.write_manifest(snapshot_id="snap-2026-11")
        db = load_database(self.dir)
        self.assertEqual((db.snapshot_id, db.snapshot_source), ("snap-2026-11", "manifest"))
        self.assertEqual(db.index.snapshot_id, "snap-2026-11")

    def test_snapshot_id_changes_with_content(self):
        self.write_manifest()
        before = load_database(self.dir).snapshot_id
        self.hashes["labour_disruption.json"] = _write(
            self.dir / "labour_disruption.json",
            {"risk_type": "labour_disruption", "records": [record("L-1", event_end="2025-07-01")]},
        )
        self.write_manifest()
        self.assertNotEqual(load_database(self.dir).snapshot_id, before)

    def test_hash_mismatch_raises_unless_no_verify(self):
        self.write_manifest({**self.hashes, "cyberattack.json": "0" * 64})
        with self.assertRaises(DatabaseError) as ctx:
            load_database(self.dir)
        self.assertIn("cyberattack.json", ctx.exception.problems[0])
        db = load_database(self.dir, verify=False)
        self.assertEqual(len(db.warnings), 1)
        self.assertEqual(db.record_count, 3)

    def test_file_list_mismatches(self):
        self.write_manifest({"labour_disruption.json": self.hashes["labour_disruption.json"], "gone.json": "1" * 64})
        with self.assertRaises(DatabaseError) as ctx:
            load_database(self.dir)
        text = " ".join(ctx.exception.problems)
        self.assertIn("cyberattack.json: not listed", text)
        self.assertIn("gone.json: listed", text)

    def test_missing_manifest_is_an_integrity_problem(self):
        with self.assertRaises(DatabaseError):
            load_database(self.dir)
        self.assertEqual(len(load_database(self.dir, verify=False).warnings), 1)

    def test_invalid_json_always_raises(self):
        (self.dir / "broken.json").write_text("{not json", encoding="utf-8")
        self.write_manifest()
        for verify in (True, False):
            with self.subTest(verify=verify), self.assertRaises(DatabaseError):
                load_database(self.dir, verify=verify)

    def test_bad_shape_always_raises(self):
        cases = {
            "no_risk_type": {"records": []},
            "records_not_list": {"risk_type": "natural_hazards", "records": {}},
            "record_without_id": {"risk_type": "natural_hazards", "records": [{"x": 1}]},
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                path = self.dir / "natural_hazards.json"
                _write(path, data)
                with self.assertRaises(DatabaseError):
                    load_database(self.dir, verify=False)
                path.unlink()

    def test_duplicate_evidence_id_across_files(self):
        _write(self.dir / "natural_hazards.json",
               {"risk_type": "natural_hazards", "records": [record("L-1")]})
        with self.assertRaises(DatabaseError) as ctx:
            load_database(self.dir, verify=False)
        self.assertIn("L-1", str(ctx.exception))

    def test_missing_directory(self):
        with self.assertRaises(DatabaseError):
            load_database(self.dir / "nope")


if __name__ == "__main__":
    unittest.main()
