import os
import json
import asyncio
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

SIMULATION_PAYLOAD = {
    "network_graph": {
        "nodes": [
            "Flextronics Shah Alam",
            "Port of Penang",
            "Port of Felixstowe",
            "Dyson UK Distribution"
        ],
        "edges": [
            {"source": "Flextronics Shah Alam", "target": "Port of Penang", "weight": 1.0},
            {"source": "Port of Penang", "target": "Port of Felixstowe", "weight": 0.8},
            {"source": "Port of Felixstowe", "target": "Dyson UK Distribution", "weight": 1.0}
        ]
    },
    "target_supplier": "Flextronics Shah Alam",
    "monteCarloRuns": 100,
    "varianceReduction": True
}

async def run_flextronics_test():
    print("Starting local Supply Chain Digital Twin MCP Server...")

    # Point directly to your local Python server script
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "langchain/digital_twin_server.py"],
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONUNBUFFERED": "1"  # Ensures real-time stdout/stdin streaming
        }
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Local MCP Connection Established!")

            print("\nRunning disruption simulation for Flextronics Shah Alam...")
            result = await session.call_tool(
                "simulate_disruption_cascade", 
                arguments=SIMULATION_PAYLOAD
            )

            raw_text = result.content[0].text
            response_json = json.loads(raw_text)

            cascade_steps = response_json.get("cascadeSteps", [])
            target_step = next(
                (step for step in cascade_steps if step.get("node") == "Flextronics Shah Alam"), 
                {}
            )

            compact_summary = {
                "target_node": "Flextronics Shah Alam",
                "failure_probability": target_step.get("failureProbability", 0),
                "cascade_delay_days": target_step.get("cascadeDelay", 0),
                "economic_impact_m": target_step.get("economicImpact", 0),
                "total_affected_nodes": response_json.get("nodesAffected", 0),
                "percolation_threshold": response_json.get("percolationThreshold", 0)
            }

            print("\n--- Flextronics Disruption Test Output ---")
            print(json.dumps(compact_summary, indent=2))
            return compact_summary

if __name__ == "__main__":
    asyncio.run(run_flextronics_test())