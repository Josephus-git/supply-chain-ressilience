"""Home page and Graph Explorer endpoints. Every query is read-only.

Home
    GET /api/home/stats            KPI tiles
    GET /api/home/network          suppliers, Dyson sites, ports and routes for the world map
    GET /api/home/top-suppliers    monthly shipments per company (supplier_basename)

Graph Explorer
    GET /api/graph/suppliers               companies and their Supplier nodes (picker)
    GET /api/graph/start                   Dyson-centred starter view (real relationships)
    GET /api/graph/snapshot                aggregated view of one or more suppliers
    GET /api/graph/nodes/{id}/neighbours   a node, its properties and its neighbours
    GET /api/graph/edges/shipments         the shipments behind an aggregated link
    GET /api/graph/search                  text search over node names and keys
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from functools import lru_cache
from typing import Any

import searoute
from fastapi import APIRouter, HTTPException, Query, Request

from supplier_risk_engine.engine import describe_database

from .config import LOCATIONS_PATH, STUDY_END, STUDY_START
from .graph_model import (
    KINDS,
    SEARCH_PROPERTIES,
    UnknownNodeId,
    match_clause,
    node_out,
    node_return,
    parse_node_id,
)
from .neo4j_client import ReadOnlyNeo4j

home_router = APIRouter(prefix="/api/home", tags=["home"])
graph_router = APIRouter(prefix="/api/graph", tags=["graph"])

# Shipment -> X relationships, collapsed into Supplier -> X links in the snapshot.
SHIPMENT_RELS = ["CONTAINS_PRODUCT", "DEPARTED_FROM", "ARRIVED_AT", "CARRIED_BY", "TRANSPORTED_ON", "CONSIGNED_TO"]

DATE_FILTER = """
  ($date_from IS NULL OR date(sh.arrival_date) >= date($date_from))
  AND ($date_to IS NULL OR date(sh.arrival_date) <= date($date_to))
