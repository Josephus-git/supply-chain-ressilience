import os
import json
from ast import literal_eval
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j_graphrag.embeddings.openai import OpenAIEmbeddings
from neo4j_graphrag.generation import GraphRAG
from neo4j_graphrag.llm import OpenAILLM
from neo4j_graphrag.retrievers import VectorCypherRetriever
from neo4j_graphrag.types import RetrieverResultItem

load_dotenv()

TEMPLATE_PAGE = Path(__file__).with_name("graph_search_results_template.html")
RESULTS_PAGE = Path(__file__).with_name("graph_search_results.html")

# Connect to Neo4j database
driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(
        os.getenv("NEO4J_USERNAME"),
        os.getenv("NEO4J_PASSWORD"),
    ),
)

# Create embedder using the same model used for Product.embedding.
embedder = OpenAIEmbeddings(model="text-embedding-3-small")

# Start with a semantically similar Product node, then traverse the graph
# to find suppliers and shipments departing from the requested port.
retrieval_query = """
MATCH (node)<-[:CONTAINS_PRODUCT]-(shipment:Shipment)
MATCH (supplier:Supplier)-[:SHIPPED]->(shipment)
MATCH (shipment)-[:DEPARTED_FROM]->(exit_port)
WHERE toLower(coalesce(exit_port.exit_port, ""))
      CONTAINS toLower($departure_port)
OPTIONAL MATCH (shipment)-[:ARRIVED_AT]->(entry_port)
RETURN
    node.product_description AS product_description,
    node.full_hs_code_description AS full_hs_code_description,
    supplier.supplier_name AS supplier,
    exit_port.exit_port AS departure_port,
    collect(DISTINCT entry_port.entry_port) AS arrival_ports,
    count(DISTINCT shipment) AS shipment_count,
    score AS similarity_score
ORDER BY similarity_score DESC, shipment_count DESC
"""


def format_result(record):
    """Keep string content for GraphRAG and structured fields for HTML."""
    values = dict(record)
    score = values.pop("similarity_score", None)
    return RetrieverResultItem(
        content=str(values),
        metadata={"score": score, "result": values},
    )

# Create retriever over the Product.embedding vector index.
retriever = VectorCypherRetriever(
    driver,
    neo4j_database=os.getenv("NEO4J_DATABASE"),
    index_name="embedding",
    embedder=embedder,
    retrieval_query=retrieval_query,
    result_formatter=format_result,
)

# Change these values while testing.
query_text = "vacuum cleaner"
departure_port = "Tanjung Pelepas"
top_k = 50

# Create the LLM and GraphRAG pipeline.
llm = OpenAILLM(model_name="gpt-5.2")
rag = GraphRAG(retriever=retriever, llm=llm)

# Search for similar products connected to shipments from the requested port.
response = rag.search(
    query_text=query_text,
    retriever_config={
        "top_k": top_k,
        "query_params": {"departure_port": departure_port},
    },
    return_context=True,
)

retrieved_items = response.retriever_result.items
answer = response.answer
if not retrieved_items:
    answer = (
        f"No verified suppliers were found for products similar to "
        f"'{query_text}' departing from '{departure_port}'."
    )

context = []
for rank, item in enumerate(retrieved_items, start=1):
    metadata = item.metadata or {}
    if isinstance(metadata.get("result"), dict):
        values = metadata["result"]
    else:
        try:
            values = literal_eval(item.content)
        except (SyntaxError, TypeError, ValueError):
            values = {"content": item.content}

    context.append(
        {
            "rank": rank,
            "similarity_score": metadata["score"]
            if "score" in metadata
            else values.get("similarity_score"),
            **values,
        }
    )

page_data = {
    "answer": answer,
    "query": query_text,
    "departure_port": departure_port,
    "results": context,
}
page_data_json = json.dumps(page_data, default=str).replace("<", "\\u003c")
template = TEMPLATE_PAGE.read_text(encoding="utf-8")
RESULTS_PAGE.write_text(
    template.replace("__PAGE_DATA__", page_data_json),
    encoding="utf-8",
)

print(f"Results written to {RESULTS_PAGE}")

# Close the database connection
driver.close()
