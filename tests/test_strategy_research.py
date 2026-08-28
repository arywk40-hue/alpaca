from vegaguard.strategy.backtest import HistoricalBacktestResult, HistoricalTrade
from vegaguard.strategy.replay import load_observations
from vegaguard.strategy.research import compare_replay_scorers, confidence_calibration_study


def test_conflict_scorer_comparison_is_offline_and_reports_required_metrics():
    report = compare_replay_scorers(
        load_observations("tests/fixtures/strategy_replay_sanitized.json")
    )
    assert report["mode"] == "offline_research_only"
    assert report["live_execution"] == "disabled_by_design"
    assert report["out_of_sample_assessment"].startswith("unavailable")
    for variant in ("baseline", "conflict_tolerant"):
        result = report[variant]
        assert {"trade_count", "performance", "regime_distribution", "rejection_reasons"} <= set(
            result
        )
        assert {
            "net_pnl",
            "win_rate",
            "profit_factor",
            "max_drawdown",
            "costs",
        } <= set(result["performance"])
    assert set(report["threshold_comparison"]) == {"40", "50", "60", "70"}
    for threshold_report in report["threshold_comparison"].values():
        assert {"trade_count", "performance", "regime_distribution", "rejection_reasons"} <= set(
            threshold_report
        )


def test_confidence_calibration_is_offline_and_requires_real_sample_depth():
    trades = [
        HistoricalTrade(
            symbol="SPY",
            regime="bullish",
            entry_score=72,
            entry_timestamp=f"2026-08-{index + 1:02d}T14:00:00+00:00",
            exit_timestamp=f"2026-08-{index + 1:02d}T14:30:00+00:00",
            quantity=1,
            long_symbol="SPY260918C00650000",
            short_symbol="SPY260918C00655000",
            entry_debit=1.0,
            exit_value=1.2 if index < 2 else 0.8,
            gross_pnl=20.0 if index < 2 else -20.0,
            estimated_bid_ask_cost=0.0,
            fees_usd=0.0,
            slippage_usd=0.0,
            total_costs_usd=0.0,
            net_pnl=20.0 if index < 2 else -20.0,
            exit_reason="take_profit" if index < 2 else "stop_loss",
            holding_minutes=30,
        )
        for index in range(3)
    ]
    result = HistoricalBacktestResult(
        data_classification="REAL HISTORICAL OPTION BACKTEST",
        score_threshold=40,
        observations=3,
        eligible_opportunities=3,
        no_trade_decisions=0,
        missing_data_count=0,
        trades=trades,
        rejected=[],
        maximum_simultaneous_exposure=1,
        per_symbol_net_pnl={"SPY": 20.0},
        per_regime_net_pnl={"bullish": 20.0},
    )

    report = confidence_calibration_study(result, minimum_observations_per_bucket=3)

    assert report["mode"] == "offline_confidence_calibration_research"
    assert report["live_execution"] == "disabled_by_design"
    assert report["production_threshold"] == 70
    assert report["status"] == "ready_for_research_review"
    assert report["automatic_live_calibration"] is False
    assert report["buckets"] == [
        {
            "score_bucket": "70-79",
            "regime": "bullish",
            "trade_count": 3,
            "win_count": 2,
            "observed_win_rate": 0.6667,
            "smoothed_empirical_win_probability": 0.6,
            "average_net_pnl": 6.67,
            "net_pnl": 20.0,
            "profit_factor": 2.0,
            "sufficient_observations": True,
        }
    ]

    insufficient = confidence_calibration_study(result, minimum_observations_per_bucket=4)
    assert insufficient["status"] == "insufficient_real_historical_evidence"
