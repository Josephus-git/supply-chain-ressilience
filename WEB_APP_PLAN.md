# App plan: Dyson supply-chain risk decision-support web app

## Context
Research brief: "KG and LLM-based decision support for supply-chain resilience and supplier
risk explanation". Case study: Dyson and its top suppliers (10 supplier CSVs, 478 shipments,
in Neo4j). Done so far: the knowledge graph (brief output 1) and the supplier risk evidence
engine (109 records, 157 tests). The app delivers brief output 4 (an LLM explanation
workflow) and makes it inspectable. Users can see each question asked, each Cypher query
run, each retrieved context and each cited record, and they can explore the KG
interactively. Evaluation design (output 5) gets its own discussion later. The app stores
every run so that discussion has data to work with.

## Decisions confirmed (2026-11-15)
- Local web app: React, Vite and TypeScript, with Tailwind and shadcn/ui.
- The graph is drawn with Cytoscape.js.
- LangChain and LangGraph orchestrate the workflow, with OpenAI gpt-5.2.
- The first version has a Home page plus all five pages.
- Evaluation design is deferred.
- Home page charts and the map use **Apache ECharts** (`echarts-for-react`). One library
  covers the world map with animated route lines and the line chart. The world GeoJSON is
  bundled, so the map works offline with no map key or tile server.
- The Graph Explorer opens on a simple snapshot of one or two suppliers, not the full
  graph.
- Supplier exposure profiles count only shipments with `arrival_date <= as_of_date`. This
  is the same no-look-ahead rule the engine applies to evidence.

## Stack
- **Backend:** FastAPI in the existing .venv.
  - Imports `supplier_risk_engine` directly (`load_database()` once at startup). The engine
    still has no HTTP layer. Only the app has endpoints.
  - Uses the `neo4j` driver with **read-only sessions** (`default_access_mode=READ`).
  - LangChain and LangGraph (already installed) orchestrate the workflow.
  - `init_chat_model("gpt-5.2", model_provider="openai")`. Embeddings use
    `text-embedding-3-small` against the vector index `embedding` on `Product.embedding`,
    the same model as `rag/update_embeddings.py`.
- **Frontend:** React, Vite and TypeScript, Tailwind CSS with shadcn/ui (professional
  components), TanStack Query, and **Cytoscape.js** for the graph (MIT licence, click and
  select events, many layouts).
  - React is worth it here: a graph you can click through, linked side panels and a live
    trace are hard to build in Streamlit.
  - Node 24 and npm 11 are installed.
- **Streaming:** the backend sends LangGraph `astream_events` to the browser over
  Server-Sent Events. The trace panel fills in live.
- **Dev:** `uvicorn` plus `vite dev` with an `/api` proxy. For a demo, run
  `vite build` and let FastAPI serve the files, so one command starts the app.

## Layout
```
webapp/
  backend/  main.py, config.py, neo4j_client.py (read-only),
            graph_api.py, evidence_api.py, runs_store.py,
            pipeline/ (state.py, retrieve.py, profiles.py, evidence.py, report.py, graph.py)
            reference/locations.json (reviewed site coordinates, see Home)
  frontend/ src/pages/{Home,Explorer,Assess,Evidence,Runs,Ask}.tsx, src/components/graph/…
runs/       one JSON file per assessment run (payload, retrieved context, Cypher, evidence, LLM output)
```

## Pages
0. **Home** (intro page)
   - **World map:**
     - Shows every supplier company linked to Dyson by animated arcs. Arc width shows
       shipment count.
     - Hover or click a supplier for its shipments, products and ports. A toggle shows the
       real route instead: supplier → exit port → entry port → Dyson site.
     - The backend fetches all suppliers live from Neo4j (`GET /api/home/network`).
   - **Top 10 suppliers chart,** in the style of ImportYeti:
     - Monthly shipments per supplier from 2025-01 to 2026-09, one line each, from
       `GET /api/home/top-suppliers`.
     - Suppliers are grouped by `Supplier.supplier_basename`. That gives exactly the 10
       companies from 18 Supplier nodes.
   - KPI tiles: suppliers, shipments, products, ports, carriers and evidence records.
   - **Coordinates:** Supplier and Buyer nodes have no lat/lon, so they come from a
     hand-reviewed `reference/locations.json`.
     - Each entry is city-level, read from the stored address (for example Senai, Johor),
       and records its basis.
     - Nothing is sent to an external geocoding service.
     - The graph is not changed.
     - Missing port coordinates also go in this file: "Ning Bo" has none, and the "All other
       … ports" catch-alls are drawn at country level and labelled that way.
   - **Country caveat:** `supplier_country_code` is the country ImportYeti reports, and
     sometimes differs from the address (for example Ihastek Malaysia = CN). The map plots
     the address location and shows the reported country as a separate label. The engine
     keeps using the graph value, as before.
