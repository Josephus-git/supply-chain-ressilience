import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult


SIMULATIONS = 100
TOOL_NAME = "simulate_disruption_cascade"
TIMEOUT_SECONDS = 300.0
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def validate_server_url(url: str) -> str:
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    if (
        parts.scheme != "https"
        or not hostname.endswith(".apify.actor")
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "MCP_SERVER_URL must be an HTTPS Apify Actor URL without credentials, "
            "a query string, or a fragment."
        )
    return url


def get_apify_token() -> str:
    token = os.getenv("APIFY_TOKEN", "").strip()
    alternate_token = os.getenv("APFIY_TOKEN", "").strip()
    if token and alternate_token and token != alternate_token:
        raise ValueError("APIFY_TOKEN and APFIY_TOKEN differ; configure only one.")
    if not token and not alternate_token:
        raise ValueError("Set APIFY_TOKEN (or APFIY_TOKEN) in the environment or .env.")
    return token or alternate_token


async def simulate_disruption(
    server_url: str, token: str, query: str
) -> CallToolResult:
    server_url = validate_server_url(server_url)
    if not token.strip():
        raise ValueError("An Apify token is required.")
    if not query.strip():
        raise ValueError("A supplier query is required.")

    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT_SECONDS,
    ) as http_client:
        async with streamable_http_client(
            server_url, http_client=http_client
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(
                    TOOL_NAME,
                    arguments={"query": query, "simulations": SIMULATIONS},
                    read_timeout_seconds=TIMEOUT_SECONDS,
                )
                if not isinstance(result, CallToolResult):
                    raise RuntimeError(
                        f"Unexpected response type from {TOOL_NAME}: "
                        f"{type(result).__name__}"
                    )
                return result


def main() -> int:
    load_dotenv(ENV_FILE)
    parser = argparse.ArgumentParser(
        description="Run one paid disruption simulation against an Apify MCP server."
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Supplier and scenario description to send to the MCP server.",
    )
    parser.add_argument(
        "--server-url",
        default=os.getenv("MCP_SERVER_URL"),
        help="Apify Actor MCP URL; alternatively set MCP_SERVER_URL in .env.",
    )
    args = parser.parse_args()
    if not args.server_url:
        parser.error("Provide --server-url or set MCP_SERVER_URL in .env.")

    try:
        token = get_apify_token()
        result = asyncio.run(simulate_disruption(args.server_url, token, args.query))
    except ValueError as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            result.model_dump(mode="json", by_alias=True, exclude_none=True),
            indent=2,
        )
    )
    if result.is_error:
        print("The MCP tool reported an error.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())