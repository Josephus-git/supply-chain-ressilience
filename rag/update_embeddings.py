"""Create embeddings for Product nodes that do not have one yet."""

import os

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j_graphrag.embeddings.openai import OpenAIEmbeddings

load_dotenv()


EMBEDDING_MODEL = "text-embedding-3-small"  # Very important, remember that the embedding must be the same for the entire project


def update_product_embeddings() -> int:
    """Embed missing Product nodes and return the number of nodes updated."""
    required_environment = (
        "NEO4J_URI",
        "NEO4J_USERNAME",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "OPENAI_API_KEY",
    )
    missing_environment = [name for name in required_environment if not os.getenv(name)]
    if missing_environment:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing_environment)
        )

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    embedder = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    updated_count = 0

    try:
        driver.verify_connectivity()
        records, _, _ = driver.execute_query(
            """
            MATCH (product:Product)
            WHERE product.embedding IS NULL
            RETURN elementId(product) AS element_id,
                   product.full_hs_code_description AS full_hs_code_description,
                   product.product_description AS product_description
            ORDER BY element_id
            """,
            database_=os.environ["NEO4J_DATABASE"],
        )

        for record in records:
            full_hs_code_description = record["full_hs_code_description"] or ""
            product_description = record["product_description"] or ""
            text = (
                f"Full HS code description: {full_hs_code_description}\n"
                f"Product description: {product_description}"
            )
            embedding = embedder.embed_query(text)

            driver.execute_query(
                """
                MATCH (product:Product)
                WHERE elementId(product) = $element_id
                  AND product.embedding IS NULL
                SET product.embedding = $embedding
                """,
                element_id=record["element_id"],
                embedding=embedding,
                database_=os.environ["NEO4J_DATABASE"],
            )
            updated_count += 1

        return updated_count
    finally:
        driver.close()


if __name__ == "__main__":
    count = update_product_embeddings()
    print(f"Updated embeddings for {count} Product node(s).")
