# Web app

Plan: [WEB_APP_PLAN.md](../WEB_APP_PLAN.md). Phase 1 (backend skeleton) is in place;
the frontend arrives in phase 2.

## Run the backend

From the repository root (Neo4j running, `.env` filled in):

```bash
.venv/bin/uvicorn webapp.backend.main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

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