"""


def _client(request: Request) -> ReadOnlyNeo4j:
    return request.app.state.neo4j


@lru_cache(maxsize=1)
def load_locations() -> dict[str, Any]:
    with LOCATIONS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _date_param(value: str | None, name: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(400, f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}")


def _node_or_400(node_id: str) -> None:
    try:
        parse_node_id(node_id)
    except UnknownNodeId as e:
        raise HTTPException(400, str(e))


# --------------------------------------------------------------------------- home


@home_router.get("/stats")
def home_stats(request: Request) -> dict[str, Any]:
    client = _client(request)
    counts = {
        row["label"]: row["n"]
        for row in client.read(
            "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n", name="label_counts"
        )
    }
    extra = client.read(
        """
        MATCH (s:Supplier)
        WITH count(DISTINCT s.supplier_basename) AS companies
        MATCH (sh:Shipment)
        RETURN companies,
               toString(date(min(sh.arrival_date))) AS first_arrival,
               toString(date(max(sh.arrival_date))) AS last_arrival
        """,
        name="companies_and_dates",
    )[0]
    db = describe_database(request.app.state.evidence_db.index)
    return {
        "suppliers": counts.get("Supplier", 0),
        "supplier_companies": extra["companies"],
        "parent_companies": counts.get("ParentCompany", 0),
        "shipments": counts.get("Shipment", 0),
        "products": counts.get("Product", 0),
        "ports": counts.get("Exit Port", 0) + counts.get("Entry Port", 0),
        "exit_ports": counts.get("Exit Port", 0),
        "entry_ports": counts.get("Entry Port", 0),
        "carriers": counts.get("Carrier", 0),
        "vessels": counts.get("Vessel", 0),
        "buyers": counts.get("Buyer", 0),
        "evidence_records": db["record_count"],
        "evidence_snapshot_id": db["data_snapshot_id"],
        "first_arrival": extra["first_arrival"],
        "last_arrival": extra["last_arrival"],
        "study_window": {"start": STUDY_START.isoformat(), "end": STUDY_END.isoformat()},
    }


def _place(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry:
        return None
    label = entry.get("label") or ", ".join(x for x in (entry.get("city"), entry.get("region")) if x)
    return {
        "lat": entry["lat"],
        "lon": entry["lon"],
        "label": label,
        "country_code": entry.get("country_code"),
        "level": entry.get("level", "city"),
        "basis": entry.get("basis"),
        "source": "reference/locations.json",
    }


@lru_cache(maxsize=512)
def _sea_route(from_lon: float, from_lat: float, to_lon: float, to_lat: float) -> dict[str, Any] | None:
    """Likely ocean path between two ports along the searoute maritime network.

    This is the shortest path over a generic network of shipping lanes, not the
    vessel's recorded track: bills of lading give only the two ports.
    """
    try:
        r = searoute.searoute(
            [from_lon, from_lat], [to_lon, to_lat], append_orig_dest=True, return_passages=True
        )
    except Exception:  # noqa: BLE001 - an unroutable pair falls back to a straight arc
        return None
    coords = [[round(x, 3), round(y, 3)] for x, y in r.geometry["coordinates"]]
    passages = r.properties.get("traversed_passages", [])
    if "suez" in passages:
        via = "Suez Canal"
    elif "panama" in passages:
        via = "Panama Canal"
    elif any(y < -30 and 10 < x < 35 for x, y in coords):
        via = "Cape of Good Hope"
    else:
        via = "Trans-Pacific"
    return {
        "coords": coords,
        "length_km": round(r.properties["length"]),
        "passages": passages,
        "via": via,
    }


def _port_location(kind: str, props: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any] | None:
    prefix = "exit_port" if kind == "exit_port" else "entry_port"
    lat, lon = props.get(f"{prefix}_lat"), props.get(f"{prefix}_lon")
    if lat is not None and lon is not None:
        return {"lat": lat, "lon": lon, "label": props.get(prefix), "level": "port", "source": "graph"}
    table = ref.get("exit_ports" if kind == "exit_port" else "entry_ports", {})
    return _place(table.get(props.get(f"{prefix}_id")))


@home_router.get("/network")
def home_network(request: Request) -> dict[str, Any]:
    """Everything the world map needs, fetched live from Neo4j."""
    client = _client(request)
    ref = load_locations()

    supplier_rows = client.read(
        """
        MATCH (s:Supplier)
        OPTIONAL MATCH (s)-[:SUBSIDIARY_OF]->(p:ParentCompany)
        OPTIONAL MATCH (s)-[:SHIPPED]->(sh:Shipment)
        RETURN s {.*} AS s, p.canonical_name AS parent, p.company_number AS parent_number,
               count(sh) AS shipments,
               toString(date(min(sh.arrival_date))) AS first_arrival,
               toString(date(max(sh.arrival_date))) AS last_arrival
        ORDER BY shipments DESC, s.supplier_name
        """,
        name="network_suppliers",
    )
    # Per-supplier breakdowns for the hover/click card.
    breakdown_rows = client.read(
        """
        MATCH (s:Supplier)-[:SHIPPED]->(sh:Shipment)-[r]->(t)
        WHERE type(r) IN ['CONTAINS_PRODUCT', 'DEPARTED_FROM', 'ARRIVED_AT', 'CARRIED_BY']
        RETURN s.supplier_id AS supplier_id, type(r) AS rel, labels(t) AS t_labels,
               t {.*, embedding: null} AS t_props, count(DISTINCT sh) AS shipments
        ORDER BY shipments DESC
        """,
        name="network_breakdowns",
    )
    route_rows = client.read(
        """
        MATCH (s:Supplier)-[:SHIPPED]->(sh:Shipment)
        MATCH (sh)-[:DEPARTED_FROM]->(xp:`Exit Port`)
        MATCH (sh)-[:ARRIVED_AT]->(ep:`Entry Port`)
        MATCH (sh)-[:CONSIGNED_TO]->(b:Buyer)
        RETURN s.supplier_id AS supplier_id, xp.exit_port_id AS exit_port_id,
               ep.entry_port_id AS entry_port_id, b.buyer_id AS buyer_id,
               count(sh) AS shipments
        ORDER BY shipments DESC
        """,
        name="network_routes",
    )
    buyer_rows = client.read(
        """
        MATCH (b:Buyer)
        OPTIONAL MATCH (sh:Shipment)-[:CONSIGNED_TO]->(b)
        RETURN b {.*} AS b, count(sh) AS shipments ORDER BY shipments DESC
        """,
        name="network_buyers",
    )
    port_rows = client.read(
        """
        MATCH (p) WHERE p:`Exit Port` OR p:`Entry Port`
        OPTIONAL MATCH (sh:Shipment)-[:DEPARTED_FROM|ARRIVED_AT]->(p)
        RETURN labels(p) AS p_labels, p {.*} AS p_props, count(sh) AS shipments
        """,
        name="network_ports",
    )

    breakdown: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    rel_key = {
        "CONTAINS_PRODUCT": "products",
        "DEPARTED_FROM": "exit_ports",
        "ARRIVED_AT": "entry_ports",
        "CARRIED_BY": "carriers",
    }
    for row in breakdown_rows:
        node = node_out(row["t_labels"], row["t_props"])
        breakdown[row["supplier_id"]][rel_key[row["rel"]]].append(
            {"id": node["id"], "name": node["name"], "shipments": row["shipments"]}
        )

    missing: list[str] = []
    suppliers = []
    for row in supplier_rows:
        s = row["s"]
        location = _place(ref["suppliers"].get(s["supplier_id"]))
        if location is None:
            missing.append(f"supplier:{s['supplier_id']}")
        b = breakdown.get(s["supplier_id"], {})
        suppliers.append(
            {
                "id": f"supplier:{s['supplier_id']}",
                "supplier_id": s["supplier_id"],
                "name": s.get("supplier_name"),
                "company": s.get("supplier_basename"),
                "parent": row["parent"],
                "parent_id": f"parent:{row['parent_number']}" if row["parent_number"] else None,
                "reported_country_code": s.get("supplier_country_code"),
                "address": s.get("supplier_address"),
                "location": location,
                "shipments": row["shipments"],
                "first_arrival": row["first_arrival"],
                "last_arrival": row["last_arrival"],
                "products": b.get("products", []),
                "exit_ports": b.get("exit_ports", []),
                "entry_ports": b.get("entry_ports", []),
                "carriers": b.get("carriers", []),
            }
        )

    buyers = []
    for row in buyer_rows:
        b = row["b"]
        location = _place(ref["buyers"].get(b["buyer_id"]))
        if location is None:
            missing.append(f"buyer:{b['buyer_id']}")
        buyers.append(
            {
                "id": f"buyer:{b['buyer_id']}",
                "buyer_id": b["buyer_id"],
                "name": b.get("buyer_name"),
                "reported_country_code": b.get("buyer_country_code"),
                "address": b.get("buyer_address"),
                "location": location,
                "shipments": row["shipments"],
            }
        )

    ports = []
    for row in port_rows:
        node = node_out(row["p_labels"], row["p_props"])
        location = _port_location(node["kind"], node["properties"], ref)
        if location is None:
            missing.append(node["id"])
        ports.append(
            {
                "id": node["id"],
                "kind": node["kind"],
                "name": node["name"],
                "code": node["properties"].get(f"{node['kind']}_code"),
                "location": location,
                "shipments": row["shipments"],
            }
        )
    ports.sort(key=lambda p: (p["kind"], -p["shipments"]))

    links: dict[tuple[str, str], int] = defaultdict(int)
    routes = []
    for row in route_rows:
        links[(row["supplier_id"], row["buyer_id"])] += row["shipments"]
        routes.append(
            {
                "supplier": f"supplier:{row['supplier_id']}",
                "exit_port": f"exit_port:{row['exit_port_id']}",
                "entry_port": f"entry_port:{row['entry_port_id']}",
                "buyer": f"buyer:{row['buyer_id']}",
                "shipments": row["shipments"],
            }
        )

    # One likely sea path per exit -> entry port pair. Catch-all ports drawn at
    # country level have no real coastline point, so they keep a straight arc.
    port_loc = {p["id"]: p["location"] for p in ports}
    sea_paths = []
    for xp, ep in dict.fromkeys((r["exit_port"], r["entry_port"]) for r in routes):
        a, b = port_loc.get(xp), port_loc.get(ep)
        if not a or not b or "country" in (a.get("level"), b.get("level")):
            continue
        path = _sea_route(a["lon"], a["lat"], b["lon"], b["lat"])
        if path:
            sea_paths.append({"exit_port": xp, "entry_port": ep, **path})

    return {
        "suppliers": suppliers,
        "buyers": buyers,
        "ports": ports,
        "sea_paths": sea_paths,
        "links": [
            {"supplier": f"supplier:{s}", "buyer": f"buyer:{b}", "shipments": n}
            for (s, b), n in sorted(links.items(), key=lambda kv: -kv[1])
        ],
        "routes": routes,
        "missing_locations": missing,
        "notes": [
            "Supplier and Dyson site coordinates are city-level, hand-reviewed from each stored "
            "address (reference/locations.json). They are not in the graph.",
            "reported_country_code is the country ImportYeti reports and can differ from the "
            "address location (for example Ihastek Malaysia = CN).",
            "Catch-all ports ('All Other … Ports') are drawn at country level.",
            "Sea paths are the likely shortest route along common shipping lanes (searoute), "
            "not recorded vessel tracks: the shipment records name only the exit and entry ports.",
        ],
    }


def _months(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


@home_router.get("/top-suppliers")
def home_top_suppliers(request: Request, limit: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
    """Monthly shipments per supplier company, grouped by Supplier.supplier_basename."""
    client = _client(request)
    rows = client.read(
        """
        MATCH (s:Supplier)-[:SHIPPED]->(sh:Shipment)
        WHERE date(sh.arrival_date) >= date($start) AND date(sh.arrival_date) <= date($end)
        RETURN s.supplier_basename AS company,
               left(toString(date(sh.arrival_date)), 7) AS month,
               count(sh) AS shipments
        """,
        {"start": STUDY_START.isoformat(), "end": STUDY_END.isoformat()},
        name="monthly_shipments",
    )
    meta_rows = client.read(
        """
        MATCH (s:Supplier)
        OPTIONAL MATCH (s)-[:SUBSIDIARY_OF]->(p:ParentCompany)
        RETURN s.supplier_basename AS company, collect(DISTINCT s.supplier_id) AS supplier_ids,
               collect(DISTINCT p.canonical_name) AS parents
        """,
        name="company_meta",
    )
    months = _months(STUDY_START, STUDY_END)
    position = {m: i for i, m in enumerate(months)}
    series: dict[str, list[int]] = {}
    for row in rows:
        counts = series.setdefault(row["company"], [0] * len(months))
        counts[position[row["month"]]] += row["shipments"]
    meta = {r["company"]: r for r in meta_rows}
    ranked = sorted(series.items(), key=lambda kv: (-sum(kv[1]), kv[0]))[:limit]
    return {
        "months": months,
        "grouping": "Supplier.supplier_basename",
        "series": [
            {
                "company": company,
                "total": sum(counts),
                "monthly": counts,
                "supplier_ids": sorted(f"supplier:{i}" for i in meta[company]["supplier_ids"]),
                "parents": meta[company]["parents"],
            }
            for company, counts in ranked
        ],
    }


# -------------------------------------------------------------------------- graph


@graph_router.get("/suppliers")
def graph_suppliers(request: Request) -> dict[str, Any]:
    """Companies (supplier_basename) with their Supplier nodes, busiest first."""
    rows = _client(request).read(
        """
        MATCH (s:Supplier)
        OPTIONAL MATCH (s)-[:SUBSIDIARY_OF]->(p:ParentCompany)
        OPTIONAL MATCH (s)-[:SHIPPED]->(sh:Shipment)
        RETURN s.supplier_basename AS company, s.supplier_id AS supplier_id,
               s.supplier_name AS name, s.supplier_country_code AS reported_country_code,
               p.canonical_name AS parent, count(sh) AS shipments
        """,
        name="supplier_picker",
    )
    companies: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = companies.setdefault(r["company"], {"company": r["company"], "shipments": 0, "parent": r["parent"], "suppliers": []})
        c["shipments"] += r["shipments"]
        c["suppliers"].append(
            {
                "id": f"supplier:{r['supplier_id']}",
                "name": r["name"],
                "reported_country_code": r["reported_country_code"],
                "shipments": r["shipments"],
            }
        )
    out = sorted(companies.values(), key=lambda c: (-c["shipments"], c["company"]))
    for c in out:
        c["suppliers"].sort(key=lambda s: (-s["shipments"], s["name"]))
    return {"companies": out}


def _resolve_suppliers(client: ReadOnlyNeo4j, values: list[str]) -> list[str]:
    """Accept Supplier node IDs, raw supplier_ids or company basenames; return supplier_ids."""
    keys = [v.removeprefix("supplier:") for v in values]
    rows = client.read(
        """
        MATCH (s:Supplier)
        WHERE s.supplier_id IN $keys OR s.supplier_basename IN $keys
        RETURN DISTINCT s.supplier_id AS id
        """,
        {"keys": keys},
        name="resolve_suppliers",
    )
    return sorted(r["id"] for r in rows)


def _default_supplier(client: ReadOnlyNeo4j) -> list[str]:
    """The busiest company (by shipments in the graph), all of its Supplier nodes."""
    rows = client.read(
        """
        MATCH (s:Supplier)-[:SHIPPED]->(sh:Shipment)
        WITH s.supplier_basename AS company, count(sh) AS n
        ORDER BY n DESC, company LIMIT 1
        MATCH (s:Supplier {supplier_basename: company})
        RETURN s.supplier_id AS id
        """,
        name="default_supplier",
    )
    return sorted(r["id"] for r in rows)


DYSON_BASENAME = "Dyson"
DYSON_PRIMARY = "org:dyson-inc"


@graph_router.get("/start")
def graph_start(
    request: Request,
    suppliers: str | None = Query(
        None,
        description="Comma-separated Supplier IDs, supplier_ids or company basenames. "
        "Default: shipments from any supplier.",
    ),
    shipments: int = Query(3, ge=1, le=10, description="How many shipments to attach to Dyson"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> dict[str, Any]:
    """A small, clean starting graph with real relationships (no aggregation): a Dyson
    buyer in the centre, its latest few shipments (one per supplier where possible), the
    first shipment expanded into every relationship, and that shipment's supplier
    expanded to its parent company."""
    client = _client(request)
    params = {"date_from": _date_param(date_from, "date_from"), "date_to": _date_param(date_to, "date_to")}
    requested = [v.strip() for v in (suppliers or "").split(",") if v.strip()]
    supplier_ids = _resolve_suppliers(client, requested) if requested else None
    if requested and not supplier_ids:
        raise HTTPException(404, f"No Supplier matches {requested}")

    rows = client.read(
        f"""
        MATCH (s:Supplier)-[:SHIPPED]->(sh:Shipment)-[:CONSIGNED_TO]->(b:Buyer)
        WHERE b.buyer_basename = $dyson AND {DATE_FILTER}
          AND ($ids IS NULL OR s.supplier_id IN $ids)
        RETURN b.buyer_id AS buyer, s.supplier_basename AS company, sh.shipment_id AS shipment
        ORDER BY b.buyer_id = $primary DESC, sh.arrival_date DESC, sh.shipment_id
        LIMIT 500
        """,
        {"dyson": DYSON_BASENAME, "primary": DYSON_PRIMARY, "ids": supplier_ids, **params},
        name="start_shipments",
    )
    if not rows:
        raise HTTPException(404, "No shipments to Dyson match these filters")
    buyer_id = rows[0]["buyer"]
    rows = [r for r in rows if r["buyer"] == buyer_id]
    # Latest shipment per company first (variety), then fill with the next latest.
    picked: list[str] = []
    seen: set[str] = set()
    for r in rows:
        if r["company"] not in seen and len(picked) < shipments:
            picked.append(r["shipment"])
            seen.add(r["company"])
    for r in rows:
        if len(picked) >= shipments:
            break
        if r["shipment"] not in picked:
            picked.append(r["shipment"])
    featured = picked[0]

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    def add(row: dict[str, Any], a: str, rel: str, b: str) -> None:
        na = node_out(row[f"{a}_labels"], row[f"{a}_props"])
        nb = node_out(row[f"{b}_labels"], row[f"{b}_props"])
        nodes.setdefault(na["id"], na)
        nodes.setdefault(nb["id"], nb)
        e = _edge(na["id"], nb["id"], rel, aggregated=False)
        edges.setdefault(e["id"], e)

    for row in client.read(
        f"""
        MATCH (sh:Shipment)-[:CONSIGNED_TO]->(b:Buyer {{buyer_id: $buyer}})
        WHERE sh.shipment_id IN $picked
        RETURN {node_return('sh')}, {node_return('b')}
        """,
        {"buyer": buyer_id, "picked": picked},
        name="start_consigned",
    ):
        add(row, "sh", "CONSIGNED_TO", "b")

    for row in client.read(
        f"""
        MATCH (sh:Shipment {{shipment_id: $featured}})-[r]-(m)
        RETURN {node_return('sh')}, type(r) AS rel, startNode(r) = sh AS outgoing, {node_return('m')}
        """,
        {"featured": featured},
        name="start_featured",
    ):
        if row["outgoing"]:
            add(row, "sh", row["rel"], "m")
        else:
            add(row, "m", row["rel"], "sh")

    for row in client.read(
        f"""
        MATCH (s:Supplier)-[:SHIPPED]->(:Shipment {{shipment_id: $featured}})
        MATCH (s)-[:SUBSIDIARY_OF]->(p:ParentCompany)
        RETURN {node_return('s')}, {node_return('p')}
        """,
        {"featured": featured},
        name="start_parent",
    ):
        add(row, "s", "SUBSIDIARY_OF", "p")

    return {
        "mode": "start",
        "center": f"buyer:{buyer_id}",
        "featured": f"shipment:{featured}",
        "suppliers": [f"supplier:{i}" for i in supplier_ids or []],
        "filters": params,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
    }


@graph_router.get("/snapshot")
def graph_snapshot(
    request: Request,
    suppliers: str | None = Query(
        None,
        description="Comma-separated Supplier IDs (supplier:org:…), supplier_ids or company "
        "basenames. Default: the busiest company.",
    ),
    date_from: str | None = Query(None, description="Only shipments arriving on or after this date"),
    date_to: str | None = Query(None, description="Only shipments arriving on or before this date"),
    full: bool = Query(False, description="Return the whole graph, shipments included, with real relationships"),
) -> dict[str, Any]:
    """Aggregated snapshot: each supplier linked directly to its parent, products, ports,
    carriers, vessels and buyers, each link labelled with its shipment count."""
    client = _client(request)
    params = {"date_from": _date_param(date_from, "date_from"), "date_to": _date_param(date_to, "date_to")}
    if full:
        return _full_graph(client, params)

    requested = [v.strip() for v in (suppliers or "").split(",") if v.strip()]
    supplier_ids = _resolve_suppliers(client, requested) if requested else _default_supplier(client)
    if requested and not supplier_ids:
        raise HTTPException(404, f"No Supplier matches {requested}")

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for row in client.read(
        f"""
        MATCH (s:Supplier) WHERE s.supplier_id IN $ids
        OPTIONAL MATCH (s)-[:SUBSIDIARY_OF]->(p:ParentCompany)
        RETURN {node_return('s')}, {node_return('p')}
        """,
        {"ids": supplier_ids},
        name="snapshot_suppliers",
    ):
        s = node_out(row["s_labels"], row["s_props"])
        nodes[s["id"]] = s
        if row["p_props"]:
            p = node_out(row["p_labels"], row["p_props"])
            nodes[p["id"]] = p
            edges.append(_edge(s["id"], p["id"], "SUBSIDIARY_OF", aggregated=False))

    for row in client.read(
        f"""
        MATCH (s:Supplier)-[:SHIPPED]->(sh:Shipment)-[r]->(t)
        WHERE s.supplier_id IN $ids AND type(r) IN $rels AND {DATE_FILTER}
        RETURN s.supplier_id AS sid, type(r) AS rel, {node_return('t')},
               count(DISTINCT sh) AS shipments,
               toString(date(min(sh.arrival_date))) AS first_arrival,
               toString(date(max(sh.arrival_date))) AS last_arrival
        ORDER BY shipments DESC
        """,
        {"ids": supplier_ids, "rels": SHIPMENT_RELS, **params},
        name="snapshot_links",
    ):
        t = node_out(row["t_labels"], row["t_props"])
        nodes.setdefault(t["id"], t)
        edges.append(
            _edge(
                f"supplier:{row['sid']}",
                t["id"],
                row["rel"],
                aggregated=True,
                shipments=row["shipments"],
                first_arrival=row["first_arrival"],
                last_arrival=row["last_arrival"],
            )
        )

    return {
        "mode": "snapshot",
        "suppliers": [f"supplier:{i}" for i in supplier_ids],
        "filters": params,
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def _edge(source: str, target: str, rel: str, *, aggregated: bool, **extra: Any) -> dict[str, Any]:
    edge = {
        "id": f"{'agg' if aggregated else 'rel'}|{source}|{rel}|{target}",
        "source": source,
        "target": target,
        "type": rel,
        "aggregated": aggregated,
    }
    if aggregated:
        edge["via"] = f"(:Supplier)-[:SHIPPED]->(:Shipment)-[:{rel}]->()"
        edge["label"] = str(extra.get("shipments", ""))
    edge.update(extra)
    return edge


def _full_graph(client: ReadOnlyNeo4j, params: dict[str, Any]) -> dict[str, Any]:
    """Every node and relationship; the date filter limits shipments (and what hangs off them)."""
    nodes: dict[str, dict[str, Any]] = {}
    edges = []
    for row in client.read(
        f"""
        MATCH (a)-[r]->(b)
        WITH a, r, b, CASE WHEN a:Shipment THEN a WHEN b:Shipment THEN b END AS sh
        WHERE sh IS NULL OR {DATE_FILTER}
        RETURN {node_return('a')}, type(r) AS rel, {node_return('b')}
        """,
        params,
        name="full_graph",
    ):
        a = node_out(row["a_labels"], row["a_props"])
        b = node_out(row["b_labels"], row["b_props"])
        nodes.setdefault(a["id"], a)
        nodes.setdefault(b["id"], b)
        edges.append(_edge(a["id"], b["id"], row["rel"], aggregated=False))
    return {"mode": "full", "filters": params, "nodes": list(nodes.values()), "edges": edges}


@graph_router.get("/nodes/{node_id:path}/neighbours")
def graph_neighbours(
    request: Request,
    node_id: str,
    aggregate: bool = Query(
        False,
        description="Collapse shipments: link the node straight to what its shipments touch, "
        "with shipment counts (as in the snapshot).",
    ),
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    _node_or_400(node_id)
    client = _client(request)
    match, params = match_clause("n", node_id)
    params.update(date_from=_date_param(date_from, "date_from"), date_to=_date_param(date_to, "date_to"))

    center_rows = client.read(f"{match} RETURN {node_return('n')}", params, name="node")
    if not center_rows:
        raise HTTPException(404, f"No node {node_id}")
    center = node_out(center_rows[0]["n_labels"], center_rows[0]["n_props"])
    kind = center["kind"]

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    if aggregate and kind != "shipment":
        # Direct non-shipment neighbours (SUBSIDIARY_OF) ...
        direct = client.read(
            f"""
            {match}
            MATCH (n)-[r]-(m) WHERE NOT m:Shipment
            RETURN type(r) AS rel, startNode(r) = n AS outgoing, {node_return('m')}
            """,
            params,
            name="neighbours_direct",
        )
        # ... and everything reachable through one shipment, with counts.
        via = client.read(
            f"""
            {match}
            MATCH (n)-[]-(sh:Shipment)-[r2]-(m)
            WHERE m <> n AND {DATE_FILTER}
            RETURN type(r2) AS rel, {node_return('m')}, count(DISTINCT sh) AS shipments,
                   toString(date(min(sh.arrival_date))) AS first_arrival,
                   toString(date(max(sh.arrival_date))) AS last_arrival
            ORDER BY shipments DESC LIMIT $limit
            """,
            {**params, "limit": limit},
            name="neighbours_via_shipments",
        )
        for row in direct:
            m = node_out(row["m_labels"], row["m_props"])
            nodes.setdefault(m["id"], m)
            src, dst = (center["id"], m["id"]) if row["outgoing"] else (m["id"], center["id"])
            edges.append(_edge(src, dst, row["rel"], aggregated=False))
        for row in via:
            m = node_out(row["m_labels"], row["m_props"])
            nodes.setdefault(m["id"], m)
            # Keep the supplier on the source side, as in the snapshot.
            src, dst = (m["id"], center["id"]) if m["kind"] == "supplier" else (center["id"], m["id"])
            edge = _edge(src, dst, row["rel"], aggregated=True, shipments=row["shipments"],
                         first_arrival=row["first_arrival"], last_arrival=row["last_arrival"])
            edge["via"] = "(n)--(:Shipment)--(m)"
            edges.append(edge)
        total = len(direct) + len(via)
    else:
        rows = client.read(
            f"""
            {match}
            MATCH (n)-[r]-(m)
            WHERE NOT m:Shipment OR (
              ($date_from IS NULL OR date(m.arrival_date) >= date($date_from))
              AND ($date_to IS NULL OR date(m.arrival_date) <= date($date_to)))
            RETURN type(r) AS rel, startNode(r) = n AS outgoing, {node_return('m')}
            ORDER BY m:Shipment, m.arrival_date DESC
            """,
            params,
            name="neighbours",
        )
        total = len(rows)
        for row in rows[:limit]:
            m = node_out(row["m_labels"], row["m_props"])
            nodes.setdefault(m["id"], m)
            src, dst = (center["id"], m["id"]) if row["outgoing"] else (m["id"], center["id"])
            edges.append(_edge(src, dst, row["rel"], aggregated=False))

    return {
        "node": center,
        "aggregate": aggregate and kind != "shipment",
        "neighbours": list(nodes.values()),
        "edges": edges,
        "total": total,
        "truncated": total > len(edges),
    }


@graph_router.get("/edges/shipments")
def graph_edge_shipments(
    request: Request,
    source: str = Query(..., description="Node ID at one end of an aggregated link"),
    target: str = Query(..., description="Node ID at the other end"),
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Expand an aggregated link into its underlying shipments and real relationships."""
    _node_or_400(source)
    _node_or_400(target)
    match_a, pa = match_clause("a", source)
    match_b, pb = match_clause("b", target)
    params = {**pa, **pb, "date_from": _date_param(date_from, "date_from"), "date_to": _date_param(date_to, "date_to")}
    rows = _client(request).read(
        f"""
        {match_a}
        {match_b}
        MATCH (a)-[r1]-(sh:Shipment)-[r2]-(b)
        WHERE {DATE_FILTER}
        RETURN {node_return('sh')}, type(r1) AS r1, startNode(r1) = a AS r1_out,
               type(r2) AS r2, startNode(r2) = b AS r2_out
        ORDER BY sh.arrival_date DESC
        """,
        params,
        name="edge_shipments",
    )
    shipments, edges = [], []
    for row in rows:
        sh = node_out(row["sh_labels"], row["sh_props"])
        shipments.append(sh)
        for other, rel, out in ((source, row["r1"], row["r1_out"]), (target, row["r2"], row["r2_out"])):
            src, dst = (other, sh["id"]) if out else (sh["id"], other)
            edges.append(_edge(src, dst, rel, aggregated=False))
    return {"source": source, "target": target, "shipments": shipments, "edges": edges, "count": len(shipments)}


