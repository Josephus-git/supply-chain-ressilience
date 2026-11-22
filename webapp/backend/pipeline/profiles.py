"""build_profiles: fixed Cypher aggregation into engine payload schema 1.1.

The queries are fixed (not LLM-written) so the no-look-ahead rule
(`arrival_date <= as_of_date`) and the engine's payload format never depend on
an LLM (R2 in METHODOLOGY_NOTES.md). The shape follows
SUPPLIER_RISK_EVIDENCE_ENGINE_PLAN.md section 6.1 and the fixture builder in
supplier_risk_engine/examples/build_payloads.py, but reads Neo4j instead of
the processed CSVs. With `as_of_date` at the end of the study window the
profiles equal the fixture payloads (tested).

Every query is logged (name, Cypher, parameters, row count, time) so the
trace shows exactly how each figure was computed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from ..neo4j_client import ReadOnlyNeo4j

SCHEMA_VERSION = "1.1"
EVENT_WINDOW_DAYS = 14
IMPORTING_COUNTRY = "US"  # every entry port and buyer in the data is in the US

# ISO 4217 currency of each country (section 6.1: currency from the supplier
# country through a fixed table). Covers every country the engine can name.
CURRENCY = {
    "AE": "AED", "AU": "AUD", "BD": "BDT", "BE": "EUR", "BN": "BND", "BR": "BRL", "CA": "CAD",
    "CH": "CHF", "CN": "CNY", "CZ": "CZK", "DE": "EUR", "EG": "EGP", "ES": "EUR", "FR": "EUR",
    "GB": "GBP", "HK": "HKD", "HU": "HUF", "ID": "IDR", "IE": "EUR", "IL": "ILS", "IN": "INR",
    "IR": "IRR", "IT": "EUR", "JP": "JPY", "KH": "KHR", "KP": "KPW", "KR": "KRW", "LA": "LAK",
    "LK": "LKR", "MM": "MMK", "MO": "MOP", "MX": "MXN", "MY": "MYR", "NL": "EUR", "NZ": "NZD",
    "PA": "PAB", "PH": "PHP", "PK": "PKR", "PL": "PLN", "PT": "EUR", "RU": "RUB", "SA": "SAR",
    "SE": "SEK", "SG": "SGD", "TH": "THB", "TR": "TRY", "TW": "TWD", "US": "USD", "VN": "VND",
    "ZA": "ZAR",
}

# Exit ports use CBP Schedule K codes; the first three digits identify the
# country. The graph has no port-country property, so the caller derives it.
SCHEDULE_K_COUNTRY = {
    "552": "VN", "557": "MY", "559": "SG", "565": "PH",
    "570": "CN", "580": "KR", "582": "HK", "583": "TW",
}

# The graph's Vessel node for IMO 9444261 is named "Mol Premium" (see build_payloads.py).
_BASE = """
MATCH (s:Supplier) WHERE s.supplier_id IN $ids
OPTIONAL MATCH (s)-[:SUBSIDIARY_OF]->(pc:ParentCompany)
WITH s, collect(DISTINCT pc.canonical_name) AS parents
OPTIONAL MATCH (s)-[:SHIPPED]->(sh:Shipment)
WHERE date(sh.arrival_date) <= date($as_of)
RETURN s.supplier_id AS supplier_id, s.supplier_name AS supplier_name,
       s.supplier_basename AS company, s.supplier_country_code AS country,
       s.supplier_address AS address, parents,
       count(sh) AS shipments,
       min(date(sh.arrival_date)) AS first_arrival,
       max(date(sh.arrival_date)) AS last_arrival
"""


def _dimension(rel: str, label: str, fields: str) -> str:
    return f"""
MATCH (s:Supplier)-[:SHIPPED]->(sh:Shipment)-[:{rel}]->(x:{label})
WHERE s.supplier_id IN $ids AND date(sh.arrival_date) <= date($as_of)
RETURN s.supplier_id AS supplier_id, {fields}, count(DISTINCT sh) AS shipments
"""


QUERIES = {
    "profile_base": _BASE,
    "profile_hs_codes": _dimension("CONTAINS_PRODUCT", "Product", "x.hs_code AS code"),
    "profile_exit_ports": _dimension("DEPARTED_FROM", "`Exit Port`", "x.exit_port AS name, x.exit_port_code AS code"),
    "profile_entry_ports": _dimension(
        "ARRIVED_AT", "`Entry Port`", "x.entry_port AS name, x.entry_port_code AS code, x.entry_port_lon AS lon"
    ),
    "profile_buyers": _dimension("CONSIGNED_TO", "Buyer", "x.buyer_name AS name"),
    "profile_carriers": _dimension("CARRIED_BY", "Carrier", "x.carrier_name AS name, x.carrier_code AS code"),
    "profile_vessels": _dimension("TRANSPORTED_ON", "Vessel", "x.vessel_name AS name"),
}

# Products the Cypher LLM matched to each item, recounted up to as_of_date.
MATCH_QUERY = """
UNWIND $pairs AS pair
MATCH (s:Supplier {supplier_id: pair.supplier_id})-[:SHIPPED]->(sh:Shipment)-[:CONTAINS_PRODUCT]->(p:Product {product_id: pair.product_id})
WHERE date(sh.arrival_date) <= date($as_of)
RETURN pair.item AS item, s.supplier_id AS supplier_id, p.product_id AS product_id,
       p.product_description AS product_description, p.hs_code AS hs_code,
       count(sh) AS shipments, max(date(sh.arrival_date)) AS last_arrival
