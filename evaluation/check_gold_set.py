"""Run every reference_cypher in ask_gold_set.csv against the live graph.

Each query goes through the same read-only check as Ask the Graph (check_cypher),
then runs (run_query). Prints one line per question: ok/failed, row count, and any
problem. A gold query that fails the check or returns no rows must be fixed by
hand before the evaluation runs. Nothing is written to the graph.

    .venv/bin/python -m evaluation.check_gold_set
"""

from __future__ import annotations

import csv
from pathlib import Path

from webapp.backend.ask.pipeline import check_cypher, run_query
from webapp.backend.neo4j_client import ReadOnlyNeo4j

GOLD = Path(__file__).with_name("ask_gold_set.csv")


def main() -> None:
    client = ReadOnlyNeo4j()
    failed = 0
    try:
        with GOLD.open(newline="") as f:
            for row in csv.DictReader(f):
                if row["compare"] == "refusal":
                    # Unanswerable questions (option F). The optional proof query
                    # shows the graph has no such data: it must return n = 0.
                    if not row["reference_cypher"].strip():
                        print(f"{row['id']}  refusal  (no proof query: the graph has no such property)")
                        continue
                    result = run_query(client, row["reference_cypher"])
                    n = result["rows"][0].get("n") if result["ok"] and result["rows"] else None
                    if n == 0:
                        print(f"{row['id']}  refusal  ok  proof query returns n = 0")
                    else:
                        failed += 1
                        print(f"{row['id']}  REFUSAL PROOF FAILED  {result.get('error') or f'n = {n}'}")
                    continue
                check = check_cypher(client, row["reference_cypher"])
                if not check.ok:
                    failed += 1
                    print(f"{row['id']}  CHECK FAILED  {' '.join(check.problems)}")
                    continue
                result = run_query(client, check.cypher)
                if not result["ok"]:
                    failed += 1
                    print(f"{row['id']}  QUERY FAILED  {result['error']}")
                elif result["row_count"] == 0:
                    failed += 1
                    print(f"{row['id']}  NO ROWS")
                else:
                    print(f"{row['id']}  ok  {result['row_count']} rows")
    finally:
        client.close()
    print(f"\n{failed} question(s) need attention.")


if __name__ == "__main__":
    main()
