"""Evaluation batch runner (evaluation/run_batch.py) and the per-provider model settings.

Plan, manifest and model-setting tests need neither Neo4j nor any API key. The
end-to-end tests run the real pipelines against the live Neo4j in .env (skipped if
unreachable) with fake LLMs and a fake embedder, writing to a temporary folder.

    .venv/bin/python -m unittest discover -s webapp/backend/tests -t .
"""

from __future__ import annotations

import asyncio
import csv
import json
import tempfile
import unittest
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda

from evaluation import run_batch as rb
from webapp.backend.llm_factory import model_kwargs
from webapp.backend.config import CYPHER_MAX_TOKENS, CYPHER_TIMEOUT_S, LLM_MAX_RETRIES, OLLAMA_NUM_CTX

SAMPLE = rb.read_sample()
GOLD = rb.read_gold()


class PlanTests(unittest.TestCase):
    def test_set_sizes_match_the_plan(self):
        sizes = {s: len(rb.plan_jobs(s, SAMPLE, GOLD)) for s in rb.SETS}
        self.assertEqual(sizes, {"main": 20, "out_of_scope": 8, "stability": 12, "graph_off": 20, "ask_gold": 35})

    def test_items_dates_and_goal_come_from_the_sample(self):
        jobs = {j.query_id: j for j in rb.plan_jobs("out_of_scope", SAMPLE, GOLD)}
        o08 = jobs["o08"]
        self.assertEqual([i["text"] for i in o08.items], ["Airwrap hair styler", "espresso machine"])
        self.assertEqual([i["product_id"] for i in o08.items], ["hs:851632", None])
        self.assertEqual((o08.as_of_date, o08.date_mode, o08.goal), ("2025-01-29", "random", "Best supplier per item"))

    def test_stability_and_graph_off(self):
        st = rb.plan_jobs("stability", SAMPLE, GOLD)
        self.assertEqual({(j.query_id, j.repeat) for j in st}, {(q, r) for q in ("c02", "c03", "s04", "s08") for r in (1, 2, 3)})
        go = rb.plan_jobs("graph_off", SAMPLE, GOLD)
        self.assertTrue(all(j.graph_off and j.repeat == 0 for j in go))
        self.assertEqual({j.query_id for j in go}, {j.query_id for j in rb.plan_jobs("main", SAMPLE, GOLD)})

    def test_arms(self):
        m1, m2, m3 = rb.arm_for("M1"), rb.arm_for("M2"), rb.arm_for("M3")
        self.assertEqual((m1.provider, m1.model, m1.key_env), ("openai", "gpt-5.2", "OPENAI_API_KEY"))
        self.assertEqual((m2.provider, m2.model, m2.key_env), ("deepseek", "deepseek-flash", "DEEPSEEK_API_KEY"))
        self.assertEqual((m3.provider, m3.model, m3.key_env), ("anthropic", "claude-sonnet-5-5", "ANTHROPIC_API_KEY"))
        with self.assertRaises(SystemExit):
            rb.arm_for("M9")

    def test_graph_off_is_m1_only(self):
        with self.assertRaises(SystemExit):
            rb.main(["--arm", "M3", "--set", "graph_off", "--dry-run"])


class ManifestTests(unittest.TestCase):
    def test_infra_runs_are_not_done(self):
        rows = [
            {"set": "main", "query_id": "s01", "arm": "M1", "repeat": "0", "infra_error": ""},
            {"set": "main", "query_id": "s02", "arm": "M1", "repeat": "0", "infra_error": "RateLimitError"},
        ]
        self.assertEqual(rb.done_keys(rows), {("main", "s01", "M1", 0)})

    def test_infra_error_names(self):
        self.assertEqual(rb.infra_error({"error": "AuthenticationError: Error code: 401"}), "AuthenticationError")
        self.assertEqual(rb.infra_error({"error": "ConnectError: [Errno 111] Connection refused"}), "ConnectError")
        # A timeout or an unreadable reply is model behaviour: kept, not re-run.
        self.assertEqual(rb.infra_error({"error": "APITimeoutError: Request timed out."}), "")
        self.assertEqual(rb.infra_error({"error": "ValueError: The risk LLM's reply could not be read"}), "")
        self.assertEqual(rb.infra_error({"error": None}), "")
        self.assertEqual(rb.infra_error({"error": "BadRequestError: Error code: 400"}), "BadRequestError")


