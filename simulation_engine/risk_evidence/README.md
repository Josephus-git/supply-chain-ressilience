# Risk evidence database

This folder contains the simulation engine's historical evidence dataset.
Each JSON file has a record template and a `records` array; records are added
directly to the database files as research proceeds. This is a file-based
database, not a database server or a working simulation. The research is limited to a small, selected set of
suppliers, countries, products, and routes; these must be defined before
collecting reports.

## Layout

- `database/`: the working evidence files for the 18 selected risk factors
  and the study manifest.
- `snapshots/<snapshot-id>/`: optional historical copies, not the working
  files. Existing snapshots are retained as previously collected.

When collecting evidence, copy the relevant `record_template` into the same
file's `records` array and populate the copied record. Keep the template as a
guide; it is not itself evidence or a JSON Schema definition. Only actual
reviewed records belong in `records`. Update the study manifest with sources
searched, coverage and limitations. A future loader must read records rather
than treating templates as evidence.

## Conventions

- `null` means a value is unknown or not supplied; an empty array means no
  entries have been recorded. Neither implies zero risk or a clean supplier.
- Use ISO 8601 dates (`YYYY-MM-DD`). Record event dates, publication dates,
  retrieval dates, and tariff effective dates separately; do not infer them.
- Populated risk files use `search_window` with inclusive `start` and `end`
  dates, a `basis` and an explanatory `note` for date-based candidate
  retrieval. `event_date` means a known event date; `report_date` or
  `document_date` identifies when a source reported an issue, not when it
  began or ended; `claim_date` identifies an unverified claim. An
  `observation_period` is a comparison window, not continuous observations;
  `month_approximation` expands a reported month to calendar dates for
  searching only. A window is not a verified incident interval, and its
  absence outside a query is not proof of no overlap.
- Future retrieval must return the window's basis and note, distinguish
  candidates from verified temporal matches, and not treat missing event
  endpoints as zero-duration events or definitive non-overlaps. Search-window
  dates are indexing aids, not inferred event dates or impact probabilities.
- Store a verified country name alongside its ISO 3166-1 alpha-2 code where
  available (for example, `Malaysia` and `MY`). Use `null` for an unknown
  name or code; do not guess. For multiple countries, use an array of objects
  pairing `country_name` with `country_code`; replace the blank example
  object with actual entries, or use `[]` if none are recorded.
- A future lookup should accept either a country name or code, normalize
  case and whitespace, and use a reviewed name/alias-to-code mapping. Reject
  ambiguous or conflicting name/code pairs instead of silently selecting a
  country; preserve the distinction between country, state, territory, and
  tariff origin. These files alone do not implement lookup.
- `source` records identify the source of a factual claim. Record a URL,
  publisher, publication and retrieval dates, and relevant licence or
  access conditions when known. Do not copy full copyrighted reports.
- `scope` describes what a report actually covers. Supplier, port, and
  country IDs must not be inferred from similar names without review.
- `related_evidence_ids` links a cause and its reported effects, such as a
  flood and a resulting port closure. It does not imply they should be
  counted as independent disruptions.
- A location or identity match alone does not prove that a shipment was
  affected. Any future matching must distinguish reviewed links from
  uncertain or rejected ones.
- Store observed facts and their provenance here. Simulation probabilities
  and impact assumptions belong in separately labelled scenario inputs; an
  incident report does not automatically establish a probability.
- Specify rate units, currency, dates, classification and conditions for
  tariffs and other costs. Supplier country alone does not establish product
  origin or tariff applicability.
- Do not commit credentials, confidential information, unnecessary personal
  data, or material that the source licence does not permit you to share.

For reproducible experiments, retain an immutable version or export of the
working files and record its coverage, limitations, source conditions, and
file hashes. Updating the working database does not update an earlier export.
The detailed collection and matching approach is in the
[evidence dataset plan](../../RISK_EVIDENCE_DATASET_PLAN.md).
