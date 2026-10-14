"""Offset pagination against the documented PowerQuery response shape."""

from collections.abc import Iterator
from typing import Any, Callable

from .models import BOLPage


def iter_pages(
    fetch: Callable[[dict[str, Any]], dict[str, Any]],
    filters: dict[str, Any],
    page_size: int,
    start_offset: int = 0,
) -> Iterator[tuple[int, BOLPage]]:
    offset = start_offset
    while True:
        params = {**filters, "page_size": page_size, "offset": offset}
        page = BOLPage.from_response(fetch(params))
        yield offset, page
        if not page.records:
            break
        if page.total_count is not None:
            if offset + len(page.records) >= page.total_count:
                break
        elif len(page.records) < page_size:
            break
        offset += len(page.records)
