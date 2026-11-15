"""Read the JSON evidence database and pass its records to the engine.

The loader is an adapter (plan section 3): it does file access and integrity
checks only, and contains no matching or retrieval logic.

    db = load_database()               # risk_evidence/database/ by default
    lookup_suppliers(payload, db.index)

Checks, all against the files on disk:

- every data file parses, is named `<risk_type>.json` after the `risk_type`
  it holds, and has a `records` list;
- each file's sha256 equals the value in manifest.json, and the manifest and
  the directory list the same files;
- evidence IDs are unique across files (enforced by `build_index`).

A failed check raises `DatabaseError` listing every problem, unless
`verify=False`, in which case hash and file-list mismatches become
`warnings` on the returned database. Parse and shape errors always raise.

The data snapshot ID is the manifest's `snapshot_id` when one is set (and
all entries agree). Otherwise the loader computes it from the sha256 of each
data file's bytes, so it changes whenever any stored record changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .engine import EvidenceIndex, build_index

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE_DIR = PACKAGE_DIR / "risk_evidence" / "database"
MANIFEST_NAME = "manifest.json"
SNAPSHOT_PREFIX = "db-sha256:"


class DatabaseError(Exception):
    """The database could not be loaded. `problems` lists each issue."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class LoadedDatabase:
    path: Path
    records: dict[str, list[dict[str, Any]]]
    file_hashes: dict[str, str]  # file name -> sha256 of its bytes
    manifest_sha256: str | None
    snapshot_id: str
    snapshot_source: str  # "manifest" or "computed"
    index: EvidenceIndex
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def record_count(self) -> int:
        return sum(len(v) for v in self.records.values())


def compute_snapshot_id(file_hashes: dict[str, str]) -> str:
    """Fingerprint of the data files: sha256 over sorted `name:sha256` lines."""
    lines = "".join(f"{name}:{digest}\n" for name, digest in sorted(file_hashes.items()))
    return SNAPSHOT_PREFIX + hashlib.sha256(lines.encode("utf-8")).hexdigest()[:16]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path, problems: list[str]) -> tuple[Any, bytes] | None:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        problems.append(f"{path.name}: cannot be read ({exc.strerror or exc})")
        return None
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        problems.append(f"{path.name}: not valid JSON ({exc})")
        return None


def _manifest_files(manifest: Any, problems: list[str]) -> tuple[dict[str, str], list[Any]]:
    """Map file name -> expected sha256, and collect the snapshot_id values."""
    expected: dict[str, str] = {}
    snapshot_ids: list[Any] = []
    entries = manifest.get("records") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        problems.append(f"{MANIFEST_NAME}: missing a 'records' list")
        return expected, snapshot_ids
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append(f"{MANIFEST_NAME}: a manifest entry is not an object")
            continue
        snapshot_ids.append(entry.get("snapshot_id"))
        for item in entry.get("files") or []:
            name = item.get("path") if isinstance(item, dict) else None
            digest = item.get("sha256") if isinstance(item, dict) else None
            if not isinstance(name, str) or not isinstance(digest, str):
                problems.append(f"{MANIFEST_NAME}: a file entry lacks path or sha256")
                continue
            if name in expected and expected[name] != digest:
                problems.append(f"{MANIFEST_NAME}: {name} is listed with two hashes")
            expected[name] = digest
    return expected, snapshot_ids


def load_database(path: str | Path | None = None, *, verify: bool = True) -> LoadedDatabase:
    """Load every risk-type file in `path` and build the engine index."""
    db_dir = Path(path) if path is not None else DEFAULT_DATABASE_DIR
    if not db_dir.is_dir():
        raise DatabaseError([f"database directory not found: {db_dir}"])

    fatal: list[str] = []
    integrity: list[str] = []

    manifest_path = db_dir / MANIFEST_NAME
    manifest_sha256: str | None = None
    expected: dict[str, str] = {}
    snapshot_ids: list[Any] = []
    if manifest_path.is_file():
        loaded = _read_json(manifest_path, fatal)
        if loaded is not None:
            manifest, raw = loaded
            manifest_sha256 = _sha256(raw)
            expected, snapshot_ids = _manifest_files(manifest, fatal)
    else:
        integrity.append(f"{MANIFEST_NAME} not found; file hashes cannot be checked")

    records: dict[str, list[dict[str, Any]]] = {}
    file_hashes: dict[str, str] = {}
    for file_path in sorted(db_dir.glob("*.json")):
        if file_path.name == MANIFEST_NAME:
            continue
        loaded = _read_json(file_path, fatal)
        if loaded is None:
            continue
        data, raw = loaded
        file_hashes[file_path.name] = _sha256(raw)
        if not isinstance(data, dict):
            fatal.append(f"{file_path.name}: top level is not an object")
            continue
        risk_type = data.get("risk_type")
        if risk_type != file_path.stem:
            fatal.append(
                f"{file_path.name}: risk_type {risk_type!r} does not match the file name"
            )
            continue
        file_records = data.get("records")
        if not isinstance(file_records, list) or not all(
            isinstance(r, dict) and isinstance(r.get("evidence_id"), str) for r in file_records
        ):
            fatal.append(f"{file_path.name}: 'records' must be a list of objects with evidence_id")
            continue
        records[risk_type] = file_records

    if not file_hashes and not fatal:
        fatal.append(f"no risk-type files found in {db_dir}")

    if manifest_path.is_file():
        for name in sorted(set(file_hashes) - set(expected)):
            integrity.append(f"{name}: not listed in {MANIFEST_NAME}")
        for name in sorted(set(expected) - set(file_hashes)):
            integrity.append(f"{name}: listed in {MANIFEST_NAME} but missing")
        for name in sorted(set(expected) & set(file_hashes)):
            if expected[name] != file_hashes[name]:
                integrity.append(
                    f"{name}: sha256 {file_hashes[name][:12]}... differs from "
                    f"{MANIFEST_NAME} {expected[name][:12]}..."
                )

    if fatal or (verify and integrity):
        raise DatabaseError(fatal + integrity)

    distinct = set(snapshot_ids)
    if len(distinct) == 1 and isinstance(snapshot_ids[0], str) and snapshot_ids[0]:
        snapshot_id, source = snapshot_ids[0], "manifest"
    else:
        if any(distinct - {None, ""}):
            integrity.append(f"{MANIFEST_NAME}: snapshot_id values disagree; computed instead")
        snapshot_id, source = compute_snapshot_id(file_hashes), "computed"

    try:
        index = build_index(records, data_snapshot_id=snapshot_id)
    except ValueError as exc:  # duplicate evidence_id
        raise DatabaseError([str(exc)]) from exc

    return LoadedDatabase(
        path=db_dir,
        records=records,
        file_hashes=file_hashes,
        manifest_sha256=manifest_sha256,
        snapshot_id=snapshot_id,
        snapshot_source=source,
        index=index,
        warnings=tuple(integrity),
    )
