# App plan: Dyson supply-chain risk decision-support web app

**Status (2026-11-16):** phases 1–4 are done and committed (backend, Home, Graph
Explorer, Ask the Graph, and the Evidence Library, now shown as **Risk Library**; up to
f2a0cfd). Risk Assessment (with its History tab) is the last placeholder page and is
next; its spec is open for discussion before building. Tests: 61 backend, 157 engine,
all passing; `tsc` and oxlint clean.

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
- LangChain orchestrates the workflow, with OpenAI gpt-5.2. **No LangGraph** (revised
  2026-11-16): both pipelines are straight sequences of steps, so plain Python async
  generators that call LangChain chains are enough. The user knows LangChain but not LangGraph.
- The first version has a Home page plus all five pages.
- **Page and build order (revised 2026-11-16):** Home → Graph Explorer → Ask the Graph →
  Evidence Library (shown as Risk Library) → Risk Assessment. Risk Assessment is last because it is the main
  result of the app and the research. Run History is a tab inside Risk Assessment, not a
  separate page.
- Risk Assessment covers **one component (BOM line) per run**. Several parts mean several
  runs, compared in the history. A batch BOM mode can be added later on top of it.
- Evaluation design is deferred.
- Home page charts and the map use **Apache ECharts** (`echarts-for-react`). One library
  covers the world map with animated route lines and the line chart. The world GeoJSON is
  bundled, so the map works offline with no map key or tile server.
- The Graph Explorer opens on a small Dyson-centred view in the style of Neo4j Bloom, not
  the full graph (revised 2026-11-15; see Pages).
- Supplier exposure profiles count only shipments with `arrival_date <= as_of_date`. This
  is the same no-look-ahead rule the engine applies to evidence.

## Stack
- **Backend:** FastAPI in the existing .venv.
  - Imports `supplier_risk_engine` directly (`load_database()` once at startup). The engine
    still has no HTTP layer. Only the app has endpoints.
  - Uses the `neo4j` driver with **read-only sessions** (`default_access_mode=READ`).
  - LangChain (`init_chat_model`, prompt templates, `|` chains, `.ainvoke`/`.astream`)
    plus plain Python orchestrates the workflow. LangGraph is not used.
  - `init_chat_model("gpt-5.2", model_provider="openai")`. Embeddings use
    `text-embedding-3-small` against the vector index `embedding` on `Product.embedding`,
    the same model as `rag/update_embeddings.py`.
- **Frontend:** React, Vite and TypeScript, Tailwind CSS with shadcn/ui (professional
  components), TanStack Query, and **Cytoscape.js** for the graph (MIT licence, click and
  select events, many layouts).
  - React is worth it here: a graph you can click through, linked side panels and a live
    trace are hard to build in Streamlit.
  - Node 24 and npm 11 are installed.
- **Streaming:** each pipeline is an async generator that yields one event per step (and
  answer tokens from LangChain `.astream()`). FastAPI sends them to the browser as
  Server-Sent Events, so the trace panel fills in live.
- **Dev:** `npm start` in `webapp/backend` (uvicorn with reload, port 8000, using the
  repo `.venv`) and `npm run dev` in `webapp/frontend` (Vite with an `/api` proxy).
  `npm test` in `webapp/backend` runs the backend tests.
  For a demo, run `npm run build` in the frontend and let FastAPI serve `dist/`
  (restart the backend after a build), so one command starts the app.

## Layout
```
webapp/
  backend/  main.py, config.py, neo4j_client.py (read-only),
            graph_api.py, evidence_api.py, runs_store.py,
            ask/ (Ask the Graph: schema.txt, prompts.py, llm.py, safety.py, pipeline.py, api.py)
            pipeline/ (state.py, retrieve.py, profiles.py, evidence.py, report.py, graph.py)
            reference/locations.json (reviewed site coordinates, see Home)
  frontend/ src/pages/{Home,Explorer,Ask,Evidence,Assess}.tsx (Run History is a tab in Assess), src/components/graph/…
runs/       one JSON file per assessment run (payload, retrieved context, Cypher, evidence, LLM output)
```

