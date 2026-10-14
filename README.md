# Dyson Supply Chain Data Extraction

This project is the initial, deliberately limited foundation for Dyson supply-chain research. It retrieves US-import bill-of-lading records returned by the documented ImportYeti PowerQuery API. It does not implement monitoring, knowledge graphs, GraphRAG, tariff analysis, or supplier recommendations.

## Setup (Ubuntu)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Put the private key in `.env` as `IMPORTYETI_API_KEY`. The API key is sent only in the `IYApiKey` request header and is never logged.

## Run

Validate configuration and inspect the request without consuming API credits:

```bash
dyson-extract --dry-run
```

Run a small sample first:

```bash
dyson-extract --max-pages 1
```

Run the configured extraction:

```bash
dyson-extract --company-slug dyson
```

The CLI uses `GET /v1.0/company/{company}/bols`, where `company` is an ImportYeti URL slug, not a display or legal name. It defaults to the Dyson profile slug `dyson`; override it with `--company-slug` when needed. The endpoint's `page_size`/`offset` pagination is followed until the final page, and optional `--start-date`/`--end-date` filters use `mm/dd/yyyy`. Raw response envelopes are written to `data/raw`, normalized rows to `data/processed`, manifests to `data/manifests`, and logs to `logs`. These outputs are ignored by Git.

## Tests

```bash
pytest
```

Tests must use mocked API responses and never spend live credits.

## Coverage and limitations

An extraction represents only records returned by the exact ImportYeti queries recorded in its manifest. It must not be described as Dyson's entire global supply chain. ImportYeti documents US and Mexico datasets, but this foundation intentionally targets the US-import BOL endpoint. The API publishes no fixed request-rate limit; transient 429/5xx responses are retried with bounded exponential backoff. API credit availability and search/account restrictions remain external prerequisites.
