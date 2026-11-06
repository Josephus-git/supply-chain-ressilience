import json
import random
from mcp.server.mcpserver import MCPServer

# Initialize MCP 2.x server
mcp = MCPServer("SupplyChainDigitalTwin")

@mcp.tool()
def simulate_disruption_cascade(
    network_graph: dict,
    target_supplier: str,
    monteCarloRuns: int = 100,
    varianceReduction: bool = True
) -> str:
    """Run a local Monte Carlo disruption cascade simulation across a supply chain network."""
    
    nodes = network_graph.get("nodes", [])
    edges = network_graph.get("edges", [])

    failure_counts = 0
    total_delay = 0

    for _ in range(monteCarloRuns):
        simulated_delay = sum(random.uniform(1.0, 5.0) * edge.get("weight", 1.0) for edge in edges)
        if simulated_delay > 8.0:
            failure_counts += 1
        total_delay += simulated_delay

    failure_probability = failure_counts / monteCarloRuns
    avg_delay = total_delay / monteCarloRuns

    cascade_steps = [
        {
            "node": target_supplier,
            "failureProbability": round(failure_probability, 2),
            "cascadeDelay": round(avg_delay, 1),
            "economicImpact": round(failure_probability * 1.5, 2)
        }
    ]

    result = {
        "status": "success",
        "nodesAffected": len(nodes),
        "percolationThreshold": 0.42,
        "cascadeSteps": cascade_steps
    }

    return json.dumps(result)

if __name__ == "__main__":
    mcp.run(transport="stdio")