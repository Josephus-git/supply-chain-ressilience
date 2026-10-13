"""Resumable extraction orchestration."""

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from .client import ImportYetiClient
from .models import ExtractionStats, validate_record
from .pagination import iter_pages
from .storage import append_jsonl, write_json

LOGGER = logging.getLogger(__name__)


def extract(
    client: ImportYetiClient,
    filters: dict[str, Any],
    raw_path: Path,
    normalized_path: Path,
    manifest_path: Path,
    page_size: int,
    start_offset: int = 0,
    max_pages: int | None = None,
) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    started = datetime.now(timezone.utc).isoformat()
    stats = ExtractionStats()
    seen: set[str] = set()
    status = "partial"
    manifest: dict[str, Any] = {
        "run_id": run_id, "started_at": started, "filters": filters,
        "endpoint": client.endpoint, "page_size": page_size, "pages_processed": [],
        "status": status, "outputs": {"raw": str(raw_path), "normalized": str(normalized_path)},
    }
    try:
        for page_number, (offset, page) in enumerate(
            iter_pages(client.search_bols, filters, page_size, start_offset), start=1
        ):
            if max_pages is not None and page_number > max_pages:
                break
            stats.pages += 1
            stats.retrieved += len(page.records)
            append_jsonl(raw_path, [{"run_id": run_id, "offset": offset, "response": page.raw}])
            normalized: list[dict[str, Any]] = []
            for record in page.records:
                bol = record.get("bol_number")
                if not isinstance(bol, str) or bol in seen:
                    stats.deduplicated += 1
                    continue
                seen.add(bol)
                errors = validate_record(record)
                normalized.append({**record, "_validation_errors": errors, "_run_id": run_id})
                if errors:
                    stats.rejected += 1
                else:
                    stats.retained += 1
            append_jsonl(normalized_path, normalized)
            manifest["pages_processed"].append({"offset": offset, "records": len(page.records), "total_count": page.total_count})
            manifest.update({"api_total_count": page.total_count, "credits_remaining": page.credits_remaining})
            write_json(manifest_path, {**manifest, "stats": stats.__dict__})
            LOGGER.info("Processed offset %s: %s records (total %s)", offset, len(page.records), page.total_count)
            if max_pages is not None and page_number >= max_pages:
                break
        status = "completed" if max_pages is None or stats.pages < max_pages else "partial"
    except Exception as exc:
        stats.errors.append(str(exc))
        LOGGER.exception("Extraction failed")
        raise
    finally:
        manifest.update({"status": status, "finished_at": datetime.now(timezone.utc).isoformat(), "stats": stats.__dict__})
        write_json(manifest_path, manifest)
    return manifest