## Pages
0. **Home** (intro page)
   - **World map:**
     - Shows every supplier company linked to Dyson by animated arcs. Arc width shows
       shipment count.
     - Hover or click a supplier for its shipments, products and ports. A toggle shows the
       real route instead: supplier → exit port → entry port → Dyson site. The ocean leg
       follows a likely sea path from the `searoute` package.
     - The backend fetches all suppliers live from Neo4j (`GET /api/home/network`).
   - **"Dyson's top 10 relationships" tree** (`RelationshipsTree.tsx`), above the line
     chart: Dyson → its 10 supplier companies → their parent companies (`SUBSIDIARY_OF`).
     It shows knowledge-graph data only. The scrape is Dyson-only, so suppliers' other
     customers are not available, and a hand-copied ImportYeti column was tried and removed.
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
1. **Graph Explorer** (Neo4j Bloom style; revised 2026-11-15)
   - **Look:** plain coloured circles with the caption inside, and the relationship type
     written on each edge. No icons or varied shapes. Real relationships are shown by
     default, not aggregated shipment counts.
   - **Start view** (`GET /api/graph/start`): Dyson Inc at the centre with about 3
     shipments attached. One shipment is fully expanded, and its supplier is expanded to
     its parent company. A supplier picker can restrict the shipments to chosen suppliers.
   - Details appear only on click (inspector panel with properties and neighbours; it
     opens on the Properties tab) or on expand (double-click). Actions: expand neighbours, expand an aggregated link into its
     shipments, hide.
   - Filters by node type and date range, plus a search box. The view state lives in the
     URL. A "show full graph" option (the aggregated `/api/graph/snapshot`) sits in the
     advanced settings.
   - **Handoff from other pages:** a result can be opened here through router state
     (`location.state.askGraph`: nodes, edges, question). The Explorer then shows that
     graph instead of the start view, with a banner and a "back to the normal view"
     action. It survives a reload but not a new tab. The Evidence Library and Risk
     Assessment use URL params instead (`?suppliers=`, `from`, `to`), so links can be shared.
   - The first version (an 80-node aggregated supplier hub with stars, triangles and
     pentagons) was rejected as cluttered. Later graph views, such as the Risk Assessment
     mini graph, should follow the same Bloom style and start small.
2. **Ask the Graph:** natural-language Q&A that reuses the prompt in
   `langchain/cypher_qa.py`. It shows the generated Cypher and its rows before the answer,
   and runs read-only.
   - Its role is exploratory: questions there is no page for. The LLM writes the Cypher,
     so the answers are less reliable than Risk Assessment and no `as_of_date` rule is
     applied.
   - It is also a contrast case for the evaluation: the Cypher is shown, so its mistakes
     can be seen.
3. **Risk Library** (built as the Evidence Library; `pages/Evidence.tsx`, `components/evidence/`)
   - **Name:** renamed to "Risk Library" in the nav and page title only (f2a0cfd). The
     route stays `/evidence/:id?`, the API stays `/api/evidence`, and code names stay
     `Evidence*`. A second `/risk-library` route was tried and dropped: one page, one URL.
   - **Drill-down layout** (f2a0cfd): 4 risk groups (`RISK_GROUPS` in `lib/evidence.ts`:
     supplier and operations, logistics and transport, trade policy and markets, natural
     hazards) → a tile per risk type with a one-line blurb (`RISK_BLURB`) and its record
     count and date span → `?type=` card list with chips for the sibling types → the
     detail sheet. A text search with no type chosen groups its results by type.
   - Browse the 109 engine records (18 risk types) as cards. Filters: risk type, country
     (from every country-code field; see phase 4 notes), date range and a text search over the id, scope,
     entities and publisher. Filter state lives in the URL.
   - **Dates:** each risk type has its own date fields (`DATE_FAMILY` / `FAMILY_FIELDS` in
     `engine/dates.py`: event, observation point, observation window, effective interval).
     The card shows that family's start and end, plus `source.published_at`. The date
     filter keeps a record whose start–end range overlaps the chosen range. A record with
     no end date counts as a single day, except effective intervals, which stay open to
     the end of the study window (the same rule as the engine).
   - **Card:** id, risk type, scope, countries, dates, measure (name, value, unit),
     reported entities or routes, verification status, limitations, source (publisher,
     link, licence notes) and related evidence ids (as links to those cards).
   - **Addressable:** each card has its own URL (`/evidence/:id`, which opens the card in a
     detail panel over the filtered list). Risk Assessment citation chips link here.
   - **Graph link:** where a record's countries match suppliers in the graph, a "show in
     Graph Explorer" action opens `/explorer?suppliers=…`. The match is by
     `supplier_country_code` only; the evidence has no supplier ids.
   - The data comes from `app.state.evidence_db`, which is already loaded at startup.
     Nothing is read again from disk and Neo4j is not needed, except for the supplier
     list used by the graph link.
