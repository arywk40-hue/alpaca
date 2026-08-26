"""Market-hours scheduler for the bounded paper-trading cycle."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from httpx import HTTPError

from .journal import DecisionJournal
from .models import JournalEntry


class MarketHoursScheduler:
    """Runs an autonomous cycle at a fixed cadence and journals every outcome.

    The cycle itself checks Alpaca's paper clock before it scans or can submit a
    plan. Keeping that check inside the cycle makes this scheduler safe to start
    before market open and resilient to a stale local wall clock.
    """

    def __init__(
        self,
        cycle: Any,
        journal: DecisionJournal,
        *,
        interval_seconds: int = 900,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        if interval_seconds < 60:
            raise ValueError("scheduler interval must be at least 60 seconds")
        self.cycle = cycle
        self.journal = journal
        self.interval_seconds = interval_seconds
        self.sleep = sleep

    async def run(self, *, max_cycles: int | None = None) -> list[dict[str, Any]]:
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be at least one")
        outcomes: list[dict[str, Any]] = []
        while max_cycles is None or len(outcomes) < max_cycles:
            try:
                lifecycle = None
                manager = getattr(self.cycle, "manage_open_spreads", None)
                if callable(manager):
                    lifecycle = await manager()
                outcome = await self.cycle.run_once()
                if lifecycle is not None:
                    outcome = {"entry_cycle": outcome, "lifecycle": lifecycle}
            except (HTTPError, OSError, RuntimeError, TimeoutError) as exc:
                # Keep paper monitoring alive after a transient data/runtime failure.
                outcome = {
                    "status": "cycle_error",
                    "error_type": type(exc).__name__,
                    "reason": str(exc) or type(exc).__name__,
                }
            outcomes.append(outcome)
            self.journal.append(JournalEntry(event="scheduled_cycle", payload=outcome))
            if max_cycles is None or len(outcomes) < max_cycles:
                await self.sleep(self.interval_seconds)
        return outcomes
