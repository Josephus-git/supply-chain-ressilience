"""Step 1 of the assessment pipeline: BOM line -> candidate Product nodes.

Rebuilt from the deleted rag/vector_cypher_retriever.py (see git history before
commit 92edc08). Differences:

- The query text is embedded with LangChain's `OpenAIEmbeddings` using
  text-embedding-3-small, the model rag/update_embeddings.py used to fill
  `Product.embedding`, and searched against the vector index `embedding`.
- Retrieval stops at products. Supplier aggregation is the job of
  `build_profiles` (phase 3), and the departure-port filter is gone.
- The Cypher, parameters and row count are logged for the trace, but the
  1536-dim query vector is not.
- Read-only: runs through `ReadOnlyNeo4j`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Callable, Sequence

from ..config import EMBEDDING_MODEL, VECTOR_INDEX
from ..neo4j_client import ReadOnlyNeo4j

Embedder = Callable[[str], Sequence[float]]

# Cypher 25 SEARCH clause (db.index.vector.queryNodes is deprecated in Neo4j 2026.x).
# The index name cannot be a parameter here, so it is inlined from config.
VECTOR_QUERY = f"""
CYPHER 25
MATCH (node:Product)
  SEARCH node IN (VECTOR INDEX {VECTOR_INDEX} FOR $query_vector LIMIT $top_k) SCORE AS score
WITH node, score WHERE score >= $min_score
OPTIONAL MATCH (node)<-[:CONTAINS_PRODUCT]-(sh:Shipment)
WHERE $as_of_date IS NULL OR date(sh.arrival_date) <= date($as_of_date)
OPTIONAL MATCH (sup:Supplier)-[:SHIPPED]->(sh)
RETURN node.product_id AS product_id,
       node.hs_code AS hs_code,
       node.product_description AS product_description,
       node.hs_code_description AS hs_code_description,
       node.full_hs_code_description AS full_hs_code_description,
       score,
       count(DISTINCT sh) AS shipments,
       count(DISTINCT sup) AS suppliers
ORDER BY score DESC, shipments DESC
"""


@dataclass
class RetrievedProduct:
    product_id: str
    node_id: str
    hs_code: int | None
    product_description: str | None
    hs_code_description: str | None
    full_hs_code_description: str | None
    score: float
    shipments: int
    suppliers: int


@dataclass
class RetrievalResult:
    query_text: str
    embedding_model: str
    index_name: str
    top_k: int
    min_score: float
    as_of_date: str | None
    products: list[RetrievedProduct]
    queries: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def openai_embedder(model: str = EMBEDDING_MODEL) -> Embedder:
    from langchain_openai import OpenAIEmbeddings

    embeddings = OpenAIEmbeddings(model=model)
    return embeddings.embed_query


def retrieve_products(
    client: ReadOnlyNeo4j,
    query_text: str,
    *,
    top_k: int = 10,
    min_score: float = 0.0,
    as_of_date: date | str | None = None,
    embedder: Embedder | None = None,
    log: list[dict[str, Any]] | None = None,
) -> RetrievalResult:
    """Vector search over Product.embedding.

    `as_of_date` only limits the shipment and supplier counts shown with each
    product (no look-ahead); it does not change which products match.
    """
    query_text = (query_text or "").strip()
    if not query_text:
        raise ValueError("query_text is empty")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    embed = embedder or openai_embedder()
    vector = list(embed(query_text))
    as_of = as_of_date.isoformat() if isinstance(as_of_date, date) else as_of_date

    queries: list[dict[str, Any]] = []
    rows = client.read(
        VECTOR_QUERY,
        {
            "top_k": top_k,
            "query_vector": vector,
            "min_score": min_score,
            "as_of_date": as_of,
        },
        log=queries,
        name="retrieve_products",
        log_params=["top_k", "min_score", "as_of_date"],
    )
    queries[-1]["params"]["index_name"] = VECTOR_INDEX
    queries[-1]["params"]["query_text"] = query_text
    queries[-1]["params"]["query_vector"] = f"<{len(vector)}-dim {EMBEDDING_MODEL} embedding of query_text>"
    if log is not None:
        log.extend(queries)

    products = [
        RetrievedProduct(node_id=f"product:{r['product_id']}", **r)
        for r in rows
    ]
    return RetrievalResult(
        query_text=query_text,
        embedding_model=EMBEDDING_MODEL,
        index_name=VECTOR_INDEX,
        top_k=top_k,
        min_score=min_score,
        as_of_date=as_of,
        products=products,
        queries=queries,
    )
