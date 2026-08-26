from dataclasses import dataclass
from enum import StrEnum


class Regime(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    # Inputs may be complete yet not point to a trade.  This is distinct from
    # NO_TRADE, which the live scanner reserves for unavailable/stale data.
    NEUTRAL = "neutral"
    NO_TRADE = "no_trade"


@dataclass(frozen=True)
class SignalInputs:
    price: float
    ema_20: float
    return_5d_pct: float
    ema_fast: float
    ema_slow: float
    vwap: float
    volume_ratio: float
    realized_volatility: float
    prior_realized_volatility: float
    implied_volatility: float
    prior_implied_volatility: float
    market_return_1d_pct: float


@dataclass(frozen=True)
class SignalScore:
    score: int
    regime: Regime
    daily_regime: int
    intraday_trend: int
    volume_confirmation: int
    volatility_state: int
    market_alignment: int
    agreeing_components: int
    reasons: tuple[str, ...]


def _direction(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def score_signal(inputs: SignalInputs, threshold: int = 70) -> SignalScore:
    daily = (
        25
        if inputs.return_5d_pct > 0 and inputs.price > inputs.ema_20
        else -25
        if inputs.return_5d_pct < 0 and inputs.price < inputs.ema_20
        else 0
    )
    intraday = (
        25
        if inputs.ema_fast > inputs.ema_slow and inputs.price > inputs.vwap
        else -25
        if inputs.ema_fast < inputs.ema_slow and inputs.price < inputs.vwap
        else 0
    )
    primary_direction = _direction(daily + intraday)
    reasons: list[str] = []
    if primary_direction == 0:
        reasons.append("daily and intraday regimes are not aligned")

    volume = 20 * primary_direction if primary_direction and inputs.volume_ratio >= 1.10 else 0
    if primary_direction and not volume:
        reasons.append("volume confirmation is absent")

    volatility_is_usable = (
        inputs.realized_volatility >= inputs.prior_realized_volatility
        and inputs.implied_volatility <= inputs.prior_implied_volatility * 1.15
    )
    volatility = 15 * primary_direction if primary_direction and volatility_is_usable else 0
    if primary_direction and not volatility:
        reasons.append("volatility state is not favourable")

    market_direction = _direction(inputs.market_return_1d_pct)
    market = (
        15 * primary_direction
        if primary_direction and market_direction == primary_direction
        else -15 * primary_direction
        if primary_direction and market_direction == -primary_direction
        else 0
    )
    if primary_direction and market < 0:
        reasons.append("market direction conflicts with the candidate")

    components = (daily, intraday, volume, volatility, market)
    total = max(-100, min(100, sum(components)))
    final_direction = _direction(total)
    agreeing = sum(
        _direction(component) == final_direction and component != 0 for component in components
    )
    if total >= threshold and agreeing >= 3:
        regime = Regime.BULLISH
    elif total <= -threshold and agreeing >= 3:
        regime = Regime.BEARISH
    else:
        regime = Regime.NEUTRAL
        reasons.append("score or agreement threshold was not met")

    return SignalScore(
        score=total,
        regime=regime,
        daily_regime=daily,
        intraday_trend=intraday,
        volume_confirmation=volume,
        volatility_state=volatility,
        market_alignment=market,
        agreeing_components=agreeing,
        reasons=tuple(reasons),
    )
