import pytest

from vegaguard.analytics import PaperTradeOutcome, summarize_paper_metrics


def test_paper_metrics_keep_costs_fills_and_regimes_auditable():
    metrics = summarize_paper_metrics(
        [
            PaperTradeOutcome("SPY", 100, 10, 130, 2, "bullish"),
            PaperTradeOutcome("QQQ", -50, 5, 100, 1, "bearish"),
        ],
        orders_submitted=3,
        orders_filled=2,
        rejected_opportunity_pnl=12,
    )
    assert metrics.gross_pnl == 50
    assert metrics.net_pnl == 35
    assert metrics.costs == 15
    assert metrics.fill_rate == pytest.approx(2 / 3, abs=0.0001)
    assert metrics.maximum_drawdown == -55
    assert metrics.per_regime_net_pnl == {"bullish": 90, "bearish": -55}
    assert metrics.rejected_opportunity_pnl == 12
