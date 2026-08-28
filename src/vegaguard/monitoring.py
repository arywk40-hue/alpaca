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
    provider_status: str
    fill_state: str
    filled_qty: float
    updated_at: datetime
    provider_order_id: str | None = None


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
        now: datetime | None = None,
    ) -> ExitDecision:
        if entry_debit <= 0:
            raise ValueError("entry debit must be positive")
        now = (now or datetime.now(UTC)).astimezone(UTC)
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

    terminal_statuses = frozenset({"filled", "cancelled", "rejected", "expired"})

    def __init__(self, journal: DecisionJournal):
        self.journal = journal
        self._states: dict[str, LifecycleState] = {}

    def apply(self, event: dict[str, Any], *, source: str) -> LifecycleState | None:
        order = event.get("order", event)
        client_order_id = str(order.get("client_order_id") or "")
        provider_status = str(event.get("event") or order.get("status") or "unknown").lower()
        status = self._canonical_status(provider_status)
        if not client_order_id:
            return None
        filled_qty = float(order.get("filled_qty") or 0)
        previous = self._states.get(client_order_id)
        if previous and previous.status == status and previous.filled_qty == filled_qty:
            return previous
        quantity = float(order.get("qty") or 0)
        fill_state = (
            "filled"
            if status == "filled"
            else "partially_filled"
            if filled_qty > 0
            else "unfilled_terminal"
            if status in self.terminal_statuses
            else "unfilled_pending"
        )
        updated_at = self._provider_timestamp(
            order.get("updated_at") or order.get("filled_at") or event.get("timestamp")
        )
        provider_order_id = str(order.get("id")) if order.get("id") is not None else None
        state = LifecycleState(
            client_order_id,
            status,
            provider_status,
            fill_state,
            filled_qty,
            updated_at,
            provider_order_id,
        )
        self._states[client_order_id] = state
        self.journal.append(
            JournalEntry(
                event="order_lifecycle_transition",
                payload={
                    "source": source,
                    "client_order_id": client_order_id,
                    "previous_status": previous.status if previous else None,
                    "status": status,
                    "provider_status": provider_status,
                    "provider_order_id": provider_order_id,
                    "fill_state": fill_state,
                    "filled_qty": filled_qty,
                    "ordered_qty": quantity or None,
                    "provider_updated_at": updated_at.isoformat(),
                },
            )
        )
        return state

    def reconcile(self, orders: list[dict[str, Any]]) -> list[LifecycleState]:
        states = [
            state for order in orders if (state := self.apply(order, source="rest_reconcile"))
        ]
        return states

    @staticmethod
    def _canonical_status(status: str) -> str:
        return {
            "new": "accepted",
            "pending_new": "submitted",
            "accepted": "accepted",
            "partial_fill": "partially_filled",
            "partially_filled": "partially_filled",
            "fill": "filled",
            "filled": "filled",
            "canceled": "cancelled",
            "cancelled": "cancelled",
        }.get(status, status)

    @staticmethod
    def _provider_timestamp(value: Any) -> datetime:
        if value is None:
            return datetime.now(UTC)
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return datetime.now(UTC)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


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
        if (
            OrderLifecycle._canonical_status(
                str(event.get("event") or order.get("status") or "").lower()
            )
            != "filled"
        ):
            return
        plan = self.journal.plan_for_client_order_id(str(order.get("client_order_id") or ""))
        if plan is None or plan.is_closing:
            return
        try:
            filled_price = abs(float(order.get("filled_avg_price")))
        except (TypeError, ValueError):
            return
        self.journal.record_entry_fill(
            plan,
            filled_price=filled_price,
            source="trade_updates",
            filled_at=OrderLifecycle._provider_timestamp(order.get("filled_at")),
            provider_order_id=str(order.get("id")) if order.get("id") is not None else None,
            fees_usd=self._provider_fees(order),
        )

    def _record_exit_outcome(self, event: dict[str, Any]) -> None:
        """Finalize the no-trade shadow when a previously submitted close fills."""
        order = event.get("order", event)
        if (
            OrderLifecycle._canonical_status(
                str(event.get("event") or order.get("status") or "").lower()
            )
            != "filled"
        ):
            return
        exit_plan = self.journal.plan_for_client_order_id(str(order.get("client_order_id") or ""))
        if exit_plan is None or not exit_plan.is_closing or not exit_plan.parent_client_order_id:
            return
        entry_plan = self.journal.plan_for_client_order_id(exit_plan.parent_client_order_id)
        filled_price = order.get("filled_avg_price")
        if entry_plan is None or filled_price is None:
            return
        entry_fill = self.journal.entry_fill_for(entry_plan.client_order_id)
        entry_debit = self.journal.entry_debit_for(entry_plan.client_order_id)
        if entry_fill is None or entry_debit is None:
            return
        exit_credit = abs(float(filled_price))
        multiplier = 100
        gross_realized_pnl = round((exit_credit - entry_debit) * multiplier * entry_plan.qty, 2)
        entry_fees = self._optional_float((entry_fill.get("payload") or {}).get("fees_usd"))
        exit_fees = self._provider_fees(order)
        total_fees = (
            round(entry_fees + exit_fees, 2)
            if entry_fees is not None and exit_fees is not None
            else None
        )
        realized_after_fees = (
            round(gross_realized_pnl - total_fees, 2) if total_fees is not None else None
        )
        entry_slippage = float(
            (entry_fill.get("payload") or {}).get("entry_slippage_vs_approved_limit_usd", 0.0)
        )
        exit_slippage = round(
            (abs(exit_plan.limit_price) - exit_credit) * multiplier * entry_plan.qty, 2
        )
        total_slippage = round(entry_slippage + exit_slippage, 2)
        maximum_adverse, maximum_favorable = self.journal.position_excursions(
            entry_plan.client_order_id
        )
        exit_reason = (
            self.journal.exit_reason_for(exit_plan.client_order_id) or "unknown_exit_reason"
        )
        if self.journal.record_shadow_outcome(
            entry_plan.client_order_id,
            selected_net_pnl=gross_realized_pnl,
            shadow_net_pnl=0.0,
            close_reason=exit_reason,
        ):
            self.journal.append(
                JournalEntry(
                    timestamp=OrderLifecycle._provider_timestamp(order.get("filled_at")),
                    event="exit_fill_reconciled",
                    plan=exit_plan,
                    payload={
                        "filled_price": exit_credit,
                        "entry_debit": entry_debit,
                        "debit_paid_usd": round(entry_debit * multiplier * entry_plan.qty, 2),
                        "credit_received_usd": round(exit_credit * multiplier * entry_plan.qty, 2),
                        "contract_multiplier": multiplier,
                        "quantity": entry_plan.qty,
                        "reason": exit_reason,
                        "provider_order_id": str(order.get("id"))
                        if order.get("id") is not None
                        else None,
                        "entry_fees_usd": entry_fees,
                        "exit_fees_usd": exit_fees,
                        "total_fees_usd": total_fees,
                        "fees_status": "reported_by_provider"
                        if total_fees is not None
                        else "not_reported_by_alpaca",
                        "slippage_vs_limits_usd": total_slippage,
                        "realized_pnl_before_fees": gross_realized_pnl,
                        "realized_pnl_after_fees": realized_after_fees,
                        "maximum_adverse_excursion_usd": maximum_adverse,
                        "maximum_favorable_excursion_usd": maximum_favorable,
                    },
                )
            )
            self.journal.append(
                JournalEntry(
                    event="shadow_outcome_recorded",
                    payload={
                        "parent_client_order_id": entry_plan.client_order_id,
                        "selected_net_pnl": gross_realized_pnl,
                        "selected_pnl_basis": "actual_fills_before_unreported_fees",
                        "realized_pnl_before_costs": gross_realized_pnl,
                        "pnl_after_costs": realized_after_fees,
                        "costs_usd": total_fees,
                        "costs_status": "reported_by_provider"
                        if total_fees is not None
                        else "not_reported_by_alpaca",
                        "shadow_net_pnl": 0.0,
                        "exit_filled_price": exit_credit,
                    },
                )
            )

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            return abs(float(value)) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _provider_fees(cls, order: dict[str, Any]) -> float | None:
        for key in ("commission", "fees", "fee"):
            if key in order:
                return cls._optional_float(order.get(key))
        return None
