# App plan: Dyson supply-chain risk decision-support web app

**Status (2026-11-16):** phases 1–5 are built: backend, Home, Graph Explorer, Ask the
Graph, the Evidence Library (shown as **Risk Library**; committed up to f2a0cfd) and
Risk Assessment with its History tab (phase 5, built 2026-11-16, not yet committed).
Tests: 78 backend, 157 engine, all passing; `tsc` clean, oxlint warnings only. Next:
the user reviews `reference/product_categories.json` (draft), then the evaluation design.

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
- ~~Risk Assessment covers one component per run.~~ **Revised 2026-11-16:** one run covers
  a whole parts list (capped at 20 items) or a free-text description; see Pages §4.
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
            graph_api.py, evidence_api.py, products_api.py, runs_store.py, usage.py,
            ask/ (Ask the Graph: schema.txt, prompts.py, llm.py, safety.py, pipeline.py, api.py)
            pipeline/ (Risk Assessment: retrieve.py, profiles.py, evidence.py, prompts.py,
                       report.py, llm.py, assess.py, api.py)
            reference/locations.json (reviewed site coordinates, see Home)
            reference/product_categories.json (draft catalogue categories, for review)
  frontend/ src/pages/{Home,Explorer,Ask,Evidence,Assess}.tsx (Run History is a tab in Assess),
            src/components/{graph,ask,evidence,assess}/…
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
   **Input (agreed 2026-11-16).** The research goal is to start from what a buyer has: a list
   of items, plus what they want to achieve. Two modes, chosen with a toggle at the top:
   - **Parts list:** a numbered list of items (one per line, typed or pasted from a
     spreadsheet), capped at **20 items**. Under it, an optional "What do you want to know?"
     box with example goal chips (best supplier per item, risks to watch, single points of
     failure). An empty goal defaults to "assess supplier risk for these items".
   - **Product catalogue (agreed 2026-11-16):** not every product is in the graph, so a
     "Browse products" panel beside the parts list shows what is (43 products from customs
     lines, not a parts breakdown). Items can be **added from the catalogue with one click
     or typed freely**, including things not in the list. Each item records its `source`
     (`catalogue` or `typed`) in the run, for comparison in the evaluation.
     - **Category tiles** with `lucide-react` icons (e.g. Floorcare, Hair care, Air
       treatment, Spares and accessories, Cables and electrical, Other), each with product
       and supplier counts. Opening one lists its products: cleaned name, raw description
       underneath, HS code, shipments, suppliers and an **Add** button.
     - **Search** over all products with shadcn Command (`cmdk`, MIT); the same search is
       autocomplete while typing an item. Both libraries are already installed.
     - **No exploded parts drawing:** the data has no parts breakdown, so a drawing would
       suggest parts the graph does not have, and Dyson's drawings are copyrighted.
     - **Categories and cleaned names** come from a hand-reviewed
       `reference/product_categories.json` (drafted by Claude, reviewed by the user), like
       `locations.json`, because the HS codes are unreliable (see L5 in
       METHODOLOGY_NOTES.md). The graph is not changed.
     - `GET /api/products` reads the products live from Neo4j, with shipment and supplier
       counts up to the chosen `as_of_date` (no look-ahead).
   - **Describe your need:** a single free-text box, e.g. "Who supplies parts for air
     filters?", with example chips.
   - Both modes take a simulated `as_of_date` and produce the same output layout.
   - **Date (agreed 2026-11-16):** the user picks any date, or presses **Random** to have
     one drawn uniformly from the study window. Dates are limited to the study window
     2025-01-01 to 2026-09-30, because outside it there is no shipment or evidence data.
     The run stores the date and whether it was chosen or random (`date_mode`).

   **Output (agreed 2026-11-16).** Three layers, each one click deeper, so it is easy to
   read but every claim can be traced to raw data:
   - **Layer 1, summary:** one or two sentences answering the user's goal. In parts list
     mode, a table below it with one row per item: item, recommended supplier, closest
     alternative, main risk (with citation chip) and deciding factor (match, risk or track
     record). Describe mode gets the sentences plus a short ranked list. Items with no
     support say "I don't have enough data to support that".
   - **Layer 2, reasoning per item** (expand a row): every candidate the risk LLM
     considered, in rank order, each with why it matches the query, its risks, its track
     record and the factor that decided its place; candidates it set aside and why; and
     country-level notes when the fallback was used (marked as coming from a Cypher LLM
     suggestion where that applies). Every claim carries citation chips (evidence id or
     graph figure), each marked verified or not found, and a "show in trace" link that
     jumps to the exact input in layer 3.
   - **Layer 3, "How this answer was reached"** (collapsed): the Cypher LLM's queries and their rows,
     the fixed profile queries, the supplier profiles and risk engine evidence, i.e.
     exactly what was sent to the risk LLM. "Reasoning" here means that input, not the
     model's hidden reasoning.
   - Every node links to Graph Explorer and every evidence id to `/evidence/:id`, so a
     wrong answer can be traced and debugged.
   - **Citation check, flag only:** each citation is checked against what the risk LLM was
     actually given and marked verified or not found. Wrong citations are **not removed or
     corrected**: the run keeps the model's raw output so its mistakes can be studied
     (research decision; see METHODOLOGY_NOTES.md).
   - **Mini graph (agreed 2026-11-16):** the same component as Ask the Graph (Bloom style,
     starts with about 15 nodes via `startView.ts`, expand on demand, "Open in Graph
     Explorer" handoff), shown **only in the detailed views** (layers 2 and 3), not in
     the summary. It shows the nodes the Cypher LLM retrieved, with the candidate
     suppliers highlighted.
   - **Live progress (agreed 2026-11-16):** the timeline follows exactly how the data was
     retrieved and reviewed, in pipeline order: Cypher LLM (query, checks, rows, any
     retry and any labelled country suggestion) → fixed profile queries → risk engine
     evidence → risk LLM writing the report → citation check. Each step appears as it
     starts, fills in when done, and the finished timeline becomes layer 3.
   - **Service status (agreed 2026-11-16):** the header health indicator (c70697a) is the
     one place that shows if anything is down. It gains OpenAI (key present and API
     reachable, checked without spending tokens, e.g. listing models) next to Neo4j and
     the evidence engine, plus today's token use against the 250,000 free tokens. If a
     service fails during a run, the failing step in the timeline shows the error.
   - **History tab (agreed 2026-11-16):** a list of past runs (when it ran, mode, first
     items or the description, item count, `as_of_date` and whether it was random, tokens
     used), filterable by mode. Opening a run shows it in the normal three-layer view
     with its full trace.
     - **No side-by-side view.** Instead, "Re-run" opens the main Assess page pre-filled
       with the run's mode, items and goal, where the user sets a new date (or Random) and
       runs it. The result is a **new, separate run record**, linked to the original by
       `rerun_of`. This data will feed the evaluation.

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
**Revised 2026-11-16:** two separate LLMs. A **Cypher LLM** finds the data; a **risk LLM**
compares the evidence and decides.

`find_candidates` (Cypher LLM writes read-only Cypher mapping the items or description to
products and suppliers; shown in the trace; reuses the `ask/` safety checks) →
`build_profiles` (**fixed** Cypher aggregation into payload schema 1.1 with the
`as_of_date` filter; see SUPPLIER_RISK_EVIDENCE_ENGINE_PLAN.md section 6.1) →
`lookup_evidence` (`lookup_suppliers` with a fixed `as_of_date`) → `write_report` (risk LLM)
→ `check_citations` (flag only).
- **Why the profile query is fixed:** the no-look-ahead rule and the engine's exact payload
  format must not depend on the LLM remembering a date filter. The Cypher LLM may still
  make mistakes in *finding* candidates; that is allowed and visible (research decision).
- **Nothing found is not the end:** if the Cypher LLM returns no supplier or product, the
  risk engine is still asked for evidence related to the question, at least by the
  countries it mentions (e.g. a question about China returns ongoing China risks with no
  supplier). The risk LLM can then answer at country level ("consider another country
  because …"). The engine has no country-only lookup today (`lookup_suppliers` takes
  supplier payloads), so this needs a small country lookup with the same date rules.
- **Countries for the engine (agreed 2026-11-16):** the Cypher LLM's job stays retrieval.
  Countries come from what its Cypher returned. When it has to approximate (nothing
  returned, or a region such as "Southeast Asia"), it may add suggested countries in the
  same response, explicitly labelled as a **recommendation to the risk engine**, not a
  retrieved fact. The trace and the final answer say when country evidence came from such
  a suggestion. The engine itself stays deterministic.
- **Retry:** the Cypher LLM keeps Ask's one automatic retry (error or no rows); both
  attempts stay in the trace, so first-attempt accuracy can be measured.
- **Ranking (agreed 2026-11-16), done by the risk LLM following this priority:**
  1. **Closest match to the query:** how well the supplier's products match the item or
     description. This decides what is returned at all.
  2. **Risk:** among close matches, fewer and less severe evidence records as of the date
     is better.
  3. **Track record, when risk does not separate them:** e.g. "supplier X has delivered
     more shipments than Y". The graph has no failed or late deliveries (customs records
     are completed arrivals), so track record means the profile's shipment count up to
     `as_of_date`, how recent the last arrival is, and how long the relationship has run
     (`footprint_window`). The answer must say which of the three decided each ranking.
