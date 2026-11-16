"""Evidence Library endpoints over the engine's stored records.

    GET /api/evidence        filtered records (as summaries) plus facet counts
    GET /api/evidence/{id}   one record, its incident group and related records

Data comes from `app.state.evidence_db` (loaded once at startup); nothing is
read again from disk. Neo4j is used only for the supplier list behind the
"show in Graph Explorer" link, and the endpoints still work without it.

Each risk type has its own date fields (`DATE_FAMILY` / `FAMILY_FIELDS`). The
date filter keeps a record whose start-end range overlaps the chosen range:

- no end date: a single day, except an effective interval, which stays open
  to the end of the study window (the engine's rule);
- no start date (an undated candidate): its stored search window is used
  instead, and the summary says so.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from supplier_risk_engine.engine import get_evidence
from supplier_risk_engine.engine.dates import FAMILY_FIELDS, OPEN_EFFECTIVE_END
from supplier_risk_engine.engine.reference import DATE_FAMILY, STUDY_END, STUDY_START
from supplier_risk_engine.loader import LoadedDatabase

evidence_router = APIRouter(prefix="/api/evidence", tags=["evidence"])

# The field(s) that name what a record is about, per risk type. The first two
# present are joined into the card's title.
TITLE_FIELDS: dict[str, list[str]] = {
    "border_customs_delays": ["border_or_customs_location", "cause"],
    "carrier_vessel_disruption": ["reported_carrier", "reported_vessel", "disruption_type"],
    "currency_fluctuations": ["_currency_pair", "reported_organisation"],
    "cyberattack": ["reported_organisation", "incident_type"],
    "energy_or_transport_cost_increase": ["reported_route_or_market", "cost_type"],
    "geopolitical_conflict": ["affected_area"],
    "goods_in_transit_loss_theft_or_damage": ["incident_type", "location.label", "location"],
    "government_restrictions": ["restriction_type", "issuing_country_name"],
    "input_material_shortage": ["material", "reported_supplier"],
    "labour_disruption": ["reported_organisation", "disruption_type"],
    "natural_hazards": ["hazard_type", "location.label"],
    "port_disruption": ["reported_port", "cause"],
    "product_quality_compliance": ["product_description", "reported_supplier"],
    "route_chokepoint_disruption": ["route_or_chokepoint", "disruption_type"],
    "supplier_financial_distress": ["reported_supplier", "distress_indicator"],
    "supplier_operational_disruption": ["reported_supplier", "cause"],
    "supplier_or_route_concentration": ["assessment_scope"],
    "tariffs_and_duties": ["_tariff_lane", "_tariff_rate"],
}

# Narrative fields, in the order they are tried for the card's description.
DESCRIPTION_FIELDS = [
    "reported_effect",
    "reported_operational_impact",
    "reported_supply_chain_effect",
    "reported_loss_or_damage",
    "conflict_description",
    "distress_indicator",
    "issue_or_standard",
    "cause",
    "rate_definition",
    "assessment_scope",
]

# Reported entities or routes (names the engine matches on).
ENTITY_FIELDS = [
    "reported_supplier",
    "reported_organisation",
    "reported_carrier",
    "reported_vessel",
    "reported_port",
    "reported_shipment",
    "facility",
    "material",
    "route_or_chokepoint",
    "border_or_customs_location",
    "reported_route_or_market",
    "location",
    "reported_entities_or_routes",
]

RISK_LABELS = {rt: rt.replace("_", " ").capitalize() for rt in DATE_FAMILY}
RISK_LABELS["energy_or_transport_cost_increase"] = "Energy or transport cost increase"
RISK_LABELS["goods_in_transit_loss_theft_or_damage"] = "Goods in transit: loss, theft or damage"


# ------------------------------------------------------------------ summaries


def _path(record: dict[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _iso(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _humanise(value: str) -> str:
    return value.replace("_", " ")


def _title(risk_type: str, record: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in TITLE_FIELDS.get(risk_type, []):
        if field == "_currency_pair":
            base, quote = record.get("base_currency"), record.get("quote_currency")
            value = f"{base}/{quote}" if base and quote else None
        elif field == "_tariff_lane":
            origin = record.get("origin_country_name") or "All origins"
            value = f"{origin} → {record.get('importing_country_name') or record.get('importing_country_code')}"
        elif field == "_tariff_rate":
            rate = record.get("rate") or {}
            value = None
            if isinstance(rate.get("value"), (int, float)):
                kind = _humanise(rate.get("kind") or "")
                if rate.get("unit") == "percent":
                    unit, kind = "%", kind.removesuffix(" percent")
                else:
                    unit = f" {rate.get('unit') or ''}".rstrip()
                value = f"{rate['value']:g}{unit} {kind}".strip()
        else:
            value = _text(_path(record, field))
            if value and field == "cost_type":
                value = _humanise(value)
        # Skip a part that repeats an earlier one ("retail diesel" in "... retail diesel").
        if value and not any(value.casefold() in p.casefold() for p in parts):
            parts.append(value)
        if len(parts) == 2:
            break
    return " — ".join(parts) or RISK_LABELS.get(risk_type, risk_type)


def _description(record: dict[str, Any]) -> str | None:
    for field in DESCRIPTION_FIELDS:
        value = _text(record.get(field))
        if value:
            return value
    return None


def _entities(record: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(field: str, value: Any) -> None:
        value = _text(value)
        if value and value not in seen:
            seen.add(value)
            out.append({"field": field, "value": value})

    for field in ENTITY_FIELDS:
        value = record.get(field)
        if isinstance(value, dict):
            add(field, value.get("label"))
        elif isinstance(value, list):
            for item in value:
                add(field, item)
        else:
            add(field, value)
    return out


def _measures(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Numbers a record reports, under one shape: label, value, unit, note."""
    out: list[dict[str, Any]] = []

    def add(label: str, value: Any, unit: Any = None, note: Any = None) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append({"label": label, "value": value, "unit": unit, "note": note})

    delay = record.get("reported_delay")
    if isinstance(delay, dict):
        add("Reported delay", delay.get("value"), delay.get("unit"))
    rate = record.get("rate")
    if isinstance(rate, dict):
        add(_humanise(rate.get("kind") or "rate").capitalize(), rate.get("value"), rate.get("unit"), rate.get("currency"))
    measure = record.get("measure")
    if isinstance(measure, dict):
        add(measure.get("name") or "Measure", measure.get("value"), measure.get("unit"), measure.get("definition"))
    for key, label in (("baseline", "Baseline"), ("observed", "Observed")):
        point = record.get(key)
        if isinstance(point, dict):
            unit = "/".join(str(u) for u in (point.get("currency"), point.get("unit")) if u)
            add(label, point.get("value"), unit or None, point.get("date"))
    pair = "/".join(str(c) for c in (record.get("base_currency"), record.get("quote_currency")) if c) or None
    add("Starting rate", record.get("starting_rate"), pair)
    add("Ending rate", record.get("ending_rate"), pair)
    add("Reported change", record.get("reported_change_percent"), "percent")
    return out


