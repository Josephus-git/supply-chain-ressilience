"""D11 no-graph baseline: with graph_off=True, Risk Assessment must not call the
Cypher LLM, must not touch Neo4j, and must still return a valid trace.

Runs without Neo4j or an OpenAI key (the fakes below fail if anything is called).

    .venv/bin/python -m unittest discover -s webapp/backend/tests -t .
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import date

from supplier_risk_engine.loader import load_database
from webapp.backend.evidence_api import EvidenceView
from webapp.backend.pipeline.assess import assess
from webapp.backend.tests.test_assess import FakeStructuredLLM

DB = load_database()
VIEW = EvidenceView(DB)


class _NoGraph:
    """Any attribute access means the graph was touched."""

    def __getattr__(self, name):
        raise AssertionError(f"graph accessed: {name}")


class GraphOffTests(unittest.TestCase):
    def test_no_cypher_llm_no_graph_and_r7_without_country(self):
        cypher = FakeStructuredLLM([])  # any call would pop from an empty list and fail the run
        report = FakeStructuredLLM([])

        async def run():
            events = []
            async for ev in assess(
                mode="describe",
                items=[{"text": "Vacuum cleaner motor bar"}],
                goal=None,
                as_of=date(2026, 6, 30),
                date_mode="chosen",
                rerun_of=None,
                client=_NoGraph(),
                db=DB,
                view=VIEW,
                cypher_llm=cypher,
                report_llm=report,
                runs_dir=None,
                graph_off=True,
            ):
                events.append(ev)
            return events

        events = asyncio.run(run())
        run_record = events[-1]["run"]
        self.assertEqual(cypher.prompts, [])
        self.assertEqual(report.prompts, [])
        self.assertTrue(run_record["graph_off"])
        self.assertEqual(run_record["attempts"], [])
        self.assertEqual(run_record["status"], "insufficient_data", run_record.get("error"))


if __name__ == "__main__":
    unittest.main()
