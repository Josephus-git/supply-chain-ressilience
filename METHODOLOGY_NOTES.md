# Methodology notes: interventions on LLM behaviour

This file records every design choice that changes what the LLMs see or how their
output is handled. It is a source for the methodology section of the report. Each entry
says what was done, why, and what effect it may have on measured performance. Add an
entry whenever a guard rail, prompt rule or post-processing step is added or changed.

Status: **planned** (agreed, not built) or **built** (with commit).

## Ask the Graph (Text2Cypher baseline)

| # | Intervention | Why | Possible effect on results | Status |
|---|---|---|---|---|
| A1 | Schema given to the LLM is a hand-edited copy with property types and value hints (DATETIME compared with `date()`, INTEGER codes, `supplier_basename` grouping, ISO country codes) | The raw schema led to type errors | Raises query accuracy above a plain-schema baseline | built (phase 3) |
| A2 | Few-shot examples in the Cypher prompt, starting from `langchain/cypher_qa.py` | Standard Text2Cypher practice | Raises accuracy, especially on question shapes similar to the examples | built (phase 3) |
| A3 | Write clauses refused; `EXPLAIN` syntax check; unknown labels, relationship types or properties (GQL 01N50/01N51/01N52) fail the check | Safety (read-only) and catching invented schema | Turns some wrong queries into a visible failure instead of a wrong answer | built (phase 3) |
| A4 | One automatic retry when the query errors or returns no rows; a no-rows retry tells the model to match a shorter fragment of a name | Recover from near misses (e.g. "VS Industry" vs "Vs Industrial …") | Raises success rate; both attempts are kept in the trace, so first-attempt accuracy can still be measured | built (phase 3) |
| A5 | Rows capped at 200; the answer prompt sees at most 60 rows | Cost and context length | Answers about large result sets may be incomplete | built (phase 3) |
| A6 | No `as_of_date` rule in Ask | It is the exploratory baseline | Answers may use data after the simulated date | built (phase 3) |

## Risk Assessment

