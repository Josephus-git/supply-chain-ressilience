"""Prompts and the structured output schema for Risk Assessment.

Two LLMs (R1 in METHODOLOGY_NOTES.md):
- the **Cypher LLM** finds candidate products and suppliers (one call for the
  whole list, plus at most one retry) and may add labelled country
  suggestions for the risk engine (R4a);
- the **risk LLM** compares the supplier profiles and evidence it is given and
  ranks the candidates (R5, R6, R10, R11). It has no tools.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field

# ----------------------------------------------------------------------------- Cypher LLM


class SuggestedCountry(BaseModel):
    code: str = Field(description="ISO 3166-1 alpha-2 code, e.g. VN")
    reason: str = Field(description="Why the risk engine should look at this country")


class CandidateQuery(BaseModel):
    """The Cypher LLM's reply."""

    cypher: str = Field(description="One read-only Cypher query; columns item, supplier_id, product_id first")
    suggested_countries: list[SuggestedCountry] = Field(
        description="Only when the query cannot retrieve the answer directly (a region, or a country with no "
        "supplier in the graph). A recommendation to the risk engine, not a retrieved fact. Usually empty."
    )
    interpretation: str = Field(description="One sentence: how the items or description were read")


CANDIDATE_EXAMPLE = """MATCH (supplier:Supplier)-[:SHIPPED]->(shipment:Shipment)-[:CONTAINS_PRODUCT]->(product:Product)
WITH supplier, shipment, product
UNWIND [
  {item: 1, keywords: ["airwrap", "styler"]},
  {item: 2, keywords: ["filter"]},
  {item: 3, product_id: "hs:850760", keywords: []}
] AS line
WITH line, supplier, shipment, product
WHERE product.product_id = line.product_id
   OR any(k IN line.keywords WHERE toLower(product.product_description) CONTAINS k
                               OR toLower(coalesce(product.hs_code_description, "")) CONTAINS k)
RETURN line.item AS item,
       supplier.supplier_id AS supplier_id,
       product.product_id AS product_id,
       supplier.supplier_name AS supplier_name,
       supplier.supplier_country_code AS country,
       product.product_description AS product_description,
       count(DISTINCT shipment) AS shipments
ORDER BY item, shipments DESC"""

CANDIDATE_TEMPLATE = """Task: write ONE read-only Cypher query that finds, in Dyson's supply-chain
knowledge graph, the suppliers and products that match a buyer's request.

The request:
{request}

Rules:
- Use only the labels, relationship types and properties in the schema.
- The query must only read: never CREATE, MERGE, SET, DELETE, REMOVE, DROP, LOAD CSV or call procedures.
- Return one row per (item, supplier, product) with the columns `item` (the item number, an integer),
  `supplier_id` and `product_id` first. Add readable columns after them (supplier_name, country,
  product_description, shipments).
- Do NOT filter by date. The app applies its own as-of date to everything you find.
- Product descriptions are noisy customs text: match short lower-case keywords with
  toLower(...) CONTAINS, try a few synonyms per item, and also check hs_code_description.
  When an item gives a catalogue product_id, match that product_id exactly as well.
- In describe mode there is one item (item 1). If the description asks about a country, region,
  port or carrier instead of a product, still return the matching suppliers (product_id may be null).
- suggested_countries: leave it empty when the query can retrieve the answer. Only when you must
  approximate (a region such as "Southeast Asia", or a country with no supplier in the graph),
  list the ISO alpha-2 countries the risk engine should look up, each with a reason. These are
  labelled as your recommendation, not as data from the graph.

Example (three items; item 3 came from the catalogue):
{example}

Schema:
{schema}
{feedback}"""

CANDIDATE_RETRY = """
A previous attempt failed. Write a corrected query.
Previous Cypher:
{cypher}
Problem:
{problem}
"""

candidate_prompt = PromptTemplate.from_template(CANDIDATE_TEMPLATE)

# ----------------------------------------------------------------------------- risk LLM


class Claim(BaseModel):
    text: str = Field(description="One short statement")
    citations: list[str] = Field(description="Citation ids from the data that support the statement")


