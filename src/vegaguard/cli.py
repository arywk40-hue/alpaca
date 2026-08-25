import argparse
import asyncio
import json

from .config import get_settings
from .mcp_client import AlpacaMCPClient


async def _inspect_mcp() -> None:
    tools = await AlpacaMCPClient(get_settings()).tool_schemas()
    print(json.dumps(tools, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="VegaGuard paper-options agent")
    parser.add_argument("command", choices=["inspect-mcp"])
    args = parser.parse_args()
    if args.command == "inspect-mcp":
        asyncio.run(_inspect_mcp())

