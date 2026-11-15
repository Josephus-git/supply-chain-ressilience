"""Matching rules for each risk type (plan sections 4, 5.1, and 7).

Each rule takes one stored record and one supplier and returns every `Link`
it finds. An empty list means the record does not link to the supplier.
Rules never look at dates; `dates.py` handles those.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from .models import ExposureEntry, Link, RequestContext, Supplier
from .normalise import (
    contains_whole_words,
    hs_codes_match,
    is_generic_port_name,
    normalise_name,
    normalise_port_name,
    normalise_text,
    split_name_list,
)

_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")


@dataclass(frozen=True)
class MatchContext:
    supplier: Supplier
    request: RequestContext


Rule = Callable[[dict[str, Any], MatchContext], list[Link]]


# --------------------------------------------------------------------------
# Approximated fields


def _approximation(record: dict[str, Any], field: str) -> tuple[bool, str | None, bool]:
    """Return (approximated, basis, informational_only) for a record field."""
    for entry in record.get("approximations") or []:
        if entry.get("field") == field:
            basis = entry.get("basis")
            informational = "informational only" in (basis or "").casefold()
            return True, basis, informational
    return False, None, False


def _link(
    record: dict[str, Any],
    *,
    basis: str,
    strength: str,
    matched_value: str,
    input_value: str,
    record_field: str,
    record_value: Any,
    exposure: ExposureEntry | None = None,
    approx_field: str | None = None,
) -> Link | None:
    """Build a link, applying the approximated-field rules (plan section 4).

    Returns None when the field is approximated and informational only.
    """
    approximated, approx_basis, informational = _approximation(
        record, approx_field or record_field.split(".")[0].split("[")[0]
    )
    if informational:
        return None
    return Link(
        link_basis=basis,
        link_strength="weak" if approximated else strength,
        matched_value=matched_value,
        input_value=input_value,
        record_field=record_field,
        record_value=record_value if isinstance(record_value, str) else _compact(record_value),
        matched_exposure=dict(exposure.raw) if exposure is not None else None,
        approximated=approximated,
        approximation_basis=approx_basis,
    )


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _add(links: list[Link], link: Link | None) -> None:
    if link is not None:
        links.append(link)


# --------------------------------------------------------------------------
# Building blocks


def _record_names(value: Any, list_valued: bool) -> list[str]:
    """Raw name entries from a record field, with role text removed."""
    if value is None:
        return []
    if isinstance(value, list):
        raw: list[str] = []
        for item in value:
            if isinstance(item, str):
                raw.extend(split_name_list(item))
    elif isinstance(value, str):
        raw = split_name_list(value) if list_valued else [value]
    else:
        return []
    return [" ".join(_BRACKETS.sub(" ", entry).split()) for entry in raw]


def company_links(
    record: dict[str, Any], field: str, ctx: MatchContext, *, list_valued: bool = False
) -> list[Link]:
    """Supplier and parent names against a company-name field.

    Parent links run one way: a report about a parent links to the supplier
    the payload names under it. A parent equal to the supplier's own name is
    reported once, as `company_name`.
    """
    links: list[Link] = []
    supplier = ctx.supplier
    own = normalise_name(supplier.supplier_name)
    for entry in _record_names(record.get(field), list_valued):
        norm = normalise_name(entry)
        if not norm:
            continue
        if norm == own:
            _add(
                links,
                _link(
                    record,
                    basis="company_name",
                    strength="strong",
                    matched_value=entry,
                    input_value=supplier.supplier_name,
                    record_field=field,
                    record_value=record.get(field),
                ),
            )
        for parent in supplier.parent_companies:
            parent_norm = normalise_name(parent)
            if parent_norm == norm and parent_norm != own:
                _add(
                    links,
                    _link(
                        record,
                        basis="parent_company_name",
                        strength="strong",
                        matched_value=entry,
                        input_value=parent,
                        record_field=field,
                        record_value=record.get(field),
                    ),
                )
    return links


def buyer_links(record: dict[str, Any], field: str, ctx: MatchContext) -> list[Link]:
    links: list[Link] = []
    for entry in _record_names(record.get(field), False):
        norm = normalise_name(entry)
        for buyer in ctx.supplier.buyers:
            if buyer.name and normalise_name(buyer.name) == norm:
                _add(
                    links,
                    _link(
                        record,
                        basis="buyer_name",
                        strength="strong",
                        matched_value=entry,
                        input_value=buyer.name,
                        record_field=field,
                        record_value=record.get(field),
                        exposure=buyer,
                    ),
                )
    return links


def _country_codes(record: dict[str, Any], field: str) -> list[tuple[str, str]]:
    """(code, record_field) pairs from a scalar code or a list of
    {country_code: ...} objects."""
    value = _get_path(record, field)
    if isinstance(value, str):
        return [(value, field)]
    out: list[tuple[str, str]] = []
    if isinstance(value, list):
        for i, item in enumerate(value):
            if isinstance(item, dict) and isinstance(item.get("country_code"), str):
                out.append((item["country_code"], f"{field}[{i}].country_code"))
    return out


def supplier_country_links(
    record: dict[str, Any], fields: list[str], ctx: MatchContext
) -> list[Link]:
    """Country-only links on the supplier's country (always weak)."""
    links: list[Link] = []
    for field in fields:
        for code, path in _country_codes(record, field):
            if code == ctx.supplier.country:
                _add(
                    links,
                    _link(
                        record,
                        basis="country_code",
                        strength="weak",
                        matched_value=code,
                        input_value=ctx.supplier.country,
                        record_field=path,
                        record_value=code,
                        approx_field=field.split(".")[0],
                    ),
                )
    return links


