"""Prompts for Ask the Graph.

`CYPHER_TEMPLATE` keeps the wording and the first few-shot example of the
prototype in langchain/cypher_qa.py (left untouched there). The extra examples
cover the patterns the schema hints warn about: grouping by company, DATETIME
comparisons and integer HS codes. They are generic on purpose, so they do not
give away the answers to the questions in example_questions.json.
"""

from __future__ import annotations

from langchain_core.prompts import PromptTemplate

FEW_SHOT = """Question: Find suppliers for products matching <product_keyword> departing from <exit_port_name>.
Cypher:
MATCH (product:Product)<-[:CONTAINS_PRODUCT]-(shipment:Shipment)
MATCH (supplier:Supplier)-[:SHIPPED]->(shipment)
MATCH (shipment)-[:DEPARTED_FROM]->(exit_port:`Exit Port`)
WHERE toLower(coalesce(product.product_description, "")) CONTAINS toLower("<product_keyword>")
  AND toLower(coalesce(exit_port.exit_port, "")) CONTAINS toLower("<exit_port_name>")
OPTIONAL MATCH (shipment)-[:ARRIVED_AT]->(entry_port:`Entry Port`)
RETURN
    product.product_description AS product_description,
    product.full_hs_code_description AS full_hs_code_description,
    supplier.supplier_name AS supplier,
    exit_port.exit_port AS departure_port,
    collect(DISTINCT entry_port.entry_port) AS arrival_ports,
    count(DISTINCT shipment) AS shipment_count
ORDER BY shipment_count DESC

Question: How many shipments did each supplier company send per month in <year>?
Cypher:
MATCH (supplier:Supplier)-[:SHIPPED]->(shipment:Shipment)
WHERE date(shipment.arrival_date) >= date("<year>-01-01")
  AND date(shipment.arrival_date) <= date("<year>-12-31")
RETURN
    supplier.supplier_basename AS company,
    date.truncate('month', shipment.arrival_date) AS month,
    count(shipment) AS shipments
ORDER BY company, month

Question: Which vessels carried products under HS heading <four_digit_heading>?
Cypher:
MATCH (shipment:Shipment)-[:CONTAINS_PRODUCT]->(product:Product)
MATCH (shipment)-[:TRANSPORTED_ON]->(vessel:Vessel)
WHERE toString(product.hs_code) STARTS WITH "<four_digit_heading>"
RETURN vessel.vessel_name AS vessel, count(shipment) AS shipments
ORDER BY shipments DESC"""

CYPHER_TEMPLATE = """Task: Generate Cypher statement to query a graph database.
Instructions:
Use only the provided relationship types and properties in the schema.
Do not use any other relationship types or properties that are not provided.
The query must only read: never use CREATE, MERGE, SET, DELETE, REMOVE, DROP, LOAD CSV or procedure calls.
Return named columns (use AS) that a reader can understand.
If the question asks to show nodes, paths or a graph, return the nodes themselves (e.g. RETURN s, pc) so they can be drawn.

Examples:

{examples}

Schema:
{schema}

Note: Do not include any explanations or apologies in your responses.
Do not respond to any questions that might ask anything else than for you to construct a Cypher statement.
Do not include any text except the generated Cypher statement.
{feedback}
The question is:
{question}"""

# Appended (as {feedback}) on the retry after a failed first attempt.
RETRY_FEEDBACK = """
A previous attempt at this question failed. Write a corrected query.
Previous Cypher:
{cypher}
Problem:
{problem}
"""

ANSWER_TEMPLATE = """You answer questions about Dyson's inbound supply chain using only the rows
returned by a Cypher query against a knowledge graph of US customs shipment records.

Rules:
- Use only the rows below. Do not add facts from general knowledge.
- If the rows are empty, say that the graph returned no matching data, and do not guess.
- If the rows look like they do not fit the question (for example the query filtered on
  the wrong thing), say so plainly.
- Name suppliers, ports and carriers as they appear in the rows, and quote the numbers.
- Be concise: a short direct answer first, then a few bullet points if useful.
- If the rows were truncated, say the answer covers only the rows shown.

Question:
{question}

Cypher that was run:
{cypher}

Rows ({row_count} returned{truncated_note}):
{rows}

Answer:"""

cypher_prompt = PromptTemplate.from_template(CYPHER_TEMPLATE)
answer_prompt = PromptTemplate.from_template(ANSWER_TEMPLATE)
