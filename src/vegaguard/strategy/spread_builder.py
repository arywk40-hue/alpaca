from collections.abc import Iterable
from dataclasses import dataclass
from math import floor, sqrt

from ..models import OptionCandidate
from .scorer import Regime


@dataclass(frozen=True)
class DebitSpread:
    regime: Regime
    long_leg: OptionCandidate
    short_leg: OptionCandidate
    debit: float
    width: float
    max_loss_per_contract: float
    expected_move: float


def expected_move(underlying_price: float, implied_volatility: float, dte: int) -> float:
    if underlying_price <= 0 or implied_volatility < 0 or dte < 0:
        raise ValueError("underlying price, IV and DTE must be non-negative")
    return underlying_price * implied_volatility * sqrt(dte / 365)


def _midpoint(candidate: OptionCandidate) -> float:
    return (candidate.bid + candidate.ask) / 2


def build_debit_spread(
    candidates: Iterable[OptionCandidate],
    regime: Regime,
    *,
    target_long_delta: float = 0.45,
    target_short_delta: float = 0.25,
    min_dte: int = 14,
    max_dte: int = 28,
    max_leg_spread_pct: float = 0.08,
) -> DebitSpread | None:
    if regime not in {Regime.BULLISH, Regime.BEARISH}:
        return None
    option_type = "call" if regime == Regime.BULLISH else "put"
    filtered = [
        candidate
        for candidate in candidates
        if candidate.option_type == option_type
        and min_dte <= candidate.dte <= max_dte
        and candidate.bid > 0
        and candidate.ask > candidate.bid
        and candidate.spread_pct <= max_leg_spread_pct
        and candidate.delta is not None
    ]
    if not filtered:
        return None

    long_leg = min(
        filtered,
        key=lambda candidate: (
            abs(abs(candidate.delta or 0) - target_long_delta),
            candidate.spread_pct,
        ),
    )
    same_expiry = [
        candidate for candidate in filtered if candidate.expiration == long_leg.expiration
    ]
    if regime == Regime.BULLISH:
        legal_shorts = [
            candidate for candidate in same_expiry if candidate.strike > long_leg.strike
        ]
    else:
        legal_shorts = [
            candidate for candidate in same_expiry if candidate.strike < long_leg.strike
        ]
    if not legal_shorts:
        return None
    short_leg = min(
        legal_shorts,
        key=lambda candidate: (
            abs(abs(candidate.delta or 0) - target_short_delta),
            candidate.spread_pct,
        ),
    )
    # Conservative fill estimate: buy at ask and sell at bid.
    debit = round(long_leg.ask - short_leg.bid, 4)
    width = round(abs(short_leg.strike - long_leg.strike), 4)
    if debit <= 0 or debit >= width * 0.40:
        return None
    iv = long_leg.implied_volatility or 0.0
    return DebitSpread(
        regime=regime,
        long_leg=long_leg,
        short_leg=short_leg,
        debit=debit,
        width=width,
        max_loss_per_contract=round(debit * 100, 2),
        expected_move=round(expected_move(long_leg.underlying_price, iv, long_leg.dte), 4),
    )


def position_size(
    *,
    equity: float,
    max_loss_per_contract: float,
    risk_fraction: float = 0.005,
    hard_max_risk: float = 500.0,
) -> int:
    if equity <= 0 or max_loss_per_contract <= 0:
        return 0
    budget = min(equity * risk_fraction, hard_max_risk)
    return max(0, floor(budget / max_loss_per_contract))