@graph_router.get("/search")
def graph_search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200),
    kinds: str | None = Query(None, description=f"Comma-separated subset of {sorted(KINDS)}"),
    limit: int = Query(25, ge=1, le=200),
) -> dict[str, Any]:
    wanted = [k.strip() for k in (kinds or "").split(",") if k.strip()]
    bad = [k for k in wanted if k not in KINDS]
    if bad:
        raise HTTPException(400, f"Unknown kinds {bad}; use {sorted(KINDS)}")
    labels = [KINDS[k].label for k in wanted] or [k.label for k in KINDS.values()]
    rows = _client(request).read(
        f"""
        MATCH (n)
        WHERE any(l IN labels(n) WHERE l IN $labels)
        WITH n, [k IN $props WHERE n[k] IS NOT NULL
                 AND toLower(toString(n[k])) CONTAINS toLower($q) | k] AS matched
        WHERE size(matched) > 0
        RETURN {node_return('n')}, matched
        """,
        {"q": q.strip(), "labels": labels, "props": SEARCH_PROPERTIES},
        name="search",
    )
    needle = q.strip().lower()
    results = []
    for row in rows:
        node = node_out(row["n_labels"], row["n_props"])
        name = node["name"].lower()
        rank = 0 if name == needle else 1 if name.startswith(needle) else 2 if needle in name else 3
        results.append((rank, node["kind"] == "shipment", node["name"], {**node, "matched": row["matched"]}))
    results.sort(key=lambda r: r[:3])
    return {"q": q, "total": len(results), "results": [r[3] for r in results[:limit]]}
