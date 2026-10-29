import os
import json
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j_graphrag.embeddings.openai import OpenAIEmbeddings
from neo4j_graphrag.retrievers import VectorRetriever

load_dotenv()

TEMPLATE_PAGE = Path(__file__).with_name("product_results_template.html")
RESULTS_PAGE = Path(__file__).with_name("product_search_results.html")

# Connect to Neo4j database
driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(
        os.getenv("NEO4J_USERNAME"),
        os.getenv("NEO4J_PASSWORD"),
    ),
)

# Create embedder
# This must match the model used to create the Product.embedding vectors.
embedder = OpenAIEmbeddings(model="text-embedding-3-small")

# Create retriever
retriever = VectorRetriever(
    driver,
    neo4j_database=os.getenv("NEO4J_DATABASE"),
    # This is the Neo4j vector index name, not the node property name.
    index_name="embedding",
    embedder=embedder,
    return_properties=["product_description", "full_hs_code_description"],
)

# Search for similar products

query_text = "air purifier"  
top_k = 5  


result = retriever.search(query_text=query_text, top_k=top_k)

results_data = [
    {
        "rank": rank,
        "score": item.metadata["score"],
        "content": item.content,
    }
    for rank, item in enumerate(result.items, start=1)
]
results_json = json.dumps(results_data).replace("<", "\\u003c")
template = TEMPLATE_PAGE.read_text(encoding="utf-8")
RESULTS_PAGE.write_text(
    template.replace("__QUERY__", json.dumps(query_text)).replace(
        "__RESULTS_JSON__", results_json
    ),
    encoding="utf-8",
)

# Close the database connection
driver.close()
