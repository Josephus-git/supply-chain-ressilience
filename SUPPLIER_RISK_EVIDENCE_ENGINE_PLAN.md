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
no simulation, and does not infer impact. It runs locally on this machine,
called through a CLI or a direct Python import, using only historical data
already stored here. A LangChain application can import it later without
changing it.

The engine simulates a real-time decision. `as_of_date` is the simulated
"today": the engine returns only evidence that was known on that date
(section 5.2), never later reports of events that had not yet happened.

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
  - CLI: for testing and evaluation runs
  - LangChain app (later): imports the engine directly (no server)
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
Apify service. It is unrelated to this engine.

## 4. Linked context and limits

The engine reports which records are linked to a supplier, and how. It does not
decide that an event affected a supplier.

- **Link basis:** every linked report states its basis: `company_name`,
  `parent_company_name`, `buyer_name`, `carrier_name`, `vessel_name`,
  `port_code`, `port_name`, `port_country`, `hs_code`, `importing_country`,
  `currency`, `trade_lane`, or `country_code`. It also states a `link_strength` (`strong`, `medium`, or
  `weak`). A link is relevant context, not evidence of impact.
- **Approximated fields:** some records hold analyst-approximated values,
  listed in the record's `approximations` field with a `basis`. A link made
  through an approximated field is always `weak`. It is returned with
  `"approximated": true` and the stored basis. Approximated values that are
  marked informational only are never used to link.
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
  Links are treated as two-way. 12 links are stored in one direction only. When
  the loader reads the records, it groups them into incident groups using the
  union of both directions, and the data files stay unchanged.
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
- **Buyers:** the caller may pass the buyers a supplier ships to. Buyer names
  are normalised like company names and compared with `reported_organisation`
  on currency records.
- **Trade lanes:** a lane matches when the supplier's country is in
  `origin_country_codes`, `request_context.importing_country` equals
  `destination_country_code`, and at least one payload entry port has a
  `coast` equal to `destination_coast`. If no entry port carries `coast`, no
  lane link is made.

### 5.2 Dated retrieval

Each risk type uses one of four date families, given in section 7. The query
date `as_of_date` and the caller-supplied `event_window_days` apply to each
family as follows.

The window looks back only. A record is in scope from the date it became
known, and stays in scope for `event_window_days` after its end, so the
after-effects of an event (for example a hurricane) stay visible. Nothing is
returned before it is known: the engine never warns about an event that has
not yet happened (decided 2026-11-15; implemented in phase 6, section 9).

A record that becomes known only after its end (a late report, such as an
annual report on a finished financial year) stays in scope for
`event_window_days` from `known_from` instead, so every family's upper bound
is `max(end, known_from) + event_window_days`. This only reaches forwards
from the date the record became known, so it adds no look-ahead (decided
2026-11-15). Such reports are labelled
`"dated: known after its end date; ..."`.

- **Event interval** (`event_start`, `event_end`): in scope when

      known_from <= as_of_date <= (event_end or event_start) + event_window_days

- **Observation point** (`observation_date`): in scope when
  `known_from <= as_of_date <= observation_date + event_window_days`.
- **Observation start** (`observation_start`, and `observation_end` where
  present): in scope under the same rule as an event interval. An open end is
  treated as the start date.
- **Effective interval** (`effective_from`, `effective_to`): in scope when
  `known_from <= as_of_date <= effective_to + event_window_days`. When `effective_to` is null,
  the record is treated as in force until the study end (2026-09-30), which
  matches its `study_period_bound` search window. It is labelled
  `"open_end": "no end date recorded; continued force not verified"`. This
  applies to 6 tariffs and all 5 government restrictions. Event and observation
  families keep the rule that an open end equals the start date.

A record without its date field is not returned as in scope. If its
`search_window` contains `as_of_date` and it is known by `as_of_date`, it is
returned as an undated candidate, labelled as a retrieval aid rather than an
event date. If it became known only after its search window ended, it is an
undated candidate for `event_window_days` from `known_from` instead (the
late-report rule above).

**When a record becomes known (`known_from`):**

1. A record with a start date (`event_start`, `observation_date`,
   `observation_start`, or `effective_from`) is known from that date. A
   sudden public event, such as a hurricane, is known as it happens, even if
   the report about it was published days later.
