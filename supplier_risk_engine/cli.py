"""Command-line adapter for testing and evaluation runs (plan section 8.3).

    python -m supplier_risk_engine query <payload.json> [--out result.json]
    python -m supplier_risk_engine run-all <dir> --out <dir> [--expected expected_ids.json]
    python -m supplier_risk_engine evidence <evidence_id>
    python -m supplier_risk_engine describe

Global options (before the command): --database DIR, --no-verify.

The CLI only reads files, calls the engine, and writes JSON. It contains no
matching or retrieval logic, so its results equal a direct
`lookup_suppliers(payload, records)` call.

Exit codes: 0 success; 1 a payload was rejected, an evidence ID was not
found, or a run-all result differs from the gold set; 2 usage, file, or
database errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .engine import describe_database, get_evidence, lookup_suppliers
from .loader import DatabaseError, LoadedDatabase, load_database

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ERROR = 2

SUMMARY_NAME = "_summary.json"


class CliError(Exception):
    """A usage or file error; reported on stderr with exit code 2."""


# --------------------------------------------------------------------------
# I/O helpers


def _dumps(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _write(data: Any, out: Path | None) -> None:
    text = _dumps(data)
    if out is None:
        sys.stdout.write(text)
        return
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot write {out}: {exc.strerror or exc}") from exc


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CliError(f"file not found: {path}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise CliError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"{path} is not valid JSON: {exc}") from exc


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _returned_ids(result: dict[str, Any]) -> list[list[str]]:
    """evidence_ids returned for each supplier, in result order."""
    return [
        [r["evidence_id"] for r in s.get("linked_reports", [])]
        for s in result.get("suppliers", [])
    ]


# --------------------------------------------------------------------------
# Commands


def cmd_query(args: argparse.Namespace, db: LoadedDatabase) -> int:
    result = lookup_suppliers(_read_json(args.payload), db.index)
    _write(result, args.out)
    if result["status"] != "completed":
        for err in result.get("errors", []):
            print(f"rejected: {err['field']}: {err['code']}: {err['message']}", file=sys.stderr)
        return EXIT_FAILED
    return EXIT_OK


def cmd_evidence(args: argparse.Namespace, db: LoadedDatabase) -> int:
    result = get_evidence(args.evidence_id, db.index)
    _write(result, args.out)
    return EXIT_OK if result["status"] == "found" else EXIT_FAILED


def cmd_describe(args: argparse.Namespace, db: LoadedDatabase) -> int:
    result = describe_database(db.index)
    result["database"] = {
        "path": str(db.path),
        "snapshot_source": db.snapshot_source,
        "manifest_sha256": db.manifest_sha256,
        "files": dict(sorted(db.file_hashes.items())),
        "warnings": list(db.warnings),
    }
    _write(result, args.out)
    return EXIT_OK


def _load_gold(path: Path) -> tuple[dict[Path, dict[str, Any]], dict[str, Any]]:
    gold = _read_json(path)
    fixtures = gold.get("fixtures") if isinstance(gold, dict) else None
    if not isinstance(fixtures, list):
        raise CliError(f"{path}: missing a 'fixtures' list")
    by_payload: dict[Path, dict[str, Any]] = {}
    for fixture in fixtures:
        payload = fixture.get("payload") if isinstance(fixture, dict) else None
        if not isinstance(payload, str):
            raise CliError(f"{path}: a fixture lacks a 'payload' path")
        by_payload[(path.parent / payload).resolve()] = fixture
    return by_payload, gold


def _compare(fixture: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    expected = set(fixture.get("expected_ids") or [])
    returned_lists = _returned_ids(result)
    returned = set(returned_lists[0]) if len(returned_lists) == 1 else set()
    entry: dict[str, Any] = {
        "fixture": fixture.get("fixture"),
        "expected": len(expected),
        "returned": len(returned),
        "missed": sorted(expected - returned),
        "unexpected": sorted(returned - expected),
    }
    if result.get("status") != "completed":
        entry["note"] = "payload rejected"
    elif len(returned_lists) != 1:
        entry["note"] = f"gold fixtures cover one supplier; result has {len(returned_lists)}"
    entry["passed"] = (
        result.get("status") == "completed"
        and len(returned_lists) == 1
        and not entry["missed"]
        and not entry["unexpected"]
    )
    return entry


def cmd_run_all(args: argparse.Namespace, db: LoadedDatabase) -> int:
    payload_dir: Path = args.payload_dir
    if not payload_dir.is_dir():
        raise CliError(f"payload directory not found: {payload_dir}")
    paths = sorted(p for p in payload_dir.glob("*.json") if p.is_file())
    if not paths:
        raise CliError(f"no payload files (*.json) in {payload_dir}")
    out_dir: Path = args.out
    if out_dir.resolve() == payload_dir.resolve():
        raise CliError("--out must differ from the payload directory")

    gold_by_payload: dict[Path, dict[str, Any]] = {}
    gold: dict[str, Any] | None = None
    if args.expected is not None:
        gold_by_payload, gold = _load_gold(args.expected)
        gold_sha = (gold.get("evidence_database") or {}).get("manifest_sha256")
        if gold_sha and db.manifest_sha256 and gold_sha != db.manifest_sha256:
            _warn(
                "the gold set was written against a different manifest.json; "
                "recheck the fixtures against the current records"
            )

    runs: list[dict[str, Any]] = []
    for path in paths:
        result = lookup_suppliers(_read_json(path), db.index)
        _write(result, out_dir / path.name)
        run: dict[str, Any] = {
            "payload": path.name,
            "status": result["status"],
            "returned_ids": _returned_ids(result),
        }
        if result["status"] != "completed":
            run["errors"] = result.get("errors", [])
        if gold is not None:
            fixture = gold_by_payload.get(path.resolve())
            run["gold"] = _compare(fixture, result) if fixture else None
        runs.append(run)

    rejected = [r["payload"] for r in runs if r["status"] != "completed"]
    summary: dict[str, Any] = {
        "data_snapshot_id": db.snapshot_id,
        "payload_dir": str(payload_dir),
        "payloads": len(runs),
        "completed": len(runs) - len(rejected),
        "rejected": rejected,
        "runs": runs,
    }
    failed = bool(rejected)

    if gold is not None:
        compared = [r["gold"] for r in runs if r["gold"] is not None]
        expected_total = sum(c["expected"] for c in compared)
        returned_total = sum(c["returned"] for c in compared)
        missed_total = sum(len(c["missed"]) for c in compared)
        unexpected_total = sum(len(c["unexpected"]) for c in compared)
        hits = expected_total - missed_total
        listed = {p.name for p in gold_by_payload if p.parent == payload_dir.resolve()}
        summary["gold"] = {
            "expected_file": str(args.expected),
            "fixtures_compared": len(compared),
            "fixtures_passed": sum(1 for c in compared if c["passed"]),
            "payloads_without_fixture": [r["payload"] for r in runs if r["gold"] is None],
            "fixtures_without_payload": sorted(listed - {p.name for p in paths}),
            "expected_ids": expected_total,
            "returned_ids": returned_total,
            "missed_ids": missed_total,
            "unexpected_ids": unexpected_total,
            "recall": round(hits / expected_total, 4) if expected_total else None,
            "precision": round(hits / returned_total, 4) if returned_total else None,
        }
        failed = failed or any(not c["passed"] for c in compared)

    _write(summary, out_dir / SUMMARY_NAME)
    _print_run_all(summary)
    return EXIT_FAILED if failed else EXIT_OK


def _print_run_all(summary: dict[str, Any]) -> None:
    lines = [f"{summary['completed']}/{summary['payloads']} payloads completed"]
    gold = summary.get("gold")
    for run in summary["runs"]:
        mark = run["status"]
        g = run.get("gold")
        if g is not None:
            mark = "pass" if g["passed"] else "FAIL"
            detail = ""
            if g["missed"]:
                detail += f" missed={','.join(g['missed'])}"
            if g["unexpected"]:
                detail += f" unexpected={','.join(g['unexpected'])}"
            mark += detail
        lines.append(f"  {run['payload']}: {mark}")
    if gold is not None:
        lines.append(
            f"gold: {gold['fixtures_passed']}/{gold['fixtures_compared']} fixtures passed; "
            f"missed {gold['missed_ids']}, unexpected {gold['unexpected_ids']}; "
            f"recall {gold['recall']}, precision {gold['precision']}"
        )
    print("\n".join(lines), file=sys.stderr)


# --------------------------------------------------------------------------
# Entry point


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m supplier_risk_engine",
        description="Supplier risk evidence engine: CLI adapter for testing and evaluation.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="evidence database directory (default: the package's risk_evidence/database/)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="load even if file hashes do not match manifest.json (mismatches become warnings)",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("query", help="run one payload")
    p.add_argument("payload", type=Path)
    p.add_argument("--out", type=Path, default=None, help="result file (default: stdout)")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("run-all", help="run every *.json payload in a directory")
    p.add_argument("payload_dir", type=Path)
    p.add_argument("--out", type=Path, required=True, help="directory for result files")
    p.add_argument(
        "--expected",
        type=Path,
        default=None,
        help="gold set (expected_ids.json) to compare returned evidence_ids against",
    )
    p.set_defaults(func=cmd_run_all)

    p = sub.add_parser("evidence", help="print the stored record behind an evidence_id")
    p.add_argument("evidence_id")
    p.add_argument("--out", type=Path, default=None)
    p.set_defaults(func=cmd_evidence)

    p = sub.add_parser("describe", help="study window, risk types, counts, snapshot ID")
    p.add_argument("--out", type=Path, default=None)
    p.set_defaults(func=cmd_describe)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        db = load_database(args.database, verify=not args.no_verify)
    except DatabaseError as exc:
        print("error: the evidence database could not be loaded:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_ERROR
    for warning in db.warnings:
        _warn(warning)
    try:
        return args.func(args, db)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
