# Supplier risk evidence engine plan

Status: **draft for discussion**. This document proposes an implementation; it
does not describe an existing engine. Examples and values are illustrative,
not findings.

## 1. Goal and scope

Build a reproducible Python engine that receives a payload of suppliers (name
and country) and a query date, matches each supplier against stored
supply-chain records, and returns the matched records with their dated,
source-attributed evidence reports and related context.

The engine only retrieves stored records. It estimates no probabilities, runs
no simulation, and does not infer impact. It runs locally as an MCP server on
this machine, using only historical data already stored here. A LangChain
application can connect to it later without changing it.

The engine should:

- Accept one or many suppliers in a single request.
- Preserve stored shipment, route, and evidence records with their identifiers
  and sources.
- Report shared departure ports as stored facts, without treating them as
  shared exposure to any event.
- Report unmatched, ambiguous, and partially covered inputs, along with data
  gaps and limitations.
- Keep retrieved reports separate from any conclusion about impact.

The [evidence dataset plan](./RISK_EVIDENCE_DATASET_PLAN.md) covers historical
incidents, tariff rules, provenance, and matching.

## 2. Current graph and data boundaries

The documented [graph schema](./langchain/schema.txt) includes suppliers,
shipments, buyers, products, departure and arrival ports, carriers, vessels,
and parent companies. In particular:

| Information | Documented source |
| --- | --- |
| Supplier ID, name, country, address | `Supplier` |
| Shipment ID, dates, quantity, weight, costs | `Shipment` |
| Departure and arrival ports and coordinates | `Exit Port`, `Entry Port` |
| Buyer identity and country | `Buyer` |
| Product description and HS code | `Product` |
| Carrier, vessel, and parent company | Related nodes where available |

These are historical records, not necessarily current routes or verified
dependencies. The schema does not list tariff rates, financial health, actual
sailing paths, or inventory levels. The
[combined dataset](./data/processed/combined/combined.csv) contains
`source_file` and `source_row`, but the documented schema does not show them;
verify whether this provenance is actually present in Neo4j.

Before implementation, inspect the local Neo4j database read-only. The relationship
names in [cypher_qa.py](./langchain/cypher_qa.py) and
[vector_cypher_retriever.py](./rag/vector_cypher_retriever.py) differ from
parts of `schema.txt`. Do not assume which reflects the database.

## 3. Architecture

```text
Payload: suppliers, as_of_date, event_window_days
             |
             v
Supplier risk evidence engine (standalone)
  - validates the payload
  - matches suppliers to stored records
  - retrieves dated reports and linked context
  - returns a structured result with coverage and warnings
             ^
             |
Adapters (outside the engine)
  - application layer: reads Neo4j and the evidence files, passes records in
  - MCP server: exposes the engine to MCP clients on this machine
  - LangChain app (later): calls the MCP server as a client
  - CLI: for testing
```

The engine receives stored records as plain input. It contains no Neo4j, LLM,
MCP, or UI code. The application layer reads the records and passes them in,
so the matching and retrieval logic can be tested with fixed records.

Evidence `search_window` dates are retrieval aids with an explicit basis, not
necessarily incident start or end dates. The engine must distinguish report,
claim, and approximate dates from verified overlaps, and must surface unknown
event dates rather than treating a search window as proof of impact. Every
evidence record needs valid ISO search-window dates in order. Invalid or
incomplete records are reported and rejected, not silently dropped. Template
placeholders are not evidence.

The dataset may include `scenario_recovery` suggestions: subjective,
low-confidence handling-delay ranges. The engine returns them only as stored,
labelled with their scope and anchor. They are not verified recovery durations,
and the engine never uses them, or any retrieval window, as a duration.

The existing [mcp_client.py](./langchain/mcp_client.py) targets an external
Apify service. It is unrelated to this local MCP server.

## 4. Shared exposure and linked context

The engine reports facts from the stored records. It does not decide that an
event has occurred.

- **Shared departure port:** when a matched supplier's stored shipments depart
  from a port that other stored suppliers also use, return the port and the
  number of other suppliers. This is a fact about the stored shipments, not a
  shared exposure to any event.
- **Observed routes:** a route is one shipment's departure and arrival port
  pair. Do not combine ports into pairs that were never observed together.
- **Country:** a common country is not an event. A country-only link is labelled
  as weak.
- **Duplicate reports:** reports describing the same event are returned as
  linked, not counted separately.
- **Historical associations:** a shipment association does not establish a
  verified route, a chokepoint crossing, supplier capacity, financial exposure,
  or a current event.

## 5. Matching and dated retrieval

