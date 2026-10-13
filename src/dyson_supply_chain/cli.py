"""Command-line entry point."""

import argparse
from datetime import datetime
from pathlib import Path

from .config import Settings
from .importyeti.client import ImportYetiClient
from .importyeti.extractor import extract
from .logging_config import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract documented ImportYeti US-import BOL records")
    parser.add_argument("--company", default="Dyson", help="Documented company filter value")
    parser.add_argument("--product-description", help="Optional documented product_description filter")
    parser.add_argument("--start-date", help="mm/dd/yyyy")
    parser.add_argument("--end-date", help="mm/dd/yyyy")
    parser.add_argument("--max-pages", type=int, help="Bounded sample mode")
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true", help="Validate configuration and print filters")
    args = parser.parse_args()
    settings = Settings.from_env()
    filters = {"company": args.company}
    if args.product_description:
        filters["product_description"] = args.product_description
    if args.start_date:
        filters["start_date"] = args.start_date
    if args.end_date:
        filters["end_date"] = args.end_date
    if args.dry_run:
        print({"endpoint": ImportYetiClient.endpoint, "filters": filters, "page_size": settings.page_size})
        return 0
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    configure_logging(Path("logs") / f"extraction-{stamp}.log")
    manifest = extract(
        ImportYetiClient(settings), filters, Path("data/raw") / f"{stamp}.jsonl",
        Path("data/processed") / f"{stamp}.jsonl", Path("data/manifests") / f"{stamp}.json",
        settings.page_size, args.start_offset, args.max_pages,
    )
    print(f"{manifest['status']}: {manifest['stats']}")
    return 0

