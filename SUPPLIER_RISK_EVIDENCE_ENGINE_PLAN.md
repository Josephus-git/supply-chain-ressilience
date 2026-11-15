# Supplier risk evidence engine plan

Status: **draft for discussion**. This document proposes an implementation; it
does not describe an existing engine. Examples and values are illustrative,
not findings.

## 1. Goal and scope

Build a reproducible Python engine that receives a payload of candidate
suppliers for one bill-of-materials (BOM) line and a query date, finds the stored evidence that could affect each
supplier, and returns the matched records with their dated, source-attributed
evidence reports and related context.

The engine only retrieves stored records. It estimates no probabilities, runs
no simulation, and does not infer impact. It runs locally as an MCP server on
this machine, using only historical data already stored here. A LangChain
application can connect to it later without changing it.

The engine should:

- Accept one or many suppliers in a single request.
- Treat each supplier as the subject of the query. The evidence describes the
  environment around a supplier, so a supplier does not need its own record.
- Match evidence by company name, country, port, carrier, vessel, HS code,
  importing country, or currency, using the rules for each risk type
  (section 7).
- Report data gaps and limitations alongside results.
- Keep retrieved reports separate from any conclusion about impact.

The [evidence dataset plan](./RISK_EVIDENCE_DATASET_PLAN.md) covers how the
records are collected, verified, and reviewed.

## 2. Stored data and its boundaries

The engine's only database is the JSON evidence database in
[supplier_risk_engine/risk_evidence/database/](./supplier_risk_engine/risk_evidence/database/).
It holds one file per risk type, plus a manifest, and 97 evidence records
across 18 risk types. The study window is 2025-01-01 to 2026-09-30.

The engine does not use Neo4j, the combined CSV, or any other store. The
records do not contain:

- A supplier registry. A supplier is never matched to a stored supplier ID.
- Shipments, buyers, products, or port identifiers. The `supplier_ids` and
  `port_ids` fields are empty in every record.
- Parent-company or ownership links, carriers, vessels, ports, or HS codes for a
  supplier. The caller derives these from the Neo4j graph and supplies them in
  the payload (section 6.1). The engine matches them but never queries Neo4j.
- Provenance fields such as `source_file` and `source_row`. Each record has its
  own `source` object with a URL and publisher instead.

Records describe reported events, observations, and rules, not verified impacts
on any supplier. Each record carries its own `verification_status` and
`limitations`, and the engine returns them unchanged.

## 3. Architecture

```text
Caller (LangChain layer, uses Neo4j)
  - BOM line -> vector search on Product.embedding -> candidate products
  - candidate products -> shipments -> suppliers
  - aggregates each supplier's footprint into an exposure profile
             |
             v
Payload: one BOM line, its supplier exposure profiles, as_of_date,
         event_window_days
             |
             v
Supplier risk evidence engine (standalone)
  - validates the payload
  - matches each supplier against the evidence records, by risk type
  - applies dated retrieval
  - returns a structured result with the study window and any validation errors
             ^
             |
Adapters (outside the engine)
  - loader: reads the JSON database and passes records in
  - MCP server: exposes the engine to MCP clients on this machine
  - CLI: for testing and evaluation runs
  - LangChain app (later): calls the MCP server as a client
  - Python import (later): a Python frontend or app calls the engine directly
```

The engine receives records as plain input. It contains no file access, LLM,
MCP, or UI code, so its matching and retrieval logic can be tested with fixed
records.

Evidence `search_window` dates are retrieval aids with an explicit basis, not
necessarily incident start or end dates. The engine must distinguish report,
claim, and approximate dates from verified overlaps, and must surface unknown
event dates rather than treating a search window as proof of impact. Template
placeholders are not evidence.

The `scenario_recovery` field is returned only as stored, labelled with its
scope and anchor. It is not a verified recovery duration, and the engine never
uses it, or any retrieval window, as an impact duration.

The existing [mcp_client.py](./langchain/mcp_client.py) targets an external
Apify service. It is unrelated to this local MCP server.

## 4. Linked context and limits

The engine reports which records are linked to a supplier, and how. It does not
decide that an event affected a supplier.

- **Link basis:** every linked report states its basis: `company_name`,
  `parent_company_name`, `carrier_name`, `vessel_name`, `port_code`,
  `port_name`, `port_country`, `hs_code`, `importing_country`, `currency`, or
  `country_code`. It also states a `link_strength` (`strong`, `medium`, or
  `weak`). A link is relevant context, not evidence of impact.