- **No support at all:** when neither the graph nor the engine returns anything relevant,
  the answer is "I don't have enough data to support that". The prompt also requires this
  for any claim it cannot cite.
- `write_report` uses `report_llm` (gpt-5.2) **without tools**. The supplier profiles and
  their evidence records go straight into the prompt, so the trace shows exactly what the
  LLM saw. This also avoids LangChain's agent helper, which runs on LangGraph.
- Its output is structured (LangChain `with_structured_output`), so layers 1 and 2 are
  rendered from fields, not parsed from prose. Per item: `status` (answered,
  country_level or insufficient_data); `candidates[]` in rank order, each with
  `supplier_id`, `match_reason`, `risks[]` and `track_record` as claims with `citations[]`
  (evidence ids or graph figures such as a profile's shipment count), and
  `deciding_factor` (match, risk or track_record); `set_aside[]` with reasons;
  `country_notes[]`. Plus a top-level `summary` answering the goal. The summary table is
  built from these fields, so it cannot say something the reasoning does not.
- The LLMs never choose the date. The Cypher LLM writes only the candidate-finding queries.
- Each step logs its inputs and outputs to the trace and to `runs/`.

## API credit safety (agreed 2026-11-16)
The OpenAI account gets 250,000 free tokens a day, so the app warns before that is reached.
- Every run (Ask and Assess) records its token usage (LangChain `usage_metadata`) in its
  run JSON, which also gives the evaluation cost data.
- The backend sums today's usage; the page shows it and **warns** near the free amount
  (default at 80%, set in `.env`) and again past it. It warns, it does not block.
  Assumption to check: the free-token day resets at 00:00 UTC, and which models count.
- Every LLM call gets a `max_tokens` cap, a timeout and `max_retries=1`. Calls per run are
  bounded (e.g. one Cypher call for the whole list, not one per item). The Assess button
  is disabled while a run is going.
- Today the backend binds to 127.0.0.1 only and Ask makes at most 3 calls per question,
  but there are no token caps, timeouts or usage records yet.
- A spend limit in the OpenAI dashboard is the only hard guarantee.

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
- `GET /api/products?as_of=` (catalogue for Risk Assessment)
- `GET /api/evidence/{id}`
- `POST /api/assess` (SSE; 409 while another assessment runs)
- `POST /api/ask` (SSE)
- `GET /api/ask/examples`, `GET /api/ask/runs`, `GET /api/ask/runs/{id}`
- `GET /api/runs?mode=` (assessment history, summaries)
- `GET /api/runs/{id}`
- `GET /api/health`: Neo4j and the evidence engine reported separately (c70697a). If
  Neo4j is down, `status` is `degraded`, `neo4j` is `unavailable` and `neo4j_error`
  holds the reason; the evidence engine still works. The header dot describes Neo4j only
  and its tooltip has a section for each part. Phase 5 added `openai` (key present and
  API reachable, by listing models, cached five minutes; no tokens spent) and
  `tokens_today` (used, limit, warn level), shown in the header as "Nk / 250k tokens".

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
5. **Built (2026-11-16, not yet committed).** Risk Assessment and its History tab.
   Backend: `pipeline/` (`profiles.py`, `evidence.py`, `prompts.py`, `report.py`,
   `llm.py`, `assess.py`, `api.py`), `products_api.py`, `usage.py`,
   `reference/product_categories.json` (draft), health additions, token usage in Ask runs.
   Frontend: `pages/Assess.tsx`, `components/assess/` (`ItemsEditor`, `Catalogue`,
   `Report`, `Citations`, `Timeline`, `History`), `lib/assess.ts`; `GraphCanvas` gained a
   `highlight` prop (ringed candidate suppliers). 17 tests in `tests/test_assess.py`
   (fake structured-output LLM, live Neo4j, real evidence). Notes from building it:
   - **Profiles equal the fixtures:** at `as_of_date` 2026-09-30 the fixed Neo4j queries
     give exactly the 18 fixture payloads built from the CSVs (tested key for key). One
     query per payload key (base, HS codes, exit/entry ports, buyers, carriers, vessels),
     each in the trace.
   - **Candidate step:** one structured Cypher-LLM call (`cypher`, labelled
     `suggested_countries`, `interpretation`) for the whole list, with the Ask safety
     checks and one retry (also on unparsable replies or missing `item`/`supplier_id`
     columns). Catalogue items reach it as `[catalogue product_id: hs:…]`. Its query is
     not date-filtered; the matched (item, supplier, product) triples are recounted up to
     the date, and suppliers with no shipment by then get no profile (R14).
   - **Engine calls:** one `lookup_suppliers` call per supplier (avoids duplicate-name
     rejections). Country lookups use a placeholder-supplier payload with the country's
     currency, so the engine's own country rules apply (R17). Countries named in the request
     are detected deterministically (`mentioned`); the Cypher LLM's are `suggested` (R16).
   - **Report:** `with_structured_output(AssessmentReport, include_raw=True)`; supplier
     profiles and evidence are listed once (not per item) to bound the prompt. Graph
     figures have citation ids (`graph:<sid>:<field>`, `match:<item>:<sid>`, R18). If
     nothing relevant was found, the risk LLM is not called (R7).
   - **Citation check:** verified or not found, plus a scope note when a real id was cited
     for another supplier, item or country; uncited claims are listed. Nothing is changed.
   - **Page:** form (mode toggle, items with autocomplete and paste, catalogue tiles and
     search, goal chips, date picker with Random), then layer 1 (answer + table), layer 2
     (expand a row; mini graph with ranked suppliers ringed), layer 3 (collapsible
     timeline, open while running). Chips link evidence to `/evidence/:id` and jump to the
     exact input in layer 3. `?run=`, `?tab=history`, `?rerun=` in the URL.
   - **First real run** (2026-11-16, 2 items, as of 2026-04-01): 2 LLM calls, 22,510
     tokens, 71 citations, all verified, 2 with a scope note.
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
- Assessment (`tests/test_assess.py`): profiles equal the fixture payloads at the end of
  the study window and respect `as_of_date`; inactive and unknown suppliers; the candidate
  example compiles; country lookups follow engine rules; the citation check flags without
  changing; full pipeline, retry, R7 (no LLM call) and country-fallback runs with fake
  LLMs; SSE, history, re-run linkage, token totals and validation through the API; the
  catalogue covers all 43 products.
- Run the app and do one assessment end to end. Check that every citation chip resolves
  to a returned evidence record, and that the run JSON is saved. Done 2026-11-16.
- Existing engine tests still pass:
  `python -m unittest discover -s supplier_risk_engine/tests -t .`
