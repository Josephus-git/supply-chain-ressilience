"""Phase 5 tests: Risk Assessment (profiles, evidence, citations, pipeline, API, products).

Run against the live Neo4j in .env (skipped if unreachable) and the real
evidence database. No OpenAI calls: a fake model plays both LLMs and returns
structured objects, the way `with_structured_output(..., include_raw=True)` does.

    .venv/bin/python -m unittest discover -s webapp/backend/tests -t .
"""

from __future__ import annotations

import asyncio
import glob
import json
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from supplier_risk_engine.loader import load_database
from webapp.backend.evidence_api import EvidenceView
from webapp.backend.neo4j_client import ReadOnlyNeo4j
from webapp.backend.pipeline.assess import assess, candidates_from_rows
from webapp.backend.pipeline.evidence import lookup_evidence, mentioned_countries
from webapp.backend.pipeline.profiles import build_profiles
from webapp.backend.pipeline.prompts import CANDIDATE_EXAMPLE, INSUFFICIENT
from webapp.backend.pipeline.report import check_citations
from webapp.backend.products_api import load_categories
from webapp.backend.runs_store import load_run

ROOT = Path(__file__).resolve().parents[3]
DB = load_database()
VIEW = EvidenceView(DB)
client: ReadOnlyNeo4j | None = None


def _live() -> ReadOnlyNeo4j:
    global client
    if client is None:
        try:
            c = ReadOnlyNeo4j()
            c.verify()
        except Exception as e:  # pragma: no cover - environment dependent
            raise unittest.SkipTest(f"Neo4j unavailable: {e}")
        client = c
    return client


def tearDownModule() -> None:
    if client is not None:
        client.close()


