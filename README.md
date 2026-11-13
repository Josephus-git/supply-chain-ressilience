# Disruption simulation experiment

The MCP client calls an external Apify server. Set `APIFY_TOKEN` in the
repository's `.env` file (`APFIY_TOKEN` is also accepted), and set
`MCP_SERVER_URL` to the HTTPS MCP URL from your Actor's Apify Server tab,
including its MCP path. Keep the token private and do not put it in the URL.

Run one simulation with a supplier and scenario description:

```bash
python langchain/mcp_client.py --query "Assess disruption risk for Supplier A in Malaysia."
```

You can provide the endpoint with `--server-url` instead of `MCP_SERVER_URL`.
The client sends `simulations=100` and prints the complete MCP tool response.
It does not yet retrieve suppliers from Neo4j. Only send supplier details you
are comfortable sharing with the external service.

Calls may incur charges. The upstream README describes pay-per-tool-call
pricing, so 100 simulations does not necessarily reduce the price. Confirm
the current pricing and spending limit in Apify before running the client.
The hosted service constructs its own network; it does not directly simulate
your Neo4j graph.