The engine receives a payload of suppliers and a query date. It matches the
suppliers against stored records and returns the matched records with their
dated context. It makes no external lookups.

### 5.1 Supplier matching

For each supplier in the payload:

1. Normalise the name (case, whitespace, punctuation) and the country to an
   ISO 3166-1 alpha-2 code. An unrecognised country is a validation error, not
   a non-match.
2. Match the normalised name and country exactly against stored supplier
   records.
3. Return one status:
   - `matched`: exactly one stored record matches.
   - `ambiguous`: more than one record matches. List all candidates and link
     none automatically.
   - `not_found`: no stored record matches.

Fuzzy candidates are not linked automatically. Whether they are listed at all
is an open decision (section 5.5).

`not_found` means the database holds no record for the supplier. It does not
mean the supplier is low-risk or unknown in the outside world.

### 5.2 Dated reports

Each evidence record has an event interval (`event_start`, `event_end`). Given
the query date `as_of_date` and the caller-supplied `event_window_days`, a
dated report is in scope when:

    event_start - event_window_days <= as_of_date
        <= (event_end or event_start) + event_window_days

A record with no `event_start` is returned only as an undated candidate, and
only when its `search_window` contains `as_of_date`. It is labelled as a
retrieval aid, not as an event date.

The window is a retrieval setting. It does not describe how long an event
lasted. Each returned report carries its source, verification status, and
limitations exactly as stored.

### 5.3 Linking reports to matched suppliers

A report is linked to a matched supplier only through a stored, checkable
field:

- **`country_only`:** the report's country code equals the supplier's country.
  This link is weak and is labelled as such.
- **`port_match`:** the report's reported port matches a departure or arrival
  port in the supplier's stored shipments, using a reviewed mapping table.

A link means the report is relevant context. It does not show that the supplier
or any of its shipments was affected.

### 5.4 Shipment context

For each matched supplier, return its stored shipments with arrival dates,
departure and arrival ports, carrier, vessel, and product. Dates are returned
as stored, with their position relative to `as_of_date` (before, on, or after).

The engine does not infer which shipments were in transit on `as_of_date`. The
stored data has no departure date, so that inference would need an assumption
that is not in the data.

### 5.5 Open decisions

Agree these before implementation:

1. Whether fuzzy supplier candidates are returned, and at what threshold.
2. Which country formats the payload accepts: names, ISO codes, or both.
3. Whether `event_window_days` is required in every request, as proposed, or
   has a default.
4. Whether `country_only` links appear in the main results or in a separate
   list.
5. Which store is authoritative for supplier records: Neo4j, the evidence
   JSON files, or both.

### 5.6 Not in scope

The engine does not estimate probabilities, delays, costs, or impacts. It does
not calculate tariffs, assess financial health, model cascades across tiers, or
infer which shipments were affected by an event. Any of these would be a
separate project with its own plan and its own assumptions.

## 6. Request and response contract

### 6.1 Request

```json
{
  "schema_version": "1.0",
  "as_of_date": "2025-09-25",
  "event_window_days": 14,
  "suppliers": [
    {"supplier_name": "Supplier A", "country": "MY"},
    {"supplier_name": "Supplier B", "country": "CN"}
  ]
}
```

- `as_of_date`: ISO date. Required.
- `event_window_days`: non-negative integer. Required. Returned in the response.
- `suppliers`: non-empty array. Each entry needs `supplier_name` and `country`.
  An optional `supplier_id` must match a stored record exactly if given.

Two entries with the same normalised name and country are a validation error.

### 6.2 Response

The values below are illustrative.

```json
{
  "schema_version": "1.0",
  "status": "completed",
  "as_of_date": "2025-09-25",
  "event_window_days": 14,
  "data_snapshot_id": "illustrative-snapshot",
  "engine_version": "0.1.0",
  "coverage": {
    "coverage_start": "2025-01-01",
    "coverage_end": "2026-09-30",
    "as_of_within_coverage": true
  },
  "suppliers": [
    {
      "input": {"supplier_name": "Supplier B", "country": "CN"},
      "match_status": "matched",
      "matched_record": {
        "supplier_id": "S2",
        "supplier_name": "Supplier B",
        "country": "CN"
      },
      "linked_reports": [
        {
          "evidence_id": "PORT-2025-CN-RAGASA-001",
          "risk_type": "port_disruption",
          "event_start": "2025-09-22",
          "event_end": null,
          "in_scope_reason": "as_of_date within event_start window",
          "link_basis": "country_only",
          "verification_status": "secondary_source_reviewed_market_sources_attributed",
          "limitations": ["Stored limitations are returned unchanged."]
        }
      ],
      "shipments": [
        {
          "shipment_id": "SH2",
          "arrival_date": "2025-10-03",
          "position_vs_as_of": "after",
          "departure_port": {"id": "P1", "name": "Port A"},
          "arrival_port": {"id": "P2", "name": "Port B"},
          "product_hs_code": "850870"
        }
      ],
      "shared_departure_ports": [
        {"port_id": "P1", "other_stored_suppliers": 2}
      ]
    }
  ],
  "warnings": []
}
```