2. A record without a start date is known from its publication date
   (`source.published_at`), the only evidence of when anyone knew.
3. A record may store its own `known_from`, recorded with its basis in
   `approximations`. It overrides rules 1 and 2 in two cases:
   - announced in advance: a tariff or restriction announced before it takes
     effect is known from the announcement;
   - disclosed later: an onset that was not public when it happened (for
     example a cyberattack disclosed later, or a financial figure that exists
     only once reported) is known from the disclosure.

Each returned report states its `known_from` and which rule set it.

The window is a retrieval setting. It does not describe how long an event
lasted.

### 5.3 Study window

The engine covers a fixed study window, 2025-01-01 to 2026-09-30. A query with
`as_of_date` outside this window returns no records and no warning.
`event_window_days` is separate: it only sets how long after an event's end
the event stays in scope.

A record needs only to overlap the study window, not to sit entirely inside it.
Its dates are returned as stored. For example, `CONCENTRATION-2025-MY-VS-001`
covers VS Industry's financial year, 2024-08-01 to 2025-07-31. Search windows
that run past 2026-09-30 are allowed, since `as_of_date` cannot exceed the
study end.

### 5.4 Open decisions

Agree these before implementation (all are resolved):

1. **Payload keys:** resolved. The caller builds an exposure profile for each
   supplier from the graph (section 6.1). Each request covers one BOM line.
2. **Company-name strictness:** resolved on 2026-11-15. Names match only on
   exact equality after normalisation, so "Nexperia" does not match "Nexperia
   Philippines Inc.". Looser matching would attach other companies' evidence
   to a supplier.
3. **Data fixes needed before some risk types can be matched:**
   - `natural_hazards`: resolved. `location.country_code` now exists.
   - `currency_fluctuations`: resolved by the payload `currency` key.
   - `tariffs_and_duties`: origin and importing country now come from the
     payload. Most records have no commodity code. These link on origin and
     importing country with `link_strength: weak`, labelled "country-wide
     measure; product applicability not established". Records with a code also
     need an `hs_code` match. Check graph `hs_code` precision before
     implementing.
   - `route_chokepoint_disruption`: resolved by approximated `trade_lanes`
     (Suez, Panama) and an approximated country (Hormuz), with the
     `approximations` field recording the basis for each.
4. **Country-name mapping:** resolved on 2026-11-15. The graph stores an ISO
   alpha-2 code beside every country name (supplier, supplier address, buyer
   and vessel), so the caller sends codes (section 6.1). The name table in
   `engine/reference.py` is kept as a fallback and was reviewed against the
   graph CSVs (`data/processed/*_shipments_clean.csv`). Their nine names
   all convert to the code stored beside them, after "Portugal" was added,
   and a test checks this on every run. An unknown name is still rejected.
   Data note: one Ihastek Malaysia Sdn Bhd shipment has `supplier_country`
   "Portugal" with address country MY, which looks like a source error. It
   does not reach the engine, because the payload uses the supplier node's
   single country code.
5. **Required request fields:** resolved on 2026-11-15. `as_of_date` and
   `event_window_days` are required in every request: the date is what
   decides which evidence is returned.
6. **Parent chain:** resolved on 2026-11-15. The graph stores one ultimate
   parent per supplier and no intermediate parents, so the payload carries
   that one name. The engine matches every name it receives and does not climb
   a chain, so a longer list would still work.

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
| `buyers` | `(Shipment)-[:CONSIGNED_TO]->(Buyer).buyer_name`, with shipment counts |
| `entry_ports[].coast` | US entry ports only: `east_gulf` when `entry_port_lon` > -100, otherwise `west` |
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
      "entry_ports": [{"name": "Los Angeles, Ca", "code": "2704", "country": "US", "coast": "west", "shipments": 7}],
      "buyers":      [{"name": "Dyson Inc", "shipments": 31}],
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
- Countries: send ISO alpha-2 codes, taken from the graph's `*_country_code`
  properties. Names are accepted only through the fallback table (decision
  4, section 5.4), and an unknown name is rejected.
- `request_context`: required. `importing_country` is required. `bom_line_id`
  and `component_query` are echoed back and not matched.
