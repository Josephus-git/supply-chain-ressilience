# Verified ImportYeti API notes

Source: official documentation at <https://docs.importyeti.com/> (consulted 2026-10-13).

- Base URL: `https://data.importyeti.com`.
- Authentication: `IYApiKey` header (Bearer authentication is also documented, but this project uses the explicit header).
- Search route: `GET /v1.0/powerquery/us-import/bols`.
- Relevant parameters: `company`, `product_description`, `start_date`, `end_date`, `page_size`, `offset` and `page`; dates are `mm/dd/yyyy`.
- PowerQuery records are under `data.data`; the match total is `data.totalCount`.
- Stable record identifier: `bol_number`.
- Documented errors include 400, 401, 403, 404, 429, and 500. No fixed rate limit is published.

The default `company=Dyson` is configurable because the docs do not define a canonical set of Dyson legal-name variants. Search variants and filters must be supplied deliberately and are recorded in each manifest.

