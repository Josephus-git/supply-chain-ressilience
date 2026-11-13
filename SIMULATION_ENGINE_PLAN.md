# Local supply-chain simulation engine plan

Status: **draft for discussion**. This document proposes an implementation; it
does not describe an existing engine or a validated risk model. Examples and
numerical values are illustrative, not empirical findings.

## 1. Goal and research scope

Build a reproducible Python simulation engine that uses structured knowledge
graph evidence and explicit scenario assumptions to explore potential supply
chain disruption impacts. Its results should be suitable for a command-line
application, an eventual web interface, and grounded LLM explanations.

The engine should:

- Support one or multiple suppliers in a single request.
- Preserve historical shipment and route evidence.
- Model shared exposure, such as multiple suppliers using the same port.
- Report assumptions, uncertainty, data gaps, and limitations alongside results.
- Avoid presenting scenario outcomes as observed events or calibrated forecasts.

A simulation and a grounded explanation address the project's risk analysis
and LLM explanation goals. They are not a link-prediction baseline; confirm
with the supervisor whether a separate link-prediction experiment is required.
See the separate [evidence dataset plan](./RISK_EVIDENCE_DATASET_PLAN.md)
for historical incidents, tariff rules, provenance, and matching.

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
dependencies. The schema does not list flood probabilities, tariff rates,
financial health, actual sailing paths, or inventory levels. The
[combined dataset](./data/processed/combined/combined.csv) contains
`source_file` and `source_row`, but the documented schema does not show them;
verify whether this provenance is actually present in Neo4j.

Before implementation, inspect the live database read-only. The relationship
names in [cypher_qa.py](./langchain/cypher_qa.py) and
[vector_cypher_retriever.py](./rag/vector_cypher_retriever.py) differ from
parts of `schema.txt`. Do not assume which reflects the database.

## 3. Architecture

```text
CLI now / web frontend later
             |
             v
Application service
  - retrieves Neo4j records
  - matches a versioned copy of the historical evidence database
  - constructs and validates requests
  - invokes the simulation engine
  - optionally requests a grounded LLM explanation
             |
             v
Standalone Python simulation engine
             |
             v
Structured result: evidence, assumptions, estimates, warnings
```

Keep the engine independent of Neo4j, the LLM, MCP, and the UI. The
application layer converts database and evidence records into engine input.
Historical evidence may motivate scenarios, but does not by itself establish
their probabilities or prove that particular suppliers were affected. A future HTTP
API can expose the same functionality to a frontend. An MCP server may be
added as a thin adapter for MCP-compatible clients; it is not required for
the engine or web API.

Evidence `search_window` dates are retrieval aids with an explicit basis, not
necessarily incident start or end dates. The application must distinguish
report-date, claim-date and approximate candidates from verified temporal
overlaps, and surface unknown event dates rather than treating a search window
as proof of impact.

The existing [mcp_client.py](./langchain/mcp_client.py) targets an external
Apify service and is not the local simulation engine.

## 4. Event scope and shared exposure

The proposed contract supports multiple separately identified events. The
application matches evidence and scenario targets against the network
snapshot; the engine evaluates the resulting explicit targets.

- **Country:** a country-wide scenario can target suppliers matching a
  specified country. Common country alone does not establish that an event
  exists, nor that its scope really is country-wide.
- **Port, carrier, or route:** apply a shared event to verified matching
  entities or explicitly assumed route segments.
- **Supplier:** target one supplier for an event such as a cyber incident,
  unless evidence establishes a broader shared dependency.
- **Product and trade corridor:** a tariff or restriction can also depend on
  product, origin, destination, and date; do not apply it from supplier
  country alone.

Sample a shared stochastic event **once per run**, then apply it to all
eligible suppliers. Shared occurrence does not require identical impact:
routes, products, shipment values, or supplier circumstances can differ.
Persist the same event ID on linked results so correlations remain clear.
Do not silently treat distinct events as independent or double-count an
underlying event, for example flooding causing a port closure. Explicit
dependency and impact-combination rules are needed before modelling them.