- `suppliers`: non-empty array. Each entry needs `supplier_name`, `country`,
  `parent_companies`, and `currency`. `parent_companies` is a non-empty list of
  parent names. The graph has one ultimate parent per supplier, so the list
  normally holds that one name. If the supplier has no parent, the caller
  passes the supplier's own name.
  `supplier_id` is echoed back and not matched. The list keys (`hs_codes`,
  `exit_ports`, `entry_ports`, `carriers`, `vessels`, `buyers`) are optional. Their
  `shipments` counts are echoed back unchanged.

Two entries with the same normalised name and country are a validation error.

### 6.2 Response

The values below are illustrative. The example assumes the caller has stated
that "Supplier A" is a subsidiary of "Flex Ltd". The engine does not verify that
link. The linked report is the cyberattack claim `CYBER-CLAIM-2026-001`, which is
unverified and has no event date. It is returned as an undated candidate because
`as_of_date` falls within its search window and on or after its `known_from`
(here its publication date, rule 2 in section 5.2). Its stored limitations are
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
          "known_from": "2026-09-21",
          "known_from_rule": "source_published_at",
          "in_scope_reason": "undated candidate: as_of_date within search_window and on or after known_from",
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
| Route or chokepoint disruption (`route_chokepoint_disruption.json`) | 5 | none | `countries[].country_code` | `trade_lanes` against supplier country, importing country, and entry-port coast (section 5.1) | event interval | allowed, labelled | Suez and Panama link by approximated lane; Hormuz by approximated country (SG). All are weak. |
| Loss, theft, or damage in transit (`goods_in_transit_loss_theft_or_damage.json`) | 8 | none | `country_code` | `reported_carrier`, split on `;`, role text removed | event interval | allowed, labelled | `reported_shipment` is not matched. |
| Tariffs and duties (`tariffs_and_duties.json`) | 15 | none | `origin_country_code` = supplier country and `importing_country_code` = `importing_country`, both required | `hs_codes` against `product_classification.code`, where present | effective interval | country pair only, weak, "country-wide measure" | A null origin means global: it matches on importing country alone. |
| Government restrictions (`government_restrictions.json`) | 5 | `reported_organisation` | `affected_countries[]`, `issuing_country_code` | none | effective interval | allowed, labelled | `product_classification` is not in the key set. |
| Border and customs delays (`border_customs_delays.json`) | 6 | none | `country_code` | port name against `border_or_customs_location` (section 5.1) | event interval | allowed, labelled | |
| Geopolitical conflict (`geopolitical_conflict.json`) | 3 | none | `affected_countries[]` | none | event interval | allowed, labelled | `affected_area` text is not matched. |
| Input or material shortage (`input_material_shortage.json`) | 5 | `reported_supplier` | `affected_countries[]` | none | event interval | allowed, labelled | `material` is not in the key set. |
| Energy or transport cost increases (`energy_or_transport_cost_increase.json`) | 5 | none | `affected_countries[]` | none | observation start | allowed, labelled | Market context, not supplier costs. |
| Supplier or route concentration (`supplier_or_route_concentration.json`) | 3 | `reported_entities_or_routes`, split into list items, `(unnamed)` ignored | `countries[].country_code` | none | observation start | allowed, labelled | |
| Currency fluctuations (`currency_fluctuations.json`) | 6 | `reported_organisation` against payload `buyers` (`buyer_name`) | `country_code` is informational only, never linked | `currency` against `quote_currency` and `base_currency` | observation start | not applicable | The Dyson record has no currencies and links only by buyer name. |

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
| Python import | in scope | The LangChain app (and a Streamlit or Gradio frontend) imports `lookup_suppliers`, `get_evidence`, and `describe_database` and calls them directly. No server is needed. |
| MCP server | dropped on 2026-11-15 | Not needed: the LangChain app is Python and imports the engine. It would only help an assistant outside the app (for example in VS Code), which this research does not need. It can be added later as a thin adapter without changing the engine. |

The engine has no HTTP endpoint of its own. The interactive frontend talks to
the LangChain app, never to the engine. The app reaches the engine through a
direct import:

- With a Python frontend (for example Streamlit, which can also draw the Neo4j
  graph view), everything runs in one process and needs no endpoint.
- A browser (JavaScript) frontend would need HTTP, but on the LangChain app's
  backend, not on the engine.

So that any of these callers works without changing the engine:

- Request and response models are defined once, in the engine package, and
  serialise to JSON. Adapters do not reshape them.