4. **Risk Assessment** (main workflow, last page)
   - Inputs: one BOM line (one component per run) and a simulated `as_of_date`, limited to
     the study window 2025-01-01 to 2026-09-30.
   - A live step timeline shows:
     a. vector search, with the products found and their scores
     b. each Cypher query and its rows
     c. a supplier exposure profile for each supplier (schema 1.1)
     d. the engine's evidence records for each supplier
     e. the LLM report, streamed
   - Citation chips in the report link to evidence cards and to the graph elements they
     cite. A mini graph highlights the candidate suppliers.
   - Note: the page needs both Neo4j (retrieval, profiles) and the evidence engine. The
     header health dot reports them separately (c70697a), so the page should say which
     part is missing if Neo4j is down.
   - **History tab:** reopen any past run with its full trace. This data will feed the
     evaluation.

## Ask the Graph pipeline (Text2Cypher, `webapp/backend/ask/`)
All Cypher-LLM logic lives in `ask/`, separate from the Risk Assessment `pipeline/`.
Orchestration is LangChain (`init_chat_model`, prompt templates, `|` chains) called from
a plain Python async generator in `ask/pipeline.py`, which yields one SSE event per step.
`GraphCypherQAChain` is not used, because it hides the intermediate steps.
- **Own LLM:** `ask/llm.py` builds `cypher_llm` from `ASK_CYPHER_MODEL` (default gpt-5.2).
  Risk Assessment uses a separate `report_llm` from `REPORT_MODEL`.
- **Schema:** `langchain/schema.txt` is **copied** to `ask/schema.txt`. `langchain/` was a
  prototype and stays untouched. `Product.embedding` is removed from the copy.
  **Done 2026-11-16:** the copy has property types and value hints, checked against the live
  graph. It covers DATETIME dates compared with `date()`, INTEGER HS and port codes,
  grouping by `supplier_basename`, ISO country codes, and one product per shipment.
- **Example questions:** `ask/example_questions.json` holds 8 drafts for the user to review.
  Each has a hand-written `reference_cypher`, checked against the graph, as a candidate
  gold answer for the evaluation. The reference Cypher is not shown to the LLM. A
  test checks that each label, property and relationship in the file exists in Neo4j.
- **Steps** (functions in `ask/pipeline.py`):
  1. `generate_cypher`: `cypher_llm` gets the schema, the few-shot examples (starting with
     the one in `cypher_qa.py`) and the question, and returns only Cypher.
  2. `check_cypher`: refuses write clauses (CREATE, MERGE, DELETE, SET, REMOVE, DROP,
     LOAD CSV, CALL of write procedures), runs `EXPLAIN` to check syntax, and adds a row
     limit.
  3. `run_query`: runs through `ReadOnlyNeo4j`. If the query errors or returns nothing, the
     error goes back to `generate_cypher` for one retry. Both attempts appear in the trace.
  4. `write_answer`: `cypher_llm` answers from the question and the rows only. If there are
     no rows, it says so.
- **UI:** a question box with example chips. Each step is shown in order: Cypher (copyable),
  checks, rows table, answer. When the rows contain nodes, a small Bloom-style graph
  appears next to the table. Single questions, with no follow-up chat in this version.
  - **Value-only rows** (names, counts) also get a graph: `companion_graph` re-runs the
    query with its final top-level RETURN replaced by the matched variables (`RETURN
    DISTINCT …`, up to 2000 rows). Variables out of scope at the RETURN are dropped using
    EXPLAIN errors. UNION queries are skipped. The result's `source` is `rows` or `query`.
  - Up to 800 nodes are sent to the page (`GRAPH_NODE_CAP`). The inline view starts with
    about 15 (`components/graph/startView.ts`: non-shipment nodes first, busiest first,
    then shipments) and shows more as nodes are expanded. "Open in Graph Explorer" hands
    the whole result to the Explorer.
