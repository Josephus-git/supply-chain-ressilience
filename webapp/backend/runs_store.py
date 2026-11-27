"""Stored runs: one JSON file per run under runs/<kind>/ (git-ignored).

Ask the Graph writes to runs/ask/; Risk Assessment will write to runs/assess/.
The evaluation (deferred) reads these files.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_RUN_ID = re.compile(r"^[a-z]+-\d{8}T\d{6}Z-[0-9a-f]{6}$")


def new_run_id(kind: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{kind}-{stamp}-{secrets.token_hex(3)}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valid_run_id(run_id: str) -> bool:
    return bool(_RUN_ID.match(run_id))


def save_run(directory: Path, run: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run['run_id']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(run, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def load_run(directory: Path, run_id: str) -> dict[str, Any] | None:
    if not valid_run_id(run_id):
        return None
    path = directory / f"{run_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def find_run(directories: list[Path], run_id: str) -> dict[str, Any] | None:
    """The first stored run with this id in any of the folders."""
    for d in directories:
        run = load_run(d, run_id)
        if run is not None:
            return run
    return None


def list_runs(directory: Path, limit: int = 50) -> list[dict[str, Any]]:
    """Newest first. Unreadable files are skipped."""
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.json"), reverse=True)[:limit]:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out
