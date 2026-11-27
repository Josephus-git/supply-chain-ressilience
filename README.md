# Knowledge graph and LLM decision support for supply-chain resilience

MSc project: a Dyson case study. US customs records of Dyson's inbound shipments are loaded into a Neo4j knowledge graph. A curated, dated store of supply-chain risk evidence sits beside it. A web app lets a user explore the graph, ask it questions in plain English, and get supplier recommendations for a parts list on a chosen date, with every claim cited to a graph figure or an evidence record.

The research question is how such GraphRAG recommendations can be evaluated for **factual precision**, **decision provenance** and **operational utility**.

## How it fits together

```
ImportYeti customs data ──► notebooks (clean, combine) ──► combined.csv ──► Neo4j knowledge graph
                                                                              │  + parent companies (manual)
                                                                              │  + product embeddings
                                                                              ▼
Risk evidence store (dated JSON) ──► risk evidence engine ──►  web app backend (FastAPI)  ◄── LLMs (OpenAI by default)
                                                                 │  Ask the Graph: question → Cypher → answer
                                                                 │  Risk Assessment: parts list + date → cited recommendation
                                                                 ▼
                                                         runs/  (every run saved as JSON)
                                                                 ▼
                                                 evaluation notebook (reads saved runs only)
```

- **Knowledge graph.** Suppliers, shipments, products (HS codes), exit and entry ports, carriers, vessels, buyers and parent companies. About 478 shipments, 2 Jan 2025 to 28 Sep 2026. All app access is read-only.
- **Risk evidence engine** (`supplier_risk_engine/`). A file-based store of about 110 dated evidence records in 18 risk types: tariffs, port disruption, natural hazards, financial distress and so on. Each record carries its source and limitations. The engine links records to suppliers by country, parent company, ports, carriers and other keys, and only returns what was known by the requested date. It makes no LLM calls.
- **Ask the Graph.** Text-to-Cypher: an LLM writes a Cypher query from the question. The query is checked to be read-only and valid against the schema, then run, with one automatic retry. A second call writes the answer from the returned rows only.
- **Risk Assessment.** For a parts list and an `as_of_date`, the system finds candidate suppliers in the graph and builds their exposure profiles from fixed, date-filtered queries. It fetches the evidence that applies to them from the engine. A risk LLM then ranks the candidates and must cite an evidence id or graph figure for every claim; otherwise it answers "I don't have enough data to support that". Citations are checked and flagged, never corrected, so mistakes stay visible for evaluation.

## Repository layout

