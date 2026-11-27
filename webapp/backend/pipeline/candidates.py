"""Parts-list candidate retrieval without an LLM (R26, R27 in METHODOLOGY_NOTES.md).

    catalogue item -> its own product_id (no keywords, no embedding)
    typed item     -> vector search over Product.embedding: the top CANDIDATE_TOP_K
                      products, kept only if their score is at least CANDIDATE_MIN_SCORE
    then           -> one fixed Cypher query: every supplier that shipped one of those
                      products

The rows keep the shape the Cypher LLM's query used to return (item, supplier_id,
product_id, supplier_name, ...), so `candidates_from_rows`, the date recount (R14),
profiles, evidence and the report are unchanged. Like the LLM-written query, the
supplier query has no date filter: `match_products` and `build_profiles` apply
`as_of_date` afterwards and record pairs that only shipped after the date.

An item with no product at or above the threshold gets no candidates, so the R4/R7
path gives a country-level answer or "I don't have enough data to support that".

Neo4j reports cosine similarity rescaled to 0-1, (1 + cos) / 2, so unrelated text
still scores above 0.5; the threshold was calibrated on that scale (R27).
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

from ..config import CANDIDATE_MIN_SCORE, CANDIDATE_TOP_K, EMBEDDING_MODEL, VECTOR_INDEX
from ..neo4j_client import ReadOnlyNeo4j
from .retrieve import Embedder, openai_embedder, retrieve_products

SUPPLIER_QUERY = """
UNWIND $targets AS t
MATCH (supplier:Supplier)-[:SHIPPED]->(shipment:Shipment)-[:CONTAINS_PRODUCT]->(product:Product {product_id: t.product_id})
RETURN t.item AS item,
       supplier.supplier_id AS supplier_id,
       product.product_id AS product_id,
       supplier.supplier_name AS supplier_name,
       supplier.supplier_country_code AS country,
       product.product_description AS product_description,
       count(DISTINCT shipment) AS shipments
ORDER BY item, shipments DESC, supplier_id, product_id
"""


def retrieval_settings(top_k: int = CANDIDATE_TOP_K, min_score: float = CANDIDATE_MIN_SCORE) -> dict[str, Any]:
    """Stored in the run header so every run records how candidates were found."""
    return {
        "method": "embedding",
        "embedding_model": EMBEDDING_MODEL,
        "index": VECTOR_INDEX,
        "top_k": top_k,
        "min_score": min_score,
        "score_scale": "neo4j (1 + cos) / 2",
    }


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def retrieve_candidates(
    client: ReadOnlyNeo4j,
    items: list[dict[str, Any]],
    as_of: date,
    *,
    embedder: Embedder | None = None,
    top_k: int = CANDIDATE_TOP_K,
    min_score: float = CANDIDATE_MIN_SCORE,
) -> dict[str, Any]:
    """Per-item retrieval trace plus the fixed supplier query and its rows.

    `items` are the numbered request items (`n`, `text`, `source`, `product_id`).
    Vector search runs with min_score 0 so the trace shows the top results that
    failed the threshold too; `passed` marks the ones kept.
    """
    started = time.perf_counter()
    queries: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    embed: Embedder | None = embedder
    embedding_calls = 0

    for it in items:
        t0 = time.perf_counter()
        pid = it.get("product_id")
        if pid:
            traces.append({
                "item": it["n"], "text": it["text"], "source": it.get("source"), "method": "catalogue",
                "query_text": None, "top_k": None, "threshold": None, "results": [],
                "product_ids": [pid], "elapsed_ms": _ms(t0),
            })
            continue
        if embed is None:
            embed = openai_embedder()
        embedding_calls += 1
        found = retrieve_products(client, it["text"], top_k=top_k, min_score=0.0, as_of_date=as_of, embedder=embed, log=queries)
        results = [
            {
                "product_id": p.product_id,
                "product_description": p.product_description,
                "hs_code": p.hs_code,
                "hs_code_description": p.hs_code_description,
                "score": p.score,
                "shipments": p.shipments,
                "suppliers": p.suppliers,
                "passed": p.score >= min_score,
            }
            for p in found.products
        ]
        traces.append({
            "item": it["n"], "text": it["text"], "source": it.get("source"), "method": "vector",
            "query_text": found.query_text, "top_k": top_k, "threshold": min_score, "results": results,
            "product_ids": [r["product_id"] for r in results if r["passed"]], "elapsed_ms": _ms(t0),
        })

    targets = [{"item": t["item"], "product_id": pid} for t in traces for pid in t["product_ids"]]
    t0 = time.perf_counter()
    rows = client.read(SUPPLIER_QUERY, {"targets": targets}, log=queries, name="candidate_suppliers") if targets else []
    supplier_query = {
        "cypher": SUPPLIER_QUERY.strip(),
        "targets": targets,
        "columns": list(rows[0].keys()) if rows else [],
        "rows": rows,
        "row_count": len(rows),
        "elapsed_ms": _ms(t0),
    }
    return {
        **retrieval_settings(top_k, min_score),
        "items": traces,
        "supplier_query": supplier_query,
        "queries": queries,
        "embedding_calls": embedding_calls,
        "elapsed_ms": _ms(started),
    }
