from datetime import UTC, datetime, timedelta

import pytest
from test_execution import NoCallMCP, plan

from vegaguard.config import Settings
from vegaguard.execution import PaperExecutionAgent
from vegaguard.journal import DecisionJournal
from vegaguard.models import GateResult, JournalEntry
from vegaguard.monitoring import OrderLifecycle, PaperTradeUpdateMonitor, PositionGuardian
from vegaguard.service import AutonomousCycle


def test_guardian_applies_profit_stop_and_reversal_exits_without_execution():
    guardian = PositionGuardian()
    entered = datetime.now(UTC) - timedelta(hours=1)
    expiration = datetime.now(UTC) + timedelta(days=10)
    assert (
        guardian.evaluate(
            entry_debit=1,
            executable_exit_value=1.5,
            entered_at=entered,
            expiration=expiration,
        ).reason
        == "take_profit"
    )
    assert (
        guardian.evaluate(
            entry_debit=1,
            executable_exit_value=0.65,
            entered_at=entered,
            expiration=expiration,
        ).reason
        == "stop_loss"
    )
    assert (
        guardian.evaluate(
            entry_debit=1,
            executable_exit_value=1,
            entered_at=entered,
            expiration=expiration,
            signal_reversed=True,
        ).reason
        == "signal_reversal"
    )


def test_guardian_applies_time_stop():
    decision = PositionGuardian().evaluate(
        entry_debit=1,
        executable_exit_value=1,
        entered_at=datetime.now(UTC) - timedelta(days=3, minutes=1),
        expiration=datetime.now(UTC) + timedelta(days=10),
    )
    assert decision.action == "exit"
    assert decision.reason == "time_stop"


def test_lifecycle_handles_partial_fill_and_rest_reconnect_idempotently(tmp_path):
    lifecycle = OrderLifecycle(DecisionJournal(tmp_path / "journal.jsonl"))
    partial = lifecycle.apply(
        {"event": "partial_fill", "order": {"client_order_id": "vg-1", "filled_qty": "1"}},
        source="trade_updates",
    )
    assert partial is not None and partial.status == "partial_fill"
    reconciled = lifecycle.reconcile(
        [{"client_order_id": "vg-1", "status": "filled", "filled_qty": "2"}]
    )
    assert reconciled[0].status == "filled"
    repeated = lifecycle.reconcile(
        [{"client_order_id": "vg-1", "status": "filled", "filled_qty": "2"}]
    )
    assert repeated[0] == reconciled[0]


def test_trade_update_records_selected_vs_no_trade_outcome_on_guardian_exit_fill(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    entry = plan()
    journal.register_shadow(entry, regime="bullish")
    journal.append(
        JournalEntry(
            event="order_submission_intent", plan=entry, gate=GateResult(approved=True, reasons=[])
        )
    )
    exit_plan = entry.closing_plan(executable_credit=1.8)
    journal.append(
        JournalEntry(
            event="exit_submission_intent",
            plan=exit_plan,
            gate=GateResult(approved=True, reasons=[]),
        )
    )
    PaperTradeUpdateMonitor(Settings(), journal)._record_exit_outcome(
        {
            "event": "fill",
            "order": {"client_order_id": exit_plan.client_order_id, "filled_avg_price": "1.8"},
        }
    )
    shadow = journal.shadows()[0]
    assert shadow["selected_net_pnl"] == 50.0
    assert shadow["shadow_net_pnl"] == 0.0


def test_trade_update_uses_actual_entry_fill_for_realized_paper_pnl(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    entry = plan()
    journal.register_shadow(entry, regime="bullish")
    journal.append(
        JournalEntry(
            event="order_submission_intent", plan=entry, gate=GateResult(approved=True, reasons=[])
        )
    )
    monitor = PaperTradeUpdateMonitor(Settings(), journal)
    monitor._record_entry_fill(
        {
            "event": "fill",
            "order": {"client_order_id": entry.client_order_id, "filled_avg_price": "1.4"},
        }
    )
    assert journal.entry_debit_for(entry.client_order_id) == 1.4
    exit_plan = entry.closing_plan(executable_credit=1.8)
    journal.append(
        JournalEntry(
            event="exit_submission_intent",
            plan=exit_plan,
            gate=GateResult(approved=True, reasons=[]),
        )
    )
    monitor._record_exit_outcome(
        {
            "event": "fill",
            "order": {"client_order_id": exit_plan.client_order_id, "filled_avg_price": "1.8"},
        }
    )
    assert journal.shadows()[0]["selected_net_pnl"] == 40.0
    evidence = journal.complete_trade_evidence()
    assert len(evidence) == 1
    assert evidence[0]["client_order_id"] == entry.client_order_id
    assert evidence[0]["underlying"] == "SPY"
    assert evidence[0]["trade_mode"] == "production"
    assert evidence[0]["score_threshold"] == 70
    assert evidence[0]["strategy"] == "debit_spread"
    assert evidence[0]["quantity"] == 1
    assert evidence[0]["entry_filled_at"]
    assert evidence[0]["entry_debit"] == 1.4
    assert evidence[0]["exit_filled_at"]
    assert evidence[0]["exit_credit"] == 1.8
    assert evidence[0]["exit_reason"] == "guardian_exit_fill"
    assert evidence[0]["realized_pnl"] == 40.0


@pytest.mark.asyncio
async def test_lifecycle_manager_only_closes_a_filled_tracked_spread_in_dry_run(tmp_path):
    settings = Settings(allow_order_execution=True, dry_run=True)
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    executor = PaperExecutionAgent(settings, journal, NoCallMCP())
    cycle = AutonomousCycle(settings, executor)
    entry = plan()
    journal.append(
        JournalEntry(
            event="order_submission_intent", plan=entry, gate=GateResult(approved=True, reasons=[])
        )
    )

    async def account_state():
        return {}, {"is_open": True}, []

    async def orders():
        return [
            {
                "client_order_id": entry.client_order_id,
                "status": "filled",
                "filled_at": "2026-09-01T14:00:00Z",
            }
        ]

    async def snapshots(_underlying):
        return {
            entry.legs[0].symbol: {"latestQuote": {"bp": 2.6, "ap": 2.7}},
            entry.legs[1].symbol: {"latestQuote": {"bp": 0.4, "ap": 0.5}},
        }

    cycle._account_state = account_state
    cycle.alpaca.orders = orders
    cycle.alpaca.option_snapshots = snapshots
    managed = await cycle.manage_open_spreads()
    assert managed["managed"][0]["status"] == "dry_run"
    assert managed["managed"][0]["reason"] == "take_profit"
    marks = [event for event in journal.latest() if event["event"] == "position_mark"]
    assert marks[0]["payload"]["unrealized_pnl"] == 80.0
