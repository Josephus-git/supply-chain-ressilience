# Historical risk evidence dataset plan

Status: **implementation in progress**. Evidence collection has begun; the
working files contain reviewed records with documented limitations, not a
complete or validated dataset. This plan complements the
[simulation engine plan](./SIMULATION_ENGINE_PLAN.md).

## 1. Purpose

Create a small, reproducible collection of historical evidence for the
case-study period from January 2025 through September 2026. Match relevant records to supplier and shipment
context from Neo4j, then use them to inform explicitly labelled analysis
scenarios and, where applicable, tariff calculations.

The dataset is not a complete catalogue of all supplier risks or all US
tariffs. A missing record means **no matching evidence was found in the
selected evidence version**, not that no risk or event exists.

## 2. Storage recommendation

For the first research prototype, use **versioned JSON files**, separate
from Neo4j. JSON is a file format rather than a database; a small collection
of files and Python loaders is enough initially. The graph remains the source
of historical supplier, shipment, product, and port relationships. The
evidence collection stores incident reports and tariff rules and references
graph entities only when a match has been verified.

Current file-based database and optional historical-copy layout:

```text
simulation_engine/risk_evidence/
  database/
    manifest.json
    entity_matches.json
    <risk-factor>.json
  snapshots/
    <snapshot-id>/
      manifest.json
      <risk-factor>.json
      entity_matches.json
```

There is a working file for each of the 18 selected risk factors. Add
reviewed evidence directly to its `records` array and retain the
`record_template` as a guide, not evidence. Update the working manifest with
the sources searched, scope and limitations. See
[the database instructions](./simulation_engine/risk_evidence/README.md).

The working database is mutable. For each experiment retain an immutable
version or export and its hashes so results remain reproducible; existing
snapshot folders are historical copies, not the collection target. Versions
can be reviewed with Git, provided source permissions and data sensitivity
allow redistribution. Avoid committing confidential material, credentials,
personal data, or copyrighted full-text reports. Keep appropriate source
references and separately documented provenance.

| Choice | Benefits | Trade-offs |
| --- | --- | --- |
| JSON working files with versioned experiment inputs | Simple, auditable, local, no second service; suitable for a small study. | Manual schemas, indexes, migrations, and more difficult concurrent updates or complex searches. |
| JSON/document database | Useful when many records, concurrent edits, or indexed queries are needed. | More setup, hosting, backup, access control, and cost. |
| Neo4j | Useful if incident-to-entity and temporal relationships become central to graph analysis. | New graph schema, temporal relationships, matching/provenance complexity, and possible contamination of observed versus inferred links. |

Use JSON files first. Move to a database only if scale, query performance,
collaboration, or operational requirements justify it. Neo4j remains a valid
later option; keeping the evidence separate does not prevent linking records
to graph entity IDs through a reviewed matching table.

## 3. Research scope and dates

Before collecting data, choose:

1. A fixed analysis period from `2025-01-01` through `2026-09-30`, inclusive
   (21 months).
2. The case-study company names below, together with the relevant products,
   shipment routes, countries, and ports verified from the graph.
3. Initial categories: **flood incidents**, **cyber incidents**, and
   **tariff rules**. Other approved risk factors can be added later with
   category-specific schemas and credible sources.
4. Whether each experiment is a historical case study or a future
   hypothetical scenario informed by a historical evidence version.

### Country scope

The research covers these countries:

- Singapore
- Malaysia
- Philippines
- United States
- Taiwan
- China

Delaware is a US state and is included within the United States, not as a
separate country. The Cayman Islands is a British Overseas Territory and is
outside the country-only scope. Verify graph values and entity locations
before matching evidence or applying country-level rules; incorporation in a
location does not establish that operations occur there.

### Case-study company names

The following names were provided as the research scope. They are listed
exactly as supplied and grouped only to preserve the supplied context: a
group does **not** establish that the names are aliases, the same legal
entity, parent and subsidiary, or located at the same facility.

