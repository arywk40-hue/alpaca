"""Read-only paper-account and MCP readiness checks for a reproducible demo."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .alpaca_api import AlpacaRESTClient
from .config import Settings
from .mcp_client import AlpacaMCPClient


class PaperPreflight:
    """Prove configuration surfaces without calling OpenAI or submitting orders."""

    required_mcp_tools = frozenset(
        {
            "get_account_info",
            "get_clock",
            "get_all_positions",
            "get_option_contracts",
            "get_option_chain",
            "get_option_snapshot",
            "get_orders",
            "place_option_order",
        }
    )

    def __init__(
        self,
        settings: Settings,
        *,
        alpaca: AlpacaRESTClient | None = None,
        mcp: AlpacaMCPClient | None = None,
    ):
        self.settings = settings
        self.alpaca = alpaca or AlpacaRESTClient(settings)
        self.mcp = mcp or AlpacaMCPClient(settings)

    async def run(self) -> dict[str, Any]:
        if not self.settings.alpaca_paper_trade:
            raise RuntimeError("VegaGuard refuses a non-paper preflight")
        account, clock, snapshots, schemas = await asyncio.gather(
            self.alpaca.account(),
            self.alpaca.clock(),
            self.alpaca.option_snapshots(self.settings.universe[0]),
            self.mcp.tool_schemas(),
        )
        tool_names = sorted(str(schema.get("name")) for schema in schemas if schema.get("name"))
        missing_tools = sorted(self.required_mcp_tools - set(tool_names))
        return {
            "status": "ready" if not missing_tools else "incomplete",
            "checked_at": datetime.now(UTC).isoformat(),
            "paper_only": True,
            "rest": {
                "account_status": account.get("status"),
                "account_id_present": bool(account.get("id")),
                "market_open": bool(clock.get("is_open")),
            },
            "market_data": {
                "underlying": self.settings.universe[0],
                "option_snapshot_count": len(snapshots),
            },
            "mcp": {
                "available_tools": tool_names,
                "missing_required_tools": missing_tools,
                "schemas": schemas,
            },
        }

    @staticmethod
    def write_report(report: dict[str, Any], path: str | Path = "data/mcp_preflight.json") -> Path:
        """Persist the schema/result only; no setting values or API keys are serialized."""
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return output