- **Exposure counts:** the payload's shipment counts for each port, carrier,
  vessel, and HS code are echoed back on the matching link (`matched_exposure`),
  unchanged. The engine never uses them to filter or rank.
- **Parent companies:** a report about a parent company is linked to each
  subsidiary the payload names under it. The link runs one way, from parent to
  child. A report about a subsidiary is not linked to its parent. The caller
  states the ownership; the engine does not verify it or look it up.
- **Country-only links:** labelled as weak. Some risk types do not allow them at
  all (section 7).
- **Shared exposure:** not reported. The records contain no shipment or port
  data, so the engine cannot say that two suppliers share a route or port.
- **Duplicate reports:** records with `related_evidence_ids` describe the same
  incident. Return them together, and do not count them as separate events.
- **Verified links:** the engine cannot show that a supplier used a vessel,
  route, or port, or that a record describes its operations. It returns only the
  name, vessel, or country match.

## 5. Matching and dated retrieval

The engine receives a payload of suppliers and a query date. It matches the
suppliers against the evidence records and returns the linked reports with
their dated context. It makes no external lookups.

### 5.1 Normalisation

Matching compares normalised values for exact equality. There is no fuzzy
scoring.

- **Company, parent-company, carrier, and vessel names:** Unicode case-fold, trim, collapse
  whitespace, remove punctuation, remove bracketed role text such as
  "(charterer)", and remove legal suffixes at the end of the name (for example
  Inc, Ltd, Corp, Co, LLC, Berhad, Bhd, Sdn Bhd, Pte Ltd, GmbH, Plc).
- **List-valued name fields:** split on `;` or `,` before normalising. Ignore
  entries marked `(unnamed)`.
- **Country:** the payload country, given as an ISO 3166-1 alpha-2 code or a
  name, is converted to a code through a reviewed mapping table. An unknown name
  is a validation error. Matching then compares codes only.

Under these rules, "Nexperia" matches "Nexperia Inc." but not "Nexperia
Philippines Inc." (section 5.4, decision 2).

