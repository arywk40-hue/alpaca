"""Paper trade-update intake and deterministic, non-executing exit decisions."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import websockets

from .config import Settings
from .journal import DecisionJournal
from .models import JournalEntry


@dataclass(frozen=True)
class ExitDecision:
    action: str
    reason: str
    spread_return_pct: float


class PositionGuardian:
    """Evaluates exits only; execution remains separately gated and disabled by default."""

    def evaluate(
        self,
        *,
        entry_debit: float,
        executable_exit_value: float,
        entered_at: datetime,
        expiration: datetime,
        signal_reversed: bool = False,
    ) -> ExitDecision:
        if entry_debit <= 0:
            raise ValueError("entry debit must be positive")
        now = datetime.now(UTC)
        spread_return = (executable_exit_value - entry_debit) / entry_debit
        if spread_return >= 0.50:
            return ExitDecision("exit", "take_profit", spread_return)
        if spread_return <= -0.35:
            return ExitDecision("exit", "stop_loss", spread_return)
        if signal_reversed:
            return ExitDecision("exit", "signal_reversal", spread_return)
        if now - entered_at.astimezone(UTC) >= timedelta(days=3):
            return ExitDecision("exit", "time_stop", spread_return)
        if expiration.astimezone(UTC).date() - now.date() <= timedelta(days=2):
            return ExitDecision("exit", "expiry_exit", spread_return)
        return ExitDecision("hold", "no_exit_trigger", spread_return)


class PaperTradeUpdateMonitor:
    """Consume Alpaca paper ``trade_updates`` and write only an audit trail.

    This module never calls an order endpoint. It makes lifecycle state observable
    before any future, separately authorized exit-execution work is introduced.
    """

    stream_url = "wss://paper-api.alpaca.markets/stream"

    def __init__(self, settings: Settings, journal: DecisionJournal):
        self.settings = settings
        self.journal = journal

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        if not self.settings.alpaca_paper_trade:
            raise RuntimeError("refusing to monitor a non-paper account")
        if not self.settings.alpaca_api_key or not self.settings.alpaca_secret_key:
            raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env")
        async with websockets.connect(self.stream_url) as socket:
            await socket.send(
                json.dumps(
                    {
                        "action": "auth",
                        "key": self.settings.alpaca_api_key.get_secret_value(),
                        "secret": self.settings.alpaca_secret_key.get_secret_value(),
                    }
                )
            )
            await socket.send(
                json.dumps({"action": "listen", "data": {"streams": ["trade_updates"]}})
            )
            async for message in socket:
                payload = json.loads(message)
                if payload.get("stream") != "trade_updates":
                    continue
                event = payload.get("data", {})
                self.journal.append(JournalEntry(event="trade_update", payload=event))
                yield event
