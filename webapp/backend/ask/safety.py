"""Step 2 of Ask the Graph: check LLM-written Cypher before it runs.

Three layers keep the graph safe and the browser responsive:

1. `static_checks` (no database): strips Markdown fences, refuses more than one
   statement, write and admin clauses (CREATE, MERGE, DELETE, SET, REMOVE,
   DROP, LOAD CSV, FOREACH, ...) and procedure calls outside a short read-only
   allowlist. String literals, comments and backticked names are blanked out
   first, so `CONTAINS 'set'` or `` `Entry Port` `` do not trip the checks.
2. `ReadOnlyNeo4j.explain` (in `pipeline.check_cypher`): the query must compile,
   and labels, relationship types and properties must exist in the database
   (server notifications 01N50/01N51/01N52).
3. Every query runs in a read-only session, so the server rejects writes even
   if a check were missed.

A `LIMIT` is appended when the query does not end with one, and the driver
stops reading at `MAX_ROWS` either way.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

MAX_ROWS = 200

WRITE_CLAUSES = [
    "CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE", "DROP", "FOREACH",
    "LOAD CSV", "ALTER", "RENAME", "GRANT", "DENY", "REVOKE", "TERMINATE",
    "START DATABASE", "STOP DATABASE", "SHOW", "USE", "FINISH",
]

# Read-only procedures the LLM may reasonably call to inspect the schema.
ALLOWED_PROCEDURES = {
    "db.labels", "db.relationshiptypes", "db.propertykeys",
    "db.schema.visualization", "db.schema.nodetypeproperties", "db.schema.reltypeproperties",
}

# Unknown label / relationship type / property key.
UNKNOWN_NAME_CODES = {"01N50", "01N51", "01N52"}

_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?\s*```\s*$", re.S)
_TRAILING_LIMIT = re.compile(r"\bLIMIT\s+(\d+|\$\w+)\s*$", re.I)
_PROCEDURE_CALL = re.compile(r"\bCALL\s+([A-Za-z_][\w.]*)\s*(?=\(|\bYIELD\b|$)", re.I)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class CheckResult:
    ok: bool
    cypher: str  # the query that will run (fences stripped, LIMIT added)
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(name, ok, detail))
        self.ok = self.ok and ok

    @property
    def problems(self) -> list[str]:
        return [c.detail for c in self.checks if not c.ok]

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "cypher": self.cypher, "checks": [asdict(c) for c in self.checks]}


def strip_fences(text: str) -> str:
    """Remove a Markdown code fence and a leading `cypher` word if the LLM added them."""
    text = text.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1).strip()
    if re.match(r"^cypher\s*\n", text, re.I):
        text = text.split("\n", 1)[1].strip()
    return text


def mask_literals(cypher: str) -> str:
    """Blank out string literals, backticked names and comments, keeping offsets."""
    out: list[str] = []
    i, n = 0, len(cypher)
    while i < n:
        c = cypher[i]
        if c in "'\"`":
            j = i + 1
            while j < n and cypher[j] != c:
                j += 2 if cypher[j] == "\\" and c != "`" else 1
            j = min(j + 1, n)
            out.append(c + " " * (j - i - 2) + (c if j - i >= 2 else ""))
            i = j
        elif cypher.startswith("//", i):
            j = cypher.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
        elif cypher.startswith("/*", i):
            j = cypher.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(" " * (j - i))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def static_checks(raw: str, *, max_rows: int = MAX_ROWS) -> CheckResult:
    cypher = strip_fences(raw).strip()
    masked = mask_literals(cypher)
    # A trailing semicolon is harmless; anything after one is a second statement.
    if masked.rstrip().endswith(";"):
        cut = masked.rstrip().rfind(";")
        cypher, masked = cypher[:cut].rstrip(), masked[:cut].rstrip()
    result = CheckResult(ok=True, cypher=cypher)

    if not cypher:
        result.add("not_empty", False, "The model returned no Cypher.")
        return result
    result.add("not_empty", True, "Cypher returned.")

    if ";" in masked:
        result.add("single_statement", False, "More than one statement (found ';'). Send one query.")
    else:
        result.add("single_statement", True, "One statement.")

    upper = re.sub(r"\s+", " ", masked.upper())
    found = [w for w in WRITE_CLAUSES if re.search(rf"\b{w}\b", upper)]
    if found:
        result.add("read_only", False, f"Write or admin clause not allowed: {', '.join(found)}.")
    else:
        result.add("read_only", True, "No write or admin clauses.")

    procs = [p for p in _PROCEDURE_CALL.findall(masked) if p.lower() not in ALLOWED_PROCEDURES]
    if procs:
        result.add("procedures", False, f"Procedure calls not allowed: {', '.join(sorted(set(procs)))}.")
    else:
        result.add("procedures", True, "No procedure calls outside the read-only allowlist.")

    if not re.search(r"\bRETURN\b", upper):
        result.add("returns_rows", False, "The query has no RETURN clause.")
    else:
        result.add("returns_rows", True, "Has a RETURN clause.")

    if result.ok:
        m = _TRAILING_LIMIT.search(masked)
        if m is None:
            result.cypher = f"{cypher}\nLIMIT {max_rows}"
            result.add("row_limit", True, f"Added LIMIT {max_rows}.")
        elif m.group(1).isdigit() and int(m.group(1)) > max_rows:
            result.cypher = cypher[: m.start()] + f"LIMIT {max_rows}"
            result.add("row_limit", True, f"Lowered LIMIT {m.group(1)} to {max_rows}.")
        else:
            result.add("row_limit", True, f"Query already has LIMIT {m.group(1)}.")
    return result


def explain_check(result: CheckResult, notifications: list[dict[str, str]] | None, error: str | None) -> None:
    """Fold the EXPLAIN outcome into `result`."""
    if error is not None:
        result.add("compiles", False, f"EXPLAIN failed: {error}")
        return
    result.add("compiles", True, "EXPLAIN compiled the query.")
    unknown = [n["description"] for n in notifications or [] if n["code"] in UNKNOWN_NAME_CODES]
    if unknown:
        result.add("schema_names", False, " ".join(_short(d) for d in unknown))
    else:
        result.add("schema_names", True, "Every label, relationship type and property exists.")
    other = [n for n in notifications or [] if n["code"] not in UNKNOWN_NAME_CODES]
    for n in other:
        # Performance hints (e.g. cartesian product) are shown but do not block.
        result.checks.append(Check("server_note", True, f"{n['code']}: {_short(n['description'])}"))


def _short(description: str) -> str:
    # "warn: label does not exist. The label `X` does not exist in database `neo4j`. Verify ..."
    parts = [p.strip() for p in description.split(". ") if p.strip()]
    keep = [p for p in parts if "`" in p] or parts[:1]
    return ". ".join(keep).replace(" in database `neo4j`", "").rstrip(".") + "."
