"""Product catalogue for Risk Assessment.

    GET /api/products?as_of=YYYY-MM-DD

Lists the Product nodes (customs lines, not a parts breakdown) with their
shipment and supplier counts up to `as_of` (no look-ahead; the whole study
window when omitted). Category and cleaned name come from the hand-reviewed
reference/product_categories.json, because HS codes are sometimes
misdeclared. The graph is not changed.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from .config import PRODUCT_CATEGORIES_PATH, STUDY_END, STUDY_START
from .neo4j_client import ReadOnlyNeo4j

products_router = APIRouter(prefix="/api/products", tags=["products"])

PRODUCTS_QUERY = """
MATCH (p:Product)
OPTIONAL MATCH (p)<-[:CONTAINS_PRODUCT]-(sh:Shipment)<-[:SHIPPED]-(s:Supplier)
WHERE date(sh.arrival_date) <= date($as_of)
RETURN p.product_id AS product_id, p.hs_code AS hs_code,
       p.product_description AS description, p.hs_code_description AS hs_description,
       count(DISTINCT sh) AS shipments,
       collect(DISTINCT s.supplier_basename) AS companies
"""


@lru_cache(maxsize=1)
def load_categories() -> dict[str, Any]:
    with PRODUCT_CATEGORIES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def parse_as_of(value: str | None) -> date:
    if not value:
        return STUDY_END
    try:
        d = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"as_of must be YYYY-MM-DD, got {value!r}")
    if not STUDY_START <= d <= STUDY_END:
        raise HTTPException(422, f"as_of must be inside the study window {STUDY_START} to {STUDY_END}")
    return d


def catalogue(client: ReadOnlyNeo4j, as_of: date) -> dict[str, Any]:
    ref = load_categories()
    names = ref["products"]
    rows = client.read(PRODUCTS_QUERY, {"as_of": as_of.isoformat()}, name="product_catalogue")
    products = []
    for r in rows:
        meta = names.get(r["product_id"]) or {"category": "other", "name": r["description"], "note": "Not in product_categories.json."}
        products.append(
            {
                "id": r["product_id"],
                "node_id": f"product:{r['product_id']}",
                "name": meta["name"],
                "description": r["description"],
                "hs_code": r["hs_code"],
                "hs_description": r["hs_description"],
                "category": meta["category"],
                "note": meta.get("note"),
                "shipments": r["shipments"],
                "companies": sorted(c for c in r["companies"] if c),
            }
        )
    products.sort(key=lambda p: (-p["shipments"], p["name"]))
    categories = []
    for c in ref["categories"]:
        members = [p for p in products if p["category"] == c["key"]]
        companies = {name for p in members for name in p["companies"]}
        categories.append(
            {
                **c,
                "products": len(members),
                "shipments": sum(p["shipments"] for p in members),
                "companies": len(companies),
            }
        )
    return {
        "as_of": as_of.isoformat(),
        "status": ref.get("_status"),
        "basis": ref.get("_basis"),
        "categories": categories,
        "products": products,
    }


@products_router.get("")
def list_products(request: Request, as_of: str | None = Query(None, description="YYYY-MM-DD inside the study window")) -> dict[str, Any]:
    return catalogue(request.app.state.neo4j, parse_as_of(as_of))
