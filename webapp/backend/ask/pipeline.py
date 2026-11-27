"""Ask the Graph (Text2Cypher) as a plain async generator.

    generate_cypher -> check_cypher -> run_query -> (one retry) -> write_answer

`ask()` yields one event per step so FastAPI can stream them as Server-Sent
Events and the page can show each step as it happens. `GraphCypherQAChain` is
not used because it hides the intermediate steps. LangChain does the LLM work
(`prompt | llm | StrOutputParser()`, `.ainvoke` / `.astream`); everything else
is ordinary Python.

Event shapes (all JSON objects with an `event` key):
    {"event": "run",   "run": {...header...}}
    {"event": "step",  "step": <name>, "attempt": n, "status": "running"|"done"|"failed", "data": {...}}
    {"event": "token", "text": "..."}                (answer tokens)
    {"event": "done",  "run": {...full run...}}      (also saved to runs/ask/)
    {"event": "error", "message": "..."}

If the checks fail, the query errors or it returns no rows, the problem goes
back to `generate_cypher` for one retry; both attempts stay in the trace.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from neo4j.exceptions import Neo4jError
from neo4j.graph import Node, Path as NeoPath, Relationship

from ..config import ASK_CYPHER_MODEL, ASK_RUNS_DIR
from ..graph_model import label_of, node_out
from ..neo4j_client import ReadOnlyNeo4j, to_jsonable
from ..runs_store import new_run_id, now_iso, save_run
from ..usage import usage_totals
from .prompts import FEW_SHOT, RETRY_FEEDBACK, answer_prompt, cypher_prompt
from .safety import MAX_ROWS, CheckResult, explain_check, mask_literals, static_checks

ASK_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = ASK_DIR / "schema.txt"
EXAMPLES_PATH = ASK_DIR / "example_questions.json"

MAX_ATTEMPTS = 2
# Rows passed to the answer prompt (the page shows all fetched rows).
ANSWER_ROWS = 60
ANSWER_CHARS = 12_000
# Most nodes handed to the page for a result's graph (the inline view draws up
# to 150 of them; the Graph Explorer takes the rest).
GRAPH_NODE_CAP = 800
# Row cap for the companion query that fetches the nodes behind value-only rows.
NODE_QUERY_ROWS = 2000

Event = dict[str, Any]


@lru_cache(maxsize=1)
def schema_text() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8").strip()


def load_examples() -> list[dict[str, Any]]:
    return json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))["questions"]


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


# --------------------------------------------------------------------------- steps


async def generate_cypher(
    llm: BaseChatModel, question: str, previous: dict[str, Any] | None = None, *, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    feedback = ""
    if previous is not None:
        feedback = RETRY_FEEDBACK.format(cypher=previous["cypher"], problem=previous["problem"])
    values = {"examples": FEW_SHOT, "schema": schema_text(), "question": question, "feedback": feedback}
    prompt_text = cypher_prompt.format(**values)
    started = time.perf_counter()
    raw = await (cypher_prompt | llm | StrOutputParser()).ainvoke(values, config=config)
    return {
        "prompt": prompt_text,
        "feedback": previous,
        "raw": raw,
        "elapsed_ms": _ms(started),
    }


def check_cypher(client: ReadOnlyNeo4j, raw: str, *, max_rows: int = MAX_ROWS) -> CheckResult:
    result = static_checks(raw, max_rows=max_rows)
    if not result.ok:
        return result
    try:
        notes = client.explain(result.cypher)
        explain_check(result, notes, None)
    except Neo4jError as e:
        explain_check(result, None, _neo4j_message(e))
    return result


def run_query(client: ReadOnlyNeo4j, cypher: str, *, max_rows: int = MAX_ROWS) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        raw_rows = client.read(cypher, raw=True, max_rows=max_rows + 1)
    except Neo4jError as e:
        return {"ok": False, "error": _neo4j_message(e), "elapsed_ms": _ms(started)}
    truncated = len(raw_rows) > max_rows
    raw_rows = raw_rows[:max_rows]
    elapsed = _ms(started)
    columns = list(raw_rows[0].keys()) if raw_rows else []
    rows = [{k: _cell(v) for k, v in r.items()} for r in raw_rows]
    graph = rows_graph(client, raw_rows)
    if graph is None and raw_rows:
        graph = companion_graph(client, cypher)
    return {
        "ok": True,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": elapsed,
        "graph": graph,
    }


def answer_values(question: str, cypher: str, result: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("rows") or []
    shown = rows[:ANSWER_ROWS]
    text = json.dumps(shown, ensure_ascii=False, default=str)
    cut = len(text) > ANSWER_CHARS
    if cut:
        text = text[:ANSWER_CHARS] + " …"
    notes = []
    if result.get("truncated"):
        notes.append(f"; capped at {MAX_ROWS} rows")
    if len(rows) > len(shown) or cut:
        notes.append(f"; only the first {len(shown)} rows are shown below")
    return {
        "question": question,
        "cypher": cypher,
        "rows": text if rows else "(no rows)",
        "row_count": len(rows),
        "truncated_note": "".join(notes),
    }


# --------------------------------------------------------------------------- rows -> table cells and graph


def _node_ref(node: Node) -> dict[str, Any]:
    kind = label_of(sorted(node.labels))
    if kind is None:
        return {"$node": {"id": node.element_id, "kind": None, "name": ":".join(sorted(node.labels))}}
    out = node_out(sorted(node.labels), dict(node))
    return {"$node": {"id": out["id"], "kind": out["kind"], "name": out["name"]}}


def _cell(value: Any) -> Any:
    """Table cell: nodes and relationships become small references the page renders as chips."""
    if isinstance(value, Node):
        return _node_ref(value)
    if isinstance(value, Relationship):
        return {"$rel": {"type": value.type}}
    if isinstance(value, NeoPath):
        return {"$path": [_node_ref(n)["$node"] for n in value.nodes], "length": len(value.relationships)}
    if isinstance(value, dict):
        return {k: _cell(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_cell(v) for v in value]
    return to_jsonable(value)


def _walk(value: Any, nodes: dict[str, Node], rels: dict[str, Relationship]) -> None:
    if isinstance(value, Node):
        nodes.setdefault(value.element_id, value)
    elif isinstance(value, Relationship):
        rels.setdefault(value.element_id, value)
        for n in (value.start_node, value.end_node):
            if n is not None and n.labels:
                nodes.setdefault(n.element_id, n)
    elif isinstance(value, NeoPath):
        for n in value.nodes:
            nodes.setdefault(n.element_id, n)
        for r in value.relationships:
            rels.setdefault(r.element_id, r)
    elif isinstance(value, dict):
        for v in value.values():
            _walk(v, nodes, rels)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _walk(v, nodes, rels)


CONNECT_QUERY = """
MATCH (a)-[r]->(b)
WHERE elementId(a) IN $ids AND elementId(b) IN $ids
RETURN elementId(a) AS source, type(r) AS type, elementId(b) AS target
LIMIT 5000
"""


_NODE_VAR = re.compile(r"\(\s*([A-Za-z_]\w*)\s*(?=[:){])")
_REL_VAR = re.compile(r"\[\s*([A-Za-z_]\w*)\s*(?=[:\]*{])")
_PATH_VAR = re.compile(r"\b([A-Za-z_]\w*)\s*=\s*(?:shortestPath|allShortestPaths)?\s*\(")
_NOT_DEFINED = re.compile(r"Variable `([^`]+)` not defined")
_KEYWORDS = {"distinct", "not", "and", "or", "xor", "in", "is", "null", "true", "false", "case", "exists"}


def _last_top_level_return(masked: str) -> int | None:
    """Offset of the final RETURN outside any (), [] or {} (so not a subquery's)."""
    depth, last = 0, None
    for m in re.finditer(r"[()\[\]{}]|\bRETURN\b|\bUNION\b", masked, re.I):
        tok = m.group(0)
        if tok in "([{":
            depth += 1
        elif tok in ")]}":
            depth -= 1
        elif depth == 0:
            if tok.upper() == "UNION":
                return None  # several RETURNs feed one result; not worth rewriting
            last = m.start()
    return last


def node_query(cypher: str) -> tuple[str, list[str]] | None:
    """The same query with its final RETURN swapped for the variables it matched.

    Rows of plain values (names, counts) carry no nodes to draw; this returns
    the nodes and relationships behind them instead. Variables that are out of
    scope at the RETURN are dropped later, by `companion_graph`, using EXPLAIN.
    """
    masked = mask_literals(cypher)
    at = _last_top_level_return(masked)
    if at is None:
        return None
    head = masked[:at]
    names: list[str] = []
    for rx in (_NODE_VAR, _REL_VAR, _PATH_VAR):
        for m in rx.finditer(head):
            v = m.group(1)
            if v.lower() not in _KEYWORDS and v not in names:
                names.append(v)
    if not names:
        return None
    return cypher[:at].rstrip(), names


def companion_graph(client: ReadOnlyNeo4j, cypher: str) -> dict[str, Any] | None:
    built = node_query(cypher)
    if built is None:
        return None
    head, names = built
    while names:
        q = f"{head}\nRETURN DISTINCT {', '.join(names)}\nLIMIT {NODE_QUERY_ROWS}"
        if not static_checks(q, max_rows=NODE_QUERY_ROWS).ok:
            return None
        try:
            client.explain(q)
        except Neo4jError as e:
            m = _NOT_DEFINED.search(e.message or str(e))
            if m and m.group(1) in names:
                names.remove(m.group(1))
                continue
            return None
        try:
            raw_rows = client.read(q, raw=True, max_rows=NODE_QUERY_ROWS + 1)
        except Neo4jError:
            return None
        graph = rows_graph(client, raw_rows[:NODE_QUERY_ROWS])
        if graph is not None:
            graph.update(source="query", cypher=q, rows_capped=len(raw_rows) > NODE_QUERY_ROWS)
        return graph
    return None


def rows_graph(client: ReadOnlyNeo4j, raw_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Nodes found in the rows, plus the relationships among them.

    Relationships that are not in the rows are filled in with one extra
    read-only query, so returned nodes appear connected as they are in the graph.
    """
    found: dict[str, Node] = {}
    rels: dict[str, Relationship] = {}
    for row in raw_rows:
        _walk(row, found, rels)
    if not found:
        return None
    if len(found) > GRAPH_NODE_CAP:
        return {"nodes": [], "edges": [], "omitted": True, "node_count": len(found), "source": "rows"}
    by_element: dict[str, dict[str, Any]] = {}
    for element_id, node in found.items():
        if label_of(sorted(node.labels)) is None:
            continue
        by_element[element_id] = node_out(sorted(node.labels), dict(node))
    pairs = {(r.start_node.element_id, r.type, r.end_node.element_id) for r in rels.values()}
    try:
        for row in client.read(CONNECT_QUERY, {"ids": list(by_element)}):
            pairs.add((row["source"], row["type"], row["target"]))
    except Neo4jError:
        pass  # the graph view is a convenience; the rows are what matter
    edges = []
    for src, rel, tgt in sorted(pairs):
        if src in by_element and tgt in by_element:
            s, t = by_element[src]["id"], by_element[tgt]["id"]
            edges.append({"id": f"rel|{s}|{rel}|{t}", "source": s, "target": t, "type": rel, "aggregated": False})
    return {"nodes": list(by_element.values()), "edges": edges, "omitted": False, "node_count": len(by_element), "source": "rows"}


def _neo4j_message(e: Neo4jError) -> str:
    msg = (e.message or str(e)).strip()
    return msg.split("\n\n")[0][:600]


# --------------------------------------------------------------------------- orchestration


def _problem(check: CheckResult, result: dict[str, Any] | None) -> str | None:
    if not check.ok:
        return " ".join(check.problems)
    if result is None:
        return None
    if not result["ok"]:
        return f"The query failed: {result['error']}"
    if result["row_count"] == 0:
        return (
            "The query ran but returned no rows. Check the filters: names typed in the question may "
            "be spelled differently in the data, so match a shorter fragment of the name (for example "
            "its first word) with toLower(...) CONTAINS; dates are DATETIME values."
        )
    return None


async def ask(
    question: str,
    *,
    client: ReadOnlyNeo4j,
    llm: BaseChatModel,
    model_name: str = ASK_CYPHER_MODEL,
    runs_dir: Path | None = ASK_RUNS_DIR,
    max_attempts: int = MAX_ATTEMPTS,
    arm: str | None = None,
) -> AsyncIterator[Event]:
    question = question.strip()
    run: dict[str, Any] = {
        "run_id": new_run_id("ask"),
        "kind": "ask",
        "question": question,
        "model": model_name,
        "arm": arm,
        "started_at": now_iso(),
        "finished_at": None,
        "status": "running",
        "max_rows": MAX_ROWS,
        "attempts": [],
        "answer": None,
        "usage": None,
        "error": None,
    }
    usage = UsageMetadataCallbackHandler()
    llm_config = {"callbacks": [usage]}
    calls = 0
    yield {"event": "run", "run": {k: run[k] for k in ("run_id", "question", "model", "arm", "started_at", "max_rows")}}

    try:
        previous: dict[str, Any] | None = None
        final: tuple[str, dict[str, Any]] | None = None  # (cypher, result) used for the answer
        for n in range(1, max_attempts + 1):
            attempt: dict[str, Any] = {"attempt": n, "generate": None, "check": None, "run": None}
            run["attempts"].append(attempt)

            yield {"event": "step", "step": "generate_cypher", "attempt": n, "status": "running", "data": {"retry_of": previous}}
            calls += 1
            gen = await generate_cypher(llm, question, previous, config=llm_config)
            attempt["generate"] = gen
            yield {"event": "step", "step": "generate_cypher", "attempt": n, "status": "done", "data": gen}

            yield {"event": "step", "step": "check_cypher", "attempt": n, "status": "running", "data": {}}
            started = time.perf_counter()
            check = await asyncio.to_thread(check_cypher, client, gen["raw"])
            attempt["check"] = {**check.to_dict(), "elapsed_ms": _ms(started)}
            yield {
                "event": "step", "step": "check_cypher", "attempt": n,
                "status": "done" if check.ok else "failed", "data": attempt["check"],
            }

            result = None
            if check.ok:
                yield {"event": "step", "step": "run_query", "attempt": n, "status": "running", "data": {"cypher": check.cypher}}
                result = await asyncio.to_thread(run_query, client, check.cypher)
                attempt["run"] = result
                yield {
                    "event": "step", "step": "run_query", "attempt": n,
                    "status": "done" if result["ok"] else "failed", "data": result,
                }
                if result["ok"]:
                    final = (check.cypher, result)  # an empty result still beats an error

            problem = _problem(check, result)
            attempt["problem"] = problem
            if problem is None:
                break
            previous = {"cypher": check.cypher, "problem": problem}

        if final is None:
            run["status"] = "failed"
            run["error"] = "No valid query after %d attempts: %s" % (len(run["attempts"]), previous["problem"] if previous else "")
            yield {"event": "error", "message": run["error"]}
        else:
            cypher, result = final
            values = answer_values(question, cypher, result)
            answer: dict[str, Any] = {"prompt": answer_prompt.format(**values), "text": "", "elapsed_ms": None}
            run["answer"] = answer
            yield {"event": "step", "step": "write_answer", "attempt": None, "status": "running", "data": {"prompt": answer["prompt"]}}
            started = time.perf_counter()
            calls += 1
            async for chunk in (answer_prompt | llm | StrOutputParser()).astream(values, config=llm_config):
                if chunk:
                    answer["text"] += chunk
                    yield {"event": "token", "text": chunk}
            answer["elapsed_ms"] = _ms(started)
            yield {
                "event": "step", "step": "write_answer", "attempt": None, "status": "done",
                "data": {"text": answer["text"], "elapsed_ms": answer["elapsed_ms"]},
            }
            run["status"] = "answered" if result["row_count"] else "no_rows"
    except asyncio.CancelledError:
        run["status"] = "cancelled"
        raise
    except Exception as e:  # LLM/network failures: report and keep the trace
        run["status"] = "failed"
        run["error"] = f"{type(e).__name__}: {e}"
        yield {"event": "error", "message": run["error"]}
    finally:
        run["finished_at"] = now_iso()
        run["usage"] = {**usage_totals(usage), "calls": calls}
        if runs_dir is not None and question:
            save_run(runs_dir, run)
    yield {"event": "done", "run": run}
