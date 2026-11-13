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
application layer converts database records into engine input. A future HTTP
API can expose the same functionality to a frontend. An MCP server may be
added as a thin adapter for MCP-compatible clients; it is not required for
the engine or web API.

The existing [mcp_client.py](./langchain/mcp_client.py) targets an external
Apify service and is not the local simulation engine.

## 4. First model: departure-port disruption

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

## 5. Proposed request contract

One request format supports one or many suppliers using a `suppliers` array.
IDs associate evidence and results; display names and optional details can
be omitted if unavailable. The engine receives a network snapshot, not an
instruction to execute an arbitrary Cypher query.

### Single-supplier example

The following input is illustrative:

```json
{
  "schema_version": "1.0",
  "simulation": {
    "runs": 1000,
    "seed": 42
  },
  "scenario": {
    "type": "departure_port_disruption",
    "event_label": "hypothetical_flood",
    "target_departure_port_id": "P1",
    "event_probability_per_run": 0.2,
    "delay_days_if_event": {
      "distribution": "fixed",
      "value": 6
    },
    "delay_threshold_days": 5
  },
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

## 6. Proposed response contract

These numbers illustrate the **shape** only; they are not results of an
executed simulation and should not be used as evidence.

```json
{
  "schema_version": "1.0",
  "status": "completed",
  "model": {
    "name": "departure_port_disruption",
    "version": "1.0"
  },
  "simulation": {
    "requested_runs": 1000,
    "completed_runs": 1000,
    "seed": 42
  },
  "scenario": {
    "type": "departure_port_disruption",
    "event_label": "hypothetical_flood",
    "target_departure_port_id": "P1",
    "event_probability_per_run": 0.2,
    "delay_days_if_event": {
      "distribution": "fixed",
      "value": 6
    },
    "delay_threshold_days": 5
  },
  "supplier_results": [
    {
      "supplier_id": "S1",
      "supplier_name": "Supplier A",
      "status": "assessed",
      "routes": [
        {
          "route_id": "R1",
          "departure_port_id": "P1",
          "arrival_port_id": "P2",
          "shipment_ids": ["SH1"],
          "simulation_result": {
            "runs_exceeding_delay_threshold": 200,
            "estimated_probability_delay_exceeds_threshold": 0.2
          }
        }
      ]
    }
  ],
  "portfolio_result": {
    "runs_where_at_least_one_assessed_supplier_exceeds_threshold": 200,
    "estimated_probability_at_least_one_exceeds_threshold": 0.2
  },
  "risk_factors": {
    "flooding": {
      "status": "scenario_assumption",
      "detail": "The flood scenario and its event probability are assumptions."
    },
    "tariffs": {
      "status": "not_modelled",
      "value": null
    },
    "financial_health": {
      "status": "not_modelled",
      "value": null
    }
  },
  "limitations": [
    "Historical shipment routes may not represent current routes.",
    "This model does not predict actual flood events.",
    "No multi-tier disruption propagation was modelled."
  ]
}
```

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

## 7. Additional risk factors

| Factor | Available graph context | Additional requirement |
| --- | --- | --- |
| Hypothetical flooding | Country, port, possibly coordinates | Explicit assumptions or a separately sourced hazard model. |
| Tariffs | HS code, supplier/buyer countries, possibly value | Applicable rate, origin, destination, effective date, and validated cost basis. |
| Port disruption | Departure and arrival associations | Scenario probability and impact assumptions. |
| Supplier concentration | Historical shipments and buyer links | Defined measure and representative data; counts are not automatically spend or capacity. |
| Geopolitical exposure | Country and historical port information | Explicit assumptions or external evidence. |
| Financial health | No relevant fields listed | Financial data and a defined method. |
| Ownership concentration | Parent relationships where populated | Verified coverage and a defined concentration measure. |
| Carrier or vessel disruption | Related nodes where populated | A scenario and impact rules. |

Tariffs should initially be a separate cost scenario, not an automatically
invented probability. Calculate a hypothetical cost only when the rate and a
valid cost basis are supplied. Do not assume currency, completeness, or
meaning of `cif` or `shipping_cost` without validating the dataset.

Use explicit states such as `not_modelled`, `missing_input`, and
`scenario_assumption`. Missing inputs or unsupported risk categories must
never be represented as zero risk.

## 8. Proposed call patterns

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

## 9. Implementation phases

1. **Verify graph evidence and model scope.** Inspect the live schema
   read-only, sample records, provenance, route associations, and available
   IDs. Agree on the scenario and metric definitions.
2. **Implement the engine.** Add typed request and response models, validation,
   shared-event sampling, route and supplier calculations, a seed, and
   explicit partial-data handling.
3. **Test and evaluate.** Use hand-checkable networks; test zero and certain
   disruption, shared ports, unaffected routes, missing fields, fixed-seed
   reproducibility, and sampling behaviour. Run sensitivity experiments.
4. **Connect Neo4j and the CLI.** Use parameterised read-only queries and
   preserve evidence; display and optionally save inputs and results.
5. **Add grounded explanations.** Supply the LLM with evidence, assumptions,
   estimates, and limitations. Compare against a template report and evaluate
   factual and numerical consistency, transparency, and usefulness.
6. **Add interfaces when needed.** Expose a web API and frontend; add MCP only
   if tool access by agents or other MCP clients is useful.

## 10. Research evaluation and limitations

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

## 11. Decisions to discuss before implementation

1. Is the first research scenario a departure-port disruption, or should the
   initial model focus on supplier disruption instead?
2. Are supplier-level results based on at least one affected route, and what
   other decision-relevant metrics are needed?
3. What evidence or rationale will justify the scenario probabilities and
   delay distributions?
4. Should simulation requests initially be constructed from Neo4j, a JSON
   file, or both?
5. Which graph date range and level of provenance are necessary for the
   research?
6. Is a separate link-prediction baseline expected by the supervisor?
7. Which risk categories should be implemented after the initial model, and
   what inputs would make each one defensible?
