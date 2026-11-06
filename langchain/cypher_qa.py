import os
from dotenv import load_dotenv

load_dotenv()

from langchain.chat_models import init_chat_model
from langchain_core.prompts.prompt import PromptTemplate
from langchain_neo4j import GraphCypherQAChain, Neo4jGraph

# Initialize the LLM using Ollama
# ollama_model_name = os.getenv("OLLAMA_MODEL", "llama3.2")
# model = init_chat_model(ollama_model_name, model_provider="ollama")

# Initialize the LLM (GPT)
model = init_chat_model("gpt-5.2", model_provider="openai")

# Connect to Neo4j graph database
graph = Neo4jGraph(
    url=os.getenv("NEO4J_URI"),
    username=os.getenv("NEO4J_USERNAME"),
    password=os.getenv("NEO4J_PASSWORD"),
    database=os.getenv("NEO4J_DATABASE"),
)

# Read your declarative text schema directly from schema.txt
schema_path = os.path.join(os.path.dirname(__file__), "schema.txt")
with open(schema_path, "r", encoding="utf-8") as f:
    custom_schema_text = f.read()

# Enhanced Cypher prompt containing your manual query as a few-shot example
cypher_template = """Task: Generate Cypher statement to query a graph database.
Instructions:
Use only the provided relationship types and properties in the schema.
Do not use any other relationship types or properties that are not provided.

Examples:

Question: Find suppliers for products matching <product_keyword> departing from <exit_port_name>.
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

Schema:
{schema}

Note: Do not include any explanations or apologies in your responses.
Do not respond to any questions that might ask anything else than for you to construct a Cypher statement.
Do not include any text except the generated Cypher statement.

The question is:
{question}"""

cypher_prompt = PromptTemplate(
    input_variables=["schema", "question"], template=cypher_template
).partial(schema=custom_schema_text)

# Create the Cypher QA chain with the updated prompt
cypher_qa = GraphCypherQAChain.from_llm(
    graph=graph,
    llm=model,
    cypher_llm=model,
    cypher_prompt=cypher_prompt,
    allow_dangerous_requests=True,
    verbose=True,
)

# Invoke the chain with a target question
question = "who are the top 3 supplier that supply vacuum cleaners and depart from Tanjung Pelepas"
response = cypher_qa.invoke({"query": question})

print("\n--- Final Answer ---")
print(response["result"])