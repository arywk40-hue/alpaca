"""Market-hours scheduler for the bounded paper-trading cycle."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
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
        management_interval_seconds: int = 60,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        session_id: str | None = None,
        process_id: int | None = None,
    ):
        if interval_seconds < 60:
            raise ValueError("scheduler interval must be at least 60 seconds")
        if management_interval_seconds < 60:
            raise ValueError("position management interval must be at least 60 seconds")
        self.cycle = cycle
        self.journal = journal
        self.interval_seconds = interval_seconds
        self.management_interval_seconds = min(management_interval_seconds, interval_seconds)
        self.sleep = sleep
        self.now = now
        self.session_id = session_id
        self.process_id = process_id
        # Continuous workers never return their accumulated results, so retain
        # only a bounded diagnostic window while the journal remains the full
        # durable history.
        self.recent_outcomes: deque[dict[str, Any]] = deque(maxlen=100)

    async def run(self, *, max_cycles: int | None = None) -> list[dict[str, Any]]:
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be at least one")
        outcomes: list[dict[str, Any]] = []
        cycle_number = 0
        while max_cycles is None or cycle_number < max_cycles:
            cycle_number += 1
            started_at = self.now().astimezone(UTC)
            self.journal.append(
                JournalEntry(
                    timestamp=started_at,
                    event="scheduler_heartbeat",
                    payload={
                        "status": "running",
                        "cycle_number": cycle_number,
                        "interval_seconds": self.interval_seconds,
                        "management_interval_seconds": self.management_interval_seconds,
                        "next_run_at": None,
                        "session_id": self.session_id,
                        "process_id": self.process_id,
                        "last_cycle_started_at": started_at.isoformat(),
                    },
                )
            )
            lifecycle = None
            try:
                manager = getattr(self.cycle, "manage_open_spreads", None)
                if callable(manager):
                    lifecycle = await manager()
                entry_outcome = await self.cycle.run_once()
            except (HTTPError, OSError, RuntimeError, TimeoutError) as exc:
                # Keep paper monitoring alive after a transient data/runtime failure.
                entry_outcome = {
                    "status": "cycle_error",
                    "error_type": type(exc).__name__,
                    "reason": str(exc) or type(exc).__name__,
                }
            outcome = (
                {"entry_cycle": entry_outcome, "lifecycle": lifecycle}
                if lifecycle is not None
                else entry_outcome
            )
            self.recent_outcomes.append(outcome)
            if max_cycles is not None:
                outcomes.append(outcome)
            self.journal.append(JournalEntry(event="scheduled_cycle", payload=outcome))
            should_continue = max_cycles is None or cycle_number < max_cycles
            heartbeat_at = self.now().astimezone(UTC)
            next_run_at = heartbeat_at + timedelta(seconds=self.interval_seconds)
            entry_status = self._entry_outcome(outcome)
            cycle_failed = entry_status.get("status") == "cycle_error"
            market_open = self._market_open(outcome)
            lifecycle_open = isinstance(lifecycle, dict) and lifecycle.get("status") == "ok"
            self.journal.append(
                JournalEntry(
                    timestamp=heartbeat_at,
                    event="scheduler_heartbeat",
                    payload={
                        "status": "error"
                        if cycle_failed
                        else "waiting"
                        if should_continue
                        else "stopped",
                        "cycle_number": cycle_number,
                        "interval_seconds": self.interval_seconds,
                        "management_interval_seconds": self.management_interval_seconds,
                        "last_cycle_status": entry_status.get("status", "completed"),
                        "last_error": entry_status.get("reason") if cycle_failed else None,
                        "next_run_at": next_run_at.isoformat() if should_continue else None,
                        "session_id": self.session_id,
                        "process_id": self.process_id,
                        "last_cycle_started_at": started_at.isoformat(),
                        "last_cycle_completed_at": heartbeat_at.isoformat(),
                        "last_successful_cycle_at": None
                        if cycle_failed
                        else heartbeat_at.isoformat(),
                        "market_open": market_open,
                    },
                )
            )
            if should_continue:
                await self._wait_for_next_cycle(
                    manage_positions=market_open is True or lifecycle_open
                )
        return outcomes

    async def _wait_for_next_cycle(self, *, manage_positions: bool) -> None:
        """Evaluate open-position exits between the slower entry scans."""
        manager = getattr(self.cycle, "manage_open_spreads", None)
        if (
            not manage_positions
            or not callable(manager)
            or self.management_interval_seconds >= self.interval_seconds
        ):
            await self.sleep(self.interval_seconds)
            return

        elapsed = 0
        while elapsed < self.interval_seconds:
            delay = min(self.management_interval_seconds, self.interval_seconds - elapsed)
            await self.sleep(delay)
            elapsed += delay
            if elapsed >= self.interval_seconds:
                return
            try:
                outcome = await manager()
            except (HTTPError, OSError, RuntimeError, TimeoutError) as exc:
                outcome = {
                    "status": "management_error",
                    "error_type": type(exc).__name__,
                    "reason": str(exc) or type(exc).__name__,
                }
            self.journal.append(JournalEntry(event="position_management_cycle", payload=outcome))
            if outcome.get("status") == "market_closed":
                await self.sleep(self.interval_seconds - elapsed)
                return

    @staticmethod
    def _entry_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
        entry = outcome.get("entry_cycle")
        return entry if isinstance(entry, dict) else outcome

    @staticmethod
    def _market_open(outcome: dict[str, Any]) -> bool | None:
        entry = MarketHoursScheduler._entry_outcome(outcome)
        if entry.get("reason") == "market_closed" or entry.get("status") == "market_closed":
            return False
        if entry.get("status") == "cycle_error":
            return None
        return True
