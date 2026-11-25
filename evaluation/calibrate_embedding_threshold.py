"""Calibrate the minimum similarity score for embedding-based candidate retrieval.

EVALUATION_PLAN §2.14 / METHODOLOGY_NOTES R27. Vector search always returns the
nearest products, even for things Dyson never ships. A minimum score turns
"nothing close enough" into no candidates, so the existing R7 path answers
"I don't have enough data to support that". This script measures where that
score should sit. It only reads the graph and calls the embedding model.

Three groups of queries are embedded with the same model as Product.embedding
(text-embedding-3-small) and searched against the `embedding` vector index:

- in_scope: everyday phrasings of products that are in the graph. Written by
  hand, not copied from node text, so they behave like typed parts-list items.
- out_of_scope: products Dyson does not ship. Used ONLY here: do not reuse them
  in the option F refusal test, so that test stays independent of the threshold.
- catalogue: the catalogue names. Shown for information only, because they were
  drafted from the node descriptions and will score optimistically.

Neo4j reports cosine similarity rescaled to 0..1 as (1 + cos) / 2, so scores sit
well above 0.5 even for unrelated text. Compare groups, not absolute values.

Output: one line per query (top 3 scores) plus a summary, and
evaluation/embedding_calibration.csv with every result.

    .venv/bin/python -m evaluation.calibrate_embedding_threshold
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

from webapp.backend.neo4j_client import ReadOnlyNeo4j
from webapp.backend.pipeline.retrieve import openai_embedder, retrieve_products
from webapp.backend.products_api import load_categories

TOP_K = 5
OUT = Path(__file__).with_name("embedding_calibration.csv")

IN_SCOPE = [
    "cordless vacuum cleaner",
    "stick vacuum",
    "vacuum spare parts",
    "vacuum cleaner battery",
    "hair dryer",
    "hair styler",
    "air purifier",
    "desk fan",
    "fan heater",
    "hand dryer",
    "replacement filter",
    "power cable",
    "floor lamp",
    "wet floor cleaner",
    "brush bar",
]

OUT_OF_SCOPE = [
    "bicycle tyres",
    "ground coffee",
    "steel beams",
    "frozen shrimp",
    "cotton t-shirts",
    "red wine",
    "timber planks",
    "office chairs",
    "football boots",
    "portland cement",
    "printer paper",
    "dog food",
]


def _run(client, embed, group: str, queries: list[str], rows: list[dict]) -> list[float]:
    top1 = []
    for q in queries:
        r = retrieve_products(client, q, top_k=TOP_K, min_score=0.0, embedder=embed)
        scores = [p.score for p in r.products]
        top1.append(scores[0] if scores else 0.0)
        shown = ", ".join(f"{p.score:.3f} {p.product_id} ({(p.product_description or '')[:30]})" for p in r.products[:3])
        print(f"[{group:12}] {q:32} {shown}")
        for rank, p in enumerate(r.products, start=1):
            rows.append({"group": group, "query": q, "rank": rank, "score": round(p.score, 4),
                         "product_id": p.product_id, "product_description": p.product_description})
    return top1


def _describe(name: str, xs: list[float]) -> None:
    print(f"{name:12} n={len(xs):2}  min={min(xs):.3f}  median={statistics.median(xs):.3f}  max={max(xs):.3f}")


def main() -> None:
    client = ReadOnlyNeo4j()
    embed = openai_embedder()
    rows: list[dict] = []
    try:
        cat = sorted({v["name"] for v in load_categories()["products"].values()})
        top_in = _run(client, embed, "in_scope", IN_SCOPE, rows)
        top_out = _run(client, embed, "out_of_scope", OUT_OF_SCOPE, rows)
        top_cat = _run(client, embed, "catalogue", cat, rows)
    finally:
        client.close()

    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print("\nTop-1 score by group:")
    _describe("in_scope", top_in)
    _describe("out_of_scope", top_out)
    _describe("catalogue", top_cat)

    low_in, high_out = min(top_in), max(top_out)
    if low_in > high_out:
        print(f"\nThe groups separate: any threshold between {high_out:.3f} and {low_in:.3f} splits them.")
        print(f"Midpoint: {(low_in + high_out) / 2:.3f}. Record the chosen value and this output in METHODOLOGY_NOTES R27.")
    else:
        print(f"\nThe groups OVERLAP (lowest in-scope {low_in:.3f} <= highest out-of-scope {high_out:.3f}).")
        print("No threshold separates them cleanly. Look at the overlapping queries in the CSV and decide")
        print("which error is worse (missed products vs false candidates); report the trade-off.")
    print(f"\nAll results: {OUT}")


if __name__ == "__main__":
    main()
