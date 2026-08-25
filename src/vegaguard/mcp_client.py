import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import Settings


class AlpacaMCPClient:
    """Thin client for the official, locally launched Alpaca MCP v2 server."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ClientSession]:
        parameters = StdioServerParameters(
            command="uvx",
            args=["alpaca-mcp-server"],
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