- **Stored:** each question, its Cypher attempts, rows and answer go to `runs/ask/`
  (`runs/` is git-ignored; the user curates what to keep), to be
  used in the evaluation (for example, scoring against hand-written Cypher for 20–30
  questions).
- **Known data quirk (left as is, by user decision 2026-11-16):** Hi-P's single plant
  (Bldg X2, Lot 11A, First Philippine Industrial Park, Tanauan, PH) has two
  `supplier_basename` values: "Hi P Philippines Technology Corpora" (reported as TW, 47
  shipments) and "Hip Philipines Technology" (PH, 49). Per-company answers show it as two
  suppliers. This is an entity-resolution limitation of customs data, to note in the write-up.
- **Research role:** an exploratory, LLM-written-query baseline. It contrasts with Risk
  Assessment's fixed queries, enforced dates and citations. It sees the graph only, with
  no evidence and no `as_of_date` rule.

## Assessment pipeline (LangChain + plain Python, `pipeline/`)
`retrieve_products` (vector index) → `build_profiles` (Cypher aggregation into payload
schema 1.1; see SUPPLIER_RISK_EVIDENCE_ENGINE_PLAN.md section 6.1) → `lookup_evidence`
(`lookup_suppliers` with a fixed `as_of_date`) → `write_report`.
- `write_report` uses `report_llm` (gpt-5.2) **without tools**. The supplier profiles and
  their evidence records go straight into the prompt, so the trace shows exactly what the
  LLM saw. This also avoids LangChain's agent helper, which runs on LangGraph.
- Its output is structured: the ranked suppliers, each with reasons, and each reason cites
  an `evidence_id` or a graph figure.
- The LLM never chooses the date and never writes Cypher in this pipeline.
- Each step logs its inputs and outputs to the trace and to `runs/`.

## API
- `GET /api/home/network`
- `GET /api/home/top-suppliers`
- `GET /api/home/stats`
- `GET /api/graph/suppliers` (picker)
- `GET /api/graph/start` (Dyson-centred start view)
- `GET /api/graph/snapshot` (aggregated, used for the full graph)
- `GET /api/graph/nodes/{id}/neighbours`
- `GET /api/graph/edges/shipments` (shipments behind an aggregated link)
- `GET /api/graph/search`
- `GET /api/evidence`
- `GET /api/evidence/{id}`
- `POST /api/assess` (SSE)
- `POST /api/ask` (SSE)
- `GET /api/ask/examples`, `GET /api/ask/runs`, `GET /api/ask/runs/{id}`
- `GET /api/runs`
- `GET /api/runs/{id}`
- `GET /api/health`: Neo4j and the evidence engine reported separately (c70697a). If
  Neo4j is down, `status` is `degraded`, `neo4j` is `unavailable` and `neo4j_error`
  holds the reason; the evidence engine still works. The header dot describes Neo4j only
  and its tooltip has a section for each part.

## Phases
1. **Done (5b867bf).** Backend skeleton, read-only Neo4j client, `reference/locations.json`, and the home and
   graph endpoints. Rebuild vector search in
   `pipeline/retrieve.py`, using the deleted `rag/vector_cypher_retriever.py` from git
   history as reference. The `rag/` deletion is intentional, so it is not restored.
2. **Done (6063c00 to 1b8f540).** Frontend shell (navigation, theme), Home page (map,
   relationships tree, top-10 chart, KPI tiles) and Graph Explorer.