If `as_of_date` falls outside coverage, suppliers are still matched, but no
dated reports are returned and a warning explains why. An empty report list is
never presented as the absence of risk.

### 6.3 Validation

| Input | Behaviour |
| --- | --- |
| Missing or invalid `as_of_date` | Reject with a specific error. |
| Missing `event_window_days` | Reject. |
| Negative or non-integer `event_window_days` | Reject. |
| Empty `suppliers`, or a missing name or country | Reject. |
| Unrecognised country | Reject. |
| Duplicate supplier entry | Reject. |
| `as_of_date` outside coverage | Match suppliers, return no dated reports, warn. |
| No matching record | `not_found`. Not treated as no risk. |
| More than one matching record | `ambiguous`, with all candidates. No automatic link. |

## 7. Evidence categories

The stored evidence is organised into the following categories. A category is
returned only when records exist for it. A category with no records for a
matched supplier is reported as "no stored records", never as no risk.

1. Supplier operational disruption
2. Cyberattack
3. Supplier financial distress
4. Product quality or compliance
5. Labour disruption
6. Natural hazards, including flooding
7. Port disruption
8. Carrier or vessel disruption
9. Route or chokepoint disruption
10. Loss, theft, or damage to goods in transit
11. Tariffs and duties
12. Government restrictions
13. Border and customs delays
14. Geopolitical conflict
15. Supplier or route concentration
16. Input or material shortage
17. Energy or transport cost increases
18. Currency fluctuations

Each category needs its own stored records before it appears in results. The
[evidence dataset plan](./RISK_EVIDENCE_DATASET_PLAN.md) describes how those
records are collected. Historical endpoints do not prove that a shipment used a
particular chokepoint. Records describing the same incident are linked, not
counted as separate events.

## 8. Interfaces and integration

These names are proposed, not an existing API:

```python
result = lookup_suppliers(payload, records)
```

- **CLI:** reads a payload file, prints the result with its warnings, and can
  save the full JSON result.
- **MCP server:** the local interface. It exposes `lookup_suppliers` as an MCP
  tool, reads the stored records, and calls the same function. It contains no
  matching or retrieval logic of its own.
- **LangChain app (later):** connects to the local MCP server as a client and
  passes the returned records to the LLM for explanation. The LLM may explain
  returned records but must not add facts that are not in them.
- **CLI:** reads a payload file, prints the result with its warnings, and can
  save the full JSON result. Used for testing without an MCP client.

No remote servers, hosted web API, or live data sources are planned.

## 9. Implementation phases

1. **Verify stored records.** Inspect the local Neo4j schema read-only. Confirm
   relationship names, IDs, and whether `source_file` and `source_row` exist.
   Confirm which store is authoritative for supplier records (section 5.5).
2. **Settle open decisions.** Resolve section 5.5 and the shared-port wording in
   section 4.
3. **Implement the engine.** Add typed payload and result models, validation,
   supplier matching, dated retrieval, linking, shared-port facts, coverage,
   and warnings. Output must be deterministic for the same payload and records.
4. **Test with fixed records.** Cover exact, ambiguous, and missing matches;
   out-of-coverage dates; window boundaries (on the start, on the end, and one
   day outside); country-only links; undated candidates; duplicate reports;
   invalid input; and repeated runs producing identical output.
5. **Connect the application layer.** Add parameterised, read-only Neo4j queries,
   the evidence file loader, the MCP server, and the CLI. Record the data snapshot and engine
   version in each result.
6. **Connect the LangChain app.** Separate work, planned after the engine and its
   MCP server are tested. The app connects to the MCP server as a client and
   uses the returned records unchanged.

## 10. Evaluation and limitations

- Test matching, date handling, and linking against fixed records with known
  answers.
- Record the data snapshot fingerprint and engine version in every result.
- Check that every returned fact traces to a stored record and its source.
  Any LLM explanation added later should be checked against the returned
  records.
- Never infer a verified route, supplier capacity, financial exposure, or
  current event solely from a historical shipment association or a country
  match.
