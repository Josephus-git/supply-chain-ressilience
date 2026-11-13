import asyncio
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx2


spec = importlib.util.spec_from_file_location(
    "mcp_client", Path(__file__).with_name("mcp_client.py")
)
assert spec is not None and spec.loader is not None
mcp_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp_client)


class MCPClientTests(unittest.TestCase):
    def test_token_names_and_conflicts(self):
        with patch.dict(os.environ, {"APFIY_TOKEN": "example"}, clear=True):
            self.assertEqual(mcp_client.get_apify_token(), "example")
        with patch.dict(os.environ, {"APIFY_TOKEN": "example"}, clear=True):
            self.assertEqual(mcp_client.get_apify_token(), "example")
        with patch.dict(
            os.environ, {"APIFY_TOKEN": "one", "APFIY_TOKEN": "two"}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, "differ"):
                mcp_client.get_apify_token()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "Set APIFY_TOKEN"):
                mcp_client.get_apify_token()

    def test_invalid_urls_are_rejected(self):
        for url in (
            "http://example.apify.actor/mcp",
            "https://example.com/mcp",
            "https://example.apify.actor.evil.com/mcp",
            "https://example.apify.actor/mcp?token=secret",
            "https://user@example.apify.actor/mcp",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                mcp_client.validate_server_url(url)

    def test_simulation_sends_mcp_request_and_preserves_response(self):
        requests = []
        original_client = httpx2.AsyncClient

        def handle_request(request):
            requests.append(request)
            self.assertEqual(request.headers["Authorization"], "Bearer example-token")
            message = json.loads(request.content)
            method = message["method"]
            if method == "notifications/initialized":
                return httpx2.Response(202)
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "test", "version": "1.0"},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "simulate_disruption_cascade",
                            "inputSchema": {"type": "object"},
                        }
                    ]
                }
            elif method == "tools/call":
                self.assertEqual(
                    message["params"],
                    {
                        "name": "simulate_disruption_cascade",
                        "arguments": {
                            "query": "Supplier A in Malaysia",
                            "simulations": 100,
                        },
                    },
                )
                result = {
                    "content": [{"type": "text", "text": '{"nodesAffected": 2}'}],
                    "structuredContent": {"nodesAffected": 2},
                    "isError": False,
                }
            else:
                self.fail(f"Unexpected MCP method: {method}")
            return httpx2.Response(
                200, json={"jsonrpc": "2.0", "id": message["id"], "result": result}
            )

        def client_factory(**kwargs):
            return original_client(transport=httpx2.MockTransport(handle_request), **kwargs)

        with patch.object(mcp_client.httpx2, "AsyncClient", side_effect=client_factory):
            result = asyncio.run(
                mcp_client.simulate_disruption(
                    "https://example.apify.actor/mcp",
                    "example-token",
                    "Supplier A in Malaysia",
                )
            )
        self.assertEqual(result.content[0].text, '{"nodesAffected": 2}')
        self.assertEqual(result.structured_content, {"nodesAffected": 2})
        self.assertFalse(result.is_error)
        self.assertGreaterEqual(len(requests), 2)

    def test_tool_error_is_printed_and_returns_failure(self):
        response = mcp_client.CallToolResult(
            content=[{"type": "text", "text": "spending limit reached"}],
            isError=True,
        )

        async def fake_simulation(server_url, token, query):
            return response

        with (
            patch.object(mcp_client, "load_dotenv"),
            patch.object(mcp_client, "simulate_disruption", fake_simulation),
            patch.dict(os.environ, {"APIFY_TOKEN": "example"}, clear=True),
            patch(
                "sys.argv",
                [
                    "mcp_client.py",
                    "--server-url",
                    "https://example.apify.actor/mcp",
                    "--query",
                    "Supplier A",
                ],
            ),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            self.assertEqual(mcp_client.main(), 1)
            self.assertTrue(json.loads(stdout.getvalue())["isError"])
            self.assertIn("spending limit reached", stdout.getvalue())
            self.assertIn("reported an error", stderr.getvalue())

    def test_empty_query_is_rejected_without_connecting(self):
        with self.assertRaisesRegex(ValueError, "supplier query"):
            asyncio.run(
                mcp_client.simulate_disruption(
                    "https://example.apify.actor/mcp", "example-token", "  "
                )
            )


if __name__ == "__main__":
    unittest.main()
