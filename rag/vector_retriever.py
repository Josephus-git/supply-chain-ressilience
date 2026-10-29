import os

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j_graphrag.embeddings.openai import OpenAIEmbeddings
from neo4j_graphrag.retrievers import VectorRetriever

load_dotenv()

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
result = retriever.search(query_text="air purifier", top_k=5)

# Parse results
for item in result.items:
    print(item.content, item.metadata["score"])

# Close the database connection
driver.close()
