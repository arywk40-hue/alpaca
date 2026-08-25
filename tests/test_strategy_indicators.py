import pytest

from vegaguard.strategy.indicators import (
    ema,
    percent_return,
    realized_volatility,
    volume_ratio,
    vwap,
)


def test_ema_tracks_values_without_mutating_input():
    values = [10, 12, 14]
    assert ema(values, 2) == pytest.approx([10.0, 11.333333333333332, 13.11111111111111])
    assert values == [10, 12, 14]


def test_return_volatility_vwap_and_volume_ratio():
    assert percent_return([100, 110], 1) == pytest.approx(10)
    assert realized_volatility([100, 102, 101, 105]) > 0
    assert vwap([11, 13], [9, 11], [10, 12], [100, 300]) == pytest.approx(11.5)
    assert volume_ratio([100] * 20 + [200]) == pytest.approx(2)