- **Ports (lenient, tiered):** the evidence names ports in free text, and the
  graph uses CBP codes. The evidence dataset is small, so strict matching would
  rarely hit. Each port is tried in order, and the first tier that hits wins:
  1. `port_code` (**strong**): the payload code equals a code on the record.
     This applies only if a record carries a code.
  2. `port_name` (**medium**): the normalised graph port name, with any
     trailing state or province tag dropped ("Long Beach, Ca" becomes "long
     beach"), appears as a whole-word substring of the normalised
     `reported_port`, `location.label`, `location.affected_area`, or
     `border_or_customs_location`. A name made only of generic words ("port",
     "terminal", "pier", "harbour") never matches.
  3. `port_country` (**weak**, location only): the port's country equals the
     record's `country_code`.

  This is deterministic substring containment, not fuzzy scoring.
- **HS codes:** digits only. A record code matches when one code is a prefix of
  the other, with a minimum of 6 digits ("850760" matches "8507.60.00").
- **Currency:** the caller passes the supplier's currency (ISO 4217). It matches
  a record whose `quote_currency` or `base_currency` equals it.

### 5.2 Dated retrieval

Each risk type uses one of four date families, given in section 7. The query
date `as_of_date` and the caller-supplied `event_window_days` apply to each
family as follows.

- **Event interval** (`event_start`, `event_end`): in scope when

      event_start - event_window_days <= as_of_date
          <= (event_end or event_start) + event_window_days

- **Observation point** (`observation_date`): in scope when `as_of_date` is
  within `event_window_days` of `observation_date`.
- **Observation start** (`observation_start`, and `observation_end` where
  present): in scope when `as_of_date` falls within the same expanded interval.
  An open end is treated as the start date.
- **Effective interval** (`effective_from`, `effective_to`): in scope when
  `as_of_date` falls within the expanded interval. An open end is treated as
  unknown, not as indefinite.

A record without its date field is not returned as in scope. If its
`search_window` contains `as_of_date`, it is returned as an undated candidate,
labelled as a retrieval aid rather than an event date.

The window is a retrieval setting. It does not describe how long an event
lasted.

### 5.3 Study window

The engine covers a fixed study window, 2025-01-01 to 2026-09-30. A query with
`as_of_date` outside this window returns no records and no warning.
`event_window_days` is separate: it only sets how far an event's dates may sit
from `as_of_date`.

### 5.4 Open decisions

Agree these before implementation:

1. **Payload keys:** resolved. The caller builds an exposure profile for each
   supplier from the graph (section 6.1). Each request covers one BOM line.
2. **Company-name strictness:** exact equality after normalisation, as proposed,
   means "Nexperia" does not match "Nexperia Philippines Inc.". Is that the
   intended behaviour?
3. **Data fixes needed before some risk types can be matched:**
   - `natural_hazards`: resolved. `location.country_code` now exists.
   - `currency_fluctuations`: resolved by the payload `currency` key.
   - `tariffs_and_duties`: origin and importing country now come from the
     payload. Most records have no commodity code. These link on origin and
     importing country with `link_strength: weak`, labelled "country-wide
     measure; product applicability not established". Records with a code also
     need an `hs_code` match. Check graph `hs_code` precision before
     implementing.
   - `route_chokepoint_disruption`: records with empty `countries` (Red Sea,
     Hormuz, Panama) cannot be linked. Return them once per response as
     unlinked global context.
4. **Country-name mapping:** who reviews the mapping from country names to
   codes?
5. **Required request fields:** confirm that `event_window_days` is required in
   every request, as proposed.
6. **Parent chain:** should the payload carry each parent level, or only the
   ultimate parent? The engine matches every name it receives and does not climb
   the chain itself.

### 5.5 Not in scope

The engine does not estimate probabilities, delays, costs, or impacts. It does
not calculate tariffs, assess financial health, model cascades across tiers, or
infer which shipments were affected by an event. Any of these would be a
separate project with its own plan and its own assumptions.

## 6. Request and response contract

### 6.1 Request

Values are illustrative. The caller builds every supplier key from the graph:

| Payload key | Graph source |
| --- | --- |
| `supplier_id`, `supplier_name`, `country` | `Supplier.supplier_id`, `supplier_name`, `supplier_country_code` |
| `parent_companies` | `(Supplier)-[:SUBSIDIARY_OF]->(ParentCompany).canonical_name` |
| `hs_codes` | `(Shipment)-[:CONTAINS_PRODUCT]->(Product).hs_code` |
| `exit_ports`, `entry_ports` | `DEPARTED_FROM` and `ARRIVED_AT` port names and codes |
| `carriers`, `vessels` | `CARRIED_BY` and `TRANSPORTED_ON` |
| `currency` | the supplier country, through a fixed ISO 4217 table |
| `importing_country` | entry-port or buyer country |
| `shipments`, `footprint_window` | counts and the range of `Shipment.arrival_date` |

```json
{
  "schema_version": "1.1",
  "as_of_date": "2026-09-25",
  "event_window_days": 14,
  "request_context": {
    "bom_line_id": "BOM-001-L3",
    "component_query": "lithium-ion battery pack",
    "importing_country": "US"
  },
  "suppliers": [
    {
      "supplier_id": "S-123",
      "supplier_name": "Supplier A",
      "country": "MY",
      "parent_companies": ["Flex Ltd"],
      "hs_codes":    [{"code": "850760", "shipments": 12}],
      "exit_ports":  [{"name": "Tanjung Pelepas", "code": "00000", "country": "MY", "shipments": 9}],
      "entry_ports": [{"name": "Los Angeles, Ca", "code": "2704", "country": "US", "shipments": 7}],
      "carriers":    [{"name": "Maersk", "code": "MAEU", "shipments": 5}],
      "vessels":     [{"name": "Kyparissia", "shipments": 2}],
      "currency": "MYR",
      "footprint_window": {"first_arrival": "2025-02-03", "last_arrival": "2026-09-01", "shipments": 31}
    }
  ]
}
```

- `as_of_date`: ISO date. Required.
- `event_window_days`: non-negative integer. Required. Returned in the response.
- `request_context`: required. `importing_country` is required. `bom_line_id`
  and `component_query` are echoed back and not matched.
- `suppliers`: non-empty array. Each entry needs `supplier_name`, `country`,
  `parent_companies`, and `currency`. `parent_companies` is a non-empty list of
  parent names, from the nearest parent up to the ultimate parent. If the
  supplier has no parent, the caller passes the supplier's own name.
  `supplier_id` is echoed back and not matched. The list keys (`hs_codes`,
  `exit_ports`, `entry_ports`, `carriers`, `vessels`) are optional. Their
  `shipments` counts are echoed back unchanged.

Two entries with the same normalised name and country are a validation error.

### 6.2 Response

The values below are illustrative. The example assumes the caller has stated
that "Supplier A" is a subsidiary of "Flex Ltd". The engine does not verify that
link. The linked report is the cyberattack claim `CYBER-CLAIM-2026-001`, which is
unverified and has no event date. It is returned as an undated candidate because
`as_of_date` falls within its search window, and its stored limitations are
returned unchanged.

```json
{
  "schema_version": "1.1",
  "status": "completed",
  "as_of_date": "2026-09-25",
  "event_window_days": 14,
  "data_snapshot_id": "illustrative-snapshot",
  "engine_version": "0.1.0",
  "study_window": {"start": "2025-01-01", "end": "2026-09-30"},
  "suppliers": [
    {
      "input": {
        "supplier_name": "Supplier A",
        "country": "MY",
        "parent_companies": ["Flex Ltd"]
      },
      "linked_reports": [
        {
          "risk_type": "cyberattack",
          "evidence_id": "CYBER-CLAIM-2026-001",
          "event_start": null,
          "event_end": null,
          "in_scope_reason": "undated candidate: as_of_date within search_window",
          "link_basis": "parent_company_name",
          "matched_value": "Flex Ltd",
          "link_strength": "strong",
          "matched_exposure": null,
          "verification_status": "unverified_attacker_claim_source_reviewed",
          "limitations": [
            "SOCRadar labels the report alleged and says leak-site claims may not be independently verified or reflect confirmed breaches; a listing does not establish that an attack or breach occurred.",
            "No affected facility, country of incident, service, operational impact, or shipment has been verified."
          ]
        }
      ]
    }
  ],
  "unlinked_context": [],
  "warnings": []
}
```

If `as_of_date` falls outside the study window, the result contains no records
and no warning.

### 6.3 Validation

| Input | Behaviour |
| --- | --- |
| Missing or invalid `as_of_date` | Reject with a specific error. |
| Missing `event_window_days` | Reject. |
| Negative or non-integer `event_window_days` | Reject. |
| Empty `suppliers`, or a missing name, country, or `parent_companies` | Reject. |
| Unrecognised country name or code | Reject. |
| Duplicate supplier entry | Reject. |
| Empty or whitespace-only name, parent, vessel, carrier, or port | Reject. |
| Missing `request_context.importing_country` or supplier `currency` | Reject. |
| Unknown ISO 4217 currency, or a non-digit HS code | Reject. |
| Negative or non-integer `shipments` count | Reject. |
| `as_of_date` outside the study window | Return no records. |

## 7. Fetch rules by risk type

Each risk type has its own fields. The table shows what the engine matches on
for each type, using the payload keys (supplier name, country, vessel name) and
the graph-derived keys in section 6.1. Parent-company names are
matched against the same company-name field as the supplier name, for each risk
type that has one.

Date families are as defined in section 5.2. "Country alone" says whether a
country match is returned without a name, vessel, or carrier match.

| Risk type (file) | Records | Company-name field | Country field | Vessel or carrier field | Date family | Country alone | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Supplier operational disruption (`supplier_operational_disruption.json`) | 1 | `reported_supplier` | `country_code` | none | event interval | allowed, labelled | Single record. `facility` is not matched. |
| Cyberattack (`cyberattack.json`) | 1 | `reported_organisation` | `country_code` | none | event interval | allowed, labelled | The record states the company claim is unverified. |
| Supplier financial distress (`supplier_financial_distress.json`) | 5 | `reported_supplier` | `country_code` | none | observation point | allowed, labelled | `distress_indicator` is not used for ranking. |
| Product quality or compliance (`product_quality_compliance.json`) | 7 | `reported_supplier`, split on `;`, role text removed | `country_code` | none | event interval | allowed, labelled | Product fields are not in the proposed key set. |
| Labour disruption (`labour_disruption.json`) | 4 | `reported_organisation` | `country_code` | none | event interval | allowed, labelled | `location` text is not matched. |
| Natural hazards (`natural_hazards.json`) | 5 | none | `location.country_code` | port name against `location.label` and `location.affected_area` (section 5.1) | event interval | allowed, labelled | |
| Port disruption (`port_disruption.json`) | 7 | none | `country_code` | exit and entry ports against `reported_port`, tiered (section 5.1) | event interval | allowed as `port_country`, weak | |
| Carrier or vessel disruption (`carrier_vessel_disruption.json`) | 6 | none | `country_code`, the incident location | `reported_vessel` (vessel name), `reported_carrier` (carrier, role text removed) | event interval | **not used** | The record states that the country is the incident location, not the vessel's flag or the supplier's country. |
| Route or chokepoint disruption (`route_chokepoint_disruption.json`) | 5 | none | `countries[].country_code` | none | event interval | allowed, labelled | Records with empty `countries` are returned once as unlinked global context. |
| Loss, theft, or damage in transit (`goods_in_transit.json`) | 8 | none | `country_code` | `reported_carrier`, split on `;`, role text removed | event interval | allowed, labelled | `reported_shipment` is not matched. |
| Tariffs and duties (`tariffs_and_duties.json`) | 15 | none | `origin_country_code` = supplier country and `importing_country_code` = `importing_country`, both required | `hs_codes` against `product_classification.code`, where present | effective interval | country pair only, weak, "country-wide measure" | A null origin means global: it matches on importing country alone. |
| Government restrictions (`government_restrictions.json`) | 5 | `reported_organisation` | `affected_countries[]`, `issuing_country_code` | none | effective interval | allowed, labelled | `product_classification` is not in the key set. |
| Border and customs delays (`border_customs_delays.json`) | 6 | none | `country_code` | port name against `border_or_customs_location` (section 5.1) | event interval | allowed, labelled | |
| Geopolitical conflict (`geopolitical_conflict.json`) | 3 | none | `affected_countries[]` | none | event interval | allowed, labelled | `affected_area` text is not matched. |
| Input or material shortage (`input_material_shortage.json`) | 5 | `reported_supplier` | `affected_countries[]` | none | event interval | allowed, labelled | `material` is not in the key set. |
| Energy or transport cost increases (`energy_transport_cost_increase.json`) | 5 | none | `affected_countries[]` | none | observation start | allowed, labelled | Market context, not supplier costs. |
| Supplier or route concentration (`supplier_route_concentration.json`) | 3 | `reported_entities_or_routes`, split into list items, `(unnamed)` ignored | `countries[].country_code` | none | observation start | allowed, labelled | |
| Currency fluctuations (`currency_fluctuations.json`) | 6 | none | none | `currency` against `quote_currency` and `base_currency` | observation start | not applicable | Records with null currencies are skipped. |

### 7.1 Worked example: carrier or vessel disruption

This type is matched on the vessel and carrier, not on the supplier.

1. Normalise the payload's `vessel_names` and compare them with
   `reported_vessel`. For example, "Kyparissia" matches "Kyparissia" in
   `VESSEL-2025-MY-001`.
2. If the payload includes a carrier, normalise it and compare it with
   `reported_carrier`, with role text removed. "Maersk" matches "Maersk
   (charterer)".
3. Apply the event-interval rule (section 5.2) to `event_start` and `event_end`.
4. Return the linked report with its `link_basis` (`vessel_name` or
   `carrier_name`) and its stored limitations.
5. Do not link the record by country. The country is where the incident was
   reported, not where the vessel is registered or where the supplier operates.

## 8. Interfaces and integration

These names are proposed, not an existing API.

### 8.1 Core function

```python
result = lookup_suppliers(payload, records)
```

Every interface below is a thin adapter around this function. The adapters
contain no matching or retrieval logic, so every adapter gives the same result
for the same payload and records. The request (section 6.1) and the response
(section 6.2) are plain JSON, so any adapter can send them unchanged.

### 8.2 Operations

Each adapter exposes the same three operations:

| Operation | Input | Returns |
| --- | --- | --- |
| `lookup_suppliers` | the payload (section 6.1) | linked reports for each supplier (section 6.2) |
| `get_evidence` | `evidence_id` | the full stored record, with its source, limitations, and related IDs |
| `describe_database` | none | the study window, risk types and record counts, data snapshot ID, and engine version |

`lookup_suppliers` returns compact links. `get_evidence` lets a caller (an LLM,
a user in a frontend, or an evaluation script) open the stored record behind
any cited `evidence_id`.

### 8.3 Adapters

| Adapter | Status | Use |
| --- | --- | --- |
| CLI | in scope | Testing and evaluation runs. `query <payload.json> --out <result.json>` runs one payload. `run-all <dir> --out <dir>` runs a batch. `evidence <id>` and `describe` cover the other two operations. |
| MCP server (stdio, local) | in scope | Used by the LangChain app as a client. The three operations are exposed as MCP tools. It can also be registered in `.vscode/mcp.json` for manual checks. |
| Python import | available by design | A Python app (the LangChain app, or a Streamlit or Gradio frontend) can import `lookup_suppliers`, `get_evidence`, and `describe_database` and call them directly. No server is needed. |

The engine has no HTTP endpoint of its own. The interactive frontend talks to
the LangChain app, never to the engine. The app reaches the engine through MCP
or a direct import:

- With a Python frontend (for example Streamlit, which can also draw the Neo4j
  graph view), everything runs in one process and needs no endpoint.
- A browser (JavaScript) frontend would need HTTP, but on the LangChain app's
  backend, not on the engine. If an HTTP connection to the engine is ever
  needed, the same MCP server can switch to MCP's Streamable HTTP transport, so
  no separate REST API is needed.

So that any of these callers works without changing the engine:

- Request and response models are defined once, in the engine package, and
  serialise to JSON. Adapters do not reshape them.
- The response echoes the caller's stable identifiers unchanged:
  `supplier_id`, `bom_line_id`, and the port and carrier codes in
  `matched_exposure`. The frontend can use them to open the matching Neo4j
  nodes in a graph view. The engine itself never reads Neo4j.
- Validation errors are returned as structured objects (`field`, `code`,
  `message`), not as raw exceptions, so each adapter can map them to its own
  error format: CLI exit codes, MCP tool errors, or Python exceptions.
- The engine keeps no state between calls. Records are loaded once by the
  loader and passed in.

### 8.4 Later work, outside the engine

- **LangChain app:** connects to the MCP server as a client and passes the
  returned records to the LLM for explanation. The LLM may explain returned
  records, but must not add facts that are not in them.
- **Frontend:** talks to the LangChain app. It shows the engine's evidence
  alongside a Neo4j graph view, using the echoed `supplier_id` and port and
  carrier codes to link the two views.

No remote or hosted servers, and no live data sources, are planned.

## 9. Implementation phases

1. **Verify stored records.** Check the fields, IDs, and dates in each risk file
   against section 7, and confirm that every date falls within the study window.
2. **Write fixture payloads.** Hand-write one payload for each supplier in
   `data/raw_yeti_response/`, using the real ports, carriers, vessels, and HS
   codes from those files. Pair each payload with the `evidence_id`s it is
   expected to return (`examples/expected_ids.json`). These fixtures serve as
   test input and as the retrieval gold set (section 10). The future graph stage
   only has to produce the same JSON shape.
3. **Implement the engine.** Add typed payload and result models, structured
   validation errors, normalisation (including tiered port matching), matching
   for each risk type, and dated retrieval. Output must be deterministic for the
   same payload and records.
4. **Test with fixed records.** Cover exact and near-miss names, role text,
   list-valued fields, unnamed entries, country-name conversion, parent-company
   links in one direction only, the three port tiers, HS-code prefixes,
   currency, country-only links for each risk type, the carrier/vessel
   no-country rule, and window boundaries (on the start, on the end, and one day
   outside). Also cover open end dates, undated candidates, dates outside the
   study window, invalid input, and repeated runs producing identical output.
5. **Add the loader and CLI.** The loader reads the JSON database and computes
   the data snapshot ID. The CLI exposes the three operations from section 8.2
   and runs the fixture batch.
6. **Add the MCP server.** Expose the same three operations as MCP tools.
7. **Later, outside this scope:** the LangChain app and its frontend
   (section 8.4).

Proposed layout:

```text
supplier_risk_engine/
  engine/        models.py, validate.py, normalise.py, match.py, dates.py, lookup.py
  loader.py      reads risk_evidence/database/, computes the snapshot ID
  cli.py
  mcp_server.py
  examples/      fixture payloads and expected_ids.json
  tests/
```

## 10. Evaluation and limitations

- Test matching, normalisation, date handling, and linking against fixed records
  with known answers.
- Measure retrieval against the fixture gold set (`examples/expected_ids.json`):
  report missed and unexpected `evidence_id`s for each fixture.
- Record the data snapshot fingerprint and engine version in every result.
- Check that every returned fact traces to a stored record and its source. Any
  LLM explanation added later should be checked against the returned records.
- Never infer a verified route, supplier capacity, financial exposure, or
  current event from a name, vessel, or country match.