"""


def hs6(code: Any) -> str:
    """The graph stores HS codes as integers; restore the 6-digit string."""
    return str(code).strip().zfill(6)


def coast(lon: float) -> str:
    """Section 6.1: US entry ports east of -100 longitude are east_gulf."""
    return "east_gulf" if lon > -100 else "west"


def carrier_name(raw: str, code: str) -> str:
    """Graph carrier names carry a 'SCAC - ' prefix; the code is sent separately."""
    prefix = f"{code} - "
    return raw[len(prefix):] if raw.startswith(prefix) else raw


def _sorted(entries: list[dict[str, Any]], key: str = "name") -> list[dict[str, Any]]:
    return sorted(entries, key=lambda e: (-e["shipments"], str(e.get(key))))


def build_profiles(
    client: ReadOnlyNeo4j, supplier_ids: list[str], as_of: date, *, log: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Payload-ready supplier entries for `supplier_ids`, counting shipments up to `as_of`.

    Returns `{"profiles": {supplier_id: entry}, "inactive": [...], "unknown": [...]}`.
    Suppliers with no shipment by `as_of` are listed in `inactive` and get no
    profile: on that date they had not yet supplied Dyson.
    """
    ids = sorted(set(supplier_ids))
    params = {"ids": ids, "as_of": as_of.isoformat()}
    if not ids:
        return {"profiles": {}, "inactive": [], "unknown": []}
    rows = {name: client.read(q, params, log=log, name=name) for name, q in QUERIES.items()}

    dims: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in rows["profile_hs_codes"]:
        if r["code"] is not None:
            dims[r["supplier_id"]]["hs_codes"].append({"code": hs6(r["code"]), "shipments": r["shipments"]})
    for r in rows["profile_exit_ports"]:
        code = str(r["code"]).zfill(5)
        entry = {"name": r["name"], "code": code, "shipments": r["shipments"]}
        country = SCHEDULE_K_COUNTRY.get(code[:3])
        if country:
            entry["country"] = country
        dims[r["supplier_id"]]["exit_ports"].append(entry)
    for r in rows["profile_entry_ports"]:
        dims[r["supplier_id"]]["entry_ports"].append(
            {"name": r["name"], "code": str(r["code"]).zfill(4), "country": IMPORTING_COUNTRY, "coast": coast(float(r["lon"])), "shipments": r["shipments"]}
        )
    for r in rows["profile_buyers"]:
        dims[r["supplier_id"]]["buyers"].append({"name": r["name"], "shipments": r["shipments"]})
    for r in rows["profile_carriers"]:
        dims[r["supplier_id"]]["carriers"].append({"name": carrier_name(r["name"], r["code"]), "code": r["code"], "shipments": r["shipments"]})
    for r in rows["profile_vessels"]:
        if r["name"]:
            dims[r["supplier_id"]]["vessels"].append({"name": r["name"], "shipments": r["shipments"]})

    profiles: dict[str, Any] = {}
    inactive: list[dict[str, Any]] = []
    found = set()
    for b in rows["profile_base"]:
        sid = b["supplier_id"]
        found.add(sid)
        if b["shipments"] == 0:
            inactive.append({"supplier_id": sid, "supplier_name": b["supplier_name"], "company": b["company"], "country": b["country"]})
            continue
        d = dims[sid]
        country = b["country"]
        profiles[sid] = {
            "supplier_id": sid,
            "supplier_name": b["supplier_name"],
            "country": country,
            # Section 6.1: a supplier with no parent passes its own name.
            "parent_companies": b["parents"] or [b["supplier_name"]],
            "hs_codes": _sorted(d["hs_codes"], "code"),
            "exit_ports": _sorted(d["exit_ports"]),
            "entry_ports": _sorted(d["entry_ports"]),
            "buyers": _sorted(d["buyers"]),
            "carriers": _sorted(d["carriers"]),
            "vessels": _sorted(d["vessels"]),
            "currency": CURRENCY.get(country, "USD"),
            "footprint_window": {
                "first_arrival": b["first_arrival"],
                "last_arrival": b["last_arrival"],
                "shipments": b["shipments"],
            },
        }
        # App-only context (not sent to the engine): shown to the risk LLM and the page.
        profiles[sid]["_context"] = {"company": b["company"], "address": b["address"]}
    unknown = [sid for sid in ids if sid not in found]
    return {"profiles": profiles, "inactive": inactive, "unknown": unknown}


def match_products(
    client: ReadOnlyNeo4j, pairs: list[dict[str, Any]], as_of: date, *, log: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Recount each (item, supplier, product) the Cypher LLM matched, up to `as_of`."""
    pairs = [p for p in pairs if p.get("supplier_id") and p.get("product_id")]
    if not pairs:
        return []
    return client.read(MATCH_QUERY, {"pairs": pairs, "as_of": as_of.isoformat()}, log=log, name="matched_products")


def engine_payload(profile: dict[str, Any], as_of: date, *, line_id: str, query: str) -> dict[str, Any]:
    """One supplier's request to the engine (section 6.1)."""
    entry = {k: v for k, v in profile.items() if not k.startswith("_")}
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of_date": as_of.isoformat(),
        "event_window_days": EVENT_WINDOW_DAYS,
        "request_context": {"bom_line_id": line_id, "component_query": query[:200], "importing_country": IMPORTING_COUNTRY},
        "suppliers": [entry],
    }
