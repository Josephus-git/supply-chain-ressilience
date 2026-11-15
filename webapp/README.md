# Web app

Plan: [WEB_APP_PLAN.md](../WEB_APP_PLAN.md). Phase 1 (backend) and phase 2
(frontend shell, Home page, Graph Explorer) are in place.

## Run the backend

From the repository root (Neo4j running, `.env` filled in):

```bash
.venv/bin/uvicorn webapp.backend.main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

## Run the frontend

Development (hot reload, `/api` proxied to the backend on :8000):

```bash
cd webapp/frontend
npm install        # first time only
npm run dev        # http://localhost:5173
```

Demo (one process): build once, then the backend serves the app at `/`.

```bash
cd webapp/frontend && npm run build
cd ../.. && .venv/bin/uvicorn webapp.backend.main:app --port 8000   # http://localhost:8000
```

The backend only looks for `webapp/frontend/dist` at startup, so restart it after the first build.

## Pages

- **Home:** KPI tiles, a world map of supplier → Dyson arcs (toggle to real
  routes: supplier → exit port → US entry port → Dyson site; click a supplier
  for its products, ports and carriers), and monthly shipments for the top 10
  companies (chart or table).
- **Graph Explorer:** opens on the busiest supplier, with shipments aggregated
  into labelled links. Choose suppliers, search, filter by arrival date and node
  type, and change the layout. Click a node or link to inspect it. Expand
  neighbours (double-click works too), expand a link into its shipments, hide
  nodes, or add a supplier to the snapshot. The state lives in the URL
  (`?suppliers=…&from=…&to=…&full=1`), so a view can be shared or bookmarked.
- Risk Assessment, Evidence Library, Run History and Ask the Graph are
  placeholders until phases 3–5.

## Tests

```bash
.venv/bin/python -m unittest discover -s webapp/backend/tests -t .
```

The tests use the live Neo4j and skip if it is unreachable. They make no
OpenAI calls.

## Notes

- All Neo4j access is read-only (`neo4j_client.ReadOnlyNeo4j`); writes are
  rejected by the server.
- Node IDs are `<kind>:<business key>`, e.g. `supplier:org:ihastek-malaysia-sdn-bhd`,
  `exit_port:port:57020`. Kinds: supplier, parent, buyer, shipment, product,
  exit_port, entry_port, carrier, vessel.
- Map coordinates for suppliers, Dyson sites and ports without lat/lon live in
  `backend/reference/locations.json` (city-level, from each stored address).
