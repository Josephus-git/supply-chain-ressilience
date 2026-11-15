"""Build the phase 2 fixture payloads (engine plan, section 9, phase 2).

Each payload is one supplier's exposure profile, shaped as the request in
section 6.1. Shipment-level keys (ports, carriers, vessels, HS codes, buyers,
footprint) are aggregated from the cleaned shipment CSVs in
``data/processed/``. These CSVs are derived from ``data/raw_yeti_response/``
and are the files loaded into the Neo4j graph, so the counts equal what the
graph returns for each ``Supplier`` node.

Two values are not in the CSVs and are copied from the graph (Neo4j dump of
2026-10-29, read on 2026-11-15):

- ``country``: ``Supplier.supplier_country_code``. The graph keeps one value
  per supplier, which can differ from the per-shipment country in the CSVs.
- ``parent_companies``: ``(Supplier)-[:SUBSIDIARY_OF]->(ParentCompany)
  .canonical_name``. The graph holds one parent level per supplier.

One vessel name is also taken from the graph (see ``VESSEL_NAME_BY_ID``).

``as_of_date`` is chosen per fixture to exercise specific evidence records;
the reason for each date is recorded in ``expected_ids.json``.

Run from the repository root:

    python supplier_risk_engine/examples/build_payloads.py
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSV_DIR = ROOT / "data" / "processed"
OUT_DIR = Path(__file__).resolve().parent / "payloads"

SCHEMA_VERSION = "1.1"
EVENT_WINDOW_DAYS = 14
IMPORTING_COUNTRY = "US"  # every entry port and buyer in the data is in the US

# supplier_id -> (fixture number, graph country, graph parents, as_of_date)
SUPPLIERS: dict[str, tuple[int, str, list[str], str]] = {
    "org:flextronics-shah-alam": (1, "CN", ["FLEX LTD."], "2026-09-25"),
    "org:flextronics-shah-alam-sdn-bhd": (2, "MY", ["FLEX LTD."], "2025-11-10"),
    "org:flextronics-technology-penang-sdn": (3, "MY", ["FLEX LTD."], "2026-09-28"),
    "org:hi-p-philippines-technology-corp": (4, "PH", ["HI-P INTERNATIONAL PTE. LTD."], "2025-11-10"),
    "org:hi-p-philippines-technology-corpora": (5, "TW", ["HI-P INTERNATIONAL PTE. LTD."], "2026-04-01"),
    "org:hip-philipines-technology-corp": (6, "PH", ["HI-P INTERNATIONAL PTE. LTD."], "2025-09-24"),
    "org:ihastek-malaysia-sdn-bhd": (7, "CN", ["Xiamen Intretech Inc."], "2025-11-21"),
    "org:kinpo-electronics-philippines": (8, "PH", ["Kinpo Electronics, Inc."], "2026-06-19"),
    "org:kinpo-electronics-philippines-inc": (9, "HK", ["Kinpo Electronics, Inc."], "2026-04-01"),
    "org:meiban-technologies-m-sdn-bhd": (10, "MY", ["MEIBAN TECHNOLOGIES (MALAYSIA) SDN. BHD."], "2026-09-21"),
    "org:meiban-technologies-malaysia-sdn": (11, "HK", ["MEIBAN TECHNOLOGIES (MALAYSIA) SDN. BHD."], "2026-03-10"),
    "org:syarikat-sin-kwang-plastic": (12, "CN", ["SYARIKAT SIN KWANG PLASTIC INDUSTRIES SDN. BHD."], "2025-05-30"),
    "org:syarikat-sin-kwang-plastic-ind-s-b": (13, "MY", ["SYARIKAT SIN KWANG PLASTIC INDUSTRIES SDN. BHD."], "2026-03-20"),
    "org:syarikat-sin-kwang-plastic-industri": (14, "MY", ["SYARIKAT SIN KWANG PLASTIC INDUSTRIES SDN. BHD."], "2025-10-28"),
    "org:v-s-industrial-berhad": (15, "MY", ["V.S. INDUSTRY BERHAD"], "2026-09-16"),
    "org:vs-industrial-berhad": (16, "CN", ["V.S. INDUSTRY BERHAD"], "2025-03-01"),
    "org:vs-industrial-philippines-inc": (17, "PH", ["V.S. INDUSTRY BERHAD"], "2026-04-01"),
    "org:wencor-m-sdn-bhd": (18, "TW", ["WENCOR GROUP, LLC"], "2025-12-29"),
}

# Section 6.1: currency from the supplier country through a fixed ISO 4217 table.
CURRENCY = {"CN": "CNY", "HK": "HKD", "MY": "MYR", "PH": "PHP", "SG": "SGD", "TW": "TWD"}

# Exit ports use CBP Schedule K codes; the first three digits identify the
# country. The graph has no port-country property, so the caller derives it.
SCHEDULE_K_COUNTRY = {
    "552": "VN", "557": "MY", "559": "SG", "565": "PH",
    "570": "CN", "580": "KR", "582": "HK", "583": "TW",
}


# The CSVs give vessel IMO 9444261 two names; the graph Vessel node, keyed by
# vessel_id, holds "Mol Premium". Use the graph name so payloads match it.
VESSEL_NAME_BY_ID = {"vessel:9444261": "Mol Premium"}


def hs6(code: str) -> str:
    """The graph stores HS codes as integers; restore the 6-digit string."""
    return code.strip().zfill(6)


def coast(lon: float) -> str:
    """Section 6.1: US entry ports east of -100 longitude are east_gulf."""
    return "east_gulf" if lon > -100 else "west"


def carrier_name(raw: str, code: str) -> str:
    """Graph carrier names carry a 'SCAC - ' prefix; the code is sent separately."""
    prefix = f"{code} - "
    return raw[len(prefix):] if raw.startswith(prefix) else raw


def counted(counter: Counter, make) -> list[dict]:
    return [make(key, n) for key, n in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))]


def load_rows() -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(CSV_DIR.glob("*_shipments_clean.csv")):
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                rows[row["supplier_id"]].append(row)
    return rows


def build(supplier_id: str, rows: list[dict]) -> dict:
    _, country, parents, as_of = SUPPLIERS[supplier_id]
    names = {r["supplier_name"] for r in rows}
    assert len(names) == 1, (supplier_id, names)

    hs, exits, entries, carriers, vessels, buyers, products = (Counter() for _ in range(7))
    dates = []
    for r in rows:
        dates.append(r["arrival_date"])
        products[r["product_description"]] += 1
        if r["hs_code"]:
            hs[hs6(r["hs_code"])] += 1
        exits[(r["exit_port"], r["exit_port_code"].zfill(5))] += 1
        entries[(r["entry_port"], r["entry_port_code"].zfill(4), float(r["entry_port_lon"]))] += 1
        carriers[(carrier_name(r["carrier_name"], r["carrier_code"]), r["carrier_code"])] += 1
        if r["vessel_name"]:
            vessels[VESSEL_NAME_BY_ID.get(r["vessel_id"], r["vessel_name"])] += 1
        buyers[r["buyer_name"]] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of_date": as_of,
        "event_window_days": EVENT_WINDOW_DAYS,
        "request_context": {
            "bom_line_id": f"FIXTURE-{SUPPLIERS[supplier_id][0]:02d}",
            "component_query": products.most_common(1)[0][0],
            "importing_country": IMPORTING_COUNTRY,
        },
        "suppliers": [
            {
                "supplier_id": supplier_id,
                "supplier_name": names.pop(),
                "country": country,
                "parent_companies": parents,
                "hs_codes": counted(hs, lambda k, n: {"code": k, "shipments": n}),
                "exit_ports": counted(exits, lambda k, n: {
                    "name": k[0], "code": k[1], "country": SCHEDULE_K_COUNTRY[k[1][:3]], "shipments": n}),
                "entry_ports": counted(entries, lambda k, n: {
                    "name": k[0], "code": k[1], "country": "US", "coast": coast(k[2]), "shipments": n}),
                "buyers": counted(buyers, lambda k, n: {"name": k, "shipments": n}),
                "carriers": counted(carriers, lambda k, n: {"name": k[0], "code": k[1], "shipments": n}),
                "vessels": counted(vessels, lambda k, n: {"name": k, "shipments": n}),
                "currency": CURRENCY[country],
                "footprint_window": {
                    "first_arrival": min(dates),
                    "last_arrival": max(dates),
                    "shipments": len(rows),
                },
            }
        ],
    }


def main() -> None:
    rows = load_rows()
    missing = set(SUPPLIERS) ^ set(rows)
    assert not missing, f"supplier table and CSVs disagree: {sorted(missing)}"
    OUT_DIR.mkdir(exist_ok=True)
    for supplier_id in sorted(SUPPLIERS, key=lambda s: SUPPLIERS[s][0]):
        num = SUPPLIERS[supplier_id][0]
        slug = supplier_id.removeprefix("org:")
        path = OUT_DIR / f"{num:02d}_{slug}.json"
        path.write_text(json.dumps(build(supplier_id, rows[supplier_id]), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
