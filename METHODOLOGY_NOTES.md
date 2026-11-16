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
| R1 | Two separate LLMs: a Cypher LLM finds candidates, a risk LLM compares evidence and decides | Separates retrieval errors from reasoning errors | Errors can be attributed to one stage | planned |
| R2 | Supplier exposure profiles come from a **fixed** query with the `as_of_date` filter, not from LLM-written Cypher | Enforces the no-look-ahead rule and the engine's payload schema 1.1 | Profile figures are always correct for the date; only candidate *finding* can be wrong | planned |
| R3 | Cypher LLM reuses the Ask safety checks (A3) and may make mistakes in finding candidates; these are not corrected | Research: measure real model behaviour | Wrong or missing candidates flow through to the report and are visible in the trace | planned |
| R4 | If no supplier or product is found, the risk engine is still asked for evidence related to the question, by country | A useful country-level answer is still possible | The risk LLM may answer at country level instead of supplier level | planned |
| R4a | Countries for the engine come from the Cypher results; when the Cypher LLM approximates, it may add suggested countries labelled as a recommendation to the risk engine, and the answer says so | Keep the Cypher LLM a retrieval step; make approximation visible | Wrong suggested countries bring irrelevant evidence into the report; measurable from the labelled suggestions | planned |
| R4b | The Cypher LLM in Risk Assessment keeps Ask's one automatic retry (A4) | Recover from near misses | Raises success rate; first-attempt accuracy still measurable from the trace | planned |
| R5 | The risk LLM gets the profiles and evidence directly in the prompt, with no tools | The trace shows exactly what it saw | Its answer is limited to what retrieval returned | planned |
| R6 | Prompt rule: every claim must cite an evidence id or a graph figure it was given; otherwise answer "I don't have enough data to support that" | Grounding; research requirement | Fewer unsupported claims; may also cause over-refusal | planned |
| R7 | If neither the graph nor the engine returns anything relevant, the risk LLM is not called and the fixed answer "I don't have enough data to support that" is returned | Grounding and cost | Refusal rate on out-of-scope questions is set by the pipeline, not the model; report this separately | planned |
| R8 | Citations are checked against what the risk LLM was given and **flagged only** (verified / not found); wrong citations are not removed or corrected | Keep raw model output so mistakes can be studied manually | Citation error rate can be measured directly from stored runs | planned |
| R10 | Ranking priority given to the risk LLM in the prompt: (1) closest match to the query, (2) risk as of the date, (3) track record (shipment count, recency of last arrival, length of relationship) when risk does not separate suppliers; the answer must say which factor decided | Make "best supplier" explicit and comparable across runs | Rankings reflect this stated priority, not the model's own notion of "best"; "track record" is volume and recency only, since the data has no failed deliveries | planned |
| R11 | The risk LLM answers in a fixed structured format (status, ranked candidates with cited claims, deciding factor, set-aside candidates, country notes); the summary table is built from those fields | Every summary statement traces to a cited claim | Constrains how the model can express uncertainty or nuance outside the fields | planned |
| R12 | `as_of_date` is chosen by the user or drawn uniformly at random from the study window (2025-01-01 to 2026-09-30); each run stores which (`date_mode`). Re-runs with a new date are separate records linked by `rerun_of` | Lets the evaluation sample dates without bias and compare the same query over time | Results can be grouped by date and by chosen vs random; re-runs show how recommendations change as evidence accumulates | planned |
| R13 | Parts list items can be picked from a product catalogue (exact product names) or typed freely; each item records `source` (`catalogue` or `typed`). Catalogue names and categories come from a hand-reviewed file | Make the available products visible; still allow out-of-catalogue queries | Catalogue items give the Cypher LLM exact names and should retrieve better than typed items; compare the two groups | planned |
| R9 | Each run covers up to 20 items | Readability and cost | Larger lists must be split | planned |

## Cost controls (all LLM calls)

| # | Intervention | Why | Possible effect on results | Status |
|---|---|---|---|---|
| C1 | `max_tokens` cap, timeout and `max_retries=1` on each call | Cost | A very long answer may be cut off; record when this happens | planned |
| C2 | Token usage recorded per run; a warning near the 250,000 free daily tokens | Cost awareness | None on outputs (warning only) | planned |

## Data limitations to report

| # | Limitation | Effect on results |
|---|---|---|
| L1 | **Track record is volume and recency only.** Customs (ImportYeti) records are completed arrivals, so the graph has no failed, late or rejected deliveries. "Track record" means shipments arrived up to `as_of_date`, how recent the last arrival is, and how long the relationship has run. | A supplier with many shipments may be ranked "more reliable" without any evidence about delivery performance. |
| L2 | **Entity resolution in customs data:** Hi-P's single plant in Tanauan, PH appears under two `supplier_basename` values ("Hi P Philippines Technology Corpora", reported TW, 47 shipments; "Hip Philipines Technology", PH, 49). Left as is (user decision 2026-11-16). | Per-company answers and rankings may treat one supplier as two and split its track record. |
| L3 | **Reported country vs address:** `supplier_country_code` is the country ImportYeti reports and can differ from the address (e.g. Ihastek Malaysia = CN). The engine uses the graph value. | Country-level evidence may be linked to the wrong country for such suppliers. |
| L4 | **Evidence is not linked to suppliers by id:** risk evidence has no supplier ids; links to suppliers are by country, parent company, ports, carriers and similar keys. The Risk Library's graph link uses country only. | Country-level matches are broad (e.g. MY links all 6 Malaysian supplier nodes). |
| L5 | **HS codes are sometimes misdeclared:** e.g. a vacuum cleaner motorbar declared as men's overcoats (6101), other Dyson lines as cane sugar (1701), dog food (2309) and fresh grapes (0806; stored as the integer 80610, losing the leading zero). Product descriptions are noisy and some include delivery addresses. | HS-based matching (by the Cypher LLM or the engine's `hs_codes` keys) can link products to the wrong goods or tariff evidence; the catalogue uses hand-reviewed categories instead. |