def port_links(
    record: dict[str, Any],
    text_fields: list[str],
    country_field: str,
    ctx: MatchContext,
) -> list[Link]:
    """Lenient, tiered port matching. For each payload port (exit and entry),
    the first tier that hits wins: port_code, then port_name, then
    port_country."""
    texts: list[tuple[str, str, str]] = []  # (path, raw, normalised)
    for path in text_fields:
        raw = _get_path(record, path)
        if isinstance(raw, str) and raw.strip():
            texts.append((path, raw, normalise_text(raw)))
    record_codes = [str(c) for c in (record.get("port_ids") or []) if c is not None]
    record_country = _get_path(record, country_field)

    links: list[Link] = []
    for port in ctx.supplier.ports:
        # Tier 1: port code.
        if port.code is not None and port.code in record_codes:
            _add(
                links,
                _link(
                    record,
                    basis="port_code",
                    strength="strong",
                    matched_value=port.code,
                    input_value=port.code,
                    record_field="port_ids",
                    record_value=record.get("port_ids"),
                    exposure=port,
                ),
            )
            continue
        # Tier 2: port name, whole-word containment.
        name_norm = normalise_port_name(port.name or "")
        hit = None
        if not is_generic_port_name(name_norm):
            for path, raw, norm in texts:
                if contains_whole_words(norm, name_norm):
                    hit = (path, raw)
                    break
        if hit is not None:
            _add(
                links,
                _link(
                    record,
                    basis="port_name",
                    strength="medium",
                    matched_value=port.name,
                    input_value=port.name,
                    record_field=hit[0],
                    record_value=hit[1],
                    exposure=port,
                ),
            )
            continue
        # Tier 3: port country (location only, weak).
        if port.country is not None and isinstance(record_country, str) and port.country == record_country:
            _add(
                links,
                _link(
                    record,
                    basis="port_country",
                    strength="weak",
                    matched_value=port.name,
                    input_value=port.country,
                    record_field=country_field,
                    record_value=record_country,
                    exposure=port,
                ),
            )
    return links


