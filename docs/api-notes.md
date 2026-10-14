# Verified ImportYeti API notes

Source: official documentation at <https://docs.importyeti.com/> (consulted 2026-10-13).

- Base URL: `https://data.importyeti.com`.
- Authentication: `IYApiKey` header (Bearer authentication is also documented, but this project uses the explicit header).
- Company BOL route: `GET /v1.0/company/{company}/bols`; `{company}` must be an ImportYeti URL slug, not a display/legal name. Resolve other names through `GET /v1.0/company/search`.
- Relevant parameters: `start_date`, `end_date`, `page_size`, `offset`, and `fields`; dates are `mm/dd/yyyy`.
- Company BOL records are returned in `data` as a list. Continue using `offset` while a full page is returned; the endpoint may not include a total count.
- Stable record identifier: `bol_number`.
- Documented errors include 400, 401, 403, 404, 429, and 500. No fixed rate limit is published.

The default company URL slug is `dyson`. Use another slug explicitly when targeting a distinct company profile; a company profile's records are not a comprehensive global shipment history.