| # | Intervention | Why | Possible effect on results | Status |
|---|---|---|---|---|
| R1 | Two separate LLMs: a Cypher LLM finds candidates, a risk LLM compares evidence and decides | Separates retrieval errors from reasoning errors | Errors can be attributed to one stage | built (phase 5) |
| R2 | Supplier exposure profiles come from a **fixed** query with the `as_of_date` filter, not from LLM-written Cypher | Enforces the no-look-ahead rule and the engine's payload schema 1.1 | Profile figures are always correct for the date; only candidate *finding* can be wrong | built (phase 5) |
| R3 | Cypher LLM reuses the Ask safety checks (A3) and may make mistakes in finding candidates; these are not corrected | Research: measure real model behaviour | Wrong or missing candidates flow through to the report and are visible in the trace | built (phase 5) |
| R4 | If no supplier or product is found, the risk engine is still asked for evidence related to the question, by country | A useful country-level answer is still possible | The risk LLM may answer at country level instead of supplier level | built (phase 5) |
| R4a | Countries for the engine come from the Cypher results; when the Cypher LLM approximates, it may add suggested countries labelled as a recommendation to the risk engine, and the answer says so | Keep the Cypher LLM a retrieval step; make approximation visible | Wrong suggested countries bring irrelevant evidence into the report; measurable from the labelled suggestions | built (phase 5) |
| R4b | The Cypher LLM in Risk Assessment keeps Ask's one automatic retry (A4) | Recover from near misses | Raises success rate; first-attempt accuracy still measurable from the trace | built (phase 5) |
| R5 | The risk LLM gets the profiles and evidence directly in the prompt, with no tools | The trace shows exactly what it saw | Its answer is limited to what retrieval returned | built (phase 5) |
| R6 | Prompt rule: every claim must cite an evidence id or a graph figure it was given; otherwise answer "I don't have enough data to support that" | Grounding; research requirement | Fewer unsupported claims; may also cause over-refusal | built (phase 5) |
| R7 | If neither the graph nor the engine returns anything relevant, the risk LLM is not called and the fixed answer "I don't have enough data to support that" is returned | Grounding and cost | Refusal rate on out-of-scope questions is set by the pipeline, not the model; report this separately | built (phase 5) |
| R8 | Citations are checked against what the risk LLM was given and **flagged only** (verified / not found); wrong citations are not removed or corrected | Keep raw model output so mistakes can be studied manually | Citation error rate can be measured directly from stored runs | built (phase 5) |
| R10 | Ranking priority given to the risk LLM in the prompt: (1) closest match to the query, (2) risk as of the date, (3) track record (shipment count, recency of last arrival, length of relationship) when risk does not separate suppliers; the answer must say which factor decided | Make "best supplier" explicit and comparable across runs | Rankings reflect this stated priority, not the model's own notion of "best"; "track record" is volume and recency only, since the data has no failed deliveries | built (phase 5) |
| R11 | The risk LLM answers in a fixed structured format (status, ranked candidates with cited claims, deciding factor, set-aside candidates, country notes); the summary table is built from those fields | Every summary statement traces to a cited claim | Constrains how the model can express uncertainty or nuance outside the fields | built (phase 5) |
| R12 | `as_of_date` is chosen by the user or drawn uniformly at random from the study window (2025-01-01 to 2026-09-30); each run stores which (`date_mode`). Re-runs with a new date are separate records linked by `rerun_of` | Lets the evaluation sample dates without bias and compare the same query over time | Results can be grouped by date and by chosen vs random; re-runs show how recommendations change as evidence accumulates | built (phase 5) |
| R13 | Parts list items can be picked from a product catalogue (exact product names) or typed freely; each item records `source` (`catalogue` or `typed`). Catalogue names and categories come from a hand-reviewed file | Make the available products visible; still allow out-of-catalogue queries | Catalogue items give the Cypher LLM exact names and should retrieve better than typed items; compare the two groups | built (phase 5) |
| R9 | Each run covers up to 20 items | Readability and cost | Larger lists must be split | built (phase 5) |
| R14 | Candidate finding is also held to the date: matched (item, supplier, product) triples are recounted with a fixed query up to `as_of_date`; a supplier with no shipment by the date gets no profile (listed as "not yet supplying"), and products only shipped after the date are dropped from the match | No-look-ahead applies to everything the risk LLM sees, not only to the profiles | The Cypher LLM's query is not date-filtered (it is told not to filter), so its raw rows can include later suppliers; the trace shows what was dropped | built (phase 5) |
| R15 | The Cypher LLM answers in a structured format (Cypher, labelled `suggested_countries`, a one-line interpretation). The retry (R4b) is also triggered when the reply cannot be parsed or the rows lack the required `item` and `supplier_id` columns | Rows must map back to items | Raises success rate; first-attempt accuracy is still measurable from the trace | built (phase 5) |
| R16 | Countries named in the request (the engine's country-name table, whole words; "us" is ignored as ambiguous) are looked up deterministically and labelled `mentioned`, alongside the Cypher LLM's `suggested` countries | R4 asks for evidence "at least by the countries it mentions" without depending on the LLM | Country evidence can appear even when the Cypher LLM suggests nothing | built (phase 5) |
| R17 | Country-level lookup is an engine payload whose only real key is the country: a placeholder supplier name that matches no record, the country's ISO currency, no ports, carriers or vessels. The engine's own rules decide what links by country (e.g. vessel incidents never do), so FX records for that currency and US-wide tariffs (importing country) also link | Reuse the engine's rules and date logic instead of writing a second matcher | Country answers include currency and import-side context; countries without a currency in the app's table are skipped and listed | built (phase 5) |
| R18 | Graph figures get citation ids the risk LLM can cite (`graph:<supplier_id>:shipments`, `first_arrival`, `last_arrival`, `country`, `parent`, `exit_ports`, `carriers`; `match:<item>:<supplier_id>` for matched products). The citation check also notes a verified citation that was given for another supplier, item or country, and lists claims with no citation | Make graph claims checkable like evidence claims | Scope errors (citing a real id for the wrong supplier) are measurable separately from invented ids | built (phase 5) |
| R19 | The risk LLM's prompt is trimmed: evidence descriptions to 320 characters, the first two limitations to 220 characters each, at most three measures per record, and the top three exit ports and carriers per supplier. Full records stay one click away in the app | Cost and context length | The model may miss detail that is only in the trimmed text | built (phase 5) |
| R20 | Only one assessment runs at a time (the API returns 409 otherwise) | Cost | None on outputs | built (phase 5) |
| R21 | The risk LLM writes a one-sentence cited `answer` per item; the top-level `summary` is only for what is shared across items (empty if nothing). The Answer box shows one line per item, then the shared note. Item answers go through the same citation check (`items.<i>.answer`) | A single combined summary was hard to read for multi-item lists and bunched all citations at the end | One more claim per item to cite (and possibly mis-cite); runs saved before this show the old single summary | built (phase 5) |

## Cost controls (all LLM calls)

| # | Intervention | Why | Possible effect on results | Status |
|---|---|---|---|---|
| C1 | `max_tokens` cap, timeout and `max_retries=1` on each call | Cost | A very long answer may be cut off; record when this happens | built (phase 5) |
| C2 | Token usage recorded per run; a warning near the 250,000 free daily tokens | Cost awareness | None on outputs (warning only) | built (phase 5) |

## Data limitations to report

| # | Limitation | Effect on results |
|---|---|---|
| L1 | **Track record is volume and recency only.** Customs (ImportYeti) records are completed arrivals, so the graph has no failed, late or rejected deliveries. "Track record" means shipments arrived up to `as_of_date`, how recent the last arrival is, and how long the relationship has run. | A supplier with many shipments may be ranked "more reliable" without any evidence about delivery performance. |
| L2 | **Entity resolution in customs data:** Hi-P's single plant in Tanauan, PH appears under two `supplier_basename` values ("Hi P Philippines Technology Corpora", reported TW, 47 shipments; "Hip Philipines Technology", PH, 49). Left as is (user decision 2026-11-16). | Per-company answers and rankings may treat one supplier as two and split its track record. |
| L3 | **Reported country vs address:** `supplier_country_code` is the country ImportYeti reports and can differ from the address (e.g. Ihastek Malaysia = CN). The engine uses the graph value. | Country-level evidence may be linked to the wrong country for such suppliers. |
| L4 | **Evidence is not linked to suppliers by id:** risk evidence has no supplier ids; links to suppliers are by country, parent company, ports, carriers and similar keys. The Risk Library's graph link uses country only. | Country-level matches are broad (e.g. MY links all 6 Malaysian supplier nodes). |
| L5 | **HS codes are sometimes misdeclared:** e.g. a vacuum cleaner motorbar declared as men's overcoats (6101), other Dyson lines as cane sugar (1701), dog food (2309) and fresh grapes (0806; stored as the integer 80610, losing the leading zero). Product descriptions are noisy and some include delivery addresses. | HS-based matching (by the Cypher LLM or the engine's `hs_codes` keys) can link products to the wrong goods or tariff evidence; the catalogue uses hand-reviewed categories instead. |