def _get_path(record: dict[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def vessel_links(record: dict[str, Any], field: str, ctx: MatchContext) -> list[Link]:
    links: list[Link] = []
    for entry in _record_names(record.get(field), False):
        norm = normalise_name(entry)
        for vessel in ctx.supplier.vessels:
            if vessel.name and normalise_name(vessel.name) == norm:
                _add(
                    links,
                    _link(
                        record,
                        basis="vessel_name",
                        strength="strong",
                        matched_value=entry,
                        input_value=vessel.name,
                        record_field=field,
                        record_value=record.get(field),
                        exposure=vessel,
                    ),
                )
    return links


def carrier_links(
    record: dict[str, Any], field: str, ctx: MatchContext, *, list_valued: bool = False
) -> list[Link]:
    """Carrier names, role text removed. Medium: a carrier operates many
    services, so a carrier-level report is less specific than a vessel."""
    links: list[Link] = []
    for entry in _record_names(record.get(field), list_valued):
        norm = normalise_name(entry)
        for carrier in ctx.supplier.carriers:
            if carrier.name and normalise_name(carrier.name) == norm:
                _add(
                    links,
                    _link(
                        record,
                        basis="carrier_name",
                        strength="medium",
                        matched_value=entry,
                        input_value=carrier.name,
                        record_field=field,
                        record_value=record.get(field),
                        exposure=carrier,
                    ),
                )
    return links


# --------------------------------------------------------------------------
# Rules per risk type


def _supplier_like(name_field: str, country_fields: list[str], *, list_valued: bool = False) -> Rule:
    def rule(record: dict[str, Any], ctx: MatchContext) -> list[Link]:
        return company_links(record, name_field, ctx, list_valued=list_valued) + supplier_country_links(
            record, country_fields, ctx
        )

    return rule


def _country_only(country_fields: list[str]) -> Rule:
    def rule(record: dict[str, Any], ctx: MatchContext) -> list[Link]:
        return supplier_country_links(record, country_fields, ctx)

    return rule


def natural_hazards(record: dict[str, Any], ctx: MatchContext) -> list[Link]:
    return port_links(
        record, ["location.label", "location.affected_area"], "location.country_code", ctx
    ) + supplier_country_links(record, ["location.country_code"], ctx)


def port_disruption(record: dict[str, Any], ctx: MatchContext) -> list[Link]:
    # Country links only through a port's country, never the supplier's.
    return port_links(record, ["reported_port"], "country_code", ctx)


def border_customs_delays(record: dict[str, Any], ctx: MatchContext) -> list[Link]:
    return port_links(
        record, ["border_or_customs_location"], "country_code", ctx
    ) + supplier_country_links(record, ["country_code"], ctx)


def carrier_vessel_disruption(record: dict[str, Any], ctx: MatchContext) -> list[Link]:
    # Never linked by country: the country is the incident location, not the
    # vessel's flag or the supplier's country (plan section 7.1).
    return vessel_links(record, "reported_vessel", ctx) + carrier_links(
        record, "reported_carrier", ctx
    )


def goods_in_transit(record: dict[str, Any], ctx: MatchContext) -> list[Link]:
    return carrier_links(record, "reported_carrier", ctx, list_valued=True) + supplier_country_links(
        record, ["country_code"], ctx
    )


def route_chokepoint_disruption(record: dict[str, Any], ctx: MatchContext) -> list[Link]:
    links = supplier_country_links(record, ["countries"], ctx)
    supplier = ctx.supplier
    for i, lane in enumerate(record.get("trade_lanes") or []):
        if not isinstance(lane, dict):
            continue
        if supplier.country not in (lane.get("origin_country_codes") or []):
            continue
        if ctx.request.importing_country != lane.get("destination_country_code"):
            continue
        coast = lane.get("destination_coast")
        for port in supplier.entry_ports:
            if port.coast is not None and port.coast == coast:
                _add(
                    links,
                    _link(
                        record,
                        basis="trade_lane",
                        strength="weak",
                        matched_value=coast,
                        input_value=port.coast,
                        record_field=f"trade_lanes[{i}]",
                        record_value=lane,
                        exposure=port,
                        approx_field="trade_lanes",
                    ),
                )
    return links


COUNTRY_WIDE_LABEL = "country-wide measure; product applicability not established"


def tariffs_and_duties(record: dict[str, Any], ctx: MatchContext) -> list[Link]:
    """Origin = supplier country and importing = request importing_country.
    A null origin is global and matches on importing country alone. A record
    with a commodity code also needs an HS prefix match."""
    supplier = ctx.supplier
    importing = record.get("importing_country_code")
    if importing != ctx.request.importing_country:
        return []
    origin = record.get("origin_country_code")
    if origin is not None and origin != supplier.country:
        return []

    links: list[Link] = []
    code = (record.get("product_classification") or {}).get("code")
    if code:
        for hs in supplier.hs_codes:
            if hs.code and hs_codes_match(hs.code, code):
                _add(
                    links,
                    _link(
                        record,
                        basis="hs_code",
                        strength="medium",
                        matched_value=code,
                        input_value=hs.code,
                        record_field="product_classification.code",
                        record_value=code,
                        exposure=hs,
                        approx_field="product_classification",
                    ),
                )
        if not links:
            return []

    if origin is not None:
        _add(
            links,
            _link(
                record,
                basis="country_code",
                strength="weak",
                matched_value=origin,
                input_value=supplier.country,
                record_field="origin_country_code",
                record_value=origin,
            ),
        )
    else:
        _add(
            links,
            _link(
                record,
                basis="importing_country",
                strength="weak",
                matched_value=importing,
                input_value=ctx.request.importing_country,
                record_field="importing_country_code",
                record_value=importing,
            ),
        )
    return links


def government_restrictions(record: dict[str, Any], ctx: MatchContext) -> list[Link]:
    return company_links(record, "reported_organisation", ctx) + supplier_country_links(
        record, ["affected_countries", "issuing_country_code"], ctx
    )


def currency_fluctuations(record: dict[str, Any], ctx: MatchContext) -> list[Link]:
    # country_code is informational only and never linked.
    links = buyer_links(record, "reported_organisation", ctx)
    currency = ctx.supplier.currency
    for field in ("quote_currency", "base_currency"):
        if record.get(field) == currency:
            _add(
                links,
                _link(
                    record,
                    basis="currency",
                    strength="medium",
                    matched_value=currency,
                    input_value=currency,
                    record_field=field,
                    record_value=currency,
                ),
            )
    return links


RULES: dict[str, Rule] = {
    "supplier_operational_disruption": _supplier_like("reported_supplier", ["country_code"]),
    "cyberattack": _supplier_like("reported_organisation", ["country_code"]),
    "supplier_financial_distress": _supplier_like("reported_supplier", ["country_code"]),
    "product_quality_compliance": _supplier_like(
        "reported_supplier", ["country_code"], list_valued=True
    ),
    "labour_disruption": _supplier_like("reported_organisation", ["country_code"]),
    "natural_hazards": natural_hazards,
    "port_disruption": port_disruption,
    "carrier_vessel_disruption": carrier_vessel_disruption,
    "route_chokepoint_disruption": route_chokepoint_disruption,
    "goods_in_transit_loss_theft_or_damage": goods_in_transit,
    "tariffs_and_duties": tariffs_and_duties,
    "government_restrictions": government_restrictions,
    "border_customs_delays": border_customs_delays,
    "geopolitical_conflict": _country_only(["affected_countries"]),
    "input_material_shortage": _supplier_like("reported_supplier", ["affected_countries"]),
    "energy_or_transport_cost_increase": _country_only(["affected_countries"]),
    "supplier_or_route_concentration": _supplier_like(
        "reported_entities_or_routes", ["countries"], list_valued=True
    ),
    "currency_fluctuations": currency_fluctuations,
}
