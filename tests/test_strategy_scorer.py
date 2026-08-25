from vegaguard.strategy.scorer import Regime, SignalInputs, score_signal


def inputs(**overrides) -> SignalInputs:
    values = {
        "price": 110,
        "ema_20": 100,
        "return_5d_pct": 4,
        "ema_fast": 110,
        "ema_slow": 100,
        "vwap": 105,
        "volume_ratio": 1.3,
        "realized_volatility": 0.22,
        "prior_realized_volatility": 0.18,
        "implied_volatility": 0.20,
        "prior_implied_volatility": 0.20,
        "market_return_1d_pct": 0.8,
    }
    values.update(overrides)
    return SignalInputs(**values)


def test_aligned_bullish_signal_is_tradeable():
    score = score_signal(inputs())
    assert score.regime == Regime.BULLISH
    assert score.score == 100
    assert score.agreeing_components == 5


def test_aligned_bearish_signal_is_tradeable():
    score = score_signal(
        inputs(
            price=90,
            ema_20=100,
            return_5d_pct=-4,
            ema_fast=90,
            ema_slow=100,
            vwap=95,
            market_return_1d_pct=-0.8,
        )
    )
    assert score.regime == Regime.BEARISH
    assert score.score == -100


def test_conflicting_signal_is_no_trade():
    score = score_signal(inputs(ema_fast=95, ema_slow=100, vwap=115))
    assert score.regime == Regime.NO_TRADE
    assert "score or agreement threshold was not met" in score.reasons


def test_rich_iv_rejects_otherwise_incomplete_signal():
    score = score_signal(inputs(volume_ratio=1.0, implied_volatility=0.40))
    assert score.regime == Regime.NO_TRADE
    assert score.score == 65