An event can be a hypothetical scenario or informed by a documented historical
incident. Location, date, and identity matches are evidence of possible
exposure, not proof of actual damage. Define whether a run is a historical
replay or future what-if, its timeframe, and the time basis of probabilities.

## 5. First model: departure-port disruption

Start with one hypothetical event at a departure port:

1. Select the historical routes and suppliers to assess.
2. For each run, sample whether the specified port event occurs.
3. If it occurs, sample an added delay from the supplied distribution.
4. Apply the same sampled port event and delay to all assessed routes using
   that port in that run.
5. Record whether each assessed route's added delay exceeds the threshold.
6. Repeat and calculate route, supplier, and portfolio estimates.

Use the strict comparison `added_delay_days > delay_threshold_days`; a delay
equal to the threshold does not exceed it. In this initial model, unaffected
assessed routes have zero **scenario-added** delay. This is not a prediction
of total transit time.

A route without a known departure port cannot be assessed against this
scenario. It must not be treated as unaffected. A route with a known,
different departure port is assessed as unaffected by this particular event,
not as universally risk-free.

The event can be labelled `hypothetical_flood`, but the label does not turn
the supplied event probability into an empirical flood forecast. This first
model is a port-impact model, **not a multi-tier cascade model**. Cascades
would require further dependency data and explicit propagation rules.

## 6. Proposed request contract

One request format supports one or many suppliers using a `suppliers` array.
IDs associate evidence and results; display names and optional details can
be omitted if unavailable. The engine receives a network snapshot and
explicitly scoped scenarios, not an instruction to execute an arbitrary
Cypher query or look up news. A future contract can accept multiple scenarios
in an `events` array; the first runnable model remains a departure-port event.
Whether to support multiple event types in the initial release is still open.

### Single-supplier example

The following input is illustrative:

```json
{
  "schema_version": "1.0",
  "simulation": {
    "runs": 1000,
    "seed": 42
  },
  "analysis_period": {"start": "2025-01-01", "end": "2025-12-31"},
  "events": [
    {
      "event_id": "E1",
      "type": "departure_port_disruption",
      "event_label": "hypothetical_flood",
      "scope": {"type": "departure_port", "port_id": "P1"},
      "evidence_ids": ["FLOOD-001"],
      "assumptions": {
        "event_probability_per_run": 0.2,
        "probability_time_basis": "one scenario run over analysis period",
        "delay_days_if_event": {"distribution": "fixed", "value": 6},
        "delay_threshold_days": 5
      }
    }
  ],
  "suppliers": [
    {
      "supplier_id": "S1",
      "name": "Supplier A",
      "country": "Malaysia",
      "routes": [
        {
          "route_id": "R1",
          "departure_port": {
            "id": "P1",
            "name": "Port A",
            "latitude": null,
            "longitude": null
          },
          "arrival_port": {
            "id": "P2",
            "name": "Port B"
          },
          "shipment_ids": ["SH1"],
          "product_hs_codes": ["850870"]
        }
      ]
    }
  ]
}
```

A route represents an observed departure-arrival association, not a verified
full sailing path. Keep shipment-level associations intact: do not combine
all departure and arrival ports into pairs that were never observed.

### Multiple-supplier example

Include multiple suppliers in the same complete request. The following
snippet shows only the `suppliers` field:

```json
{
  "suppliers": [
    {
      "supplier_id": "S1",
      "name": "Supplier A",
      "routes": [
        {
          "route_id": "R1",
          "departure_port": {"id": "P1", "name": "Port A"}
        }
      ]
    },
    {
      "supplier_id": "S2",
      "name": "Supplier B",
      "routes": [
        {
          "route_id": "R2",
          "departure_port": {"id": "P1", "name": "Port A"}
        }
      ]
    }
  ]
}
```

Both suppliers share the same sampled `P1` event in a run. Their outcomes
must not be treated as independent.

The following illustrative second event would target only `S1`; including
it in a request would require a separately implemented and validated
cyberattack model:

