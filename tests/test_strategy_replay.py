import json
from datetime import UTC, datetime, timedelta

from vegaguard.strategy.replay import (
    ReplayObservation,
    load_observations,
    run_replay,
    write_report,
)
from vegaguard.strategy.scorer import SignalInputs


def bullish_inputs() -> SignalInputs:
    return SignalInputs(110, 100, 4, 110, 100, 105, 1.3, 0.22, 0.18, 0.2, 0.2, 0.8)


def neutral_inputs() -> SignalInputs:
    return SignalInputs(110, 100, 4, 95, 100, 115, 1.0, 0.22, 0.18, 0.4, 0.2, 0.8)


def test_replay_orders_events_without_using_future_observations(tmp_path):
    now = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    result = run_replay(
        [
            ReplayObservation(now + timedelta(minutes=15), "SPY", neutral_inputs(), 3, 2),
            ReplayObservation(now, "SPY", bullish_inputs(), 3, 2, extra_cost_per_contract=5),
        ]
    )
    assert len(result.decisions) == 2
    assert len(result.trades) == 1
    assert result.summary.net_pnl == 95
    assert result.summary.expectancy_usd_per_trade == 95
    report_path = tmp_path / "baseline.json"
    write_report(
        result, report_path, data_source="sanitized fixture", limitations=["Synthetic fixture only"]
    )
    report = json.loads(report_path.read_text())
    assert report["trades"] == 1
    assert report["limitations"] == ["Synthetic fixture only"]


def test_loads_sanitized_fixture_from_disk():
    fixture = "tests/fixtures/strategy_replay_sanitized.json"
    observations = load_observations(fixture)
    assert len(observations) == 3
    assert observations[0].symbol == "SPY"