class RankedCandidate(BaseModel):
    supplier_id: str = Field(description="The supplier_id exactly as given")
    match_reason: Claim = Field(description="Why its products match the item (cite match:... ids)")
    risks: list[Claim] = Field(description="Its risks as of the date, most important first (cite evidence ids); empty if none")
    track_record: Claim = Field(description="Shipments, last arrival and relationship length (cite graph:... ids)")
    deciding_factor: Literal["match", "risk", "track_record"] = Field(description="Which of the three decided its place")
    deciding_reason: str = Field(description="One sentence: how that factor decided its place against the others")


class SetAside(BaseModel):
    supplier_id: str
    reason: Claim


class CountryNote(BaseModel):
    country_code: str
    from_suggestion: bool = Field(description="True when the country came from the Cypher LLM's suggestion")
    note: Claim


class ItemAssessment(BaseModel):
    item: int = Field(description="The item number")
    status: Literal["answered", "country_level", "insufficient_data"]
    candidates: list[RankedCandidate] = Field(description="Recommended candidates in rank order, best first")
    set_aside: list[SetAside] = Field(description="Listed candidates you did not rank, and why")
    country_notes: list[CountryNote] = Field(description="Country-level notes, mainly when no supplier matched")
    answer: Claim = Field(
        description="One sentence answering the buyer's goal for this item alone: the recommended supplier "
        "and why, or what to do instead. Do not repeat the item name."
    )


class AssessmentReport(BaseModel):
    summary: Claim = Field(
        description="One short sentence on what applies across all items (such as a shared risk or a "
        "common caveat); do not restate each item's answer. Empty text and no citations if nothing is shared."
    )
    items: list[ItemAssessment] = Field(description="One entry per item, in item order")


INSUFFICIENT = "I don't have enough data to support that."

REPORT_TEMPLATE = """You are a supply-chain risk analyst helping a Dyson buyer. You compare suppliers
using ONLY the data below: supplier profiles from a knowledge graph of US customs records, and
risk evidence records returned by a deterministic risk engine. All figures are as of {as_of_date};
nothing after that date exists for you.

The buyer's goal: {goal}
Mode: {mode}

Rules:
1. Every claim must cite at least one citation id that appears in the data below:
   - evidence ids such as TARIFF-2025-MY-001 (from EVIDENCE),
   - graph figures such as graph:<supplier_id>:shipments (from SUPPLIERS),
   - product matches such as match:<item>:<supplier_id> (from ITEMS).
   If you cannot cite something, do not claim it; write "{insufficient}" instead.
2. Rank each item's candidates by, in order:
   (1) closest match to the item: how well the supplier's matched products fit what was asked;
       this decides whether a supplier is recommended at all;
   (2) risk: among close matches, fewer and less severe evidence records as of the date is better;
   (3) track record, only when risk does not separate them: more shipments, a more recent last
       arrival and a longer relationship. Track record is volume and recency only; the data has
       no failed or late deliveries.
   For each ranked candidate say which of the three decided its place (deciding_factor).
3. Only rank suppliers listed as candidates for that item. Put listed candidates that do not
   really match (or had no shipments by the date) in set_aside with the reason.
4. A linked evidence record is context, not proof that an event affected the supplier. Respect
   each record's link strength, verification status and limitations; say "country-level" when a
   record links by country only.
5. Item status: "answered" when at least one candidate is ranked; "country_level" when no
   supplier matched but country evidence lets you say something about where to source;
   "insufficient_data" otherwise, with that item's answer saying "{insufficient}".
   Each item gets its own one-sentence answer, citing what supports it. The top-level summary
   is only for what is shared across items; leave it empty when nothing is.
6. Country notes: use COUNTRY EVIDENCE. When a country's basis is "suggested", set
   from_suggestion true and say in the note that the country was suggested, not retrieved.
7. Be concise and specific. Quote figures exactly as given. Do not invent suppliers, products,
   dates or numbers.

ITEMS (with their candidates and matched products):
{items}

SUPPLIERS (profiles as of {as_of_date}, with the evidence linked to each):
{suppliers}

SHARED EVIDENCE (linked in exactly the same way to every supplier in SUPPLIERS):
{shared}

COUNTRY EVIDENCE (country-level lookups):
{countries}

EVIDENCE (records referenced above):
{evidence}
"""

report_prompt = PromptTemplate.from_template(REPORT_TEMPLATE)