```json
{
  "event_id": "E2",
  "type": "cyberattack",
  "scope": {"type": "supplier", "supplier_id": "S1"},
  "evidence_ids": [],
  "assumptions": {
    "event_probability_per_run": 0.1,
    "probability_time_basis": "one scenario run over analysis period",
    "added_delay_days_if_event": 3
  }
}
```

Tariff assessments use a different input shape: verified or assumed rate,
product classification, origin, destination, effective date, and optionally
customs value and currency. They are deterministic unless uncertainty is
explicitly modelled.

### Optional data and validation

Optional data includes display names, country, arrival port, product, HS
code, carrier, vessel, dates, quantity, costs, coordinates, and source
references. Their absence must remain visible.

| Missing input | Proposed behaviour |
| --- | --- |
| Arrival port | Assess departure-port impact; flag incomplete route. |
| Product or HS code | Assess delay; product-specific analysis is unavailable. |
| Supplier country | Assess if the departure-port ID is available. |
| Departure port | Mark route `not_assessed`; do not assign zero risk. |
| Supplier with no assessable routes | Mark supplier `not_assessed`. |
| Event probability, delay assumption, target port, or threshold | Reject the request with a specific validation error. |
| Invalid probability, run count, delay, or duplicate IDs | Reject with a specific validation error. |

Define numerical bounds and supported distributions during implementation.
For reproducibility, require an explicit seed in the research workflow.
There should be no silent defaults for risk assumptions.

## 7. Proposed response contract

These numbers illustrate the **shape** only; they are not results of an
executed simulation and should not be used as evidence.

Return relevant modelled assessments for each supplier, with type-specific
fields. Do not list every unmodelled risk as a risk card. Keep a compact
coverage summary separately so a missing risk is not mistaken for safety.
The LLM may explain results later; probabilities, costs, and metadata are
produced by validated calculation code, not generated by the LLM.

```json
{
  "schema_version": "1.0",
  "status": "completed",
  "model": {"name": "scenario_assessment", "version": "1.0"},
  "simulation": {
    "requested_runs": 1000,
    "completed_runs": 1000,
    "seed": 42
  },
  "supplier_results": [
    {
      "supplier_id": "S1",
      "supplier_name": "Supplier A",
      "risk_assessments": [
        {
          "type": "departure_port_disruption",
          "event_id": "E1",
          "scope": {"type": "departure_port", "port_id": "P1"},
          "route_ids": ["R1"],
          "evidence_ids": ["FLOOD-001"],
          "outcome": "scenario-added delay exceeds 5 days",
          "runs_exceeding_threshold": 200,
          "estimated_probability": 0.2,
          "added_delay_days_if_event": 6
        },
        {
          "type": "tariff",
          "rule_id": "TARIFF-001",
          "rate_percent": 10.0,
          "rate_basis": "illustrative_assumption",
          "estimated_duty_amount": null,
          "currency": null
        }
      ]
    }
  ],
  "coverage": {
    "assessed_categories": ["departure_port_disruption", "tariff"],
    "routes_assessed": 1,
    "routes_not_assessed": 0,
    "limitations": [
      "Financial health and other categories were not assessed.",
      "Historical routes may not represent current routes."
    ]
  },
  "evidence_snapshot_id": "illustrative-snapshot"
}
```

The tariff entry shows the planned future response shape; tariff calculations
are not part of the initial port model. A rate is not a probability.
Probability measures how often a specified outcome occurs; severity measures
its impact, such as delay days or cost. A combined 0-to-1 risk score would
need a separately defined and justified formula.

If two suppliers are exposed to the same event, both results reference its
ID and shared sampled occurrence. Their impacts may differ. The UI may
highlight a few results but must not silently discard additional applicable
assessments or claim that at most three risks can apply.

The final contract should additionally include:

- **Evidence:** shipment IDs, date coverage, and available provenance.
- **Coverage:** assessed and unassessed route counts and reasons.
- **Supplier metric:** define it as the probability that at least one
  assessed route exceeds the threshold; do not call it supplier failure.
