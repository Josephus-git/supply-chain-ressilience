"""Read-only Neo4j access for the web app.

Every query runs in a session opened with `default_access_mode=READ` inside a
managed read transaction, so the server rejects any write (CREATE, MERGE, SET,
DELETE, ...) with a client error. The app never needs to write to the graph.

Each call can append an entry to a `log` list (Cypher, parameters, row count,
timing). The assessment trace and `runs/` use this to show every query run.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Iterable

import neo4j
from neo4j import GraphDatabase
from neo4j.graph import Node, Path, Relationship
from neo4j.time import Date as NeoDate
from neo4j.time import DateTime as NeoDateTime

from .config import Neo4jSettings, neo4j_settings

# Large properties that are never sent to the browser.
HIDDEN_PROPERTIES = {"embedding"}


def to_jsonable(value: Any) -> Any:
    """Convert Neo4j values to JSON-safe Python values.

    Midnight-UTC datetimes (every shipment date in this graph) become plain
    `YYYY-MM-DD` dates; other temporal values become ISO strings.
    """
    if isinstance(value, NeoDateTime):
        value = value.to_native()
    if isinstance(value, NeoDate):
        value = value.to_native()
    if isinstance(value, datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Node):
        return {"labels": sorted(value.labels), "properties": clean_properties(value)}
    if isinstance(value, Relationship):
        return {"type": value.type, "properties": clean_properties(value)}
    if isinstance(value, Path):
        return [to_jsonable(n) for n in value.nodes]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def _clean_property(key: str, value: Any) -> Any:
    # Codes such as vessel_code are stored as floats (9706308.0); show them as integers.
    if key.endswith("_code") and isinstance(value, float) and value.is_integer():
        return int(value)
    return to_jsonable(value)


def clean_properties(entity: Node | Relationship | dict) -> dict[str, Any]:
    return {k: _clean_property(k, v) for k, v in entity.items() if k not in HIDDEN_PROPERTIES}


class ReadOnlyNeo4j:
    def __init__(self, settings: Neo4jSettings | None = None):
        self.settings = settings or neo4j_settings()
        self.driver = GraphDatabase.driver(
            self.settings.uri, auth=(self.settings.username, self.settings.password)
        )

    def close(self) -> None:
        self.driver.close()

    def verify(self) -> None:
        self.driver.verify_connectivity()

    def _session(self) -> neo4j.Session:
        return self.driver.session(
            database=self.settings.database,
            default_access_mode=neo4j.READ_ACCESS,
        )

    def read(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        log: list[dict[str, Any]] | None = None,
        name: str | None = None,
        raw: bool = False,
        log_params: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Run `cypher` in a read transaction and return rows as dicts.

        `raw=True` keeps Neo4j value types (needed when the caller wants Node
        objects); otherwise rows are converted with `to_jsonable`.
        `log_params` limits which parameters are logged (e.g. to leave out a
        1536-dim query vector).
        """
        params = params or {}
        started = time.perf_counter()

        def work(tx: neo4j.ManagedTransaction) -> list[neo4j.Record]:
            return list(tx.run(cypher, params))

        with self._session() as session:
            records = session.execute_read(work)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        rows = [dict(r) for r in records] if raw else [to_jsonable(r.data()) for r in records]
        if log is not None:
            shown = params if log_params is None else {k: params[k] for k in log_params if k in params}
            log.append(
                {
                    "name": name,
                    "cypher": cypher.strip(),
                    "params": to_jsonable(shown),
                    "row_count": len(rows),
                    "elapsed_ms": elapsed_ms,
                }
            )
        return rows
