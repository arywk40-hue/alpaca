import argparse
import asyncio
import json
from pathlib import Path

from .config import get_settings
from .mcp_client import AlpacaMCPClient
from .strategy.replay import load_observations, run_replay, write_report


async def _inspect_mcp() -> None:
    tools = await AlpacaMCPClient(get_settings()).tool_schemas()
    print(json.dumps(tools, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="VegaGuard paper-options agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inspect-mcp")
    replay_parser = subparsers.add_parser("replay")
    replay_parser.add_argument("--fixture", required=True, help="Sanitized replay input JSON")
    replay_parser.add_argument("--output", default="results/strategy_replay.json")
    replay_parser.add_argument("--data-source", default="sanitized fixture")
    args = parser.parse_args()
    if args.command == "inspect-mcp":
        asyncio.run(_inspect_mcp())
    if args.command == "replay":
        result = run_replay(load_observations(args.fixture))
        write_report(
            result,
            Path(args.output),
            data_source=args.data_source,
            limitations=[
                "This fixture validates deterministic accounting only.",
                "It is not a claim of historical or live strategy performance.",
            ],
        )
        print(json.dumps(result.summary.as_dict(), indent=2))
