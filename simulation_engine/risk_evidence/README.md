# Risk evidence database

This folder contains the simulation engine's historical evidence dataset.
Each JSON file has a record template and a `records` array; records are added
directly to the database files as research proceeds. This is a file-based
database, not a database server or a working simulation. The research is limited to a small, selected set of
suppliers, countries, products, and routes; these must be defined before
collecting reports.

The case study concerns Dyson. The user supplied product descriptions spanning
vacuum cleaners, hair-care equipment, filtering machinery, batteries,
components and other categories. Verify actual shipment and product details
in the graph before treating evidence as applicable. See the
[case-study scope](../../RISK_EVIDENCE_DATASET_PLAN.md).

## Product-context review

The eight populated categories were reviewed against the supplied product
descriptions. This is exploratory, not exhaustive, and the descriptions do not
establish what Dyson shipped or what its suppliers used.

- Border/customs: existing reports are contextual; the China magnet-delay
  lead remained inaccessible and was not added as a verified incident.
- Carrier/vessel: cargo contents and case-study shipment matches remain
  generally unknown.
- Currency: Dyson reported unfavorable currency developments in its 2025
  results; the company statement does not identify a currency pair or an
  affected shipment. Other records are reference-rate comparisons.
- Cyberattack: the existing company-related claim remains unverified; product
  descriptions do not establish an incident.
- Energy/transport costs: existing fuel, electricity and freight observations
  are market context, not supplier invoices or product-specific costs.
- Geopolitical conflict: existing events provide route or trade context, not
  proof of an affected case-study shipment.
- Goods in transit: three reported US lithium-ion battery handling incidents
  are product-category context, not verified Dyson shipments. Their individual
  original FAA entries were not independently verified.
- Government restrictions: the Chinese rare-earth announcement lists specific
  magnets; listed motorized products are only potentially relevant pending
  component specifications and transaction-level legal review.
- Input material shortages: contextual reports cover resins and plastics
  feedstocks, rare-earth materials, and semiconductors. Reduced production
  capacity or force majeure does not by itself prove a market-wide shortage,
  and the supplied product descriptions do not establish material composition
  or dependency on a reported supplier.
- Labour disruption: strikes and a disputed warehouse labour action provide
  manufacturing and logistics context. A strike's end is not necessarily a
  return to normal production or delivery; disputed operational impacts and
  unverified supply-chain links must remain labelled.

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
  dates, a `basis`, an explanatory `note`, and optional structured
  `anchor_date` and `anchor_basis` for date-based candidate
  retrieval. `event_date` means a known event date; `report_date` or
  `document_date` identifies when a source reported an issue, not when it
  began or ended; `claim_date` identifies an unverified claim. An
  `observation_period` is a comparison window, not continuous observations;
  `month_approximation` or `year_approximation` expands a reported month or year to calendar dates for
  searching only. A window is not a verified incident interval, and its
  absence outside a query is not proof of no overlap.
- Every actual evidence record must have non-null `search_window.start` and
  `search_window.end` in ISO `YYYY-MM-DD` format, with start on or before
  end. Use a defensible, labelled retrieval anchor; do not invent dates.
  If no suitable anchor is available, do not add the item as a completed
  evidence record until one is found. Template placeholders may remain null:
  they are not records. A future loader must explicitly report and reject
  records with missing, invalid, or reversed search dates, not silently skip
  them. No loader or automated enforcement exists yet.
- `scenario_estimate` windows include an illustrative scenario end, and can
  also include later documented milestones. `report_date_buffer` expands a
  report, document or claim anchor by 14 calendar days in each direction
  solely for retrieval; it is not an estimated recovery period. The
  `anchor_basis` distinguishes these dates from an incident date. Neither
  type proves continuous impact or complete recall.
- `event_date_buffer` expands a known incident anchor for retrieval only;
  its end is not a measured incident end, disruption, or recovery. A
  qualitative company currency statement is not a numerical exchange-rate
  observation: its currency pair and rate values remain unknown.
- `study_period_bound` is a retrieval interval from a documented or
  attributed effective date to the study cutoff when the legal end date is
  unknown. The cutoff is not an expiry date or proof that the original rule
  remained unchanged. Confirm later amendments and actual applicability
  against authoritative sources before using a restriction.
- `scenario_recovery`, when non-null, is a low-confidence hypothetical
  handling-delay assumption with a scope, anchor, severity, minimum and maximum
  elapsed days. The illustrative subjective buckets are minor 1–3, moderate
  3–7 and severe 7–14 days; they are not calibrated or inferred recovery
  observations. Explicitly opt in and review the scope before using one.
  A null assumption means no estimate, not zero duration. Currency, price,
  report-only and unverified-claim records have no recovery estimates.
- A scenario's day range is measured from its own `anchor_date`; it can refer
  to a later recovery milestone rather than the incident date. It does not
  imply a total outage, a probability, supplier exposure, or the end of
  response, shipment replacement or recovery. Known milestones can extend
  past the scenario range; related records do not represent separate events.
- Future retrieval must return the window's basis and note, distinguish
  candidates from verified temporal matches, and not treat missing event
  endpoints as zero-duration events or definitive non-overlaps. Search-window
  dates are indexing aids, not inferred event dates or impact probabilities.
- For a query `[start, end]`, future retrieval should include overlapping
  documented windows and, when duration is unknown, optionally search known
  event-date anchors from `start` minus a caller-configured number of days
  through `end`. Label lookback-only results as assumed candidates, return the
  configured value and anchor, and never treat the lookback as an observed
  event duration. For example, a seven-day lookback includes an event on March 3
  in a March 10 query; it does not prove seven days of disruption.
- Report-date anchors are not incident dates: provide a separately configured
  forward report-date search allowance if desired and label those results as
  report-date candidates. Neither finite allowance guarantees recall. A simulation
  impact duration must be an explicit, independently scoped scenario
  assumption, not the retrieval lookback.
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
- Store observed facts and their provenance separately from the explicitly
  labelled, optional `scenario_recovery` assumptions. Simulation probabilities
  and other impact assumptions belong in scenario inputs; an incident report
  does not automatically establish a probability.
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
