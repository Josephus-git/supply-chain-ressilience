"""Typed request and result models (plan sections 6.1 and 6.2).

Requests are parsed into frozen dataclasses by `validate.parse_request`.
Results are dataclasses with `to_dict()`, which gives the plain-JSON shape
every adapter sends unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


# --------------------------------------------------------------------------
# Request


@dataclass(frozen=True)
class ExposureEntry:
    """One entry of a payload list key (port, carrier, vessel, buyer, HS code).

    `raw` is the caller's entry, echoed back unchanged as `matched_exposure`.
    """

    name: str | None
    code: str | None
    country: str | None
    coast: str | None
    shipments: int | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class Supplier:
    supplier_id: Any
    supplier_name: str
    country: str
    parent_companies: tuple[str, ...]
    currency: str
    hs_codes: tuple[ExposureEntry, ...] = ()
    exit_ports: tuple[ExposureEntry, ...] = ()
    entry_ports: tuple[ExposureEntry, ...] = ()
    carriers: tuple[ExposureEntry, ...] = ()
    vessels: tuple[ExposureEntry, ...] = ()
    buyers: tuple[ExposureEntry, ...] = ()

    @property
    def ports(self) -> tuple[ExposureEntry, ...]:
        return self.exit_ports + self.entry_ports


@dataclass(frozen=True)
class RequestContext:
    importing_country: str
    bom_line_id: Any = None
    component_query: Any = None


@dataclass(frozen=True)
class LookupRequest:
    as_of_date: date
    event_window_days: int
    request_context: RequestContext
    suppliers: tuple[Supplier, ...]
    schema_version: str | None = None


# --------------------------------------------------------------------------
# Errors and warnings


@dataclass(frozen=True)
class ValidationError:
    field: str
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class Notice:
    """A warning or data-gap note. Never changes which records are returned."""

    code: str
    message: str
    field: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.field is not None:
            out["field"] = self.field
        return out


class EngineValidationError(ValueError):
    """Raised by `parse_request(..., raise_on_error=True)` for Python callers."""

    def __init__(self, errors: list[ValidationError]):
        self.errors = errors
        super().__init__("; ".join(f"{e.field}: {e.message}" for e in errors))


# --------------------------------------------------------------------------
# Results


@dataclass(frozen=True)
class Link:
    """One way a record links to a supplier. A link is context, not impact."""

    link_basis: str
    link_strength: str
    matched_value: str
    input_value: str
    record_field: str
    record_value: str
    matched_exposure: dict[str, Any] | None = None
    approximated: bool = False
    approximation_basis: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "link_basis": self.link_basis,
            "link_strength": self.link_strength,
            "matched_value": self.matched_value,
            "input_value": self.input_value,
            "record_field": self.record_field,
            "record_value": self.record_value,
            "matched_exposure": self.matched_exposure,
            "approximated": self.approximated,
        }
        if self.approximated:
            out["approximation_basis"] = self.approximation_basis
        return out


@dataclass(frozen=True)
class DateScope:
    date_family: str
    date_status: str  # "dated" or "undated_candidate"
    in_scope_reason: str
    dates: dict[str, Any]
    known_from: str
    known_from_rule: str  # see dates.KNOWN_FROM_*
    open_end: str | None = None


@dataclass(frozen=True)
class LinkedReport:
    risk_type: str
    evidence_id: str
    scope: DateScope
    links: tuple[Link, ...]
    main_basis: str
    main_strength: str
    matched_values: tuple[str, ...]
    matched_exposure: tuple[dict[str, Any], ...]
    labels: tuple[str, ...]
    search_window: dict[str, Any] | None
    verification_status: Any
    limitations: Any
    related_evidence_ids: tuple[str, ...]
    incident_group_id: str
    scenario_recovery: Any

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "risk_type": self.risk_type,
            "evidence_id": self.evidence_id,
            "date_family": self.scope.date_family,
            "date_status": self.scope.date_status,
            "in_scope_reason": self.scope.in_scope_reason,
            **self.scope.dates,
            "known_from": self.scope.known_from,
            "known_from_rule": self.scope.known_from_rule,
        }
        if self.scope.open_end is not None:
            out["open_end"] = self.scope.open_end
        out.update(
            {
                "search_window": self.search_window,
                "link_basis": self.main_basis,
                "link_strength": self.main_strength,
                "matched_values": list(self.matched_values),
                "matched_exposure": list(self.matched_exposure) or None,
                "approximated": any(
                    link.approximated
                    for link in self.links
                    if link.link_basis == self.main_basis
                ),
                "labels": list(self.labels),
                "links": [link.to_dict() for link in self.links],
                "verification_status": self.verification_status,
                "limitations": self.limitations,
                "related_evidence_ids": list(self.related_evidence_ids),
                "incident_group_id": self.incident_group_id,
            }
        )
        if self.scenario_recovery is not None:
            out["scenario_recovery"] = {
                "stored": self.scenario_recovery,
                "label": (
                    "Stored illustrative scenario, returned as stored. Not a "
                    "verified recovery duration; never used as an impact "
                    "duration."
                ),
            }
        return out


@dataclass(frozen=True)
class IncidentGroup:
    """Linked reports that describe the same incident (plan section 4)."""

    incident_group_id: str
    linked_evidence_ids: tuple[str, ...]
    unlinked_member_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_group_id": self.incident_group_id,
            "linked_evidence_ids": list(self.linked_evidence_ids),
            "unlinked_member_ids": list(self.unlinked_member_ids),
        }


@dataclass(frozen=True)
class SupplierResult:
    input: dict[str, Any]
    linked_reports: tuple[LinkedReport, ...]
    incident_groups: tuple[IncidentGroup, ...]
    data_gaps: tuple[Notice, ...]

    def to_dict(self) -> dict[str, Any]:
        distinct = {r.incident_group_id for r in self.linked_reports}
        return {
            "input": self.input,
            "linked_report_count": len(self.linked_reports),
            "distinct_incident_count": len(distinct),
            "linked_reports": [r.to_dict() for r in self.linked_reports],
            "incident_groups": [g.to_dict() for g in self.incident_groups],
            "data_gaps": [n.to_dict() for n in self.data_gaps],
        }


@dataclass(frozen=True)
class LookupResult:
    status: str  # "completed" or "rejected"
    schema_version: str
    engine_version: str
    data_snapshot_id: str | None
    study_window: dict[str, str]
    as_of_date: str | None = None
    event_window_days: int | None = None
    request_context: dict[str, Any] | None = None
    suppliers: tuple[SupplierResult, ...] = ()
    errors: tuple[ValidationError, ...] = ()
    warnings: tuple[Notice, ...] = ()
    notice: str = field(
        default=(
            "Linked reports are stored records matched by name, code, port, "
            "or country. A link is context, not evidence that an event "
            "affected the supplier, a shipment, or a route."
        )
    )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "status": self.status,
            "engine_version": self.engine_version,
            "data_snapshot_id": self.data_snapshot_id,
            "study_window": self.study_window,
        }
        if self.status == "rejected":
            out["errors"] = [e.to_dict() for e in self.errors]
            return out
        out.update(
            {
                "as_of_date": self.as_of_date,
                "event_window_days": self.event_window_days,
                "request_context": self.request_context,
                "notice": self.notice,
                "suppliers": [s.to_dict() for s in self.suppliers],
                "unlinked_context": [],
                "warnings": [w.to_dict() for w in self.warnings],
            }
        )
        return out
