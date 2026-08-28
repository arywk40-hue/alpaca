"""Point-in-time option-surface features for research and explanation only."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import median

from ..models import OptionCandidate


@dataclass(frozen=True)
class OptionSurfaceFeatures:
    iv_percentile: float | None
    iv_history_observations: int
    put_call_skew: float | None
    near_term_iv: float | None
    far_term_iv: float | None
    term_structure: float | None
    call_iv_observations: int
    put_iv_observations: int
    near_term_observations: int
    far_term_observations: int

    def as_dict(self) -> dict[str, float | int | None]:
        return asdict(self)


def option_surface_features(
    candidates: list[OptionCandidate], *, current_iv: float, iv_history: list[float]
) -> OptionSurfaceFeatures:
    """Calculate only features supported by observed, validated option records.

    IV percentile requires 20 or more observed scanner values. Skew uses
    near-the-money put IV minus call IV, and term structure is far-term median
    IV minus near-term median IV. Missing data stays ``None`` rather than being
    inferred from stock volatility or fabricated quotes.
    """
    history = [float(value) for value in iv_history if value >= 0]
    iv_percentile = (
        round(sum(value <= current_iv for value in history) / len(history) * 100, 2)
        if len(history) >= 20
        else None
    )
    near_money = [
        candidate
        for candidate in candidates
        if candidate.implied_volatility is not None
        and abs(candidate.strike - candidate.underlying_price) / candidate.underlying_price <= 0.05
    ]
    calls = [
        float(candidate.implied_volatility)
        for candidate in near_money
        if candidate.option_type == "call"
    ]
    puts = [
        float(candidate.implied_volatility)
        for candidate in near_money
        if candidate.option_type == "put"
    ]
    call_iv = median(calls) if calls else None
    put_iv = median(puts) if puts else None
    near_term = [
        float(candidate.implied_volatility)
        for candidate in candidates
        if candidate.implied_volatility is not None and 14 <= candidate.dte <= 21
    ]
    far_term = [
        float(candidate.implied_volatility)
        for candidate in candidates
        if candidate.implied_volatility is not None and 22 <= candidate.dte <= 28
    ]
    near_term_iv = round(median(near_term), 6) if near_term else None
    far_term_iv = round(median(far_term), 6) if far_term else None
    return OptionSurfaceFeatures(
        iv_percentile=iv_percentile,
        iv_history_observations=len(history),
        put_call_skew=round(put_iv - call_iv, 6)
        if put_iv is not None and call_iv is not None
        else None,
        near_term_iv=near_term_iv,
        far_term_iv=far_term_iv,
        term_structure=round(far_term_iv - near_term_iv, 6)
        if far_term_iv is not None and near_term_iv is not None
        else None,
        call_iv_observations=len(calls),
        put_iv_observations=len(puts),
        near_term_observations=len(near_term),
        far_term_observations=len(far_term),
    )