**Flex**

- Flex Ltd.
- Flextronics Shah Alam
- Flextronics Technology Penang Sdn
- Flextronics Shah Alam Sdn Bhd
- Flextronics

**Hi-P**

- Hi-P International Pte. Ltd.
- Hi P Philippines Technology Corpora
- Hip Philipines Technology

**Meiban**

- Meiban Group Pte. Ltd.
- Dymon Asia Private Equity
- Meiban Technologies (Malaysia) Sdn. Bhd.
- Meiban Technologies Malaysia Sdn
- Meiban Technologies M Sdn Bhd

**V.S. Industry**

- V.S. Industry Berhad
- Vs Industrial Berhad
- Vs Industrial Philippines

**Syarikat Sin Kwang**

- Syarikat Sin Kwang Plastic Industries Sdn. Bhd.
- Syarikat Sin Kwang Plastic Industri

**HEICO and Wencor**

- HEICO Corporation
- Wencor Group, LLC
- Wencor M
- Wencor Group

**Kinpo**

- Kinpo Electronics, Inc.
- Kinpo Electronics Philippines Inc
- Kinpo Electronics Philippines

**Malata, Intretech, and Ihastek**

- Shenzhen Malata Electronic Industrial Co., Ltd.
- Xiamen Intretech Inc.
- Xiamen Ihastek Co., Ltd.
- Ihastek Malaysia
- Ihastek Malaysia Sdn Bhd

Treat every name as a separate unresolved search target until verified.
Names that appear similar may refer to different companies, facilities, or
locations. Verify legal identity, location, relevant dates, and any corporate
relationship using credible sources and graph IDs before recording a match.
Do not propagate a company-specific incident to another name or location
solely because of similarity or grouping. Keep uncertain matches as possible,
not confirmed. The geographic scope is listed above, but do not infer an
individual company's country or location solely from its name.

Evidence records should store the verified country name and ISO 3166-1
alpha-2 code where available, for example `Malaysia` and `MY`. Leave either
field null if unknown. For records covering multiple countries, store a list
of paired name/code objects rather than separate lists that can become
misaligned. The future evidence lookup should accept a name or code, normalize
case and whitespace, and use a reviewed alias mapping. It should surface
ambiguous names or conflicting pairs, not silently choose a match. Geographic
labels in the graph still need verification before country-level matching.
The JSON templates provide field guides; no lookup has been implemented yet.

For incidents, use event start/end dates and document missing or uncertain
dates. Publication and retrieval dates are separate. This historical period
alone is not enough to establish a reliable annual event probability.

Tariff rules are different: collect applicable rules whose effective
intervals **overlap** the case-study period, including rules that began
before the period and continued into it. Keep effective start and end dates;
do not infer the end date when it is unknown.

For a historical replay, require incident and relevant shipment dates to
overlap at the precision the data supports; a temporal match plus a location
match is still not proof of actual damage. For a future what-if, explicitly
label the historical incident as scenario motivation, not a future event.

## 4. Potential sources and collection method

Prefer primary, authoritative, stable sources, with secondary reporting only
when useful and corroborated. Review their actual coverage, licensing, date
range, and access conditions before committing to one; source links below are
starting points, not proof that a particular record or tariff is available.

