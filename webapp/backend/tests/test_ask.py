"""Phase 3 tests: Ask the Graph (safety checks, pipeline, SSE endpoint, examples).

The safety tests need nothing. The rest run against the live Neo4j in .env
and are skipped if it is unreachable. No OpenAI calls: a LangChain fake chat
model plays the LLM, replying with fixed Cypher and answer text.

    .venv/bin/python -m unittest discover -s webapp/backend/tests -t .
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from webapp.backend.ask.pipeline import ask, check_cypher, load_examples, run_query
from webapp.backend.ask.safety import MAX_ROWS, mask_literals, static_checks, strip_fences
from webapp.backend.neo4j_client import ReadOnlyNeo4j
from webapp.backend.runs_store import load_run

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


GOOD = load_examples()[0]["reference_cypher"]  # q01: top vacuum suppliers from Tanjung Pelepas


class SafetyTests(unittest.TestCase):
    def assertRejected(self, cypher: str, check: str):
        r = static_checks(cypher)
        self.assertFalse(r.ok, cypher)
        self.assertIn(check, [c.name for c in r.checks if not c.ok], cypher)

    def test_write_clauses_rejected(self):
        for q in (
            "CREATE (n:X) RETURN n",
            "MATCH (n) DETACH DELETE n RETURN 1",
            "MATCH (s:Supplier) SET s.x = 1 RETURN s",
            "MATCH (s:Supplier) REMOVE s.x RETURN s",
            "MERGE (n:X {a: 1}) RETURN n",
            "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
            "MATCH (n) FOREACH (x IN [1] | SET n.y = x) RETURN n",
            "DROP INDEX foo",
            "match (n) set n.a = 1 return n",
        ):
            self.assertRejected(q, "read_only")

    def test_procedures_rejected_except_allowlist(self):
        self.assertRejected("CALL apoc.periodic.iterate('a','b',{}) YIELD batches RETURN batches", "procedures")
        self.assertRejected("CALL dbms.killQueries(['x']) YIELD queryId RETURN queryId", "procedures")
        self.assertTrue(static_checks("CALL db.labels() YIELD label RETURN label").ok)
        # Subqueries are fine.
        self.assertTrue(static_checks("CALL { MATCH (s:Supplier) RETURN s } RETURN count(s) AS n").ok)

    def test_multiple_statements_rejected(self):
        self.assertRejected("MATCH (n) RETURN n; MATCH (m) DETACH DELETE m", "single_statement")
        # A trailing semicolon is just stripped.
        r = static_checks("MATCH (n:Supplier) RETURN n LIMIT 5;")
        self.assertTrue(r.ok)
        self.assertFalse(r.cypher.endswith(";"))

    def test_keywords_inside_strings_and_names_are_ignored(self):
        q = "MATCH (p:Product) WHERE toLower(p.product_description) CONTAINS 'set of delete create' RETURN p.product_description AS d"
        self.assertTrue(static_checks(q).ok)
        self.assertTrue(static_checks("MATCH (e:`Exit Port`) // SET a comment\nRETURN e.exit_port AS port").ok)
        self.assertEqual(len(mask_literals("'abc' `x y`")), len("'abc' `x y`"))

    def test_needs_return(self):
        self.assertRejected("MATCH (n)", "returns_rows")
        self.assertRejected("", "not_empty")

    def test_row_limit(self):
        r = static_checks("MATCH (s:Supplier) RETURN s.supplier_name AS n ORDER BY n")
        self.assertTrue(r.cypher.endswith(f"LIMIT {MAX_ROWS}"))
        self.assertTrue(static_checks("MATCH (s:Supplier) RETURN s LIMIT 3").cypher.endswith("LIMIT 3"))
        self.assertTrue(static_checks("MATCH (s:Supplier) RETURN s LIMIT 100000").cypher.endswith(f"LIMIT {MAX_ROWS}"))

    def test_strip_fences(self):
        self.assertEqual(strip_fences("```cypher\nMATCH (n) RETURN n\n```"), "MATCH (n) RETURN n")
        self.assertEqual(strip_fences("```\nMATCH (n) RETURN n\n```"), "MATCH (n) RETURN n")
        self.assertEqual(strip_fences("  MATCH (n) RETURN n "), "MATCH (n) RETURN n")


class ExplainTests(unittest.TestCase):
    def setUp(self):
        self.client = _live()

    def test_syntax_error_fails_compile(self):
        r = check_cypher(self.client, "MATCH (n RETURN n")
        self.assertFalse(r.ok)
        self.assertIn("compiles", [c.name for c in r.checks if not c.ok])

    def test_unknown_names_fail(self):
        r = check_cypher(self.client, "MATCH (s:Suplier)-[:SHIPS]->(x) RETURN s.nope AS n")
        self.assertFalse(r.ok)
        bad = next(c for c in r.checks if c.name == "schema_names")
        for name in ("Suplier", "SHIPS", "nope"):
            self.assertIn(name, bad.detail)

    def test_good_query_passes(self):
        r = check_cypher(self.client, GOOD)
        self.assertTrue(r.ok, r.problems)


class ExampleQuestionTests(unittest.TestCase):
    """Every reference Cypher passes the checks (so its names exist in Neo4j) and returns rows."""

    def test_reference_cypher(self):
        c = _live()
        examples = load_examples()
        self.assertGreaterEqual(len(examples), 8)
        self.assertEqual(len({q["id"] for q in examples}), len(examples))
        for q in examples:
            with self.subTest(q["id"]):
                r = check_cypher(c, q["reference_cypher"])
                self.assertTrue(r.ok, r.problems)
                result = run_query(c, r.cypher)
                self.assertTrue(result["ok"], result.get("error"))
                self.assertGreater(result["row_count"], 0)


class RunQueryTests(unittest.TestCase):
    def test_nodes_become_chips_and_graph(self):
        c = _live()
        result = run_query(
            c,
            "MATCH (s:Supplier)-[r:SUBSIDIARY_OF]->(pc:ParentCompany) RETURN s, r, pc LIMIT 5",
        )
        self.assertTrue(result["ok"])
        row = result["rows"][0]
        self.assertTrue(row["s"]["$node"]["id"].startswith("supplier:"))
        self.assertEqual(row["r"], {"$rel": {"type": "SUBSIDIARY_OF"}})
        g = result["graph"]
        kinds = {n["kind"] for n in g["nodes"]}
        self.assertEqual(kinds, {"supplier", "parent"})
        self.assertTrue(all(e["type"] == "SUBSIDIARY_OF" for e in g["edges"]))
        self.assertGreater(len(g["edges"]), 0)
        self.assertNotIn("embedding", json.dumps(result))

    def test_returned_nodes_are_connected(self):
        # No relationship in the rows; the graph fills it in.
        c = _live()
        result = run_query(c, "MATCH (s:Supplier)-[:SUBSIDIARY_OF]->(pc:ParentCompany) RETURN s, pc LIMIT 3")
        self.assertGreater(len(result["graph"]["edges"]), 0)

    def test_scalar_rows_have_no_graph(self):
        result = run_query(_live(), "MATCH (s:Supplier) RETURN count(s) AS n")
        self.assertIsNone(result["graph"])
        self.assertEqual(result["columns"], ["n"])

    def test_row_cap(self):
        result = run_query(_live(), "MATCH (sh:Shipment) RETURN sh.shipment_id AS id", max_rows=10)
        self.assertEqual(result["row_count"], 10)
        self.assertTrue(result["truncated"])


def collect(question: str, replies: list[str], runs_dir: Path | None) -> list[dict]:
    llm = FakeListChatModel(responses=replies)

    async def go():
        return [e async for e in ask(question, client=_live(), llm=llm, runs_dir=runs_dir)]

    return asyncio.run(go())


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runs = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_happy_path(self):
        events = collect("Top vacuum suppliers from Tanjung Pelepas?", [f"```cypher\n{GOOD}\n```", "Ihastek leads."], self.runs)
        steps = [(e["step"], e["status"]) for e in events if e["event"] == "step"]
        self.assertEqual(
            steps,
            [
                ("generate_cypher", "running"), ("generate_cypher", "done"),
                ("check_cypher", "running"), ("check_cypher", "done"),
                ("run_query", "running"), ("run_query", "done"),
                ("write_answer", "running"), ("write_answer", "done"),
            ],
        )
        self.assertEqual(events[0]["event"], "run")
        self.assertEqual(events[-1]["event"], "done")
        tokens = "".join(e["text"] for e in events if e["event"] == "token")
        self.assertEqual(tokens, "Ihastek leads.")
        run = events[-1]["run"]
        self.assertEqual(run["status"], "answered")
        self.assertEqual(len(run["attempts"]), 1)
        self.assertGreater(run["attempts"][0]["run"]["row_count"], 0)
        # The answer prompt saw the rows.
        self.assertIn("shipments", run["answer"]["prompt"])
        stored = load_run(self.runs, run["run_id"])
        self.assertEqual(stored["answer"]["text"], "Ihastek leads.")

    def test_retry_after_bad_cypher(self):
        events = collect("Top vacuum suppliers?", ["MATCH (s:Suplier) RETURN s.nope AS x", GOOD, "Answer."], self.runs)
        run = events[-1]["run"]
        self.assertEqual(len(run["attempts"]), 2)
        self.assertFalse(run["attempts"][0]["check"]["ok"])
        self.assertIsNone(run["attempts"][0]["run"])
        # The retry prompt carries the first attempt and its problem.
        retry_prompt = run["attempts"][1]["generate"]["prompt"]
        self.assertIn("Suplier", retry_prompt)
        self.assertIn("previous attempt", retry_prompt.lower())
        self.assertEqual(run["status"], "answered")

    def test_write_is_refused_and_never_run(self):
        events = collect("Delete everything", ["MATCH (n) DETACH DELETE n", "MATCH (n) DETACH DELETE n"], self.runs)
        run = events[-1]["run"]
        self.assertEqual(run["status"], "failed")
        self.assertTrue(all(a["run"] is None for a in run["attempts"]))
        self.assertTrue(any(e["event"] == "error" for e in events))
        self.assertIsNone(run["answer"])

    def test_no_rows_after_retry_still_answers(self):
        empty = "MATCH (s:Supplier) WHERE s.supplier_name = 'zzz-no-such' RETURN s.supplier_name AS name"
        events = collect("Who is zzz?", [empty, empty, "The graph returned no matching data."], self.runs)
        run = events[-1]["run"]
        self.assertEqual(len(run["attempts"]), 2)
        self.assertEqual(run["status"], "no_rows")
        self.assertIn("(no rows)", run["answer"]["prompt"])


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from webapp.backend.main import create_app

        cls.tmp = tempfile.TemporaryDirectory()
        cls.llm = FakeListChatModel(responses=[GOOD, "Answer from rows."])
        cls.http = TestClient(create_app(neo4j_client=_live(), ask_llm=cls.llm, ask_runs_dir=Path(cls.tmp.name)))
        cls.http.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.http.__exit__(None, None, None)
        cls.tmp.cleanup()

    def test_examples_hide_reference_cypher(self):
        body = self.http.get("/api/ask/examples").json()
        self.assertGreaterEqual(len(body["questions"]), 8)
        self.assertNotIn("reference_cypher", json.dumps(body))

    def test_sse_stream_and_stored_run(self):
        self.llm.i = 0
        with self.http.stream("POST", "/api/ask", json={"question": "Top vacuum suppliers?"}) as r:
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.headers["content-type"].startswith("text/event-stream"))
            text = "".join(r.iter_text())
        events = [json.loads(m) for m in re.findall(r"^data: (.*)$", text, re.M)]
        self.assertEqual(events[-1]["event"], "done")
        run_id = events[-1]["run"]["run_id"]
        runs = self.http.get("/api/ask/runs").json()["runs"]
        self.assertIn(run_id, [x["run_id"] for x in runs])
        self.assertEqual(self.http.get(f"/api/ask/runs/{run_id}").json()["status"], "answered")

    def test_validation(self):
        self.assertEqual(self.http.post("/api/ask", json={"question": "x"}).status_code, 422)
        self.assertEqual(self.http.get("/api/ask/runs/../../etc").status_code, 404)
        self.assertEqual(self.http.get("/api/ask/runs/ask-nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
