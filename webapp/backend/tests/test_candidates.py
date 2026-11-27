"""R26/R27: parts-list candidates from catalogue product ids and vector search.

`FakeGraph` tests run without Neo4j or an OpenAI key: they check the threshold,
the trace and the rows handed to `candidates_from_rows`. The live tests use a
stored Product embedding as the query vector (as test_phase1 does), so they need
Neo4j but make no OpenAI call.

    .venv/bin/python -m unittest discover -s webapp/backend/tests -t .
"""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any

from webapp.backend.config import CANDIDATE_MIN_SCORE, CANDIDATE_TOP_K, EMBEDDING_MODEL
from webapp.backend.pipeline.assess import candidates_from_rows
from webapp.backend.pipeline.candidates import retrieve_candidates
from webapp.backend.neo4j_client import ReadOnlyNeo4j

AS_OF = date(2026, 4, 1)


def low_vector(_text: str) -> list[float]:
    """A unit vector along one axis: cosine with any real embedding is near 0, so the
    rescaled score is near 0.5, below the threshold."""
    return [1.0] + [0.0] * 1535


def fail_embedder(_text: str) -> list[float]:
    raise AssertionError("embedder called")


class FakeGraph:
    """Answers the vector query with fixed scores and the supplier query with fixed rows."""

    def __init__(self, scores: list[float], supplier_rows: list[dict[str, Any]] | None = None):
        self.scores = scores
        self.supplier_rows = supplier_rows or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def read(self, cypher, params=None, *, log=None, name=None, log_params=None, **_):
        params = params or {}
        self.calls.append((name, params))
        if log is not None:
            keep = params if log_params is None else {k: params[k] for k in log_params}
            log.append({"name": name, "cypher": cypher, "params": dict(keep), "row_count": 0, "elapsed_ms": 0.0})
        if name == "retrieve_products":
            return [
                {
                    "product_id": f"hs:00000{i}", "hs_code": i, "product_description": f"product {i}",
                    "hs_code_description": None, "full_hs_code_description": None,
                    "score": s, "shipments": 5, "suppliers": 1,
                }
                for i, s in enumerate(self.scores[: params["top_k"]])
            ]
        if name == "candidate_suppliers":
            return [r for r in self.supplier_rows if any(t["product_id"] == r["product_id"] for t in params["targets"])]
        raise AssertionError(f"unexpected query {name}")