| Category | Starting points | Evidence to collect |
| --- | --- | --- |
| Floods | [GDACS](https://www.gdacs.org/), official national disaster agencies, and port authority notices. | Event dates, affected locations and areas, documented port/facility impacts, source and uncertainty. |
| Cyber incidents | Supplier disclosures, regulators, and official advisories such as [CISA](https://www.cisa.gov/news-events/cybersecurity-advisories). | Organisation/service identity, dates, source, and confirmed operational impact if disclosed. Advisories alone do not prove a specific supplier was attacked. |
| US tariffs | [USITC Harmonized Tariff Schedule](https://hts.usitc.gov/), official [US Customs and Border Protection](https://www.cbp.gov/trade) guidance, and applicable government notices. | Jurisdiction, classification and rule, origin, effective dates, rate, exclusions, source, and verification notes. |

The initial process should be **manual collection and review**, not
automatic scraping. Save only permitted concise facts or references. Record
the selection criteria and sources searched, including known coverage gaps,
to reduce cherry-picking. No live lookup is required when running a fixed
research experiment.

## 5. Proposed record shapes

These are illustrative design examples, not real incidents, tariff rules, or
validated schemas. Optional fields are `null` when genuinely unknown; do
not fill them from guesses.

### Flood incident

```json
{
  "evidence_id": "FLOOD-001",
  "type": "flood",
  "event_start": "2025-01-15",
  "event_end": "2025-01-17",
  "location": {
    "label": "Area near Port X",
    "country_code": "MY",
    "country_name": "Malaysia",
    "latitude": null,
    "longitude": null
  },
  "reported_effect": "Flooding reported; port operational impact unconfirmed.",
  "source": {
    "url": "https://example.org/report",
    "published_at": "2025-01-18",
    "retrieved_at": "2026-01-10",
    "publisher": "Example source"
  },
  "verification_status": "manually_reviewed",
  "limitations": ["The report does not establish a shipment delay."]
}
```

### Cyber incident

```json
{
  "evidence_id": "CYBER-001",
  "type": "cyber_incident",
  "event_start": "2025-04-04",
  "event_end": null,
  "reported_organisation": "Example Supplier",
  "reported_effect": "Operational impact not confirmed.",
  "source": {
    "url": "https://example.org/cyber-report",
    "published_at": "2025-04-05",
    "retrieved_at": "2026-01-10",
    "publisher": "Example source"
  },
  "verification_status": "manually_reviewed",
  "limitations": ["The name has not yet been matched to a graph supplier."]
}
```

Do not expose an incident as affecting a supplier merely because names look
similar. Public reporting is incomplete; absence of a match is not a cyber
security assessment.

### Tariff rule

```json
{
  "rule_id": "TARIFF-001",
  "importing_country_code": "US",
  "importing_country_name": "United States",
  "origin_country_code": "MY",
  "origin_country_name": "Malaysia",
  "product_classification": {
    "system": "illustrative",
    "code": "850870",
    "precision_note": "Additional classification may be required."
  },
  "effective_from": "2024-07-01",
  "effective_to": null,
  "rate": {
    "kind": "ad_valorem_percent",
    "value": 10.0
  },
  "conditions": ["Illustrative rule; not a real tariff."],
  "source": {
    "url": "https://example.org/tariff-rule",
    "published_at": "2024-06-01",
    "retrieved_at": "2026-01-10",
    "publisher": "Example source"
  },
  "verification_status": "illustrative_only"
}
```

Actual tariff applicability can involve classification precision, origin,
destination, date, preference eligibility, exclusions, additional duties,
or non-percentage charges. Do not silently assume supplier country is
country of origin or that an HS6 code is a full customs classification.
Only calculate duty where the rule, customs value, currency, and relevant
conditions are sufficiently supported; otherwise report an incomplete
assessment. Legal applicability and interpretation need authoritative
verification; this is decision support, not customs advice.

### Entity match

```json
{
  "evidence_id": "FLOOD-001",
  "entity_type": "departure_port",
  "graph_entity_id": "P1",
  "match_status": "possible",
  "basis": "Reported flooding near the port; operational impact unconfirmed.",
  "reviewed_at": "2026-01-12"
}
```

Define allowed match states such as `verified`, `possible`, and `rejected`,
with review provenance. A verified identity or location match does not prove
the incident affected a shipment. Preserve original evidence separately from
derived matches and explicitly scoped scenario assumptions.

### Study and experiment manifest

Maintain the working manifest with schema version, coverage dates, sources
searched, selection criteria, known gaps, licences/redistribution notes, and
review procedures. For each experiment record a version ID and file hashes,
and preserve the exact inputs or an immutable reference to them. Working-file
hashes describe only the state at the time they were calculated.

## 6. Matching and scenario preparation

1. Retrieve the selected graph evidence using read-only queries and stable
   IDs. Preserve actual shipment associations and dates.
2. Validate and load a specific evidence version, identified by version and hashes.
3. Find candidates by relevant entity ID, country, product, location, and
   date as appropriate. Resolve ambiguous names, geographic precision, and
   missing fields explicitly; do not infer a transit chokepoint from ports
   alone.
4. Review matches and preserve the matching basis. Show possible or
   unassessable matches separately from verified matches.
5. Construct a scoped scenario with evidence IDs and explicit probability,
   delay or cost assumptions. Evidence that an event happened does not
   automatically justify a probability or establish supplier impact.
6. Pass the engine the network snapshot, event scope, assumptions, and
   evidence references. The engine does not fetch reports or invent missing
   inputs.
7. Retain the graph snapshot or a recoverable reference, evidence version,
   model version, assumptions, seed, run count, and output for reproducibility.

Country-wide evidence applies to multiple suppliers only if the underlying
event's documented scope supports that interpretation; product-specific or
route-specific restrictions require additional checks. A matched shared event
is sampled once per run, but individual impacts can differ.

## 7. Data quality, safety, and evaluation

- Validate IDs, date formats and intervals, source references, rule units,
  country and product codes, and duplicate or contradictory records.
- Test tariff effective-date boundaries and unknown end dates; do not
  calculate a rate for a date where applicability is uncertain.
- Test ambiguous names, missing ports, country mismatches, and uncertain
  dates. Never treat a failed match as proof of no incident or no risk.
- Test lookup by known code and name, case and whitespace variations, reviewed
  aliases, unknown values, and conflicting name/code pairs. Verify that
  multi-country records match the correct paired entry.
- Evaluate a small labelled set of known matches and non-matches; record
  incorrect matches, missed matches, and unresolved cases separately.
- Check that shared events apply to all eligible entities once, supplier-only
  events stay supplier-specific, and related causes/effects are not
  double-counted.
- Protect personal and sensitive data, apply access controls where needed,
  and verify source permissions and confidentiality before sharing evidence.
- Do not use any reconstructed or illustrative value as empirical evidence.

## 8. Proposed phased work

1. **Refine the case-study scope:** verify the selected companies and
   jurisdictions, choose relevant routes and products, and decide the
   historical or future-scenario framing.
2. **Verify the live graph:** check IDs, dates, actual relationship names,
   country/origin fields, port associations, and provenance coverage.
3. **Choose and document sources:** confirm coverage, permissions, licences,
   and retrieval methods for floods, cyber incidents, and relevant tariffs.
4. **Collect and review evidence:** add records directly to the working
   database, documenting sources, gaps and uncertain records.
5. **Design the matcher:** validate identity, location, temporal overlap,
   and tariff applicability; preserve reviewable matching decisions.
6. **Connect to the simulation:** convert reviewed evidence to scoped
   scenarios with explicit assumptions; implement and validate each risk type
   independently rather than promising every category at once.
7. **Evaluate and version experiment inputs:** test matching quality, scenario
   reproducibility, uncertainty, and limitations; retain provenance and an
   immutable version of inputs for each run.

## 9. Open decisions

- Which verified graph entities, routes, and products will anchor the case
  study within the selected period and geographic scope?
- Is the experiment historical replay, a future what-if informed by history,
  or both with separate contracts?
- Which records can be redistributed, and should evidence versions be public or
  private?
- Which risk factor after departure-port disruption should receive a
  validated model first: tariff cost, cyber disruption, or another category?
- Who reviews uncertain entity and tariff matches, and what evidence counts
  as sufficiently reliable?
- How will assumptions about probability and impact be justified when the
  historical record does not quantify them?