1. **Graph Explorer**
   - **Opens on a simple snapshot:** one or two suppliers (default: the top supplier),
     chosen from a supplier picker.
     - Each supplier is linked straight to its parent company, products, vessels,
       carriers, exit and entry ports and Dyson buyers.
     - Each link is labelled with its shipment count. This is an aggregated view: shipment
       nodes are hidden.
   - Click a node or relationship to open an inspector panel with its properties and
     neighbours. Actions: expand neighbours, expand a link into its underlying shipments,
     hide, add another supplier.
   - Filters by node type and date range, plus a search box. A "show full graph" option
     sits in the advanced settings.
2. **Risk Assessment** (main workflow)
   - Inputs: a BOM line and a simulated `as_of_date`, limited to the study window
     2025-01-01 to 2026-09-30.
   - A live step timeline shows:
     a. vector search, with the products found and their scores
     b. each Cypher query and its rows
     c. a supplier exposure profile for each supplier (schema 1.1)
     d. the engine's evidence records for each supplier
     e. the LLM report, streamed
   - Citation chips in the report link to evidence cards and to the graph elements they
     cite. A mini graph highlights the candidate suppliers.
3. **Evidence Library:** browse and filter the 109 records by risk type, country and date.
4. **Run History:** reopen any past run with its full trace. This data will feed the
   evaluation.
5. **Ask the Graph:** natural-language Q&A that reuses the prompt in
   `langchain/cypher_qa.py`. It shows the generated Cypher and its rows before the answer,
   and runs read-only.

## Assessment pipeline (LangGraph StateGraph)
`retrieve_products` (vector index) → `build_profiles` (Cypher aggregation into payload
schema 1.1; see SUPPLIER_RISK_EVIDENCE_ENGINE_PLAN.md section 6.1) → `lookup_evidence`
(`lookup_suppliers` with a fixed `as_of_date`) → `write_report`.
- `write_report` is gpt-5.2 with only the read-only tools `get_evidence` and
  `describe_database`.
- Its output is structured: the ranked suppliers, each with reasons, and each reason cites
  an `evidence_id` or a graph figure.
- The LLM never chooses the date and never writes Cypher in this pipeline.
- Each node logs its inputs and outputs to the trace and to `runs/`.

## API
- `GET /api/home/network`
- `GET /api/home/top-suppliers`
- `GET /api/home/stats`
- `GET /api/graph/snapshot?suppliers=…`
- `GET /api/graph/nodes/{id}/neighbours`
- `GET /api/graph/search`
- `GET /api/evidence`
- `GET /api/evidence/{id}`
- `POST /api/assess` (SSE)
- `POST /api/ask` (SSE)
- `GET /api/runs`
- `GET /api/runs/{id}`

## Phases
1. Backend skeleton, read-only Neo4j client, `reference/locations.json`, and the home and
   graph endpoints. Rebuild vector search in
   `pipeline/retrieve.py`, using the deleted `rag/vector_cypher_retriever.py` from git
   history as reference. The `rag/` deletion is intentional, so it is not restored.
2. Frontend shell (navigation, theme), Home page (map, top-10 chart, KPI tiles) and Graph
   Explorer.
3. The LangGraph assessment pipeline, SSE and the trace timeline UI.
4. Report with citations, Evidence Library and Run History.
5. Ask the Graph page.
6. Later: the evaluation design discussion, plus optional criticality and link-prediction
   views (brief outputs 2 and 3).

## Verification
- Backend unittest tests:
  - The graph endpoints return the right shapes.
  - Profiles built for VS Industry Berhad match a hand-written Cypher query.
  - `lookup_evidence` on fixture payloads matches `expected_ids.json`.
  - Writes are rejected by the read-only session.
- Run the app and do one assessment end to end. Check that every citation chip resolves
  to a returned evidence record, and that the run JSON is saved.
- Existing engine tests still pass:
  `python -m unittest discover -s supplier_risk_engine/tests -t .`
