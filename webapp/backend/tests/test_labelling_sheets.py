"""Seeded labelling-sheet generator (evaluation/make_labelling_sheets.py).

Synthetic run files only: no Neo4j, no API key.

    .venv/bin/python -m unittest discover -s webapp/backend/tests -t .
"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from evaluation import make_labelling_sheets as mls
from evaluation import run_batch as rb

SAMPLE = rb.read_sample()
GOLD = rb.read_gold()
MANIFEST_COLS = rb.MANIFEST_COLUMNS


def claim(text, cits=("graph:org:a:shipments",)):
    return {"text": text, "citations": list(cits)}


def report(items, n_cands=3):
    out = {"summary": claim("Shared US tariff risk.", ["TARIFF-1"]), "items": []}
    for it in items:
        cands = [{
            "supplier_id": f"org:s{k}", "match_reason": claim(f"Ships item {it['n']}."),
            "risks": [claim("Port closure.", ["PORT-1"])] * (1 + k % 2), "track_record": claim("12 shipments."),
            "deciding_factor": "match", "deciding_reason": "Closest match.",
        } for k in range(n_cands)]
        out["items"].append({"item": it["n"], "status": "answered", "candidates": cands, "set_aside": [],
                             "country_notes": [], "answer": claim(f"Use org:s0 for item {it['n']}.")})
    return out


def assess_run(run_id, job, arm, *, status="answered", source="llm"):
    items = [{**it, "n": i} for i, it in enumerate(job.items, start=1)]
    parsed = None if status == "failed" else report(items)
    return {
        "run_id": run_id, "kind": "assess", "mode": "parts", "items": items, "goal": job.goal,
        "as_of_date": job.as_of_date, "status": status, "error": "ValueError: unreadable" if status == "failed" else None,
        "models": {"report": {"M1": "gpt-5.2", "M2": "deepseek-flash", "M3": "claude-sonnet-5-5"}[arm]},
        "report": None if status == "failed" else {"source": source, "prompt": "ITEMS ... SUPPLIERS ... (the model's input)", "parsed": parsed},
        "citations": {"checks": [{"path": "items.0.candidates.0.risks.0", "citation": "PORT-1", "status": "not_found", "note": None}]},
        "candidates": {"by_item": {"1": [{"supplier_id": "org:s0", "supplier_name": "Supplier Zero"}]}},
        "profiles": {"profiles": {}},
        "eval": {"arm": arm},
    }


def ask_run(run_id, gold):
    return {"run_id": run_id, "kind": "ask", "question": gold["question"], "status": "no_rows",
            "attempts": [{"generate": {"raw": "MATCH (n) RETURN n"}, "check": {"cypher": "MATCH (n) RETURN n"},
                          "run": {"row_count": 0, "rows": []}}],
            "answer": {"text": "The graph has no such data."}, "model": "gpt-5.2"}


class Fixture:
    """A runs/evaluation folder with every main, graph_off and ask refusal run."""

    def __init__(self, root: Path, failed=(), pipeline=()):
        self.runs = root / "runs"
        self.out = root / "labelling"
        (self.runs / "assess").mkdir(parents=True)
        (self.runs / "ask").mkdir()
        rows = []
        n = 0
        for set_name in ("main", "graph_off"):
            for job in rb.plan_jobs(set_name, SAMPLE, GOLD):
                for arm in (["M1"] if set_name == "graph_off" else ["M1", "M2", "M3"]):
                    n += 1
                    rid = f"assess-20261201T000000Z-{n:06x}"
                    key = (set_name, job.query_id, arm)
                    run = assess_run(rid, job, arm, status="failed" if key in failed else "answered",
                                     source="pipeline" if key in pipeline else "llm")
                    (self.runs / "assess" / f"{rid}.json").write_text(json.dumps(run))
                    rows.append({"run_id": rid, "file": f"assess/{rid}.json", "set": set_name, "query_id": job.query_id,
                                 "arm": arm, "graph_off": int(set_name == "graph_off"), "repeat": 0, "status": run["status"]})
        for g in GOLD:
            if g["compare"] != "refusal":
                continue
            for arm in ("M1", "M2", "M3"):
                n += 1
                rid = f"ask-20261201T000000Z-{n:06x}"
                (self.runs / "ask" / f"{rid}.json").write_text(json.dumps(ask_run(rid, g)))
                rows.append({"run_id": rid, "file": f"ask/{rid}.json", "set": "ask_gold", "query_id": g["id"], "arm": arm,
                             "graph_off": 0, "repeat": 0, "status": "no_rows"})
        # An infrastructure failure that was later re-run must not count.
        rows.insert(0, {**rows[0], "run_id": "assess-x", "file": "assess/missing.json", "infra_error": "RateLimitError"})
        with (self.runs / "manifest.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in MANIFEST_COLS})

    def make(self, sets, **kw):
        kw.setdefault("classmate", "CM")
        return mls.make_round(sets, author="AU", arms=["M1", "M2", "M3"], runs_dir=self.runs, out=self.out, **kw)


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_main_round_sizes_and_double_labelling(self):
        fx = Fixture(self.root)
        info = fx.make(["main"])
        d = fx.out / "main"
        self.assertEqual(info["counts"]["runs"], 60)
        au_c, cm_c = read(d / "claims_AU.csv"), read(d / "claims_CM.csv")
        au_f, cm_f = read(d / "factor_AU.csv"), read(d / "factor_CM.csv")
        self.assertEqual((len(au_c), len(cm_c), len(au_f), len(cm_f)), (120, 24, 60, 12))
        self.assertTrue({r["claim_id"] for r in cm_c} <= {r["claim_id"] for r in au_c})
        self.assertTrue({r["unit_id"] for r in cm_f} <= {r["unit_id"] for r in au_f})
        units = read(d / "units_map.csv")
        for arm in ("M1", "M2", "M3"):
            arm_claims = [u for u in units if u["task"] == "claims" and u["arm"] == arm]
            self.assertEqual((len(arm_claims), sum(int(u["double_labelled"]) for u in arm_claims)), (40, 8))
            arm_f = [u for u in units if u["task"] == "factor" and u["arm"] == arm]
            self.assertEqual((len(arm_f), sum(int(u["double_labelled"]) for u in arm_f)), (20, 4))
        self.assertEqual(len(read(d / "rubric_AU.csv")), 60)
        self.assertEqual(len(read(d / "rubric_CM.csv")), 60)
        self.assertEqual(len(list((d / "outputs").glob("R*.md"))), 60)

    def test_same_runs_same_sheets(self):
        a, b = self.root / "a", self.root / "b"
        Fixture(a).make(["main"])
        Fixture(b).make(["main"])
        for name in ("claims_AU.csv", "factor_CM.csv", "rubric_AU.csv", "units_map.csv"):
            ra, rb_ = read(a / "labelling/main" / name), read(b / "labelling/main" / name)
            strip = lambda rows: [{k: v for k, v in r.items() if k != "run_id" or not v.startswith("assess-")} for r in rows]  # noqa: E731
            self.assertEqual(strip(ra), strip(rb_), name)

    def test_outputs_do_not_reveal_model_or_run(self):
        fx = Fixture(self.root)
        fx.make(["main"])
        d = fx.out / "main"
        bm = read(d / "blind_map.csv")
        for path in (d / "outputs").glob("*.md"):
            text = path.read_text()
            for word in ("gpt", "deepseek", "claude", "sonnet", "M1", "M2", "M3", "assess-2026", "graph_off", "token"):
                self.assertNotIn(word, text, f"{path.name} reveals {word}")
        for name in ("claims_AU.csv", "factor_AU.csv", "rubric_CM.csv"):
            body = (d / name).read_text()
            self.assertNotIn("assess-", body)
            self.assertNotIn("deepseek", body)
        # Arms are mixed in sheet order: the first ten rubric rows are not all one arm.
        arm_of = {r["blind_id"]: r["arm"] for r in bm}
        first = [arm_of[r["run_id"]] for r in read(d / "rubric_AU.csv")[:10]]
        self.assertGreater(len(set(first)), 1)

    def test_claim_rows_carry_flags_and_text(self):
        fx = Fixture(self.root)
        fx.make(["main"])
        rows = read(fx.out / "main" / "claims_AU.csv")
        self.assertTrue(all(r["claim_text"] and r["where"] for r in rows))
        flagged = [r for r in rows if r["where"] == "Item 1: candidate 1, risk 1"]
        self.assertTrue(all("PORT-1: not found" in r["citation_flags"] for r in flagged))
        others = [r for r in rows if r["where"] != "Item 1: candidate 1, risk 1"]
        self.assertTrue(all(r["citation_flags"] == "" for r in others))

    def test_failed_and_pipeline_runs(self):
        failed = {("main", "s01", "M2")}
        pipeline = {("main", "s02", "M1")}
        fx = Fixture(self.root, failed=failed, pipeline=pipeline)
        info = fx.make(["main"])
        d = fx.out / "main"
        self.assertEqual(info["counts"]["runs"], 59)
        ex = read(d / "excluded.csv")
        self.assertEqual([(r["query_id"], r["arm"]) for r in ex], [("s01", "M2")])
        bm = {(r["query_id"], r["arm"]): r["blind_id"] for r in read(d / "blind_map.csv")}
        pipe_blind = bm[("s02", "M1")]
        self.assertIn(pipe_blind, {r["run_id"] for r in read(d / "rubric_AU.csv")})  # scored on its merits
        self.assertNotIn(pipe_blind, {u["blind_id"] for u in read(d / "units_map.csv")})  # no model claims
        self.assertIn("no model wrote it", (d / "outputs" / f"{pipe_blind}.md").read_text())

    def test_missing_runs_and_rounds(self):
        fx = Fixture(self.root)
        lines = (fx.runs / "manifest.csv").read_text().splitlines()
        (fx.runs / "manifest.csv").write_text("\n".join(l for l in lines if ",main,s05,M3," not in l) + "\n")
        with self.assertRaises(SystemExit):
            fx.make(["main"])
        info = fx.make(["main"], allow_missing=True)
        self.assertEqual(info["missing"], ["main/s05/M3/0"])
        with self.assertRaises(SystemExit):  # never overwritten
            fx.make(["main"], allow_missing=True)
        go = fx.make(["graph_off"])
        ids = sorted(int(r["blind_id"][1:]) for r in read(fx.out / "graph_off" / "blind_map.csv"))
        self.assertEqual(ids, list(range(60, 80)))  # continues after R59 (59 runs in round 1)
        self.assertFalse((fx.out / "graph_off" / "claims_AU.csv").exists())
        self.assertEqual(go["counts"]["rubric_outputs"], 20)

    def test_ask_refusal_round(self):
        fx = Fixture(self.root)
        info = fx.make(["ask_gold"], classmate=None)
        rows = read(fx.out / "ask_gold" / "ask_refusal_AU.csv")
        self.assertEqual(len(rows), 15)  # q31-q35 x 3 arms
        self.assertTrue(all(r["run_id"].startswith("A") for r in rows))
        self.assertEqual(info["counts"]["ask_refusal_runs"], 15)

    def test_cli_checks(self):
        for argv in (["--sets", "main", "--author", "AU"], ["--sets", "main,ask_gold", "--author", "AU", "--classmate", "CM"],
                     ["--sets", "main", "--author", "A/U", "--classmate", "CM"]):
            with self.assertRaises(SystemExit):
                mls.main(argv)


if __name__ == "__main__":
    unittest.main()