class FakeStructuredLLM:
    """Stands in for a chat model's `with_structured_output(schema, include_raw=True)`.

    Each response is a dict (validated into the schema) or a callable that
    receives the prompt text and returns one. `prompts` records every prompt.
    """

    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def with_structured_output(self, schema, include_raw: bool = False):
        def call(prompt_value) -> dict[str, Any]:
            text = prompt_value.to_string()
            self.prompts.append(text)
            spec = self.responses.pop(0)
            data = spec(text) if callable(spec) else spec
            raw = AIMessage(content=json.dumps(data), usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
            return {"raw": raw, "parsed": schema.model_validate(data), "parsing_error": None}

        return RunnableLambda(call)


def candidate(cypher: str, countries: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"cypher": cypher, "suggested_countries": countries or [], "interpretation": "test"}


AIRWRAP_QUERY = """
MATCH (s:Supplier)-[:SHIPPED]->(sh:Shipment)-[:CONTAINS_PRODUCT]->(p:Product)
WHERE toLower(p.product_description) CONTAINS 'airwrap'
RETURN 1 AS item, s.supplier_id AS supplier_id, p.product_id AS product_id,
       s.supplier_name AS supplier_name, count(sh) AS shipments
"""
NO_ROWS_QUERY = """
MATCH (s:Supplier)-[:SHIPPED]->(sh:Shipment)-[:CONTAINS_PRODUCT]->(p:Product)
WHERE p.product_description = 'no such product'
RETURN 1 AS item, s.supplier_id AS supplier_id, p.product_id AS product_id
"""


def report_from_prompt(bogus: str = "FAKE-EVIDENCE-999") -> Callable[[str], dict[str, Any]]:
    """A report that ranks the first supplier in the prompt, cites its first linked
    evidence id (if any), its shipment figure, and one id that was never given."""

    def build(text: str) -> dict[str, Any]:
        suppliers_part = text.split("SUPPLIERS (", 1)[1].split("COUNTRY EVIDENCE", 1)[0]
        sid = re.search(r'"supplier_id": "([^"]+)"', suppliers_part).group(1)
        linked = re.findall(r'"evidence_id": "([^"]+)"', suppliers_part)
        risks = [{"text": "A linked risk.", "citations": [linked[0]]}] if linked else []
        return {
            "summary": {"text": "Use the first supplier.", "citations": [f"graph:{sid}:shipments"]},
            "items": [
                {
                    "item": 1,
                    "status": "answered",
                    "candidates": [
                        {
                            "supplier_id": sid,
                            "match_reason": {"text": "It ships the styler.", "citations": [f"match:1:{sid}"]},
                            "risks": risks,
                            "track_record": {"text": "Many shipments.", "citations": [f"graph:{sid}:shipments", bogus]},
                            "deciding_factor": "track_record",
                            "deciding_reason": "Most shipments.",
                        }
                    ],
                    "set_aside": [],
                    "country_notes": [],
                    "answer": {"text": "Use the first supplier.", "citations": [f"graph:{sid}:shipments"]},
                }
            ],
        }

    return build


def low_vector(_text: str) -> list[float]:
    """Scores about 0.5 against every product: below the R27 threshold."""
    return [1.0] + [0.0] * 1535


def stored_embedder(product_id: str) -> Callable[[str], list[float]]:
    """Embeds any text as the stored embedding of `product_id` (no OpenAI call)."""
    vector = _live().read("MATCH (p:Product {product_id: $pid}) RETURN p.embedding AS e", {"pid": product_id})[0]["e"]
    return lambda _text: vector


def collect(gen) -> list[dict[str, Any]]:
    async def run():
        return [e async for e in gen]

    return asyncio.run(run())


# ----------------------------------------------------------------------------- profiles


class ProfileTests(unittest.TestCase):
    def test_profiles_equal_fixture_payloads_at_study_end(self):
        """At the end of the study window no shipment is excluded, so the Neo4j
        profiles must equal the CSV-built fixture payloads key for key."""
        fixtures: dict[str, dict[str, Any]] = {}
        for p in sorted(glob.glob(str(ROOT / "supplier_risk_engine/examples/payloads/*.json"))):
            s = json.loads(Path(p).read_text())["suppliers"][0]
            fixtures.setdefault(s["supplier_id"], s)
        out = build_profiles(_live(), list(fixtures), date(2026, 9, 30))
        self.assertEqual(len(fixtures), 18)
        for sid, expected in fixtures.items():
            got = {k: v for k, v in out["profiles"][sid].items() if not k.startswith("_")}
            self.assertEqual(got, expected, sid)

    def test_as_of_date_limits_profile(self):
        sid = "org:v-s-industrial-berhad"
        as_of = date(2025, 6, 30)
        log: list[dict[str, Any]] = []
        p = build_profiles(_live(), [sid], as_of, log=log)["profiles"][sid]
        expected = _live().read(
            """MATCH (:Supplier {supplier_id: $sid})-[:SHIPPED]->(sh:Shipment)
               WHERE sh.arrival_date <= datetime('2025-06-30T00:00:00Z')
               RETURN count(sh) AS n, max(date(sh.arrival_date)) AS last""",
            {"sid": sid},
        )[0]
        self.assertEqual(p["footprint_window"]["shipments"], expected["n"])
        self.assertEqual(p["footprint_window"]["last_arrival"], expected["last"])
        self.assertLessEqual(p["footprint_window"]["last_arrival"], "2025-06-30")
        self.assertEqual(sum(h["shipments"] for h in p["hs_codes"]), expected["n"])
        self.assertTrue(all(q["params"]["as_of"] == "2025-06-30" for q in log))

    def test_supplier_without_shipments_by_date_is_inactive(self):
        out = build_profiles(_live(), ["org:wencor-m-sdn-bhd", "org:does-not-exist"], date(2025, 1, 10))
        self.assertEqual(out["profiles"], {})
        self.assertEqual([s["supplier_id"] for s in out["inactive"]], ["org:wencor-m-sdn-bhd"])
        self.assertEqual(out["unknown"], ["org:does-not-exist"])

    def test_candidate_example_compiles(self):
        notes = _live().explain(CANDIDATE_EXAMPLE)
        self.assertFalse([n for n in notes if n["code"] in {"01N50", "01N51", "01N52"}])


# ----------------------------------------------------------------------------- evidence + citations


class EvidenceTests(unittest.TestCase):
    def test_mentioned_countries(self):
        self.assertEqual(mentioned_countries("Suppliers in Malaysia or Viet Nam?"), ["MY", "VN"])
        self.assertEqual(mentioned_countries("Tell us about the filters"), [])

    def test_country_lookup_uses_engine_rules(self):
        ev = lookup_evidence(DB, VIEW, {}, date(2026, 4, 1), query="q", countries=[{"code": "CN", "basis": "suggested", "reason": "r"}])
        cn = ev["by_country"]["CN"]
        self.assertEqual(cn["status"], "completed")
        self.assertEqual(cn["basis"], "suggested")
        ids = {l["evidence_id"] for l in cn["links"]}
        self.assertIn("RESTRICT-2025-CN-001", ids)
        # Vessel and carrier records never link by country alone (engine section 7).
        self.assertFalse(any(l["risk_type"] == "carrier_vessel_disruption" for l in cn["links"]))
        self.assertEqual(set(ev["records"]), ids)

    def test_unknown_country_is_skipped(self):
        ev = lookup_evidence(DB, VIEW, {}, date(2026, 4, 1), query="q", countries=[{"code": "ZZ", "basis": "suggested", "reason": "r"}])
        self.assertEqual(ev["by_country"], {})
        self.assertEqual(ev["countries_skipped"][0]["code"], "ZZ")

    def test_check_citations_flags_but_keeps(self):
        evidence = {"by_supplier": {"S1": {"links": [{"evidence_id": "E1"}]}, "S2": {"links": [{"evidence_id": "E2"}]}}, "by_country": {}}
        given = {"E1": {"kind": "evidence"}, "E2": {"kind": "evidence"}, "graph:S1:shipments": {"kind": "graph", "supplier_id": "S1"}}
        report = {
            "summary": {"text": "x", "citations": ["E1"]},
            "items": [{"item": 1, "candidates": [{
                "supplier_id": "S1",
                "match_reason": {"text": "m", "citations": []},
                "risks": [{"text": "r", "citations": ["E1", "E2", "NOPE"]}],
                "track_record": {"text": "t", "citations": ["graph:S1:shipments"]},
            }], "set_aside": [], "country_notes": [], "answer": {"text": "a", "citations": ["graph:S1:shipments", "GONE"]}}],
        }
        before = json.dumps(report, sort_keys=True)
        out = check_citations(report, given, evidence)
        self.assertEqual(json.dumps(report, sort_keys=True), before)  # nothing removed or corrected
        by = {(c["path"], c["citation"]): c for c in out["checks"]}
        self.assertEqual(by[("items.0.candidates.0.risks.0", "E1")]["status"], "verified")
        self.assertEqual(by[("items.0.answer", "graph:S1:shipments")]["status"], "verified")
        self.assertEqual(by[("items.0.answer", "GONE")]["status"], "not_found")
        self.assertIsNone(by[("items.0.candidates.0.risks.0", "E1")]["note"])
        self.assertIn("not linked to this supplier", by[("items.0.candidates.0.risks.0", "E2")]["note"])
        self.assertEqual(by[("items.0.candidates.0.risks.0", "NOPE")]["status"], "not_found")
        self.assertEqual((out["total"], out["verified"], out["not_found"]), (7, 5, 2))
        self.assertEqual(out["uncited_claims"], ["items.0.candidates.0.match_reason"])

    def test_candidates_from_rows(self):
        rows = [
            {"item": 1, "supplier_id": "org:a", "product_id": "hs:1"},
            {"item": 1, "supplier_id": "supplier:org:a", "product_id": "hs:2"},
            {"item": 2, "supplier_id": "org:b", "product_id": None},
            {"item": 9, "supplier_id": "org:c", "product_id": "hs:1"},  # no such item
            {"item": "x", "supplier_id": "org:d"},
        ]
        out = candidates_from_rows(rows, 2)
        self.assertEqual([c["product_ids"] for c in out[1]], [["hs:1", "hs:2"]])
        self.assertEqual(out[2][0]["product_ids"], [])
        self.assertEqual(sorted(out), [1, 2])


# ----------------------------------------------------------------------------- pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_assess(self, cypher_llm, report_llm, **kw):
        args = dict(
            mode="parts",
            items=[{"text": "Airwrap hair styler", "source": "catalogue", "product_id": "hs:851632"}],
            goal="Best supplier per item",
            as_of=date(2026, 4, 1),
            date_mode="chosen",
            rerun_of=None,
        )
        args.update(kw)
        args.setdefault("embedder", low_vector)
        return collect(assess(client=_live(), db=DB, view=VIEW, cypher_llm=cypher_llm, report_llm=report_llm, runs_dir=Path(self.tmp.name), **args))

    def test_full_run(self):
        c_llm = FakeStructuredLLM([])  # R26: parts mode never calls the Cypher LLM
        r_llm = FakeStructuredLLM([report_from_prompt()])
        events = self.run_assess(c_llm, r_llm)
        steps = [(e["step"], e["status"]) for e in events if e["event"] == "step" and e["status"] != "running"]
        self.assertEqual(
            [s for s, _ in steps],
            ["retrieve_candidates", "build_profiles", "lookup_evidence", "write_report", "check_citations"],
        )
        run = events[-1]["run"]
        self.assertEqual(run["status"], "answered")
        self.assertEqual(run["attempts"], [])
        self.assertEqual(c_llm.prompts, [])
        self.assertIsNone(run["models"]["cypher"])
        self.assertEqual(run["retrieval"]["min_score"], 0.69)
        # A catalogue item matches its own product id only.
        trace = run["retrieval_trace"]["items"][0]
        self.assertEqual((trace["method"], trace["product_ids"]), ("catalogue", ["hs:851632"]))
        for c in run["candidates"]["by_item"]["1"]:
            self.assertEqual(c["product_ids"], ["hs:851632"])
        # Profiles and the report prompt only use shipments up to the date.
        for p in run["profiles"]["profiles"].values():
            self.assertLessEqual(p["footprint_window"]["last_arrival"], "2026-04-01")
        self.assertIn("as of 2026-04-01", r_llm.prompts[0])
        # The bogus citation is flagged, not removed.
        cit = run["citations"]
        self.assertEqual(cit["not_found"], 1)
        self.assertIn("FAKE-EVIDENCE-999", json.dumps(run["report"]["parsed"]))
        self.assertEqual(run["usage"]["calls"], 1)
        stored = load_run(Path(self.tmp.name), run["run_id"])
        self.assertEqual(stored["status"], "answered")
        self.assertEqual(stored["items"][0]["source"], "catalogue")
        self.assertEqual(stored["retrieval_trace"]["items"][0]["method"], "catalogue")

    def test_typed_item_uses_vector_search(self):
        r_llm = FakeStructuredLLM([report_from_prompt()])
        items = [{"text": "hair styler", "source": "typed", "product_id": None}]
        run = self.run_assess(FakeStructuredLLM([]), r_llm, items=items, embedder=stored_embedder("hs:851632"))[-1]["run"]
        trace = run["retrieval_trace"]["items"][0]
        self.assertEqual(trace["method"], "vector")
        self.assertEqual(trace["results"][0]["product_id"], "hs:851632")
        self.assertTrue(set(trace["product_ids"]) <= {r["product_id"] for r in trace["results"]})
        self.assertLessEqual(len(trace["product_ids"]), 3)
        matched = {pid for c in run["candidates"]["by_item"]["1"] for pid in c["product_ids"]}
        self.assertTrue(matched <= set(trace["product_ids"]))
        self.assertEqual(run["models"]["embedding"], "text-embedding-3-small")
        self.assertEqual(run["status"], "answered")

    def test_retry_after_write_clause(self):
        """Describe mode keeps the Cypher LLM and its one retry."""
        c_llm = FakeStructuredLLM([candidate("MATCH (n) DETACH DELETE n RETURN 1 AS item"), candidate(AIRWRAP_QUERY)])
        r_llm = FakeStructuredLLM([report_from_prompt()])
        run = self.run_assess(c_llm, r_llm, mode="describe", items=[{"text": "Who supplies Airwrap stylers?", "source": "typed", "product_id": None}], goal=None)[-1]["run"]
        self.assertEqual(len(run["attempts"]), 2)
        self.assertFalse(run["attempts"][0]["check"]["ok"])
        self.assertIn("Write or admin clause", c_llm.prompts[1])
        self.assertEqual(run["status"], "answered")

    def test_nothing_found_skips_report_llm(self):
        """R27 + R7: no product above the threshold, no countries -> the fixed answer, no LLM call."""
        c_llm = FakeStructuredLLM([])
        r_llm = FakeStructuredLLM([])
        run = self.run_assess(c_llm, r_llm, items=[{"text": "flux capacitor", "source": "typed", "product_id": None}])[-1]["run"]
        self.assertEqual(r_llm.prompts, [])
        self.assertEqual(run["retrieval_trace"]["items"][0]["product_ids"], [])
        self.assertEqual(run["candidates"]["by_item"], {})
        self.assertEqual(run["report"]["source"], "pipeline")
        self.assertEqual(run["report"]["parsed"]["summary"]["text"], INSUFFICIENT)
        self.assertEqual(run["status"], "insufficient_data")
        self.assertEqual(run["usage"]["calls"], 0)

    def test_nothing_found_in_describe_mode(self):
        """R7 in describe mode: the Cypher LLM's two attempts return no rows."""
        c_llm = FakeStructuredLLM([candidate(NO_ROWS_QUERY), candidate(NO_ROWS_QUERY)])
        r_llm = FakeStructuredLLM([])
        run = self.run_assess(c_llm, r_llm, mode="describe", items=[{"text": "Who makes flux capacitors?", "source": "typed", "product_id": None}], goal=None)[-1]["run"]
        self.assertEqual(r_llm.prompts, [])
        self.assertEqual(run["status"], "insufficient_data")
        self.assertEqual(run["usage"]["calls"], 2)
        self.assertIsNone(run["retrieval_trace"])
        self.assertEqual(run["retrieval"], {"method": "cypher_llm"})

    def test_country_fallback_from_suggestion(self):
        def country_report(text: str) -> dict[str, Any]:
            self.assertIn('"basis": "suggested"', text)
            return {
                "summary": {"text": "Consider another country.", "citations": ["RESTRICT-2025-CN-001"]},
                "items": [{"item": 1, "status": "country_level", "candidates": [], "set_aside": [], "country_notes": [
                    {"country_code": "CN", "from_suggestion": True, "note": {"text": "Export licensing.", "citations": ["RESTRICT-2025-CN-001"]}}
                ], "answer": {"text": "Consider another country.", "citations": ["RESTRICT-2025-CN-001"]}}],
            }

        c_llm = FakeStructuredLLM([
            candidate(NO_ROWS_QUERY, [{"code": "CN", "reason": "No supplier matched; the request names Chinese parts."}]),
            candidate(NO_ROWS_QUERY, [{"code": "CN", "reason": "Still none."}]),
        ])
        r_llm = FakeStructuredLLM([country_report])
        run = self.run_assess(c_llm, r_llm, mode="describe", items=[{"text": "Who makes flux capacitors?", "source": "typed", "product_id": None}], goal=None)[-1]["run"]
        self.assertEqual(run["evidence"]["by_country"]["CN"]["basis"], "suggested")
        self.assertEqual(run["status"], "country_level")
        self.assertEqual(run["citations"]["not_found"], 0)

    def test_llm_failure_keeps_trace(self):
        class Boom(FakeStructuredLLM):
            def with_structured_output(self, schema, include_raw=False):
                def fail(_):
                    raise TimeoutError("simulated timeout")

                return RunnableLambda(fail)

        run_events = self.run_assess(FakeStructuredLLM([]), Boom([]))
        err = [e for e in run_events if e["event"] == "error"][0]
        self.assertEqual(err["step"], "write_report")
        run = run_events[-1]["run"]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["failed_step"], "write_report")
        self.assertIsNotNone(run["evidence"])