3. **Done (2026-11-16).** Ask the Graph: `webapp/backend/ask/` (safety, prompts, llm,
   pipeline, api), `runs_store.py`, `POST /api/ask` (SSE) plus `GET /api/ask/examples`,
   `/api/ask/runs` and `/api/ask/runs/{id}`, the page (`pages/Ask.tsx`,
   `components/ask/`), and the sidebar in the new order (`/runs` redirects to `/assess`).
   22 tests in `tests/test_ask.py` use a LangChain fake chat model, so no OpenAI calls.
   Notes from building it:
   - `check_cypher` also reads the EXPLAIN notifications: a label, relationship type or
     property that does not exist (GQL 01N50/01N51/01N52) fails the check and triggers
     the retry. The example-questions test relies on the same check.
   - A no-rows retry tells the model to match a shorter fragment of a name. With that,
     "VS Industry" recovers "Vs Industrial …" on the second attempt.
   - When the rows hold nodes, one extra read-only query adds the relationships among
     them, so the small graph is connected. The prompt asks for nodes only when the
     question asks to show nodes or a graph; otherwise the model returns named columns.
   - Rows are capped at 200 (LIMIT added or lowered, and the driver stops reading).
     The answer prompt sees at most 60 rows.
   - Follow-ups (971fc8f, 2758d9f, 13fd71c): the result rows can be opened in Graph
     Explorer, value-only rows get a graph through `companion_graph`, the start view
     comes from `startView.ts`, and the node inspector opens on Properties.
     (Commit f8d0662 is labelled "phase 4" but holds phase 3. 971fc8f says "evidence
     library" but changes the Ask page.)
4. **Done (2026-11-16; 8e83375, c70697a, f2a0cfd).** Evidence Library (shown as Risk Library): `evidence_api.py` (`GET /api/evidence`,
   `GET /api/evidence/{id}`), `pages/Evidence.tsx` (route `evidence/:id?`),
   `components/evidence/` (`EvidenceCard`, `EvidenceDetail`, `parts`), `lib/evidence.ts`,
   and 16 tests in `tests/test_evidence.py` (fake Neo4j, real records). Notes from building it:
   - Records are heterogeneous (each risk type has its own fields), so the backend builds one
     summary per record (`EvidenceView`, cached on `app.state`): a title from per-type
     fields (`TITLE_FIELDS`), a description, measures (delay, rate, measure, baseline and
     observed, FX rates, change percent), reported entities, and the family's dates.
   - **Countries** come from every `*country_code(s)` field, not only `countries[]`
     (`country_code`, `affected_countries`, `origin/importing/issuing_country_code`,
     `location.country_code`, `trade_lanes` origins and destination). Import-side codes
     (`importing_country_code`, `destination_country_code`: the US on every tariff) count for
     the country filter but not for the graph link. Some records carry no country (the FX
     series, some vessel and transit records).
   - **Undated records** (no start date; 30 of 109) are filtered by their search window, and
     the card says "Undated". This was not in the spec; without it they could never match a
     date filter.
   - Text search covers id, title, description, entities, country names, risk label and
     publisher (the spec named id, scope, entities and publisher).
   - Facet counts apply every filter except the facet's own. Filters are single-select in the
     UI (`type`, `country`, `from`, `to`, `q` in the URL); the API also takes comma lists.
   - Graph link: supplier nodes are read once from Neo4j and cached. If Neo4j is down the
     library still works and the panel says the link is unavailable. Country-only matching
     is broad (MY links all 6 Malaysian supplier nodes); the panel says so.
   - Follow-ups: the health check no longer claims Neo4j is connected when it is not
     (c70697a), and the page was renamed Risk Library and reorganised as a drill-down
     (f2a0cfd; see Pages). `Placeholder` takes an optional `phase`.
5. **Next (to discuss first).** Risk Assessment: the assessment pipeline, SSE, trace
   timeline, report with citations, and the History tab. The page spec above is still the
   2026-11-15 outline and should be detailed and approved before building.
6. Later: the evaluation design discussion, plus optional criticality and link-prediction
   views (brief outputs 2 and 3).

## Verification
- Backend unittest tests (`npm test` in `webapp/backend`):
  - The graph endpoints return the right shapes.
  - Profiles built for VS Industry Berhad match a hand-written Cypher query.
  - `lookup_evidence` on fixture payloads matches `expected_ids.json`.
  - Writes are rejected by the read-only session.
  - Evidence (`tests/test_evidence.py`): the endpoint with no filters returns 109
    records, and the facet counts match `db.records`; each filter (risk type, country,
    date overlap, text) narrows the results to a hand-checked set; an open-ended
    effective interval matches dates up to the end of the study window; `/api/evidence/{id}`
    returns the record, and an unknown id gives 404; every `related_evidence_ids` entry
    resolves.
- Run the app and do one assessment end to end. Check that every citation chip resolves
  to a returned evidence record, and that the run JSON is saved.
- Existing engine tests still pass:
  `python -m unittest discover -s supplier_risk_engine/tests -t .`
