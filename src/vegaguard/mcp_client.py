import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import Settings


class AlpacaMCPClient:
    """Thin client for the official, locally launched Alpaca MCP v2 server."""

    # Keep the external tool server reproducible. Alpaca MCP 2.3.0 imports an API
    # removed by FastMCP 4, while its published dependency currently has no upper
    # bound. An unpinned ``uvx alpaca-mcp-server`` can therefore break on restart.
    server_version = "2.3.0"
    fastmcp_requirement = "fastmcp>=3.1,<4"

    approved_tools = frozenset(
        {
            "get_account_info",
            "get_clock",
            "get_all_positions",
            "get_option_contracts",
            "get_option_chain",
            "get_option_snapshot",
            "get_orders",
            "get_order_by_client_id",
            "place_option_order",
        }
    )

    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def _uvx_command() -> str:
        """Prefer the current virtual environment's launcher over shell PATH."""
        candidate = Path(sys.executable).with_name("uvx")
        return str(candidate) if candidate.is_file() else "uvx"

    @classmethod
    def _uvx_args(cls) -> list[str]:
        return [
            "--from",
            f"alpaca-mcp-server=={cls.server_version}",
            "--with",
            cls.fastmcp_requirement,
            "alpaca-mcp-server",
        ]

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ClientSession]:
        parameters = StdioServerParameters(
            command=self._uvx_command(),
            args=self._uvx_args(),
            env=self.settings.mcp_environment(),
        )
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            yield client

    async def tool_schemas(self) -> list[dict[str, Any]]:
        async with self.session() as client:
            tools = await client.list_tools()
            return [tool.model_dump(mode="json") for tool in tools.tools]

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in self.approved_tools:
            raise RuntimeError(
                f"MCP tool {tool_name!r} is outside VegaGuard's approved tool budget"
            )
        async with self.session() as client:
            available = {tool.name for tool in (await client.list_tools()).tools}
            if tool_name not in available:
                raise RuntimeError(
                    f"MCP tool {tool_name!r} is not available. Check ALPACA_TOOLSETS."
                )
            result = await client.call_tool(tool_name, arguments)
        payloads: list[Any] = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text is None:
                continue
            try:
                payloads.append(json.loads(text))
            except json.JSONDecodeError:
                payloads.append(text)
        if getattr(result, "isError", False):
            raise RuntimeError(f"MCP {tool_name} failed: {payloads}")
        return {"tool": tool_name, "result": payloads}
