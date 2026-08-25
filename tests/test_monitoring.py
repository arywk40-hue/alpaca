from datetime import UTC, datetime, timedelta

from vegaguard.monitoring import PositionGuardian


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
