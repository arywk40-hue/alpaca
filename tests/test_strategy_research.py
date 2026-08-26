from vegaguard.strategy.replay import load_observations
from vegaguard.strategy.research import compare_replay_scorers


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
