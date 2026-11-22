"""write_report inputs and check_citations.

`report_inputs` turns the retrieved data into the risk LLM's prompt sections
and the set of citation ids it may use. Each graph figure gets an id
(`graph:<supplier_id>:<field>`, `match:<item>:<supplier_id>`), so a claim can
cite a figure as precisely as an evidence record.

`check_citations` marks each citation verified or not found against exactly
what the LLM was given (R8). It never removes or corrects anything: the run
keeps the model's raw output so its mistakes can be studied.
"""

from __future__ import annotations

import json
from typing import Any

from .prompts import INSUFFICIENT

DESCRIPTION_CHARS = 320
LIMITATION_CHARS = 220


def _cut(text: Any, n: int) -> Any:
    if isinstance(text, str) and len(text) > n:
        return text[: n - 1].rstrip() + "…"
    return text


def _dump(value: Any) -> str:
    return json.dumps(value, indent=1, ensure_ascii=False, default=str) if value else "(none)"


def graph_id(supplier_id: str, field: str) -> str:
    return f"graph:{supplier_id}:{field}"


def match_id(item: int, supplier_id: str) -> str:
    return f"match:{item}:{supplier_id}"


def report_inputs(
    *,
    items: list[dict[str, Any]],
    candidates: dict[int, list[dict[str, Any]]],
    profiles: dict[str, dict[str, Any]],
    inactive: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Prompt sections plus `citations`: id -> {kind, supplier_id, item, country}."""
    cites: dict[str, dict[str, Any]] = {}
    inactive_ids = {s["supplier_id"] for s in inactive}

    item_rows = []
    for it in items:
        n = it["n"]
        cands = []
        for c in candidates.get(n, []):
            sid = c["supplier_id"]
            entry: dict[str, Any] = {"supplier_id": sid, "supplier_name": c.get("supplier_name")}
            if sid in inactive_ids:
                entry["note"] = "no shipments by the as-of date: not yet a supplier on that date"
            elif sid not in profiles:
                entry["note"] = "not found in the graph"
            else:
                mid = match_id(n, sid)
                entry["matched_products"] = {
                    "citation": mid,
                    "products": [
                        {
                            "product_id": p["product_id"],
                            "description": _cut(p["product_description"], 140),
                            "shipments_to_date": p["shipments"],
                            "last_arrival": p["last_arrival"],
                        }
                        for p in c.get("products", [])
                    ],
                }
                if not c.get("products"):
                    entry["matched_products"]["note"] = (
                        "the query matched this supplier without a product, or its matched products had no shipments by the date"
                    )
                cites[mid] = {"kind": "match", "item": n, "supplier_id": sid}
            cands.append(entry)
        row = {"item": n, "text": it["text"], "source": it.get("source", "typed")}
        if it.get("product_id"):
            row["catalogue_product_id"] = it["product_id"]
        row["candidates"] = cands or "none found in the graph"
        item_rows.append(row)

    supplier_rows = []
    for sid, p in sorted(profiles.items()):
        fw = p["footprint_window"]
        facts = {
            graph_id(sid, "shipments"): fw["shipments"],
            graph_id(sid, "first_arrival"): fw["first_arrival"],
            graph_id(sid, "last_arrival"): fw["last_arrival"],
            graph_id(sid, "country"): p["country"],
            graph_id(sid, "parent"): p["parent_companies"][0],
            graph_id(sid, "exit_ports"): [f"{e['name']} ({e['shipments']})" for e in p["exit_ports"][:3]],
            graph_id(sid, "carriers"): [f"{e['name']} ({e['shipments']})" for e in p["carriers"][:3]],
        }
        for fid in facts:
            cites[fid] = {"kind": "graph", "supplier_id": sid}
        links = (evidence["by_supplier"].get(sid) or {}).get("links", [])
        supplier_rows.append(
            {
                "supplier_id": sid,
                "supplier_name": p["supplier_name"],
                "company": (p.get("_context") or {}).get("company"),
                "figures": facts,
                "evidence_links": [
                    {k: l[k] for k in ("evidence_id", "risk_type", "link_basis", "link_strength", "matched_values", "date_status")}
                    for l in links
                ]
                or "none linked as of the date",
            }
        )

    country_rows = []
    for code, c in sorted(evidence["by_country"].items()):
        country_rows.append(
            {
                "country": code,
                "basis": c["basis"],
                "why": c.get("reason"),
                "evidence_links": [
                    {k: l[k] for k in ("evidence_id", "risk_type", "link_basis", "link_strength")} for l in c["links"]
                ]
                or "none linked as of the date",
            }
        )

    records = []
    for eid, r in sorted(evidence["records"].items()):
        cites[eid] = {"kind": "evidence"}
        records.append(
            {
                "evidence_id": eid,
                "risk_type": r["risk_label"],
                "title": r["title"],
                "description": _cut(r["description"], DESCRIPTION_CHARS),
                "dates": {"start": r["start"], "end": r["end"]},
                "verification_status": r["verification_status"],
                "measures": [
                    {k: m.get(k) for k in ("label", "value", "unit") if m.get(k) is not None} for m in (r["measures"] or [])[:3]
                ],
                "limitations": [_cut(x, LIMITATION_CHARS) for x in (r["limitations"] or [])[:2]],
            }
        )

    return {
        "sections": {
            "items": _dump(item_rows),
            "suppliers": _dump(supplier_rows),
            "countries": _dump(country_rows),
            "evidence": _dump(records),
        },
        "citations": cites,
    }


def has_support(candidates: dict[int, list[dict[str, Any]]], profiles: dict[str, Any], evidence: dict[str, Any]) -> bool:
    """R7: is there anything relevant to give the risk LLM?"""
    supplier_found = any(c["supplier_id"] in profiles for cs in candidates.values() for c in cs)
    country_found = any(c["links"] for c in evidence["by_country"].values())
    return supplier_found or country_found


def fixed_insufficient_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    """R7: the pipeline's own answer when neither the graph nor the engine returned anything."""
    return {
        "summary": {"text": INSUFFICIENT, "citations": []},
        "items": [
            {
                "item": it["n"], "status": "insufficient_data", "candidates": [], "set_aside": [], "country_notes": [],
                "answer": {"text": INSUFFICIENT, "citations": []},
            }
            for it in items
        ],
    }


# ----------------------------------------------------------------------------- citation check


def _claims(report: dict[str, Any]):
    """Yield (path, claim, context) for every claim in the report."""
    yield "summary", report.get("summary") or {}, {}
    for i, item in enumerate(report.get("items") or []):
        n = item.get("item")
        if item.get("answer"):
            yield f"items.{i}.answer", item["answer"], {"item": n}
        for j, c in enumerate(item.get("candidates") or []):
            ctx = {"item": n, "supplier_id": c.get("supplier_id")}
            yield f"items.{i}.candidates.{j}.match_reason", c.get("match_reason") or {}, ctx
            for k, r in enumerate(c.get("risks") or []):
                yield f"items.{i}.candidates.{j}.risks.{k}", r, ctx
            yield f"items.{i}.candidates.{j}.track_record", c.get("track_record") or {}, ctx
        for j, s in enumerate(item.get("set_aside") or []):
            yield f"items.{i}.set_aside.{j}.reason", s.get("reason") or {}, {"item": n, "supplier_id": s.get("supplier_id")}
        for j, cn in enumerate(item.get("country_notes") or []):
            yield f"items.{i}.country_notes.{j}.note", cn.get("note") or {}, {"item": n, "country": cn.get("country_code")}


def _kind(citation: str) -> str:
    if citation.startswith("graph:"):
        return "graph"
    if citation.startswith("match:"):
        return "match"
    return "evidence"


def check_citations(
    report: dict[str, Any], citations: dict[str, dict[str, Any]], evidence: dict[str, Any]
) -> dict[str, Any]:
    """Flag each citation `verified` (given to the LLM) or `not_found`. Nothing is changed.

    A verified citation also gets a `note` when it was given for another
    supplier, item or country than the claim it supports.
    """
    supplier_links = {sid: {l["evidence_id"] for l in v["links"]} for sid, v in evidence["by_supplier"].items()}
    country_links = {code: {l["evidence_id"] for l in v["links"]} for code, v in evidence["by_country"].items()}
    checks: list[dict[str, Any]] = []
    uncited: list[str] = []
    for path, claim, ctx in _claims(report):
        cited = claim.get("citations") or []
        text = (claim.get("text") or "").strip()
        if not cited and text and INSUFFICIENT.rstrip(".").lower() not in text.lower():
            uncited.append(path)
        for cit in cited:
            meta = citations.get(cit)
            entry = {"path": path, "citation": cit, "kind": _kind(cit), "status": "verified" if meta else "not_found", "note": None}
            if meta:
                sid, item, country = ctx.get("supplier_id"), ctx.get("item"), ctx.get("country")
                if meta["kind"] == "evidence":
                    if sid and cit not in supplier_links.get(sid, set()):
                        entry["note"] = "given to the model, but not linked to this supplier"
                    elif country and cit not in country_links.get(country, set()):
                        entry["note"] = "given to the model, but not linked to this country"
                elif meta["kind"] == "graph" and sid and meta["supplier_id"] != sid:
                    entry["note"] = "a figure of another supplier"
                elif meta["kind"] == "match" and ((sid and meta["supplier_id"] != sid) or (item and meta["item"] != item)):
                    entry["note"] = "a match for another item or supplier"
            checks.append(entry)
    verified = sum(1 for c in checks if c["status"] == "verified")
    return {
        "checks": checks,
        "total": len(checks),
        "verified": verified,
        "not_found": len(checks) - verified,
        "with_note": sum(1 for c in checks if c["note"]),
        "uncited_claims": uncited,
    }