# ----------------------------------------------------------------------------- API + products


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from webapp.backend.main import create_app

        cls.tmp = tempfile.TemporaryDirectory()
        cls.c_llm = FakeStructuredLLM([])
        cls.r_llm = FakeStructuredLLM([])
        cls.http = TestClient(
            create_app(
                neo4j_client=_live(), evidence_db=DB, assess_cypher_llm=cls.c_llm, assess_report_llm=cls.r_llm,
                assess_runs_dir=Path(cls.tmp.name), ask_runs_dir=Path(cls.tmp.name) / "ask", check_openai=False,
                assess_embedder=stored_embedder("hs:851632"),
            )
        )
        cls.http.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.http.__exit__(None, None, None)
        cls.tmp.cleanup()

    def test_sse_and_history(self):
        self.r_llm.responses = [report_from_prompt()]
        body = {
            "mode": "parts", "items": [{"text": "Airwrap", "source": "typed"}], "goal": "",
            "as_of_date": "2026-04-01", "date_mode": "random",
        }
        with self.http.stream("POST", "/api/assess", json=body) as r:
            self.assertEqual(r.status_code, 200)
            text = "".join(r.iter_text())
        events = [json.loads(m) for m in re.findall(r"^data: (.*)$", text, re.M)]
        run = events[-1]["run"]
        self.assertEqual(run["date_mode"], "random")
        self.assertEqual(run["goal"], "Assess supplier risk for these items.")
        runs = self.http.get("/api/runs").json()["runs"]
        self.assertEqual(runs[0]["run_id"], run["run_id"])
        self.assertEqual(runs[0]["tokens"], 120)  # one LLM call: the Cypher LLM is not used in parts mode
        self.assertEqual(self.http.get("/api/runs", params={"mode": "describe"}).json()["runs"], [])
        self.assertEqual(self.http.get(f"/api/runs/{run['run_id']}").json()["status"], "answered")
        # Re-run: a new record linked to the original.
        self.r_llm.responses = [report_from_prompt()]
        with self.http.stream("POST", "/api/assess", json={**body, "as_of_date": "2025-09-01", "rerun_of": run["run_id"]}) as r:
            text = "".join(r.iter_text())
        rerun = json.loads(re.findall(r"^data: (.*)$", text, re.M)[-1])["run"]
        self.assertNotEqual(rerun["run_id"], run["run_id"])
        self.assertEqual(rerun["rerun_of"], run["run_id"])
        # Health counts today's tokens from the stored runs.
        health = self.http.get("/api/health").json()
        self.assertEqual(health["tokens_today"]["used"], 240)
        self.assertEqual(self.c_llm.prompts, [])
        self.assertEqual(health["openai"]["status"], "not_checked")

    def test_validation(self):
        base = {"mode": "parts", "items": [{"text": "fan"}], "as_of_date": "2026-01-01"}
        self.assertEqual(self.http.post("/api/assess", json={**base, "as_of_date": "2027-01-01"}).status_code, 422)
        self.assertEqual(self.http.post("/api/assess", json={**base, "items": []}).status_code, 422)
        self.assertEqual(self.http.post("/api/assess", json={**base, "items": [{"text": "x"}] * 21}).status_code, 422)
        self.assertEqual(self.http.post("/api/assess", json={"mode": "describe", "description": "", "as_of_date": "2026-01-01"}).status_code, 422)
        self.assertEqual(self.http.get("/api/runs/assess-nope").status_code, 404)

    def test_products(self):
        body = self.http.get("/api/products").json()
        self.assertEqual(len(body["products"]), 43)
        cats = {c["key"] for c in load_categories()["categories"]}
        self.assertEqual(set(load_categories()["products"]), {p["id"] for p in body["products"]})
        self.assertTrue(all(p["category"] in cats for p in body["products"]))
        self.assertEqual(sum(c["products"] for c in body["categories"]), 43)
        total = sum(p["shipments"] for p in body["products"])
        early = self.http.get("/api/products", params={"as_of": "2025-03-01"}).json()
        self.assertLess(sum(p["shipments"] for p in early["products"]), total)
        self.assertEqual(self.http.get("/api/products", params={"as_of": "2024-01-01"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
