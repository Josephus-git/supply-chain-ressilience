"""Run History summaries and the model list (history_api.py, arms.py). No Neo4j, no key."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from webapp.backend.arms import arm_of_models, describe
from webapp.backend.history_api import all_runs, summarise


def assess(run_id, *, arm=None, model="gpt-5.2", status="answered", source="llm", ev=None):
    return {
        "run_id": run_id, "kind": "assess", "mode": "parts", "items": [{"n": 1, "text": "Fan"}], "goal": "Best supplier per item",
        "as_of_date": "2025-06-01", "status": status, "arm": arm, "models": {"report": model},
        "report": {"source": source, "parsed": {"items": [{"status": status, "candidates": [{}, {}]}]}},
        "citations": {"total": 10, "verified": 8, "not_found": 2, "with_note": 1, "uncited_claims": ["summary"]},
        "usage": {"total_tokens": 1000, "calls": 1, "by_model": {model: {}}}, "started_at": "2026-11-27T10:00:00+00:00",
        **({"eval": ev} if ev else {}),
    }


class HistoryTests(unittest.TestCase):
    def test_models_never_include_keys(self):
        d = describe()
        self.assertEqual([a["name"] for a in d["arms"]], ["M1", "M2", "M3"])
        self.assertTrue(all("key_env" not in a for a in d["arms"]))

    def test_arm_inferred_for_old_runs(self):
        self.assertEqual(arm_of_models("gpt-5.2-2025-12-11"), "M1")
        self.assertEqual(arm_of_models("deepseek-flash"), "M2")
        self.assertEqual(arm_of_models(None, "claude-sonnet-5-5"), "M3")
        self.assertIsNone(arm_of_models("llama3.2"))

    def test_summary_fields(self):
        s = summarise(assess("assess-1", arm="M2", model="deepseek-flash"), "app")
        self.assertEqual((s["arm"], s["status"], s["answered_by"], s["ranked"]), ("M2", "answered", "llm", [2]))
        self.assertEqual(s["citations"], {"total": 10, "verified": 8, "not_found": 2, "with_note": 1, "uncited": 1})
        self.assertEqual(summarise(assess("assess-2"), "app")["arm"], "M1")  # inferred from the model name
        self.assertFalse(summarise(assess("assess-3"), "app")["current_pipeline"])  # no R26 retrieval settings
        self.assertTrue(summarise({**assess("assess-4"), "retrieval": {"method": "embedding"}}, "app")["current_pipeline"])

    def test_batch_runs_follow_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pilot"
            (root / "assess").mkdir(parents=True)
            app = Path(tmp) / "app"
            app.mkdir()
            (app / "assess-a.json").write_text(json.dumps(assess("assess-a")))
            ev = {"arm": "M3", "set": "main", "query_id": "s01", "repeat": 0}
            (root / "assess" / "assess-ok.json").write_text(json.dumps(assess("assess-ok", model="claude-sonnet-5-5", ev=ev)))
            (root / "assess" / "assess-infra.json").write_text(json.dumps(assess("assess-infra", status="failed", ev=ev)))
            with (root / "manifest.csv").open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["file", "set", "query_id", "arm", "repeat", "infra_error"])
                w.writeheader()
                w.writerow({"file": "assess/assess-infra.json", "set": "main", "query_id": "s01", "arm": "M3", "repeat": 0, "infra_error": "RateLimitError"})
                w.writerow({"file": "assess/assess-ok.json", "set": "main", "query_id": "s01", "arm": "M3", "repeat": 0, "infra_error": ""})
            runs = all_runs([app], {"pilot": root})
            self.assertEqual(sorted((r["run_id"], r["source"], r["made_by"]) for r in runs),
                             [("assess-a", "pilot", "app"), ("assess-ok", "pilot", "runner")])
            pilot = next(r for r in runs if r["made_by"] == "runner")
            self.assertEqual((pilot["arm"], pilot["query_id"], pilot["set"]), ("M3", "s01", "main"))


if __name__ == "__main__":
    unittest.main()
