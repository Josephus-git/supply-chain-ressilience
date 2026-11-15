"""How graph nodes are identified and shaped for the browser.

API node IDs are `<kind>:<business key>`, for example
`supplier:org:ihastek-malaysia-sdn-bhd` or `exit_port:port:57020`. The kind
prefix keeps Entry and Exit ports apart (both use `port:` keys) and maps each
ID straight back to a label and an indexed key property. The IDs are stable
across database restarts, unlike Neo4j element IDs, so stored runs can cite
them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .neo4j_client import clean_properties


@dataclass(frozen=True)
class Kind:
    kind: str
    label: str  # Neo4j label
    key: str  # unique, indexed key property
    name: str  # display-name property


KINDS: dict[str, Kind] = {
    k.kind: k
    for k in (
        Kind("supplier", "Supplier", "supplier_id", "supplier_name"),
        Kind("parent", "ParentCompany", "company_number", "canonical_name"),
        Kind("buyer", "Buyer", "buyer_id", "buyer_name"),
        Kind("shipment", "Shipment", "shipment_id", "bol_number"),
        Kind("product", "Product", "product_id", "product_description"),
        Kind("exit_port", "Exit Port", "exit_port_id", "exit_port"),
        Kind("entry_port", "Entry Port", "entry_port_id", "entry_port"),
        Kind("carrier", "Carrier", "carrier_id", "carrier_name"),
        Kind("vessel", "Vessel", "vessel_id", "vessel_name"),
    )
}
BY_LABEL: dict[str, Kind] = {k.label: k for k in KINDS.values()}

# Properties matched by /api/graph/search.
SEARCH_PROPERTIES = [
    "supplier_name", "supplier_basename", "supplier_id",
    "canonical_name", "company_number",
    "buyer_name",
    "bol_number", "shipment_id",
    "product_description", "full_hs_code_description", "hs_code",
    "exit_port", "entry_port",
    "carrier_name", "carrier_code",
    "vessel_name",
]


class UnknownNodeId(ValueError):
    pass


def parse_node_id(node_id: str) -> tuple[Kind, str]:
    kind, sep, key = node_id.partition(":")
    if not sep or not key or kind not in KINDS:
        raise UnknownNodeId(
            f"Node IDs look like '<kind>:<key>' with kind one of {sorted(KINDS)}; got {node_id!r}"
        )
    return KINDS[kind], key


def match_clause(var: str, node_id: str) -> tuple[str, dict[str, Any]]:
    """`MATCH (var:`Label` {key: $var_key})` and its parameters."""
    kind, key = parse_node_id(node_id)
    return f"MATCH ({var}:`{kind.label}` {{{kind.key}: ${var}_key}})", {f"{var}_key": key}


def label_of(labels: list[str]) -> Kind | None:
    for label in labels:
        if label in BY_LABEL:
            return BY_LABEL[label]
    return None


def node_id_of(kind: Kind, props: dict[str, Any]) -> str:
    return f"{kind.kind}:{props[kind.key]}"


def display_name(kind: Kind, props: dict[str, Any]) -> str:
    value = props.get(kind.name)
    if kind.kind == "product":
        hs = props.get("hs_code")
        text = (value or props.get("hs_code_description") or "").strip()
        return f"HS {hs:06d} · {text}" if isinstance(hs, int) else text
    return str(value) if value not in (None, "") else str(props.get(kind.key))


def node_out(labels: list[str], props: dict[str, Any]) -> dict[str, Any]:
    """The node shape every graph endpoint returns."""
    kind = label_of(labels)
    if kind is None:
        raise ValueError(f"Unexpected labels {labels}")
    props = clean_properties({k: v for k, v in props.items() if v is not None})
    return {
        "id": node_id_of(kind, props),
        "kind": kind.kind,
        "label": kind.label,
        "name": display_name(kind, props),
        "properties": props,
    }


def node_return(var: str, alias: str | None = None) -> str:
    """Cypher RETURN items for a node; the 1536-dim embedding never leaves the server."""
    alias = alias or var
    return f"labels({var}) AS {alias}_labels, {var} {{.*, embedding: null}} AS {alias}_props"