| Path | What it holds |
|---|---|
| `data/` | Raw ImportYeti responses, per-supplier CSVs, cleaned CSVs, and `processed/combined/combined.csv` (the graph's source) |
| `jupyter_notebooks/` | Data preparation: `yeti_json_to_csv`, `yeti_response_data_analysis`, `yeti_csv_cleaning_for_knowledge_graph`, `processed_csv_combine` |
| `neo4j_base/` | How the graph was built: Data Importer model, database dump, embeddings script. See [neo4j_base/README.md](neo4j_base/README.md) |
| `supplier_risk_engine/` | Risk evidence engine, its evidence database (`risk_evidence/database/`), CLI, example payloads and tests. See [risk_evidence/README.md](supplier_risk_engine/risk_evidence/README.md) |
| `webapp/backend/` | FastAPI app: graph, home, evidence and product APIs; `ask/` (Ask the Graph); `pipeline/` (Risk Assessment); `reference/` (map locations, product catalogue); tests |
| `webapp/frontend/` | React, Vite and TypeScript front end (Tailwind, shadcn/ui, Cytoscape for the graph) |
| `evaluation/` | Evaluation inputs and helper scripts (see [Evaluation](#evaluation)) |
| `runs/` | Saved Ask and Risk Assessment runs (git-ignored until curated for the evaluation) |
| `langchain/` | Early prototypes (`cypher_qa.py`, `simple_agent.py`); not used by the app |
| `WEB_APP_PLAN.md` | Design and build log of the web app |

## Setup

**Requirements:** Python 3.13, Node.js (for the front end), Neo4j 5 or later, and an OpenAI API key.

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd webapp/frontend && npm install
```

**Graph.** Restore `neo4j_base/neo4j-2026-10-29T13-08-21.dump` into Neo4j, then run `.venv/bin/python neo4j_base/update_embeddings.py` to fill any missing product embeddings. See [neo4j_base/README.md](neo4j_base/README.md).

**`.env`** in the repository root:

| Variable | Needed for |
|---|---|
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | Everything that reads the graph |
| `OPENAI_API_KEY` | LLM calls and embeddings |
| `ASK_CYPHER_PROVIDER`, `ASK_CYPHER_MODEL`, `REPORT_PROVIDER`, `REPORT_MODEL` | Optional: change the model for the Cypher step or the risk LLM (providers `openai`, `ollama`, `anthropic`; default `openai` with `gpt-5.2`). `anthropic` also needs `ANTHROPIC_API_KEY`; `ollama` needs a local Ollama server |
| `ASSESS_GRAPH_OFF=1` | Optional: no-graph baseline for the evaluation, where the risk LLM gets only country-level evidence. Default off |

## Running the app

```bash
cd webapp/backend && npm start     # API on http://localhost:8000 (docs at /docs)
cd webapp/frontend && npm run dev  # app on http://localhost:5173
```

For a single-process demo, run `npm run build` in `webapp/frontend` once. The backend then serves the app at http://localhost:8000; restart it after the first build. More detail is in [webapp/README.md](webapp/README.md).

**Pages**
- **Home:** headline figures, a map of supplier-to-Dyson routes, and monthly shipments for the top suppliers.
- **Graph Explorer:** the graph centred on Dyson's suppliers, expandable on demand, with filters for date and node type.
- **Ask the Graph:** a question in plain English, with every step shown: the generated Cypher, the safety check, the rows and the answer.
- **Risk Assessment:** a parts list (picked from the product catalogue or typed), a goal and an as-of date, chosen or random. Returns ranked suppliers per item with cited claims, the deciding factor and country notes, and keeps a history of past runs.
- **Risk Library:** browse and inspect the risk evidence records.

Each Ask or Risk Assessment run is saved to `runs/ask/` or `runs/assess/` as JSON. A run file holds the full trace: the prompts, raw and parsed model output, citation checks, retries, token usage, models used and dates. Only one assessment runs at a time, and a warning appears near the daily token allowance.

## Risk evidence engine on its own

```bash
.venv/bin/python -m supplier_risk_engine describe
.venv/bin/python -m supplier_risk_engine query supplier_risk_engine/examples/payloads/<payload>.json
.venv/bin/python -m supplier_risk_engine run-all supplier_risk_engine/examples/payloads --out <dir> \
    --expected supplier_risk_engine/examples/expected_ids.json
```

## Evaluation

The evaluation scores the app's saved outputs; it does not re-run the app. The pipeline runs here, against Neo4j and the LLM APIs, and stores everything the evaluation needs in the run files. The evaluation notebook then reads only those files and the labelling sheets, and produces every figure, table and statistic.

| File | Purpose |
|---|---|
| `evaluation/ask_gold_set.csv` | 35 Ask questions with reference Cypher: 30 answerable, scored by execution accuracy (same rows as the reference query), and 5 unanswerable, where the system should decline |
| `evaluation/assess_sample.csv` | Risk Assessment sample: 20 in-scope parts lists (catalogue and typed items, random and event dates) and 8 out-of-scope lists for refusal tests |
| `evaluation/expected_products.csv` | Accepted products for each typed item, for scoring candidate retrieval |
| `evaluation/embedding_calibration.csv` | Similarity scores used to set the minimum score for product matching |
| `evaluation/check_gold_set.py` | Runs every reference query against the graph and reports failures |
| `evaluation/calibrate_embedding_threshold.py` | Produces the calibration scores |

```bash
.venv/bin/python -m evaluation.check_gold_set
.venv/bin/python -m evaluation.calibrate_embedding_threshold
```

**Status (27 Nov 2026):** the evaluation design and inputs are fixed. Embedding-based candidate retrieval for Risk Assessment's parts list is built (top 3 products per typed item, minimum score 0.69). Still to build: a batch runner that writes `runs/evaluation/` with a manifest, the labelling-sheet generator, and the notebook (`jupyter_notebooks/evaluation.ipynb`).

## Tests

```bash
.venv/bin/python -m unittest discover -s webapp/backend/tests -t .          # backend (graph tests skip if Neo4j is unreachable)
.venv/bin/python -m unittest discover -s supplier_risk_engine/tests -t .    # engine
```

The tests make no paid LLM calls.

## Known data limitations

- **Track record means volume and recency only.** Customs records are completed arrivals, so there is no data on late, failed or rejected deliveries.
- **HS codes are sometimes misdeclared** (e.g. vacuum parts declared as clothing or dog food), and product descriptions are noisy. Product nodes are HS codes, so one node can cover many different goods.
- **Entity resolution is left as it is in the source data.** For example, one Hi-P plant appears under two supplier names.
- **The reported supplier country can differ from the address country.**
- **Risk evidence is not linked to suppliers by id**, only by country, parent company, ports and similar keys, so country-level links are broad.