class ThresholdTests(unittest.TestCase):
    def test_settings(self):
        self.assertEqual(CANDIDATE_TOP_K, 3)
        self.assertEqual(CANDIDATE_MIN_SCORE, 0.69)

    def test_threshold_is_inclusive_and_trace_keeps_failures(self):
        rows = [
            {"item": 1, "supplier_id": "org:a", "product_id": "hs:000000", "supplier_name": "A"},
            {"item": 1, "supplier_id": "org:b", "product_id": "hs:000001", "supplier_name": "B"},
            {"item": 1, "supplier_id": "org:c", "product_id": "hs:000002", "supplier_name": "C"},
        ]
        g = FakeGraph([0.75, 0.69, 0.6899, 0.68], rows)
        items = [{"n": 1, "text": "cordless vacuum battery", "source": "typed", "product_id": None}]
        t = retrieve_candidates(g, items, AS_OF, embedder=low_vector)
        tr = t["items"][0]
        self.assertEqual(tr["method"], "vector")
        self.assertEqual([r["passed"] for r in tr["results"]], [True, True, False])  # top 3 only
        self.assertEqual(tr["product_ids"], ["hs:000000", "hs:000001"])
        self.assertEqual(tr["threshold"], 0.69)
        self.assertEqual(tr["query_text"], "cordless vacuum battery")
        # Vector search asks for every top-3 score (min_score 0); the threshold is applied after.
        vec = [p for n, p in g.calls if n == "retrieve_products"][0]
        self.assertEqual((vec["top_k"], vec["min_score"], vec["as_of_date"]), (3, 0.0, "2026-04-01"))
        self.assertEqual(t["supplier_query"]["targets"], [{"item": 1, "product_id": "hs:000000"}, {"item": 1, "product_id": "hs:000001"}])
        cand = candidates_from_rows(t["supplier_query"]["rows"], 1)
        self.assertEqual(sorted(c["supplier_id"] for c in cand[1]), ["org:a", "org:b"])
        self.assertEqual(t["embedding_calls"], 1)
        self.assertEqual((t["method"], t["embedding_model"], t["top_k"], t["min_score"]), ("embedding", EMBEDDING_MODEL, 3, 0.69))
        # The 1536-dim vector is not stored in the trace.
        self.assertTrue(t["queries"][0]["params"]["query_vector"].startswith("<1536-dim"))

    def test_nothing_above_threshold_runs_no_supplier_query(self):
        g = FakeGraph([0.68, 0.6, 0.55])
        items = [{"n": 1, "text": "garden hose", "source": "typed", "product_id": None}]
        t = retrieve_candidates(g, items, AS_OF, embedder=low_vector)
        self.assertEqual(t["items"][0]["product_ids"], [])
        self.assertEqual(t["supplier_query"]["rows"], [])
        self.assertNotIn("candidate_suppliers", [n for n, _ in g.calls])

    def test_catalogue_item_uses_its_product_id_without_embedding(self):
        rows = [{"item": 1, "supplier_id": "org:a", "product_id": "hs:851632", "supplier_name": "A"}]
        g = FakeGraph([], rows)
        items = [{"n": 1, "text": "Airwrap hair styler", "source": "catalogue", "product_id": "hs:851632"}]
        t = retrieve_candidates(g, items, AS_OF, embedder=fail_embedder)
        tr = t["items"][0]
        self.assertEqual((tr["method"], tr["product_ids"], tr["results"]), ("catalogue", ["hs:851632"], []))
        self.assertEqual(t["embedding_calls"], 0)
        self.assertEqual([n for n, _ in g.calls], ["candidate_suppliers"])
        self.assertEqual(t["supplier_query"]["targets"], [{"item": 1, "product_id": "hs:851632"}])


class LiveRetrievalTests(unittest.TestCase):
    """Against the real graph: a product's own stored embedding must find that product
    first, and the supplier query must return exactly the suppliers that shipped it."""

    PRODUCT = "hs:851632"

    @classmethod
    def setUpClass(cls):
        try:
            cls.client = ReadOnlyNeo4j()
            cls.client.verify()
        except Exception as e:  # pragma: no cover - environment dependent
            raise unittest.SkipTest(f"Neo4j unavailable: {e}")
        cls.vector = cls.client.read("MATCH (p:Product {product_id: $pid}) RETURN p.embedding AS e", {"pid": cls.PRODUCT})[0]["e"]

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_typed_item_finds_product_and_all_its_suppliers(self):
        items = [{"n": 1, "text": "hair styler", "source": "typed", "product_id": None}]
        t = retrieve_candidates(self.client, items, AS_OF, embedder=lambda _t: self.vector)
        tr = t["items"][0]
        self.assertEqual(len(tr["results"]), 3)
        self.assertEqual(tr["results"][0]["product_id"], self.PRODUCT)
        self.assertGreater(tr["results"][0]["score"], 0.99)
        self.assertIn(self.PRODUCT, tr["product_ids"])
        expected = {
            r["sid"]
            for r in self.client.read(
                "MATCH (s:Supplier)-[:SHIPPED]->(:Shipment)-[:CONTAINS_PRODUCT]->(:Product {product_id: $pid}) RETURN DISTINCT s.supplier_id AS sid",
                {"pid": self.PRODUCT},
            )
        }
        got = {r["supplier_id"] for r in t["supplier_query"]["rows"] if r["product_id"] == self.PRODUCT}
        self.assertEqual(got, expected)
        self.assertTrue(expected)

    def test_unrelated_vector_finds_nothing(self):
        items = [{"n": 1, "text": "flux capacitor", "source": "typed", "product_id": None}]
        t = retrieve_candidates(self.client, items, AS_OF, embedder=low_vector)
        self.assertEqual(len(t["items"][0]["results"]), 3)
        self.assertTrue(all(not r["passed"] for r in t["items"][0]["results"]))
        self.assertEqual(t["supplier_query"]["rows"], [])


if __name__ == "__main__":
    unittest.main()
