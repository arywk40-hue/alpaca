import json
from datetime import UTC, datetime, timedelta

from vegaguard.strategy.backtest import HistoricalBacktester, _latest_quote, write_historical_report


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
            "symbol": "SPY260918C00550000",
            "underlying": "SPY",
            "option_type": "call",
            "strike": 550,
            "expiration": "2026-09-18",
            "observed_at": entry_at.isoformat(),
        },
        {
            "symbol": "SPY260918C00555000",
            "underlying": "SPY",
            "option_type": "call",
            "strike": 555,
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
                "symbol": "SPY260918C00550000",
                "timestamp": entry_at.isoformat(),
                "bid": 3.4,
                "ask": 3.5,
            },
            {
                "symbol": "SPY260918C00555000",
                "timestamp": entry_at.isoformat(),
                "bid": 2.2,
                "ask": 2.3,
            },
            {
                "symbol": "SPY260918C00550000",
                "timestamp": exit_at.isoformat(),
                "bid": 4.3,
                "ask": 4.4,
            },
            {
                "symbol": "SPY260918C00555000",
                "timestamp": exit_at.isoformat(),
                "bid": 2.2,
                "ask": 2.3,
            },
        ],
    )
    _write_records(
        tmp_path,
        "option_snapshots",
        [
            {
                "symbol": "SPY260918C00550000",
                "timestamp": (entry_at - timedelta(minutes=5)).isoformat(),
                "bid": 3.4,
                "ask": 3.5,
                "delta": 0.46,
                "implied_volatility": 0.19,
            },
            {
                "symbol": "SPY260918C00550000",
                "timestamp": entry_at.isoformat(),
                "bid": 3.4,
                "ask": 3.5,
                "delta": 0.46,
                "implied_volatility": 0.20,
            },
            {
                "symbol": "SPY260918C00550000",
                "timestamp": exit_at.isoformat(),
                "bid": 4.3,
                "ask": 4.4,
                "delta": 0.46,
                "implied_volatility": 0.20,
            },
            {
                "symbol": "SPY260918C00555000",
                "timestamp": entry_at.isoformat(),
                "bid": 2.2,
                "ask": 2.3,
                "delta": 0.24,
                "implied_volatility": 0.20,
            },
        ],
    )
    result = HistoricalBacktester(tmp_path, symbols=["SPY"], start=entry_at, end=exit_at).run()
    assert result.data_classification == "REAL HISTORICAL OPTION BACKTEST"
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_timestamp == entry_at.isoformat()
    assert trade.exit_timestamp == exit_at.isoformat()
    assert trade.exit_reason == "take_profit"
    assert trade.entry_debit == 1.3
    assert trade.exit_value == 2.0
    assert trade.quantity == 1
    assert trade.gross_pnl == 70.0
    assert trade.estimated_bid_ask_cost == 20.0
    assert trade.net_pnl == 50.0


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