- The response echoes the caller's stable identifiers unchanged:
  `supplier_id`, `bom_line_id`, and the port and carrier codes in
  `matched_exposure`. The frontend can use them to open the matching Neo4j
  nodes in a graph view. The engine itself never reads Neo4j.
- Validation errors are returned as structured objects (`field`, `code`,
  `message`), not as raw exceptions, so each adapter can map them to its own
  error format: CLI exit codes or Python exceptions.
- The engine keeps no state between calls. Records are loaded once by the
  loader and passed in.

### 8.4 Later work, outside the engine

- **LangChain app:** the user submits a BOM; the app finds the suppliers in
  Neo4j, builds the payload, and runs `lookup_suppliers` once with the
  simulated `as_of_date`. The LLM explains the returned records and must not
  add facts that are not in them.
  - The LLM never chooses or changes `as_of_date`, and cannot rerun the lookup
    for another date: that would break the real-time simulation.
  - It gets read-only tools over the direct import: `get_evidence` (open a
    cited record's source, limitations, and related records) and
    `describe_database`.
- **Frontend:** talks to the LangChain app. It shows the engine's evidence
  alongside a Neo4j graph view, using the echoed `supplier_id` and port and
  carrier codes to link the two views.

No remote or hosted servers, and no live data sources, are planned.

## 9. Implementation phases

1. **Verify stored records.** Done on 2026-11-15, read-only.
   - Passed: all 18 files and 97 records match the section 7 counts; IDs are
     unique; every related ID resolves; dates are ISO and correctly ordered;
     source, verification status, limitations, and search window are present;
     country and currency codes are valid; manifest sha256 values match.
   - Decisions taken: open-ended effective intervals run to the study end
     (section 5.2); related links are two-way (section 4); records need only
     overlap the study window (section 5.3).
   - Coverage limits to state in the evaluation:
     - 27 of 97 records have no event date and can only be returned as
       undated candidates.
     - All 5 government restrictions have an empty `reported_organisation`,
       so they link by country only.
     - `CYBER-CLAIM-2026-001` has no country, so it links by name only.
     - 4 records could never be returned. On 2026-11-15, approximated fields
       were added, each recorded in `approximations` with its basis:
       - `FX-2025-DYSON-QUALITATIVE-001`: `reported_organisation` "Dyson"
         (taken from the source) and an informational country (SG). It links
         through payload `buyers`.
       - Suez and Panama: `trade_lanes`.
       - Hormuz: `countries` set to SG.
       The manifest sha256 values and coverage gaps were updated.
     - The manifest `snapshot_id` is null, so the loader computes it.
2. **Write fixture payloads.** Hand-write one payload for each supplier in
   `data/raw_yeti_response/`, using the real ports, carriers, vessels, and HS
   codes from those files. Pair each payload with the `evidence_id`s it is
   expected to return (`examples/expected_ids.json`). These fixtures serve as
   test input and as the retrieval gold set (section 10). The future graph stage
   only has to produce the same JSON shape.
   - Done on 2026-11-15, as a draft gold set. There are 18 payloads, one for
     each graph `Supplier` node, in `examples/payloads/`, built by
     `examples/build_payloads.py` from the cleaned CSVs the graph is loaded
     from. Supplier country and parent are copied from the graph, and every
     count matches the graph.
   - Each fixture's `as_of_date` is chosen to exercise specific records, and
     `expected_ids.json` records the reason. It also lists near-miss
     exclusions and the rule interpretations used. 43 of 97 records are
     expected in at least one fixture.
   - Graph data the caller must handle: HS and port codes are stored as
     integers and lose leading zeros. Carrier names carry a SCAC prefix. Ports
     have no country, so exit-port country comes from the Schedule K prefix.
     `supplier_country_code` sometimes differs from the shipment country, for
     example CN or HK for Malaysian entities.
   - Rule readings agreed on 2026-11-15. Phase 3 must implement them:
     - The `port_country` tier applies to natural hazards and border/customs
       delays as well as port disruption.
     - Only records that link on their own are returned. Related records are
       listed by ID and are not pulled in.
     - Undated candidates use the stored `search_window` without
       `event_window_days`.
     - Payloads carry the supplier's full shipment footprint. Shipments after
       `as_of_date` are not removed, because the engine never filters on
       them.
3. **Implement the engine.** Add typed payload and result models, structured
   validation errors, normalisation (including tiered port matching), matching
   for each risk type, and dated retrieval. Output must be deterministic for the
   same payload and records.
   - Done on 2026-11-15 in `supplier_risk_engine/engine/` (standard library
     only). All 18 fixtures return exactly their `expected_ids`, with the
     expected link basis, strength, matched values, and date status. Repeated
     runs give identical output.
   - Choices made where the plan was silent (review in phase 4):
     - Strengths: currency `medium` (as the gold set has it), carrier name
       `medium`, HS-code tariff link `medium`, buyer and vessel `strong`.
     - When two bases have the same strength, the main basis follows a fixed
       order (`reference.BASIS_PRIORITY`). Every link is still returned in
       `links`.
     - Name punctuation: dots and apostrophes are deleted ("V.S." becomes
       "vs"); other punctuation becomes a space.
     - Approximated values whose stored `basis` says "informational only" are
       never used to link.
     - `data_snapshot_id` falls back to a hash of the records passed in until
       the loader (phase 5) supplies one.
     - The country-name table was a draft, pending decision 4 (section 5.4).
       Resolved on 2026-11-15: codes first, with the table as a reviewed
       fallback.
     - `unlinked_context` is always empty.
4. **Test with fixed records.** Cover exact and near-miss names, role text,
   list-valued fields, unnamed entries, country-name conversion, parent-company
   links in one direction only, the three port tiers, HS-code prefixes,
   currency, country-only links for each risk type, the carrier/vessel
   no-country rule, and window boundaries (on the start, on the end, and one day
   outside). Also cover open end dates, undated candidates, dates outside the
   study window, invalid input, and repeated runs producing identical output.
   - Done on 2026-11-15 in `supplier_risk_engine/tests/`: 115 tests, all
     passing, standard library `unittest` only (pytest is optional). Run from
     the repository root with
     `python -m unittest discover -s supplier_risk_engine/tests -t .`.
     - `test_normalise.py`, `test_dates.py`, `test_validate.py`, and
       `test_matching.py` use synthetic records, so each rule is tested on
       its own. `test_gold_fixtures.py` runs the 18 fixtures against
       `expected_ids.json` (IDs, basis, strength, matched values, date
       status, exclusions), plus determinism and the other two operations.
     - `tests/helpers.py` has a minimal database reader that stands in for
       the phase 5 loader.
     - The phase 3 choices listed above are now fixed by tests, so changing
       one means changing its test.
5. **Add the loader and CLI.** The loader reads the JSON database and computes
   the data snapshot ID. The CLI exposes the three operations from section 8.2
   and runs the fixture batch.
   - Done on 2026-11-15: `supplier_risk_engine/loader.py`,
     `supplier_risk_engine/cli.py`, and `__main__.py` (standard library only).
     `tests/test_loader.py` and `tests/test_cli.py` bring the suite to 142
     tests, all passing. `tests/helpers.py` now reads records through the
     loader.
   - Loader checks: every file parses, is named `<risk_type>.json` after the
     `risk_type` it holds, and has a `records` list; evidence IDs are unique;
     each file's sha256 equals `manifest.json`; the manifest and the directory
     list the same files. Parse, name, and shape errors always fail.
   - Three files were renamed to match their `risk_type`:
     `energy_or_transport_cost_increase.json`,
     `goods_in_transit_loss_theft_or_damage.json`, and
     `supplier_or_route_concentration.json`. Their contents and sha256 values
     are unchanged. The manifest paths and the gold set's `manifest_sha256`
     were updated. Hash and file-list mismatches fail unless `verify=False`
     (`--no-verify`), which turns them into warnings.
   - Snapshot ID: the manifest's `snapshot_id` when every entry sets the same
     value. Otherwise `db-sha256:` plus 16 hex characters of a sha256 over the
     sorted `file name:file sha256` lines, so it changes whenever a stored
     file changes. It replaces the engine's records-hash fallback in every
     result.
   - CLI, run as `python -m supplier_risk_engine [--database DIR]
     [--no-verify] <command>`:
     - `query <payload.json> [--out FILE]` (stdout by default).
     - `run-all <dir> --out <dir> [--expected expected_ids.json]` writes one
       result per payload plus `_summary.json`. With `--expected`, it reports
       missed and unexpected IDs for each fixture, with totals, recall, and
       precision (section 10). It warns if the gold set's `manifest_sha256`
       differs from the current manifest.
     - `evidence <id>` and `describe`. `describe` adds the database path, the
       snapshot source, and the file hashes.
     - Exit codes: 0 success; 1 a payload was rejected, an ID was not found,
       or the batch differs from the gold set; 2 usage, file, or database
       errors.
   - Fixture batch:
     `python -m supplier_risk_engine run-all supplier_risk_engine/examples/payloads --out <dir> --expected supplier_risk_engine/examples/expected_ids.json`
     passes 18 of 18 fixtures, with 0 missed and 0 unexpected IDs.
6. **Apply the known-from rule (no look-ahead).** Replaces the MCP server
   phase, which was dropped on 2026-11-15 (section 8.3). Implement section
   5.2 as decided on 2026-11-15:
   - Why: `as_of_date` is the simulated "today". Before this phase the window
     also ran forwards, so events that had not yet started were returned. In
     the gold fixtures, 5 results across 3 records start after `as_of_date`:
     `PORT-2025-MY-PTP-001`, `FINANCE-2026-MY-VS-001` (in 3 fixtures), and
     `TARIFF-2025-US-CN-OPIOID-20`. Five undated candidates were also
     returned before their publication date, for example
     `CUSTOMS-2026-PH-001`.
   - Engine: drop the forward part of `event_window_days`; compute
     `known_from` (rules 1 to 3) and return it with its rule in each report.
     `event_window_days` stays required and still extends past the end of an
     event, for after-effects.
   - Data: review the tariff, restriction, cyberattack, and financial
     records, and add `known_from` with its basis in `approximations` where
     the default is wrong (announced earlier, or disclosed later). For
     example, the opioid tariff was announced before it took effect on
     2025-03-04. Refresh the manifest sha256 values.
   - Check: 25 records have no `source.published_at`. Any of them that also
     has no start date needs a `known_from` or another stored report date.
   - Gold set: recheck every fixture, update `expected_ids.json` and its
     `manifest_sha256`, and record each change with its reason. Then update
     the tests and the section 6.2 example.
   - Done on 2026-11-15. `engine/dates.py` computes `known_from` and checks
     `known_from <= as_of_date <= end + event_window_days`. Each report adds
     `known_from` and `known_from_rule` (`stored_known_from`, `start_date`,
     or `source_published_at`). A record with no usable basis is never
     returned. 152 tests pass (new `KnownFrom` and `StoredKnownFrom`
     classes), and the fixture batch passes 18 of 18.
   - Data: 25 records gained a stored `known_from`, each with one
     `approximations` entry giving its basis (`review_status`
     `unreviewed`). The manifest sha256 values were refreshed.
     - Announced in advance (10): the three China opioid tariffs (2025-02-01;
       2025-03-03, the EO 14228 signing, because the stored source is the
       later EO 14357; and 2025-11-04), the MY, PH, TW and SG reciprocal
       tariffs (2025-07-31), the global Section 122 tariff (2026-02-20), the
       China battery Section 301 tariff (2024-09-18), and
       `RESTRICT-2025-SG-001` (2025-10-03).
     - Disclosed later (3): the three concentration records, known from
       `source.published_at`.
     - Two-point comparisons (9), decided 2026-11-15: each is known from the
       date its ending value was published, because the ending value and
       the change are not known earlier. The four Federal Reserve FX pairs
       use the weekly H.10 release that first carried the 30 September
       rate (2026-10-05, after the study end), and the peso pair uses
       2026-09-30. The cost comparisons use the announcement of the
       observed value: 2025-07-09 and 2026-03-25 (Malaysian diesel),
       2026-06-30 (Singapore electricity) and 2025-06-05 (transpacific
       freight).
     - No start and no publication date (3): `CUSTOMS-2025-PH-001`
       (2025-09-30, the memorandum's release), `TRANSIT-2025-PH-001`
       (2025-08-30, the related report date), and
       `PORT-2026-SG-CONGESTION-001` (2026-10-12, the post date, after the
       study end, so it is never returned). These were the only records
       without a basis.
     - Source review, 2026-11-15: all 25 values were checked online, and
       each check is recorded in its `approximations` basis. 24 have
       `review_status` `source_checked`. Corrected, because the first
       value was too early (look-ahead): the customs memo (dated
       2025-09-24, released 2025-09-30), the Singapore congestion post
       (2026-10-12) and the four H.10 FX pairs (2026-10-05). Corrected
       because it was later than the first public date: the Singapore
       restriction (2025-10-01, its gazette publication), Singapore
       electricity (2026-06-30) and the 2026 diesel record (2026-03-25).
       The opioid 20% tariff's 2025-03-03 is confirmed by the stored EO
       14357 text. Still `unreviewed`: `FX-2025-2026-USD-PHP-001`, because
       the BSP daily bulletin for 2026-09-30 was not located. Recheck it
       when more data is collected.
     - Left at the default: `TARIFF-2025-US-CN-RECIPROCAL` (its start is a
       guidance date for a rate already in force), the five forced-labour
       Section 301 tariffs (no announcement date stored), the other
       restrictions, the financial-distress records (observation date equals
       the publication date), and the cyberattack claim (rule 2).
   - Gold set: `as_of_date`s were not changed. 40 expected results across 17
     fixtures were not yet known on their fixture's date. They moved to
     `expected_exclusions` with the reason, and the `revisions` entry lists
     them. Every expected link now records `known_from` and
     `known_from_rule`. The `effective_to_window_applies` interpretation now
     extends the end only, and `known_from_no_look_ahead` was added. The
     records expected in some fixture fell from 43 to 30, then to 29 after
     the source review removed `CUSTOMS-2025-PH-001` from FIXTURE-06.
   - Coverage restored, 2026-11-15:
     - A sweep of every fixture payload over every study date found
       reports that became known after their window had closed and so could
       never be returned (the VS Industry and Taiwan foundry concentration
       records, Dyson FX). The late-report rule (section 5.2) was added.
       It also adds Dyson FX to FIXTURE-05, 09 and 17 and the Suez report
       to FIXTURE-06.
     - FIXTURE-19 to 37 were added: existing suppliers' payloads on a second
       `as_of_date` (`EXTRA_FIXTURES` in `examples/build_payloads.py`),
       chosen by a set cover so that every record returnable for some graph
       supplier is expected in some fixture. The first 18 payloads are
       unchanged. The new fixtures' expected results came from the engine
       and were reviewed link by link against the agreed interpretations.
     - The gold set now has 37 fixtures and covers 59 of 97 records. The
       other 38 cannot be returned for any graph supplier on any study date:
       they do not link (mostly US- and SG-country records), or they become
       known only after the study end. 157 tests pass, and the batch passes
       37 of 37.
7. **Later, outside this scope:** the LangChain app and its frontend
   (section 8.4).

Proposed layout:

```text
supplier_risk_engine/
  engine/        models.py, validate.py, normalise.py, match.py, dates.py, lookup.py
  loader.py      reads risk_evidence/database/, computes the snapshot ID
  cli.py
  examples/      fixture payloads and expected_ids.json
  tests/
```

## 10. Evaluation and limitations

- Test matching, normalisation, date handling, and linking against fixed records
  with known answers.
- Measure retrieval against the fixture gold set (`examples/expected_ids.json`):
  report missed and unexpected `evidence_id`s for each fixture.
- Record the data snapshot fingerprint and engine version in every result.
- Check that no returned report has a `known_from` after its request's
  `as_of_date` (no look-ahead, section 5.2).
- Coverage limits from the known-from rule (phase 6):
  - The four H.10 FX pairs can never be returned (first published on
    2026-10-05, after the study end). The peso pair is in scope only on
    2026-09-30 and is tested only in FIXTURE-20. Point-in-time rate records
    (for example, each weekly H.10 release) would give currency links
    through the study.
  - 25 stored `known_from` values were checked against sources on
    2026-11-15 (24 confirmed). `FX-2025-2026-USD-PHP-001` is unconfirmed, and
    `TRANSIT-2025-PH-001` rests on a related report's date.
  - `PORT-2026-SG-CONGESTION-001` can never be returned: its source was
    published on 2026-10-12, after the study end.
- Check that every returned fact traces to a stored record and its source. Any
  LLM explanation added later should be checked against the returned records.
- Never infer a verified route, supplier capacity, financial exposure, or
  current event from a name, vessel, or country match.
