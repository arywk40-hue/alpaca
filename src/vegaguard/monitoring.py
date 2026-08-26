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
from .models import JournalEntry, TradePlan


@dataclass(frozen=True)
class ExitDecision:
    action: str
    reason: str
    spread_return_pct: float


@dataclass(frozen=True)
class LifecycleState:
    client_order_id: str
    status: str
    filled_qty: float
    updated_at: datetime


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

    def closing_plan(self, plan: TradePlan, *, executable_exit_value: float) -> TradePlan:
        return plan.closing_plan(executable_credit=executable_exit_value)


class OrderLifecycle:
    """Idempotently reduces stream events and REST order snapshots into journaled state."""

    terminal_statuses = frozenset({"filled", "canceled", "rejected", "expired"})

    def __init__(self, journal: DecisionJournal):
        self.journal = journal
        self._states: dict[str, LifecycleState] = {}

    def apply(self, event: dict[str, Any], *, source: str) -> LifecycleState | None:
        order = event.get("order", event)
        client_order_id = str(order.get("client_order_id") or "")
        status = str(event.get("event") or order.get("status") or "unknown")
        if not client_order_id:
            return None
        filled_qty = float(order.get("filled_qty") or 0)
        previous = self._states.get(client_order_id)
        if previous and previous.status == status and previous.filled_qty == filled_qty:
            return previous
        state = LifecycleState(client_order_id, status, filled_qty, datetime.now(UTC))
        self._states[client_order_id] = state
        self.journal.append(
            JournalEntry(
                event="order_lifecycle_transition",
                payload={
                    "source": source,
                    "client_order_id": client_order_id,
                    "previous_status": previous.status if previous else None,
                    "status": status,
                    "filled_qty": filled_qty,
                },
            )
        )
        return state

    def reconcile(self, orders: list[dict[str, Any]]) -> list[LifecycleState]:
        states = [
            state for order in orders if (state := self.apply(order, source="rest_reconcile"))
        ]
        return states


class PaperTradeUpdateMonitor:
    """Consume Alpaca paper ``trade_updates`` and write only an audit trail.

    This module never calls an order endpoint. It makes lifecycle state observable
    before any future, separately authorized exit-execution work is introduced.
    """

    stream_url = "wss://paper-api.alpaca.markets/stream"

    def __init__(
        self, settings: Settings, journal: DecisionJournal, lifecycle: OrderLifecycle | None = None
    ):
        self.settings = settings
        self.journal = journal
        self.lifecycle = lifecycle or OrderLifecycle(journal)

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
                self.lifecycle.apply(event, source="trade_updates")
                self._record_entry_fill(event)
                self._record_exit_outcome(event)
                yield event

    def _record_entry_fill(self, event: dict[str, Any]) -> None:
        order = event.get("order", event)
        if str(event.get("event") or order.get("status")) != "fill":
            return
        plan = self.journal.plan_for_client_order_id(str(order.get("client_order_id") or ""))
        if plan is None or plan.is_closing:
            return
        try:
            filled_price = abs(float(order.get("filled_avg_price")))
        except (TypeError, ValueError):
            return
        self.journal.record_entry_fill(plan, filled_price=filled_price, source="trade_updates")

    def _record_exit_outcome(self, event: dict[str, Any]) -> None:
        """Finalize the no-trade shadow when a previously submitted close fills."""
        order = event.get("order", event)
        if str(event.get("event") or order.get("status")) != "fill":
            return
        exit_plan = self.journal.plan_for_client_order_id(str(order.get("client_order_id") or ""))
        if exit_plan is None or not exit_plan.is_closing or not exit_plan.parent_client_order_id:
            return
        entry_plan = self.journal.plan_for_client_order_id(exit_plan.parent_client_order_id)
        filled_price = order.get("filled_avg_price")
        if entry_plan is None or filled_price is None:
            return
        entry_debit = (
            self.journal.entry_debit_for(entry_plan.client_order_id) or entry_plan.limit_price
        )
        selected_net_pnl = round((abs(float(filled_price)) - entry_debit) * 100 * entry_plan.qty, 2)
        if self.journal.record_shadow_outcome(
            entry_plan.client_order_id,
            selected_net_pnl=selected_net_pnl,
            shadow_net_pnl=0.0,
            close_reason="guardian_exit_fill",
        ):
            self.journal.append(
                JournalEntry(
                    event="shadow_outcome_recorded",
                    payload={
                        "parent_client_order_id": entry_plan.client_order_id,
                        "selected_net_pnl": selected_net_pnl,
                        "shadow_net_pnl": 0.0,
                    },
                )
            )
