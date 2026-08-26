from datetime import UTC, datetime, timedelta

from vegaguard.config import Settings
from vegaguard.scanner import OpportunityScanner
from vegaguard.strategy.scorer import Regime, score_signal
from vegaguard.strategy.spread_builder import build_debit_spread


def test_live_scanner_requires_prior_iv_observation_then_builds_same_bull_spread():
    now = datetime(2026, 8, 26, 15, 30, tzinfo=UTC)
    scanner = OpportunityScanner(Settings(), alpaca=object())
    daily = [{"c": 500 + index} for index in range(25)]
    intraday = [
        {
            "t": (now - timedelta(minutes=30 * (25 - index))).isoformat(),
            "c": 540 + index,
            "h": 540.2 + index,
            "l": 539.8 + index,
            "v": 100 if index < 24 else 200,
        }
        for index in range(25)
    ]
    snapshots = {
        "SPY260918C00560000": {
            "latestQuote": {"t": now.isoformat(), "bp": 3.4, "ap": 3.5},
            "greeks": {"delta": 0.46},
            "impliedVolatility": 0.2,
        },
        "SPY260918C00565000": {
            "latestQuote": {"t": now.isoformat(), "bp": 2.2, "ap": 2.3},
            "greeks": {"delta": 0.24},
            "impliedVolatility": 0.2,
        },
    }
    first, reasons = scanner._signal_inputs("SPY", daily, intraday, daily, snapshots, now)
    assert first is None
    assert "implied-volatility state" in reasons[0]
    inputs, reasons = scanner._signal_inputs("SPY", daily, intraday, daily, snapshots, now)
    assert reasons == []
    assert inputs is not None
    score = score_signal(inputs)
    assert score.regime == Regime.BULLISH
    candidates = scanner._option_candidates("SPY", inputs.price, snapshots, now)
    spread = build_debit_spread(candidates, score.regime)
    assert spread is not None
    assert spread.long_leg.symbol == "SPY260918C00560000"
    assert spread.short_leg.symbol == "SPY260918C00565000"


def test_live_scanner_reports_unavailable_greeks_as_data_limitation_not_missing_history():
    now = datetime(2026, 8, 26, 15, 30, tzinfo=UTC)
    scanner = OpportunityScanner(Settings(), alpaca=object())
    daily = [{"c": 500 + index} for index in range(25)]
    intraday = [
        {
            "t": (now - timedelta(minutes=30 * (25 - index))).isoformat(),
            "c": 540 + index,
            "h": 540.2 + index,
            "l": 539.8 + index,
            "v": 100,
        }
        for index in range(25)
    ]
    inputs, reasons = scanner._signal_inputs(
        "SPY",
        daily,
        intraday,
        daily,
        {"SPY260918C00560000": {"latestQuote": {}}},
        now,
    )
    assert inputs is None
    assert "option snapshots contained no IV/Greeks or fresh solvable quote-derived IV" in reasons
    assert not any("two fresh" in reason for reason in reasons)


def test_live_scanner_derives_iv_and_delta_from_fresh_observed_option_quotes():
    now = datetime(2026, 8, 26, 15, 30, tzinfo=UTC)
    scanner = OpportunityScanner(Settings(), alpaca=object())
    snapshots = {
        "SPY260916C00100000": {
            "latestQuote": {"t": now.isoformat(), "bp": 2.4, "ap": 2.6},
        }
    }
    iv_values = scanner._iv_values(snapshots, underlying_price=100, now=now)
    assert iv_values and iv_values[0] > 0
    candidates = scanner._option_candidates("SPY", 100, snapshots, now)
    assert len(candidates) == 1
    assert candidates[0].implied_volatility is not None
    assert candidates[0].delta is not None
