"""Thin, documented ImportYeti REST client."""

import logging
import time
from typing import Any
from urllib.parse import quote

import requests

from dyson_supply_chain.config import Settings

LOGGER = logging.getLogger(__name__)


class ImportYetiError(RuntimeError):
    """An API or transport failure."""


class ImportYetiClient:
    endpoint = "/v1.0/company/{company}/bols"

    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()

    def search_bols(self, params: dict[str, Any]) -> dict[str, Any]:
        request_params = dict(params)
        company_slug = request_params.pop("company_slug", None)
        if not isinstance(company_slug, str) or not company_slug.strip():
            raise ImportYetiError("A company URL slug is required")
        headers = {"IYApiKey": self.settings.api_key, "Accept": "application/json"}
        url = (
            f"{self.settings.base_url}/v1.0/company/"
            f"{quote(company_slug.strip(), safe='-_')}/bols"
        )
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = self.session.get(
                    url, params=request_params, headers=headers, timeout=self.settings.timeout_seconds
                )
            except requests.RequestException as exc:
                if attempt >= self.settings.max_retries:
                    raise ImportYetiError("Network request failed after retries") from exc
                self._backoff(attempt, "network error")
                continue

            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt >= self.settings.max_retries:
                    raise ImportYetiError(f"Transient API error {response.status_code}")
                self._backoff(attempt, f"HTTP {response.status_code}")
                continue
            if response.status_code >= 400:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text[:500]
                raise ImportYetiError(f"API error {response.status_code}: {detail}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise ImportYetiError("API returned malformed JSON") from exc
            if not isinstance(payload, dict):
                raise ImportYetiError("API returned a non-object JSON response")
            return payload
        raise AssertionError("unreachable")

    def _backoff(self, attempt: int, reason: str) -> None:
        delay = self.settings.retry_base_seconds * (2**attempt)
        LOGGER.warning("Retrying ImportYeti request after %s in %.1fs", reason, delay)
        time.sleep(delay)
