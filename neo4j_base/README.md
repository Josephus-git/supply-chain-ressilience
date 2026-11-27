# neo4j_base: how the knowledge graph was built

| Step | How | Artefact |
|---|---|---|
| 1. Customs data | Pulled manually from ImportYeti | `data/` |
| 2. Clean and combine | Notebooks | `jupyter_notebooks/` → `data/processed/combined/combined.csv` |
| 3. Import into Neo4j | Neo4j Data Importer | `Supply chain nodes blueprint.zip` (`combined.csv` + `neo4j_importer_model.json`) |
| 4. Parent companies (`ParentCompany` nodes, `SUBSIDIARY_OF` relationships) | Added manually in the Neo4j interface; no script | Only in the backup `neo4j-2026-10-29T13-08-21.dump` |
| 5. Product embeddings (`Product.embedding`, vector index `embedding`) | `update_embeddings.py` (`text-embedding-3-small`, 1536 dimensions, cosine). Embeds "Full HS code description" + "Product description" for every Product node without one | `update_embeddings.py` |

To rebuild: restore the dump, then run `python neo4j_base/update_embeddings.py` (needs `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` and `OPENAI_API_KEY` in `.env`). The dump may not contain the embeddings; the script only fills nodes that have none, so running it is safe either way.