- **Uncertainty:** confidence intervals for estimated proportions and
  completed run counts; document the interval method.
- **Reproducibility:** model version, seed, assumptions, and an input
  snapshot or fingerprint sufficient to locate the exact input.
- **Warnings:** incomplete records, uncertain mappings, and other limitations.
- **Partial assessment:** distinguish a completed run with unassessed routes
  from a fully assessed run; portfolio results cover assessed routes only.

Simulation uncertainty is conditional on the specified model and inputs.
Confidence intervals for Monte Carlo sampling do not measure uncertainty in
the assumptions or establish real-world predictive accuracy.

## 8. Risk factors

The engine is designed to support the following selected risk factors:

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

These are planned categories, not a claim that all can be assessed from the
current graph. Implement each only when its required inputs and calculation
method are available. The [evidence dataset plan](./RISK_EVIDENCE_DATASET_PLAN.md)
describes how supporting records will be collected.

Return relevant assessments using fields appropriate to each factor: for
example, a disruption probability and delay, or a tariff rate and estimated
cost. Keep coverage and missing data separate from the main risk list; a
missing assessment is not zero risk. Avoid double-counting linked events,
such as flooding that causes a port closure. Historical endpoints do not
prove that a shipment used a particular chokepoint.

## 9. Proposed call patterns

### Python and CLI

The application retrieves records and calls the engine. These are proposed
function names, not an existing API:

```python
request = build_request_from_graph(...)
result = run_simulation(request)
print(result)
```

The CLI can initially accept a structured request file or build one from a
graph query. It should show the assumptions and warnings, and optionally
save the complete JSON result for research.

### Single supplier

Select one supplier, retrieve its historically associated shipment routes,
provide a scenario, and run the engine once.

### Multiple suppliers

Retrieve each supplier's routes and run one shared scenario over the complete
request. This preserves shared events and permits scenario-specific
comparison.

### Partial input

Assess eligible routes and report unassessable routes and suppliers with
reasons. Report only estimates that are meaningful for the assessed subset.

### Future web API or MCP

A web backend could eventually accept the same request at
`POST /simulations` and return the structured result. Longer runs could
later use background jobs. An MCP tool could wrap the same Python engine;
neither interface should contain a second implementation of the model.

## 10. Implementation phases

1. **Verify graph evidence and model scope.** Inspect the live schema
   read-only, sample records, provenance, route associations, and available
   IDs. Agree on the scenario and metric definitions.
2. **Implement the engine.** Add typed request and response models, validation,
   shared-event sampling, route and supplier calculations, a seed, and
   explicit partial-data handling.
3. **Test and evaluate.** Use hand-checkable networks; test zero and certain
   disruption, shared ports, unaffected routes, missing fields, fixed-seed
   reproducibility, and sampling behaviour. Run sensitivity experiments.
4. **Connect Neo4j, the evidence database, and the CLI.** Collect evidence
   directly in the working files, and use an immutable version of those files
   for each experiment. Use parameterised read-only queries and verified
   matching; display and optionally save inputs, assumptions, evidence
   references, and results.
5. **Add grounded explanations.** Supply the LLM with evidence, assumptions,
   estimates, and limitations. Compare against a template report and evaluate
   factual and numerical consistency, transparency, and usefulness.
6. **Add interfaces when needed.** Expose a web API and frontend; add MCP only
   if tool access by agents or other MCP clients is useful.

## 11. Research evaluation and limitations

- Document the data snapshot, model version, assumptions, seed, and run count.
- Vary uncertain scenario inputs and report how conclusions change.
- Separate simulation software correctness from real-world validity.
- If historical disruption outcomes are unavailable, frame results as
  scenario analysis rather than calibrated predictions.
- Evaluate whether LLM claims are supported by the graph and simulation,
  whether numbers match, and whether missing information is acknowledged.
- If possible, use a consistent reviewer rubric for clarity and usefulness.
- Never infer a verified route, supplier capacity, financial exposure, or
  current event solely from a historical shipment association.
