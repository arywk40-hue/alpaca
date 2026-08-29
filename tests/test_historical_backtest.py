import json
from datetime import UTC, datetime, timedelta

import pytest

from vegaguard.data.cache import LocalMarketDataCache
from vegaguard.models import OptionCandidate
from vegaguard.strategy.backtest import (
    HistoricalBacktester,
    _latest_quote,
    _OpenPosition,
    write_historical_report,
)
from vegaguard.strategy.options_math import black_scholes_price
from vegaguard.strategy.scorer import Regime, SignalInputs
from vegaguard.strategy.spread_builder import DebitSpread


def _write_records(directory, name, rows):
    (directory / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")


def _bar(symbol, timestamp, close, volume=100):
    return {
        "symbol": symbol,
        "timestamp": timestamp.isoformat(),
        "open": close - 0.1,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": volume,
    }


def test_backtest_rejects_contract_metadata_observed_in_the_future(tmp_path):
    bar_timestamp = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    decision_at = bar_timestamp + timedelta(minutes=30)
    daily = [
        _bar("SPY", bar_timestamp - timedelta(days=30 - index), 500 + index) for index in range(25)
    ]
    intraday = [
        _bar(
            "SPY",
            bar_timestamp - timedelta(minutes=30 * (20 - index)),
            530 + index,
            100 if index < 20 else 200,
        )
        for index in range(21)
    ]
    _write_records(tmp_path, "stock_daily", daily)
    _write_records(tmp_path, "stock_30min", intraday)
    _write_records(
        tmp_path,
        "option_contracts",
        [
            {
                "symbol": "SPY260918C00530000",
                "underlying": "SPY",
                "option_type": "call",
                "strike": 530,
                "expiration": "2026-09-18",
                "observed_at": (decision_at + timedelta(minutes=1)).isoformat(),
            }
        ],
    )
    _write_records(tmp_path, "option_quotes", [])
    _write_records(
        tmp_path,
        "option_snapshots",
        [
            {
                "symbol": "SPY260918C00530000",
                "timestamp": (decision_at - timedelta(minutes=5)).isoformat(),
                "bid": 1,
                "ask": 1.1,
                "delta": 0.45,
                "implied_volatility": 0.20,
            },
            {
                "symbol": "SPY260918C00530000",
                "timestamp": decision_at.isoformat(),
                "bid": 1,
                "ask": 1.1,
                "delta": 0.45,
                "implied_volatility": 0.20,
            },
        ],
    )
    result = HistoricalBacktester(
        tmp_path, symbols=["SPY"], start=decision_at, end=decision_at
    ).run()
    assert result.data_classification == "STOCK-SIGNAL-ONLY ANALYSIS"
    assert any(
        item.reason == "option_contract_metadata_not_observed_at_decision"
        for item in result.rejected
    )
    assert not result.trades


def test_report_labels_missing_option_data_as_inconclusive(tmp_path):
    now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    result = HistoricalBacktester(tmp_path, symbols=["SPY"], start=now, end=now).run()
    report = tmp_path / "report.md"
    write_historical_report(
        result, path=report, symbols=["SPY"], start="2026-08-24", end="2026-08-24"
    )
    content = report.read_text()
    assert content.startswith("# STOCK-SIGNAL-ONLY ANALYSIS")
    assert "**Inconclusive.**" in content
    assert "returned 404" not in content


def test_failed_fetch_manifest_cannot_be_reported_as_historical_options_result(tmp_path):
    cache = LocalMarketDataCache(tmp_path)
    cache.record_fetch_status(
        "failed",
        symbols=["SPY"],
        start="2026-08-24",
        end="2026-08-24",
        include_options=True,
        error="AlpacaHTTPError: OPRA agreement is not signed",
    )
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    result = HistoricalBacktester(normalized, symbols=["SPY"], start=now, end=now).run()
    assert result.data_classification == "INCOMPLETE HISTORICAL DATASET"
    assert result.dataset_integrity == "fetch_failed"
    assert result.dataset_integrity_reason == "AlpacaHTTPError: OPRA agreement is not signed"


def test_completed_fetch_with_unavailable_quote_history_cannot_optimize_thresholds(tmp_path):
    cache = LocalMarketDataCache(tmp_path)
    cache.record_fetch_status(
        "completed",
        symbols=["SPY"],
        start="2026-08-24",
        end="2026-08-24",
        include_options=True,
        counts={
            "historical_option_quotes_available": False,
            "historical_option_quotes_limitation": "historical option quotes returned 404",
        },
    )
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    _write_records(
        normalized,
        "option_quotes",
        [{"symbol": "SPY260918C00650000", "timestamp": "2026-08-24T15:00:00+00:00"}],
    )
    now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    result = HistoricalBacktester(normalized, symbols=["SPY"], start=now, end=now).run()
    assert result.data_classification == "INCOMPLETE HISTORICAL DATASET"
    assert result.dataset_integrity == "option_quote_history_unavailable"
    assert result.dataset_integrity_reason == "historical option quotes returned 404"
    report = tmp_path / "report.md"
    write_historical_report(
        result, path=report, symbols=["SPY"], start="2026-08-24", end="2026-08-24"
    )
    assert "Historical option bid/ask quotes: unavailable" in report.read_text()


def test_backtest_uses_later_executable_quotes_for_conservative_exit(tmp_path):
    bar_timestamp = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    entry_at = bar_timestamp + timedelta(minutes=30)
    exit_at = entry_at + timedelta(minutes=30)
    daily = [
        _bar("SPY", bar_timestamp - timedelta(days=30 - index), 500 + index) for index in range(25)
    ]
    intraday = [
        _bar(
            "SPY",
            bar_timestamp - timedelta(minutes=30 * (20 - index)),
            530 + index,
            100 if index < 20 else 200,
        )
        for index in range(21)
    ]
    intraday.append(_bar("SPY", entry_at, 551, 220))
    _write_records(tmp_path, "stock_daily", daily)
    _write_records(tmp_path, "stock_30min", intraday)
    contracts = [
        {
            "symbol": "SPY260918C00555000",
            "underlying": "SPY",
            "option_type": "call",
            "strike": 555,
            "expiration": "2026-09-18",
            "observed_at": entry_at.isoformat(),
        },
        {
            "symbol": "SPY260918C00570000",
            "underlying": "SPY",
            "option_type": "call",
            "strike": 570,
            "expiration": "2026-09-18",
            "observed_at": entry_at.isoformat(),
        },
    ]
    _write_records(tmp_path, "option_contracts", contracts)
    _write_records(
        tmp_path,
        "option_quotes",
        [
            {
                "symbol": "SPY260918C00555000",
                "timestamp": (entry_at - timedelta(minutes=25)).isoformat(),
                "bid": 9.75,
                "ask": 9.85,
            },
            {
                "symbol": "SPY260918C00555000",
                "timestamp": entry_at.isoformat(),
                "bid": 9.75,
                "ask": 9.85,
            },
            {
                "symbol": "SPY260918C00570000",
                "timestamp": entry_at.isoformat(),
                "bid": 4.9,
                "ask": 5.0,
            },
            {
                "symbol": "SPY260918C00555000",
                "timestamp": exit_at.isoformat(),
                "bid": 12.5,
                "ask": 12.6,
            },
            {
                "symbol": "SPY260918C00570000",
                "timestamp": exit_at.isoformat(),
                "bid": 4.9,
                "ask": 5.0,
            },
        ],
    )
    _write_records(tmp_path, "option_snapshots", [])
    result = HistoricalBacktester(tmp_path, symbols=["SPY"], start=entry_at, end=exit_at).run()
    assert result.data_classification == "REAL HISTORICAL OPTION BACKTEST"
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_timestamp == entry_at.isoformat()
    assert trade.exit_timestamp == exit_at.isoformat()
    assert trade.exit_reason == "take_profit"
    assert trade.entry_debit == 4.95
    assert trade.exit_value == 7.5
    assert trade.quantity == 1
    assert trade.gross_pnl == 255.0
    assert trade.estimated_bid_ask_cost == 20.0
    assert trade.fees_usd == 0.0
    assert trade.slippage_usd == 0.0
    assert trade.total_costs_usd == 20.0
    assert trade.net_pnl == 235.0
    assert result.as_dict()["expectancy_usd_per_trade"] == 235.0
    assert result.as_dict()["missing_data_rate"] == 0.0

    costed = (
        HistoricalBacktester(
            tmp_path,
            symbols=["SPY"],
            start=entry_at,
            end=exit_at,
            fee_per_contract_usd=1.0,
            slippage_per_leg_usd=0.25,
        )
        .run()
        .trades[0]
    )
    assert costed.estimated_bid_ask_cost == 20.0
    assert costed.fees_usd == 2.0
    assert costed.slippage_usd == 1.0
    assert costed.total_costs_usd == 23.0
    assert costed.net_pnl == 232.0


def test_future_or_stale_quotes_are_not_executable():
    now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    assert (
        _latest_quote(
            "SPY260918C00550000",
            [
                {
                    "symbol": "SPY260918C00550000",
                    "timestamp": (now + timedelta(minutes=1)).isoformat(),
                    "bid": 3.4,
                    "ask": 3.5,
                }
            ],
            now,
        )
        is None
    )
    assert (
        _latest_quote(
            "SPY260918C00550000",
            [
                {
                    "symbol": "SPY260918C00550000",
                    "timestamp": (now - timedelta(minutes=16)).isoformat(),
                    "bid": 3.4,
                    "ask": 3.5,
                }
            ],
            now,
        )
        is None
    )


def test_historical_quote_greeks_are_derived_only_from_completed_underlying_bars(tmp_path):
    quote_at = datetime(2026, 8, 24, 15, 30, tzinfo=UTC)
    option_price = black_scholes_price(
        spot=550,
        strike=555,
        years=25 / 365,
        volatility=0.2,
        option_type="call",
    )
    assert option_price is not None
    backtester = HistoricalBacktester(tmp_path, symbols=["SPY"], start=quote_at, end=quote_at)
    intraday = [_bar("SPY", quote_at - timedelta(minutes=30), 550)]
    quotes = [
        {
            "symbol": "SPY260918C00555000",
            "timestamp": (quote_at - timedelta(minutes=1)).isoformat(),
            "bid": option_price - 0.05,
            "ask": option_price + 0.05,
        },
        {
            "symbol": "SPY260918C00555000",
            "timestamp": quote_at.isoformat(),
            "bid": option_price - 0.05,
            "ask": option_price + 0.05,
        },
    ]

    derived = backtester._derive_quote_greeks(quotes, intraday)

    # At 15:29 the 15:00 bar has not closed, so a later close cannot leak
    # backward into an IV calculation. The quote at the completed-bar time is
    # a valid observed midpoint transform.
    assert "implied_volatility" not in derived[0]
    assert derived[1]["iv_source"] == "quote_derived"
    assert derived[1]["implied_volatility"] == 0.2
    assert round(derived[1]["delta"], 4) == 0.4624
    assert derived[1]["greeks_timestamp"] == quote_at.isoformat()


def _open_position(entry_at):
    long_leg = OptionCandidate(
        underlying="SPY",
        symbol="SPY260918C00550000",
        option_type="call",
        strike=550,
        expiration="2026-09-18",
        dte=25,
        bid=3.4,
        ask=3.5,
        delta=0.46,
        implied_volatility=0.2,
        underlying_price=550,
    )
    short_leg = OptionCandidate(
        underlying="SPY",
        symbol="SPY260918C00555000",
        option_type="call",
        strike=555,
        expiration="2026-09-18",
        dte=25,
        bid=2.2,
        ask=2.3,
        delta=0.24,
        implied_volatility=0.2,
        underlying_price=550,
    )
    spread = DebitSpread(
        regime=Regime.BULLISH,
        long_leg=long_leg,
        short_leg=short_leg,
        debit=1.3,
        width=5,
        max_loss_per_contract=130,
        expected_move=10,
    )
    return _OpenPosition(
        symbol="SPY",
        regime=Regime.BULLISH,
        entry_score=70,
        spread=spread,
        quantity=1,
        entry_at=entry_at,
        entry_mid_debit=1.2,
    )


def test_stop_loss_and_time_stop_are_deterministic():
    entry_at = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    stop_at = entry_at + timedelta(minutes=30)
    stop_quotes = [
        {"symbol": "SPY260918C00550000", "timestamp": stop_at.isoformat(), "bid": 2.7, "ask": 2.8},
        {"symbol": "SPY260918C00555000", "timestamp": stop_at.isoformat(), "bid": 2.2, "ask": 2.3},
    ]
    stop_closed = HistoricalBacktester._close_positions(
        [_open_position(entry_at)], stop_quotes, stop_at
    )
    assert stop_closed[0][1].exit_reason == "stop_loss"

    time_at = entry_at + timedelta(days=3)
    time_quotes = [
        {"symbol": "SPY260918C00550000", "timestamp": time_at.isoformat(), "bid": 3.5, "ask": 3.6},
        {"symbol": "SPY260918C00555000", "timestamp": time_at.isoformat(), "bid": 2.2, "ask": 2.3},
    ]
    time_closed = HistoricalBacktester._close_positions(
        [_open_position(entry_at)], time_quotes, time_at
    )
    assert time_closed[0][1].exit_reason == "time_stop"


def test_fixed_horizon_exit_uses_first_fresh_quote_at_or_after_horizon(tmp_path):
    entry_at = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    horizon_at = entry_at + timedelta(minutes=15)
    quotes = [
        {
            "symbol": "SPY260918C00550000",
            "timestamp": horizon_at.isoformat(),
            "bid": 3.6,
            "ask": 3.7,
        },
        {
            "symbol": "SPY260918C00555000",
            "timestamp": horizon_at.isoformat(),
            "bid": 2.2,
            "ask": 2.3,
        },
    ]
    assert (
        HistoricalBacktester._close_positions(
            [_open_position(entry_at)],
            quotes,
            entry_at + timedelta(minutes=14),
            exit_horizon_minutes=15,
        )
        == []
    )
    closed = HistoricalBacktester._close_positions(
        [_open_position(entry_at)], quotes, horizon_at, exit_horizon_minutes=15
    )
    assert closed[0][1].exit_timestamp == horizon_at.isoformat()
    assert closed[0][1].exit_reason == "fixed_15_minute_exit"
    with pytest.raises(ValueError, match="15, 30, or 60"):
        HistoricalBacktester(
            tmp_path, symbols=["SPY"], start=entry_at, end=horizon_at, exit_horizon_minutes=20
        )


def test_backtest_prevents_overlapping_positions_for_the_same_underlying(tmp_path, monkeypatch):
    now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    later = now + timedelta(minutes=30)
    _write_records(
        tmp_path,
        "stock_30min",
        [_bar("SPY", now - timedelta(minutes=30), 550), _bar("SPY", now, 551)],
    )
    position = _open_position(now)
    inputs = SignalInputs(
        price=551,
        ema_20=540,
        return_5d_pct=2,
        ema_fast=551,
        ema_slow=549,
        vwap=550,
        volume_ratio=1.2,
        realized_volatility=0.2,
        prior_realized_volatility=0.18,
        implied_volatility=0.2,
        prior_implied_volatility=0.2,
        market_return_1d_pct=1,
    )
    backtester = HistoricalBacktester(tmp_path, symbols=["SPY"], start=now, end=later)
    monkeypatch.setattr(backtester, "_signal_inputs", lambda *_: inputs)
    monkeypatch.setattr(
        backtester,
        "_candidates_at",
        lambda *_: ([position.spread.long_leg, position.spread.short_leg], None),
    )
    result = backtester.run()
    assert any(item.reason == "overlapping_position" for item in result.rejected)
