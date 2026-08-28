from datetime import UTC, datetime

import pytest

from vegaguard.strategy import research


def test_walk_forward_selects_only_in_sample_and_keeps_production_fixed(monkeypatch, tmp_path):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 11, tzinfo=UTC)
    calls: list[tuple[int, datetime, datetime]] = []

    class FakeBacktester:
        def __init__(self, _data_dir, *, score_threshold, start, end, **_kwargs):
            self.score_threshold = score_threshold
            self.start = start
            self.end = end
            calls.append((score_threshold, start, end))

        def run(self):
            in_sample = self.start == start
            if self.score_threshold == 40:
                net_pnl = 100.0 if in_sample else -20.0
            else:
                net_pnl = 50.0 if in_sample else 25.0

            class Result:
                def as_dict(self):
                    return {
                        "classification": "REAL HISTORICAL OPTION BACKTEST",
                        "trade_count": 30,
                        "net_pnl": net_pnl,
                        "profit_factor": 1.5,
                    }

            return Result()

    monkeypatch.setattr(research, "HistoricalBacktester", FakeBacktester)
    report = research.walk_forward_threshold_study(
        tmp_path,
        symbols=["SPY"],
        start=start,
        end=end,
        thresholds=(40, 70),
        minimum_in_sample_trades=30,
    )
    assert len(calls) == 4
    assert report["selected_threshold_from_in_sample"] == 40
    assert report["selected_threshold_out_of_sample"]["net_pnl"] == -20.0
    assert report["production_threshold"] == 70
    assert report["automatic_production_promotion"] is False
    assert "research selection only" in report["recommendation"]


def test_walk_forward_with_insufficient_or_non_real_data_makes_no_selection(monkeypatch, tmp_path):
    class FakeBacktester:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self):
            class Result:
                def as_dict(self):
                    return {
                        "classification": "STOCK-SIGNAL-ONLY ANALYSIS",
                        "trade_count": 100,
                        "net_pnl": 999.0,
                        "profit_factor": 99.0,
                    }

            return Result()

    monkeypatch.setattr(research, "HistoricalBacktester", FakeBacktester)
    report = research.walk_forward_threshold_study(
        tmp_path,
        symbols=["SPY"],
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert report["selected_threshold_from_in_sample"] is None
    assert report["recommendation"].startswith("INSUFFICIENT EVIDENCE")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"train_fraction": 0},
        {"train_fraction": 1},
        {"minimum_in_sample_trades": 0},
        {"thresholds": (0,)},
    ],
)
def test_walk_forward_validates_research_parameters(tmp_path, kwargs):
    with pytest.raises(ValueError):
        research.walk_forward_threshold_study(
            tmp_path,
            symbols=["SPY"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
            **kwargs,
        )
