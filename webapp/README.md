# Web app

FastAPI backend and React front end for exploring the Dyson knowledge graph, asking it questions, and running cited supplier risk assessments. Project overview and setup are in the [main README](../README.md); the design and build log is in [WEB_APP_PLAN.md](../WEB_APP_PLAN.md).

## Run the backend

With Neo4j running and `.env` filled in (see the main README):

```bash
cd webapp/backend
npm start          # http://localhost:8000; reloads when backend or engine code changes
npm test           # backend tests
```

`npm start` runs uvicorn from the repository root with `.venv`, so there's nothing to activate. The long form, from the root, is `.venv/bin/uvicorn webapp.backend.main:app --reload --port 8000`.

Interactive API docs: http://localhost:8000/docs

## Run the frontend

Development (hot reload, with `/api` proxied to the backend on :8000):

```bash
cd webapp/frontend
npm install        # first time only
npm run dev        # http://localhost:5173
```

Demo (one process): build once, and the backend then serves the app at `/`.

```bash
cd webapp/frontend && npm run build
cd ../backend && npm start         # http://localhost:8000
```

The backend only looks for `webapp/frontend/dist` at startup, so restart it after the first build.

## Pages

- **Home:** headline figures, a world map of supplier-to-Dyson arcs (switchable to real routes: supplier → exit port → US entry port → Dyson site; click a supplier for its products, ports and carriers), and monthly shipments for the top 10 companies, as a chart or a table.
- **Graph Explorer:** opens on the busiest supplier, with shipments grouped into labelled links. Choose suppliers, search, filter by arrival date and node type, and change the layout. Click a node or link to inspect it, expand neighbours (double-click also works), expand a link into its shipments, hide nodes, or add a supplier. The view lives in the URL (`?suppliers=…&from=…&to=…&full=1`), so it can be shared or bookmarked.
- **Ask the Graph:** type a question or pick an example. Each step streams in as it happens: the generated Cypher, the safety check, the query (with one automatic retry on an error or empty result), the rows as a table or graph, and the answer. Past questions are listed.
- **Risk Library:** the risk evidence engine's records, as a drill-down from risk groups to risk types to single records. Filter by type, country, date and text; the filters live in the URL.
- **Risk Assessment:** build a parts list from the product catalogue or by typing items, set a goal and an as-of date (chosen or random), and run. A timeline shows each step. The report gives ranked suppliers per item with cited claims, the deciding factor, set-aside candidates and country notes, plus the citation check (verified or not found). Past runs are listed in History and can be re-run on a new date.

## Backend layout

| Path | What it does |
|---|---|
| `main.py` | App factory, routers, health check (`/api/health`), serving the built front end |
| `config.py` | Paths, models and providers, token and timeout limits, the `ASSESS_GRAPH_OFF` switch |
| `neo4j_client.py` | Read-only Neo4j access; writes are rejected by the server |
| `graph_model.py` | Node kinds, IDs and labels shared by the graph endpoints |
| `graph_api.py` | Home and Graph Explorer endpoints (`/api/home/*`, `/api/graph/*`) |
| `evidence_api.py` | Risk Library endpoints (`/api/evidence`, `/api/evidence/{id}`) |
| `products_api.py` | Product catalogue with counts up to a date (`/api/products`) |
| `ask/` | Ask the Graph: `pipeline.py` (generate → check → run → retry → answer), `safety.py` (read-only and schema checks), `prompts.py`, `llm.py`, `schema.txt` (the schema shown to the LLM), `example_questions.json`, `api.py` (`/api/ask`, streamed as Server-Sent Events) |
| `pipeline/` | Risk Assessment: `assess.py` (find candidates → profiles → evidence → report), `candidates.py` (parts-list candidates: catalogue product ids or vector search, then a fixed supplier query; no LLM), `profiles.py` (fixed, date-filtered exposure queries), `evidence.py` (risk engine calls), `report.py` (prompt sections and citation check), `prompts.py` (prompts and output schema), `llm.py` (the risk LLM), `retrieve.py` (vector search over product embeddings), `api.py` (`/api/assess`, `/api/runs`) |
| `runs_store.py`, `usage.py` | Saving runs to `runs/` and tracking daily token use |
| `reference/` | `locations.json` (map coordinates for suppliers, Dyson sites and ports without lat/lon) and `product_categories.json` (the product catalogue) |
| `tests/` | Backend tests |

## Saved runs

Every Ask the Graph run is saved to `runs/ask/` and every assessment to `runs/assess/`, one JSON file each. A file holds the full trace: prompts, raw and parsed model output, retries, citation checks, token usage, models, dates and settings. Runs are git-ignored until they are curated for the evaluation. Only one assessment runs at a time; starting another returns 409.

## Tests

```bash
.venv/bin/python -m unittest discover -s webapp/backend/tests -t .
```

Tests that need the graph use the live Neo4j and skip if it is unreachable. LLMs are replaced by fakes, so the tests make no paid calls.

## Notes

- Node IDs are `<kind>:<business key>`, e.g. `supplier:org:ihastek-malaysia-sdn-bhd` or `exit_port:port:57020`. Kinds: supplier, parent, buyer, shipment, product, exit_port, entry_port, carrier, vessel.
- The Cypher step and the risk LLM can use different models and providers. See the `ASK_CYPHER_*` and `REPORT_*` variables in the main README.