class ModelSettingsTests(unittest.TestCase):
    def test_api_providers_keep_the_c1_controls(self):
        self.assertEqual(
            model_kwargs("openai", max_tokens=CYPHER_MAX_TOKENS, timeout=CYPHER_TIMEOUT_S, stream_usage=True),
            {"max_tokens": CYPHER_MAX_TOKENS, "timeout": CYPHER_TIMEOUT_S, "max_retries": LLM_MAX_RETRIES, "stream_usage": True},
        )
        self.assertEqual(model_kwargs("anthropic", max_tokens=10, timeout=5)["max_tokens"], 10)

    def test_deepseek_has_thinking_off(self):
        kw = model_kwargs("deepseek", max_tokens=16_000, timeout=300)
        self.assertEqual(kw["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual((kw["max_tokens"], kw["timeout"], kw["max_retries"]), (16_000, 300, LLM_MAX_RETRIES))
        self.assertNotIn("extra_body", model_kwargs("openai", max_tokens=1, timeout=1))

    def test_claude_has_thinking_off_and_json_schema(self):
        import os
        from unittest import mock

        from webapp.backend.llm_factory import structured, structured_method
        from webapp.backend.pipeline.llm import make_report_llm
        from webapp.backend.pipeline.prompts import AssessmentReport

        kw = model_kwargs("anthropic", max_tokens=16_000, timeout=300)
        self.assertEqual(kw["thinking"], {"type": "between_tools"})
        self.assertNotIn("thinking", model_kwargs("openai", max_tokens=1, timeout=1))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-not-used"}):
            c = make_report_llm("claude-sonnet-5-5", "anthropic")
        self.assertEqual((c.thinking, c.max_tokens), ({"type": "between_tools"}, 16_000))
        self.assertEqual(structured_method(c), "json_schema")
        bound = structured(c, AssessmentReport)  # no forced tool choice: Anthropic structured outputs
        self.assertNotIn("tool_choice", repr(bound))
        self.assertIn("output_config", repr(bound))
        # Other providers keep LangChain's default, called exactly as before.
        self.assertIsNone(structured_method(make_report_llm("gpt-5.2", "openai")))

    def test_ollama_gets_its_own_names(self):
        kw = model_kwargs("ollama", max_tokens=16_000, timeout=300, stream_usage=True)
        self.assertEqual(kw, {"num_predict": 16_000, "num_ctx": OLLAMA_NUM_CTX, "client_kwargs": {"timeout": 300}})

    def test_built_models(self):
        from webapp.backend.ask.llm import make_cypher_llm
        from webapp.backend.pipeline.llm import make_report_llm

        o = make_report_llm("llama3.2", "ollama")
        self.assertEqual((o.num_predict, o.num_ctx, o.client_kwargs["timeout"]), (16_000, OLLAMA_NUM_CTX, 300))
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key-not-used"}):
            d = make_report_llm("deepseek-flash", "deepseek")
        self.assertEqual((type(d).__name__, d.model_name, d.max_tokens), ("ChatDeepSeek", "deepseek-flash", 16_000))
        self.assertEqual(d.extra_body, {"thinking": {"type": "disabled"}})
        a = make_cypher_llm("gpt-5.2", "openai")
        self.assertEqual((a.max_tokens, a.request_timeout, a.max_retries), (CYPHER_MAX_TOKENS, CYPHER_TIMEOUT_S, LLM_MAX_RETRIES))


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from supplier_risk_engine.loader import load_database
        from webapp.backend.evidence_api import EvidenceView
        from webapp.backend.neo4j_client import ReadOnlyNeo4j

        try:
            cls.client = ReadOnlyNeo4j()
            cls.client.verify()
        except Exception as e:  # pragma: no cover - environment dependent
            raise unittest.SkipTest(f"Neo4j unavailable: {e}")
        cls.db = load_database()
        cls.view = EvidenceView(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.arm = rb.Arm("M1", "openai", "gpt-5.2", None)  # no key check in tests

    def batch(self, jobs, cypher_llm, report_llm, **kw):
        from webapp.backend.tests.test_assess import low_vector

        return asyncio.run(rb.run_batch(
            jobs, self.arm, out_dir=self.out, client=self.client, db=self.db, view=self.view,
            cypher_llm=cypher_llm, report_llm=report_llm, commit="abc123", dirty=False,
            embedder=low_vector, log=lambda _m: None, **kw,
        ))

    def manifest(self):
        with (self.out / "manifest.csv").open(newline="") as f:
            return list(csv.DictReader(f))

    def test_assess_run_eval_block_manifest_and_resume(self):
        from webapp.backend.tests.test_assess import FakeStructuredLLM, report_from_prompt

        jobs = [j for j in rb.plan_jobs("main", SAMPLE, GOLD) if j.query_id == "s01"]
        report = FakeStructuredLLM([report_from_prompt()])
        summary = self.batch(jobs, FakeStructuredLLM([]), report)
        self.assertEqual((summary["ran"], summary["stopped"]), (1, None))
        row = self.manifest()[0]
        self.assertEqual((row["set"], row["query_id"], row["arm"], row["repeat"], row["status"]), ("main", "s01", "M1", "0", "answered"))
        self.assertEqual(row["models"], "report=gpt-5.2;embedding=text-embedding-3-small")
        run = json.loads((self.out / row["file"]).read_text())
        ev = run["eval"]
        self.assertEqual((ev["set"], ev["query_id"], ev["arm"], ev["commit"], ev["dirty"]), ("main", "s01", "M1", "abc123", False))
        self.assertEqual(ev["input_sha256"], rb.sha256(rb.SAMPLE))
        self.assertEqual(ev["retrieval"]["min_score"], 0.69)
        self.assertIsNone(ev["request_extra"])
        self.assertIsNotNone(run["retrieval_trace"])
        self.assertEqual(run["as_of_date"], "2025-02-07")
        # Resume: a run already in the manifest is never repeated.
        again = self.batch(jobs, FakeStructuredLLM([]), FakeStructuredLLM([]))
        self.assertEqual((again["ran"], again["skipped"]), (0, 1))

    def test_infra_failure_stops_and_reruns_later(self):
        from webapp.backend.tests.test_assess import FakeStructuredLLM, report_from_prompt

        class AuthenticationError(Exception):
            pass

        class Expired(FakeStructuredLLM):
            def with_structured_output(self, schema, include_raw=False):
                def fail(_):
                    raise AuthenticationError("Your API key has expired.")

                return RunnableLambda(fail)

        jobs = [j for j in rb.plan_jobs("main", SAMPLE, GOLD) if j.query_id in ("s01", "s03")]
        first = self.batch(jobs, FakeStructuredLLM([]), Expired([]))
        self.assertEqual(first["ran"], 1)  # stopped after the first infrastructure failure
        self.assertIn("AuthenticationError", first["stopped"])
        rows = self.manifest()
        self.assertEqual((rows[0]["status"], rows[0]["infra_error"]), ("failed", "AuthenticationError"))
        second = self.batch(jobs, FakeStructuredLLM([]), FakeStructuredLLM([report_from_prompt(), report_from_prompt()]))
        self.assertEqual(second["ran"], 2)  # s01 again, then s03
        self.assertEqual([r["query_id"] for r in self.manifest()], ["s01", "s01", "s03"])

    def test_ask_gold_run_stores_gold_rows(self):
        gold = next(g for g in GOLD if g["id"] == "q02")
        llm = FakeListChatModel(responses=[f"```cypher\n{gold['reference_cypher']}\n```", "Answer from rows."])
        self.batch([rb.Job("ask_gold", "q02", 0, gold=gold)], llm, None)
        row = self.manifest()[0]
        run = json.loads((self.out / row["file"]).read_text())
        self.assertEqual(run["kind"], "ask")
        self.assertEqual(run["gold"]["compare"], "set")
        self.assertTrue(run["gold"]["result"]["ok"])
        self.assertNotIn("graph", run["gold"]["result"])
        self.assertEqual(run["gold"]["result"]["row_count"], run["attempts"][-1]["run"]["row_count"])
        self.assertEqual(run["eval"]["input_sha256"], rb.sha256(rb.GOLD))
        self.assertTrue(row["file"].startswith("ask/"))

    def test_refusal_gold_keeps_proof_query(self):
        gold = next(g for g in GOLD if g["compare"] == "refusal" and g["reference_cypher"].strip())
        res = rb.gold_result(self.client, gold)
        self.assertEqual(res["result"]["rows"][0]["n"], 0)


if __name__ == "__main__":
    unittest.main()