# Country fields that describe the import side (the US, for Dyson's imports),
# not where a supplier is. They count for the country filter but not for the
# Graph Explorer link, which matches `supplier_country_code`.
IMPORT_SIDE_FIELDS = {"importing_country_code", "destination_country_code"}


def _countries(record: dict[str, Any], names: dict[str, str]) -> list[dict[str, Any]]:
    """Every country code a record carries, in any field (not the source),
    with the fields it appears in."""
    found: dict[str, list[str]] = {}

    def walk(value: Any, key: str | None) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k != "source":
                    walk(v, k)
        elif isinstance(value, list):
            for item in value:
                walk(item, key)
        elif isinstance(value, str) and key and key.endswith(("country_code", "country_codes")):
            fields = found.setdefault(value, [])
            if key not in fields:
                fields.append(key)

    walk(record, None)
    return [
        {"code": c, "name": names.get(c, c), "fields": f, "import_side": all(x in IMPORT_SIDE_FIELDS for x in f)}
        for c, f in found.items()
    ]


def _country_names(records: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    """Code -> name from every `x_country_code` / `x_country_name` pair stored."""
    names: dict[str, str] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k.endswith("country_code") and isinstance(v, str):
                    name = value.get(k[: -len("code")] + "name")
                    if isinstance(name, str) and name:
                        names.setdefault(v, name)
                walk(v)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(records)
    return names


def _dates(risk_type: str, record: dict[str, Any]) -> dict[str, Any]:
    family = DATE_FAMILY[risk_type]
    start_field, end_field = FAMILY_FIELDS[family]
    start = _iso(record.get(start_field))
    end = _iso(record.get(end_field)) if end_field else None
    out: dict[str, Any] = {
        "family": family,
        "start_field": start_field,
        "end_field": end_field,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "open_end": None,
        "undated": start is None,
        "known_from": record.get("known_from"),
        "published_at": (record.get("source") or {}).get("published_at"),
    }
    # The range the date filter compares against.
    if start is not None:
        if end is None:
            if family == "effective_interval":
                end = STUDY_END
                out["open_end"] = OPEN_EFFECTIVE_END
            else:
                end = start
        filter_range = (start, end)
    else:
        sw = record.get("search_window") or {}
        sw_start, sw_end = _iso(sw.get("start")), _iso(sw.get("end"))
        filter_range = (sw_start, sw_end) if sw_start and sw_end else None
    out["filter_range"] = (
        {"start": filter_range[0].isoformat(), "end": filter_range[1].isoformat(), "basis": "dates" if start else "search_window"}
        if filter_range
        else None
    )
    return out


class EvidenceView:
    """Summaries of every record, built once per loaded database."""

    def __init__(self, db: LoadedDatabase):
        self.db = db
        names = _country_names(db.records)
        index = db.index
        self.summaries: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        for risk_type in sorted(db.records):
            for record in db.records[risk_type]:
                eid = record["evidence_id"]
                source = record.get("source") or {}
                summary = {
                    "evidence_id": eid,
                    "risk_type": risk_type,
                    "risk_label": RISK_LABELS.get(risk_type, risk_type),
                    "title": _title(risk_type, record),
                    "description": _description(record),
                    "countries": _countries(record, names),
                    "dates": _dates(risk_type, record),
                    "measures": _measures(record),
                    "entities": _entities(record),
                    "verification_status": record.get("verification_status"),
                    "limitations": record.get("limitations") or [],
                    "source": {
                        "publisher": source.get("publisher"),
                        "url": source.get("url"),
                        "published_at": source.get("published_at"),
                        "licence_notes": source.get("licence_notes"),
                    },
                    "related_evidence_ids": list(index.related.get(eid, ())),
                    "incident_group_id": index.group_of.get(eid),
                }
                self.summaries.append(summary)
                self.by_id[eid] = summary
        # Newest first by start (or search-window start); ties by id.
        self.summaries.sort(key=lambda s: s["evidence_id"])
        self.summaries.sort(key=_start_of, reverse=True)
        self.country_names = names

    def search_text(self, s: dict[str, Any]) -> str:
        parts = [s["evidence_id"], s["title"], s["description"] or "", s["source"]["publisher"] or "", s["risk_label"]]
        parts += [e["value"] for e in s["entities"]]
        parts += [c["name"] for c in s["countries"]]
        return "\n".join(parts).casefold()


def _start_of(s: dict[str, Any]) -> str:
    fr = s["dates"]["filter_range"]
    return s["dates"]["start"] or (fr["start"] if fr else "")


def _view(request: Request) -> EvidenceView:
    db = request.app.state.evidence_db
    view = getattr(request.app.state, "evidence_view", None)
    if view is None or view.db is not db:
        view = EvidenceView(db)
        request.app.state.evidence_view = view
    return view


# ------------------------------------------------------------- graph suppliers


def _graph_suppliers(request: Request) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    """Supplier nodes grouped by `supplier_country_code`, cached after the first read."""
    cached = getattr(request.app.state, "evidence_graph_suppliers", None)
    if cached is not None:
        return cached, None
    try:
        rows = request.app.state.neo4j.read(
            """
            MATCH (s:Supplier)
            RETURN s.supplier_id AS id, s.supplier_name AS name,
                   s.supplier_basename AS company, s.supplier_country_code AS country
            ORDER BY company, name
            """,
            name="evidence_graph_suppliers",
        )
    except Exception as e:  # Neo4j down: the library still works, without the link
        return {}, f"Graph suppliers unavailable: {e}"
    by_country: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("country"):
            by_country.setdefault(r["country"], []).append(
                {"id": f"supplier:{r['id']}", "name": r["name"], "company": r["company"]}
            )
    request.app.state.evidence_graph_suppliers = by_country
    return by_country, None


def _with_graph(summary: dict[str, Any], by_country: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    ids: list[str] = []
    for c in summary["countries"]:
        if c["import_side"]:
            continue
        for s in by_country.get(c["code"], []):
            if s["id"] not in ids:
                ids.append(s["id"])
    return {**summary, "graph_supplier_ids": ids}


# ------------------------------------------------------------------ endpoints


def _date_param(value: str | None, name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}")


def _list_param(value: str | None) -> set[str]:
    return {v.strip() for v in (value or "").split(",") if v.strip()}


@evidence_router.get("")
def list_evidence(
    request: Request,
    risk_type: str | None = Query(None, description="Comma-separated risk types"),
    country: str | None = Query(None, description="Comma-separated ISO alpha-2 codes"),
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = Query(None, description="Text over id, title, description, entities, countries and publisher"),
) -> dict[str, Any]:
    view = _view(request)
    types = _list_param(risk_type)
    countries = {c.upper() for c in _list_param(country)}
    unknown = types - set(DATE_FAMILY)
    if unknown:
        raise HTTPException(400, f"Unknown risk_type: {', '.join(sorted(unknown))}")
    d_from, d_to = _date_param(date_from, "date_from"), _date_param(date_to, "date_to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(400, "date_from is after date_to")
    needle = (q or "").strip().casefold()

    def match_type(s: dict[str, Any]) -> bool:
        return not types or s["risk_type"] in types

    def match_country(s: dict[str, Any]) -> bool:
        return not countries or any(c["code"] in countries for c in s["countries"])

    def match_date(s: dict[str, Any]) -> bool:
        if not d_from and not d_to:
            return True
        fr = s["dates"]["filter_range"]
        if fr is None:
            return False
        start, end = date.fromisoformat(fr["start"]), date.fromisoformat(fr["end"])
        return (d_to is None or start <= d_to) and (d_from is None or end >= d_from)

    def match_text(s: dict[str, Any]) -> bool:
        return not needle or needle in view.search_text(s)

    checks = {"risk_type": match_type, "country": match_country, "date": match_date, "text": match_text}

    def passes(s: dict[str, Any], skip: str | None = None) -> bool:
        return all(fn(s) for name, fn in checks.items() if name != skip)

    # Facet counts: each facet applies every filter except its own.
    type_counts = {rt: 0 for rt in sorted(DATE_FAMILY)}
    country_counts: dict[str, int] = {}
    for s in view.summaries:
        if passes(s, "risk_type"):
            type_counts[s["risk_type"]] += 1
        if passes(s, "country"):
            for c in {c["code"] for c in s["countries"]}:
                country_counts[c] = country_counts.get(c, 0) + 1

    by_country, graph_error = _graph_suppliers(request)
    records = [_with_graph(s, by_country) for s in view.summaries if passes(s)]
    return {
        "total": len(view.summaries),
        "count": len(records),
        "records": records,
        "facets": {
            "risk_type": [{"value": rt, "label": RISK_LABELS[rt], "count": n} for rt, n in type_counts.items()],
            "country": [
                {"value": c, "label": view.country_names.get(c, c), "count": n}
                for c, n in sorted(country_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
        },
        "study_window": {"start": STUDY_START.isoformat(), "end": STUDY_END.isoformat()},
        "graph_suppliers_by_country": by_country,
        "graph_error": graph_error,
        "data_snapshot_id": view.db.snapshot_id,
    }


@evidence_router.get("/{evidence_id}")
def evidence_detail(request: Request, evidence_id: str) -> dict[str, Any]:
    view = _view(request)
    found = get_evidence(evidence_id, view.db.index)
    if found["status"] != "found":
        raise HTTPException(404, f"No evidence record with id {evidence_id!r}")
    by_country, graph_error = _graph_suppliers(request)
    summary = _with_graph(view.by_id[evidence_id], by_country)

    def brief(eid: str) -> dict[str, Any]:
        s = view.by_id.get(eid)
        if s is None:
            return {"evidence_id": eid, "missing": True}
        return {"evidence_id": eid, "risk_type": s["risk_type"], "risk_label": s["risk_label"], "title": s["title"]}

    graph_suppliers = [
        s for c in summary["countries"] if not c["import_side"] for s in by_country.get(c["code"], [])
    ]
    return {
        "summary": summary,
        "record": found["record"],
        "related": [brief(e) for e in found["related_evidence_ids"]],
        "incident_group_id": found["incident_group_id"],
        "incident_group": [brief(e) for e in found["incident_group_members"] if e != evidence_id],
        "graph_suppliers": list({s["id"]: s for s in graph_suppliers}.values()),
        "graph_error": graph_error,
        "engine_version": found["engine_version"],
        "data_snapshot_id": found["data_snapshot_id"],
    }
