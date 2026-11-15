# Supplier risk evidence engine plan

Status: **draft for discussion**. This document proposes an implementation; it
does not describe an existing engine. Examples and values are illustrative,
not findings.

## 1. Goal and scope

Build a reproducible Python engine that receives a payload of suppliers (name
and country) and a query date, finds the stored evidence that could affect each
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
- Match evidence by company name, country, or vessel name, using the rules for
  each risk type (section 7).
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
- Parent-company or ownership links. Parent names are supplied in the payload
  (section 6.1), not stored in the records.
- Provenance fields such as `source_file` and `source_row`. Each record has its
  own `source` object with a URL and publisher instead.

Records describe reported events, observations, and rules, not verified impacts
on any supplier. Each record carries its own `verification_status` and
`limitations`, and the engine returns them unchanged.

## 3. Architecture

```text
Payload: suppliers, as_of_date, event_window_days
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
  - LangChain app (later): calls the MCP server as a client
  - CLI: for testing
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
  `parent_company_name`, `carrier_name`, `vessel_name`, or `country_code`. A link
  is relevant context, not evidence of impact.
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

1. **Payload keys:** the proposed supplier keys are `supplier_name`, `country`,
   and `parent_companies` (required), plus optional `vessel_names`. Carrier matching for `carrier_vessel_disruption`
   and `goods_in_transit` needs a carrier key too. Should it be an optional
   `carrier_names`?
2. **Company-name strictness:** exact equality after normalisation, as proposed,
   means "Nexperia" does not match "Nexperia Philippines Inc.". Is that the
   intended behaviour?
3. **Data fixes needed before some risk types can be matched:**
   - `natural_hazards`: add a `country_code` to each record. Only `location`
     text exists now.
   - `currency_fluctuations`: has no country or company field. Add a currency
     key to the payload, or leave this risk type unmatched.
   - `tariffs_and_duties`: needs product classification and importing country.
     The dataset README says supplier country alone does not establish tariff
     applicability, so leave this type unmatched until those keys exist.
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

```json
{
  "schema_version": "1.0",
  "as_of_date": "2026-09-25",
  "event_window_days": 14,
  "suppliers": [
    {
      "supplier_name": "Supplier A",
      "country": "MY",
      "parent_companies": ["Flex Ltd"]
    }
  ]
}
```

- `as_of_date`: ISO date. Required.
- `event_window_days`: non-negative integer. Required. Returned in the response.
- `suppliers`: non-empty array. Each entry needs `supplier_name`, `country`, and
  `parent_companies`. `parent_companies` is a non-empty list of parent names,
  from the nearest parent up to the ultimate parent. If the supplier has no
  parent, the caller passes the supplier's own name. `vessel_names` is optional.

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
  "schema_version": "1.0",
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
          "verification_status": "unverified_attacker_claim_source_reviewed",
          "limitations": [
            "SOCRadar labels the report alleged and says leak-site claims may not be independently verified or reflect confirmed breaches; a listing does not establish that an attack or breach occurred.",
            "No affected facility, country of incident, service, operational impact, or shipment has been verified."
          ]
        }
      ]
    }
  ],
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
| Empty or whitespace-only name, parent, vessel, or carrier | Reject. |
| `as_of_date` outside the study window | Return no records. |

## 7. Fetch rules by risk type

Each risk type has its own fields. The table shows what the engine matches on
for each type, using the payload keys (supplier name, country, vessel name) and
the optional carrier key proposed in section 5.4. Parent-company names are
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
| Natural hazards (`natural_hazards.json`) | 5 | none | none. `location` is free text. | none | event interval | not possible | Add `country_code` to each record before country matching (section 5.4). |
| Port disruption (`port_disruption.json`) | 7 | none | `country_code` | none | event interval | allowed, labelled as location | `reported_port` is not in the key set. |
| Carrier or vessel disruption (`carrier_vessel_disruption.json`) | 6 | none | `country_code`, the incident location | `reported_vessel` (vessel name), `reported_carrier` (carrier, role text removed) | event interval | **not used** | The record states that the country is the incident location, not the vessel's flag or the supplier's country. |
| Route or chokepoint disruption (`route_chokepoint_disruption.json`) | 5 | none | `countries[].country_code` | none | event interval | allowed, labelled | `route_or_chokepoint` text is not in the key set. |
| Loss, theft, or damage in transit (`goods_in_transit.json`) | 8 | none | `country_code` | `reported_carrier` | event interval | allowed, labelled | `reported_shipment` is not matched. |
| Tariffs and duties (`tariffs_and_duties.json`) | 15 | none | `origin_country_code`, `importing_country_code` | none | effective interval | **not used** | Needs product and importing-country keys (section 5.4). Unmatched until then. |
| Government restrictions (`government_restrictions.json`) | 5 | `reported_organisation` | `affected_countries[]`, `issuing_country_code` | none | effective interval | allowed, labelled | `product_classification` is not in the key set. |
| Border and customs delays (`border_customs_delays.json`) | 6 | none | `country_code` | none | event interval | allowed, labelled | `border_or_customs_location` is not matched. |
| Geopolitical conflict (`geopolitical_conflict.json`) | 3 | none | `affected_countries[]` | none | event interval | allowed, labelled | `affected_area` text is not matched. |
| Input or material shortage (`input_material_shortage.json`) | 5 | `reported_supplier` | `affected_countries[]` | none | event interval | allowed, labelled | `material` is not in the key set. |
| Energy or transport cost increases (`energy_transport_cost_increase.json`) | 5 | none | `affected_countries[]` | none | observation start | allowed, labelled | Market context, not supplier costs. |
| Supplier or route concentration (`supplier_route_concentration.json`) | 3 | `reported_entities_or_routes`, split into list items, `(unnamed)` ignored | `countries[].country_code` | none | observation start | allowed, labelled | |
| Currency fluctuations (`currency_fluctuations.json`) | 6 | none | none | none | observation start | not possible | No country or company field. Needs a currency key (section 5.4). |

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

These names are proposed, not an existing API:

```python
result = lookup_suppliers(payload, records)
```

- **MCP server:** the local interface. It exposes `lookup_suppliers` as an MCP
  tool, reads the stored records, and calls the same function. It contains no
  matching or retrieval logic of its own.
- **CLI:** reads a payload file, prints the result with its warnings, and can
  save the full JSON result. Used for testing without an MCP client.
- **LangChain app (later):** connects to the local MCP server as a client and
  passes the returned records to the LLM for explanation. The LLM may explain
  returned records but must not add facts that are not in them.

No remote servers, hosted web API, or live data sources are planned.

## 9. Implementation phases

1. **Verify stored records.** Check the fields, IDs, and dates in each risk file
   against section 7, and confirm every date falls within the study window.
   Confirm the data fixes listed in section 5.4.
2. **Settle open decisions.** Resolve section 5.4, including the payload keys,
   company-name strictness, and the country-name mapping.
3. **Implement the engine.** Add typed payload and result models, validation,
   normalisation, per-type matching, and dated retrieval.
   Output must be deterministic for the same payload and records.
4. **Test with fixed records.** Cover exact and near-miss names, role text,
   list-valued fields, unnamed entries, country-name conversion, parent-company
   links in one direction only, country-only links for each type, the carrier/vessel no-country rule, window boundaries (on
   the start, on the end, and one day outside), open end dates, undated
   candidates, dates outside the study window, invalid input, and repeated runs producing
   identical output.
5. **Connect the application layer.** Add a loader for the JSON database, the MCP
   server, and the CLI. Record the data snapshot and engine version in each
   result.
6. **Connect the LangChain app.** Separate work, planned after the engine and its
   MCP server are tested. The app connects to the MCP server as a client and
   uses the returned records unchanged.

## 10. Evaluation and limitations

- Test matching, normalisation, date handling, and linking against fixed records
  with known answers.
- Record the data snapshot fingerprint and engine version in every result.
- Check that every returned fact traces to a stored record and its source. Any
  LLM explanation added later should be checked against the returned records.
- Never infer a verified route, supplier capacity, financial exposure, or
  current event from a name, vessel, or country match.
