from datetime import UTC, datetime, timedelta

from vegaguard.journal import DecisionJournal
from vegaguard.monitoring import OrderLifecycle, PositionGuardian


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
