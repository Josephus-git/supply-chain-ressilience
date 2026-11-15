"""The engine's three operations (plan section 8.2).

    lookup_suppliers(payload, records)
    get_evidence(evidence_id, records)
    describe_database(records)

`records` maps each stored `risk_type` to its list of record dicts, exactly
as stored in the database files. A prebuilt `EvidenceIndex` may be passed
instead, so an adapter can index once and reuse it. The engine does no file
access and keeps no state between calls.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Union

from .dates import date_scope, in_study_window
from .match import COUNTRY_WIDE_LABEL, RULES, MatchContext
from .models import (
    IncidentGroup,
    Link,
    LinkedReport,
    LookupResult,
    Notice,
    Supplier,
    SupplierResult,
)
from .reference import (
    BASIS_PRIORITY,
    DATE_FAMILY,
    ENGINE_VERSION,
    SCHEMA_VERSION,
    STRENGTH_RANK,
    STUDY_END,
    STUDY_START,
)
from .validate import parse_request

RecordsInput = Union["EvidenceIndex", Mapping[str, Sequence[dict[str, Any]]]]

STUDY_WINDOW = {"start": STUDY_START.isoformat(), "end": STUDY_END.isoformat()}

COUNTRY_BASES = {"country_code", "port_country", "importing_country"}
_COUNTRY_LABELS = {
    "country_code": (
        "country-only link: the record's country equals the supplier's "
        "country; no name, port, vessel, or carrier match"
    ),
    "port_country": (
        "country-only link: the record's country equals a payload port's "
        "country; location only, no port-name match"
    ),
    "importing_country": (
        "country-only link: the record's importing country equals the "
        "request's importing_country"
    ),
}
APPROXIMATED_LABEL = (
    "linked through an analyst-approximated field; see approximation_basis in links"
)


# --------------------------------------------------------------------------
# Index


@dataclass(frozen=True)
class EvidenceIndex:
    """Records plus derived lookups. Build with `build_index`."""

    records: tuple[tuple[str, dict[str, Any]], ...]  # (risk_type, record), sorted
    by_id: Mapping[str, tuple[str, dict[str, Any]]]
    related: Mapping[str, tuple[str, ...]]  # two-way related IDs
    group_of: Mapping[str, str]  # evidence_id -> incident group ID
    groups: Mapping[str, tuple[str, ...]]  # group ID -> member IDs
    snapshot_id: str
    unknown_risk_types: tuple[str, ...]


def build_index(
    records: Mapping[str, Sequence[dict[str, Any]]], *, data_snapshot_id: str | None = None
) -> EvidenceIndex:
    """Index records by ID and group related records into incident groups.

    Related links are treated as two-way: the groups are the connected
    components of the union of both directions (plan section 4). The input
    records are not modified.
    """
    flat: list[tuple[str, dict[str, Any]]] = []
    unknown: set[str] = set()
    for risk_type in sorted(records):
        if risk_type not in DATE_FAMILY:
            unknown.add(risk_type)
            continue
        for record in records[risk_type]:
            flat.append((risk_type, record))
    flat.sort(key=lambda item: item[1]["evidence_id"])

    by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for risk_type, record in flat:
        eid = record["evidence_id"]
        if eid in by_id:
            raise ValueError(f"Duplicate evidence_id in records: {eid}")
        by_id[eid] = (risk_type, record)

    neighbours: dict[str, set[str]] = {eid: set() for eid in by_id}
    for eid, (_, record) in by_id.items():
        for other in record.get("related_evidence_ids") or []:
            if other in by_id and other != eid:
                neighbours[eid].add(other)
                neighbours[other].add(eid)

    group_of: dict[str, str] = {}
    groups: dict[str, tuple[str, ...]] = {}
    for eid in sorted(by_id):
        if eid in group_of:
            continue
        stack, members = [eid], set()
        while stack:
            current = stack.pop()
            if current in members:
                continue
            members.add(current)
            stack.extend(neighbours[current] - members)
        ordered = tuple(sorted(members))
        group_id = ordered[0]
        groups[group_id] = ordered
        for member in ordered:
            group_of[member] = group_id

    return EvidenceIndex(
        records=tuple(flat),
        by_id=by_id,
        related={eid: tuple(sorted(n)) for eid, n in neighbours.items()},
        group_of=group_of,
        groups=groups,
        snapshot_id=data_snapshot_id or compute_snapshot_id(records),
        unknown_risk_types=tuple(sorted(unknown)),
    )


def compute_snapshot_id(records: Mapping[str, Sequence[dict[str, Any]]]) -> str:
    """Deterministic fingerprint of the records passed in.

    The loader may pass its own ID (for example from the manifest's file
    hashes); this is the fallback.
    """
    canonical = {
        risk_type: sorted(records[risk_type], key=lambda r: r.get("evidence_id", ""))
        for risk_type in sorted(records)
    }
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "records-sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _as_index(records: RecordsInput) -> EvidenceIndex:
    return records if isinstance(records, EvidenceIndex) else build_index(records)


# --------------------------------------------------------------------------
# lookup_suppliers


def lookup_suppliers(payload: Any, records: RecordsInput) -> dict[str, Any]:
    """Validate a payload and return linked reports for each supplier.

    Always returns a JSON-ready dict. A rejected payload gives
    `status: "rejected"` with structured `errors`; nothing is raised.
    """
    return lookup_suppliers_result(payload, records).to_dict()


def lookup_suppliers_result(payload: Any, records: RecordsInput) -> LookupResult:
    """As `lookup_suppliers`, returning the typed result."""
    index = _as_index(records)
    request, errors, warnings = parse_request(payload)
    if request is None:
        return LookupResult(
            status="rejected",
            schema_version=SCHEMA_VERSION,
            engine_version=ENGINE_VERSION,
            data_snapshot_id=index.snapshot_id,
            study_window=STUDY_WINDOW,
            errors=tuple(errors),
        )

    notices = list(warnings)
    for risk_type in index.unknown_risk_types:
        notices.append(
            Notice(
                code="unknown_risk_type",
                message=f"Records of unknown risk type '{risk_type}' were ignored.",
            )
        )

    active = in_study_window(request.as_of_date)
    results = []
    for supplier in request.suppliers:
        reports = _link_supplier(supplier, request, index) if active else []
        results.append(
            SupplierResult(
                input=_echo_supplier(supplier),
                linked_reports=tuple(reports),
                incident_groups=tuple(_incident_groups(reports, index)),
                data_gaps=tuple(_data_gaps(supplier)),
            )
        )

    ctx = request.request_context
    return LookupResult(
        status="completed",
        schema_version=SCHEMA_VERSION,
        engine_version=ENGINE_VERSION,
        data_snapshot_id=index.snapshot_id,
        study_window=STUDY_WINDOW,
        as_of_date=request.as_of_date.isoformat(),
        event_window_days=request.event_window_days,
        request_context={
            "bom_line_id": ctx.bom_line_id,
            "component_query": ctx.component_query,
            "importing_country": ctx.importing_country,
        },
        suppliers=tuple(results),
        warnings=tuple(notices),
    )


def _echo_supplier(supplier: Supplier) -> dict[str, Any]:
    return {
        "supplier_id": supplier.supplier_id,
        "supplier_name": supplier.supplier_name,
        "country": supplier.country,
        "parent_companies": list(supplier.parent_companies),
        "currency": supplier.currency,
    }


def _link_supplier(supplier: Supplier, request, index: EvidenceIndex) -> list[LinkedReport]:
    ctx = MatchContext(supplier=supplier, request=request.request_context)
    reports: list[LinkedReport] = []
    for risk_type, record in index.records:
        scope = date_scope(risk_type, record, request.as_of_date, request.event_window_days)
        if scope is None:
            continue
        links = RULES[risk_type](record, ctx)
        if not links:
            continue
        reports.append(_report(risk_type, record, scope, links, index))
    return reports


def _rank(link: Link) -> tuple[int, int]:
    return (STRENGTH_RANK[link.link_strength], -BASIS_PRIORITY.index(link.link_basis))


def _report(risk_type, record, scope, links: list[Link], index: EvidenceIndex) -> LinkedReport:
    ordered = sorted(
        _dedupe(links),
        key=lambda l: (-_rank(l)[0], -_rank(l)[1], l.matched_value, l.input_value),
    )
    best = ordered[0]
    main = [l for l in ordered if (l.link_basis, l.link_strength) == (best.link_basis, best.link_strength)]

    exposures: list[dict[str, Any]] = []
    seen_exposures: set[str] = set()
    for link in main:
        if link.matched_exposure is not None:
            key = json.dumps(link.matched_exposure, sort_keys=True, ensure_ascii=False)
            if key not in seen_exposures:
                seen_exposures.add(key)
                exposures.append(link.matched_exposure)

    labels: list[str] = []
    is_codeless_tariff = risk_type == "tariffs_and_duties" and not (
        (record.get("product_classification") or {}).get("code")
    )
    if is_codeless_tariff:
        labels.append(COUNTRY_WIDE_LABEL)
    if best.link_basis in COUNTRY_BASES:
        labels.append(_COUNTRY_LABELS[best.link_basis])
    if any(l.approximated for l in main):
        labels.append(APPROXIMATED_LABEL)

    eid = record["evidence_id"]
    return LinkedReport(
        risk_type=risk_type,
        evidence_id=eid,
        scope=scope,
        links=tuple(ordered),
        main_basis=best.link_basis,
        main_strength=best.link_strength,
        matched_values=tuple(sorted({l.matched_value for l in main})),
        matched_exposure=tuple(exposures),
        labels=tuple(labels),
        search_window=record.get("search_window"),
        verification_status=record.get("verification_status"),
        limitations=record.get("limitations"),
        related_evidence_ids=index.related.get(eid, ()),
        incident_group_id=index.group_of[eid],
        scenario_recovery=record.get("scenario_recovery"),
    )


def _dedupe(links: list[Link]) -> list[Link]:
    seen: set[tuple] = set()
    out: list[Link] = []
    for link in links:
        key = (
            link.link_basis,
            link.matched_value,
            link.input_value,
            link.record_field,
            json.dumps(link.matched_exposure, sort_keys=True, ensure_ascii=False),
        )
        if key not in seen:
            seen.add(key)
            out.append(link)
    return out


def _incident_groups(reports: list[LinkedReport], index: EvidenceIndex) -> list[IncidentGroup]:
    linked: dict[str, list[str]] = {}
    for report in reports:
        linked.setdefault(report.incident_group_id, []).append(report.evidence_id)
    out = []
    for group_id in sorted(linked):
        members = index.groups[group_id]
        if len(members) < 2:
            continue
        ids = sorted(linked[group_id])
        out.append(
            IncidentGroup(
                incident_group_id=group_id,
                linked_evidence_ids=tuple(ids),
                unlinked_member_ids=tuple(m for m in members if m not in ids),
            )
        )
    return out


def _data_gaps(supplier: Supplier) -> list[Notice]:
    """Payload gaps that limit which risk types can link. Informational."""
    gaps: list[Notice] = []
    if not supplier.ports:
        gaps.append(
            Notice(
                "no_ports",
                "No exit or entry ports supplied: port disruption cannot link, "
                "and natural hazards and customs delays link only by supplier country.",
            )
        )
    else:
        no_country = [p.name for p in supplier.ports if p.country is None]
        if no_country:
            gaps.append(
                Notice(
                    "port_without_country",
                    "The port_country tier cannot apply to: " + ", ".join(sorted(no_country)) + ".",
                )
            )
    if not any(p.coast for p in supplier.entry_ports):
        gaps.append(
            Notice("no_entry_port_coast", "No entry port carries a coast: trade-lane links are not possible.")
        )
    if not supplier.vessels and not supplier.carriers:
        gaps.append(
            Notice("no_vessels_or_carriers", "No vessels or carriers supplied: carrier and vessel records cannot link.")
        )
    if not supplier.hs_codes:
        gaps.append(Notice("no_hs_codes", "No HS codes supplied: tariffs with a commodity code cannot link."))
    else:
        short = [h.code for h in supplier.hs_codes if h.code and len(h.code) < 6]
        if short:
            gaps.append(
                Notice(
                    "short_hs_codes",
                    "HS codes under 6 digits cannot match: " + ", ".join(sorted(short)) + ".",
                )
            )
    if not supplier.buyers:
        gaps.append(Notice("no_buyers", "No buyers supplied: buyer-named currency records cannot link."))
    return gaps


# --------------------------------------------------------------------------
# get_evidence and describe_database


def get_evidence(evidence_id: Any, records: RecordsInput) -> dict[str, Any]:
    """Return the full stored record behind an evidence_id, unchanged."""
    index = _as_index(records)
    if not isinstance(evidence_id, str) or evidence_id not in index.by_id:
        return {
            "status": "not_found",
            "engine_version": ENGINE_VERSION,
            "data_snapshot_id": index.snapshot_id,
            "errors": [
                {
                    "field": "evidence_id",
                    "code": "not_found",
                    "message": f"No stored record has evidence_id {evidence_id!r}.",
                }
            ],
        }
    risk_type, record = index.by_id[evidence_id]
    group_id = index.group_of[evidence_id]
    return {
        "status": "found",
        "engine_version": ENGINE_VERSION,
        "data_snapshot_id": index.snapshot_id,
        "risk_type": risk_type,
        "evidence_id": evidence_id,
        "record": record,
        "related_evidence_ids": list(index.related[evidence_id]),
        "incident_group_id": group_id,
        "incident_group_members": list(index.groups[group_id]),
    }


def describe_database(records: RecordsInput) -> dict[str, Any]:
    """Study window, risk types and record counts, snapshot ID, and version."""
    index = _as_index(records)
    counts: dict[str, int] = {}
    for risk_type, _ in index.records:
        counts[risk_type] = counts.get(risk_type, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "data_snapshot_id": index.snapshot_id,
        "study_window": STUDY_WINDOW,
        "record_count": len(index.records),
        "risk_types": [
            {
                "risk_type": risk_type,
                "records": counts.get(risk_type, 0),
                "date_family": DATE_FAMILY[risk_type],
            }
            for risk_type in sorted(DATE_FAMILY)
        ],
        "incident_groups": sum(1 for m in index.groups.values() if len(m) > 1),
        "unknown_risk_types": list(index.unknown_risk_types),
    }
