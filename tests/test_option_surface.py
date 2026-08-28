from datetime import UTC, datetime

from vegaguard.models import OptionCandidate
from vegaguard.strategy.option_surface import option_surface_features


def _candidate(option_type: str, dte: int, iv: float, strike: float = 100) -> OptionCandidate:
    return OptionCandidate(
        underlying="SPY",
        symbol=f"SPY2609{dte:02d}{'C' if option_type == 'call' else 'P'}00100000",
        option_type=option_type,
        strike=strike,
        expiration="2026-09-18",
        dte=dte,
        bid=2.0,
        ask=2.1,
        implied_volatility=iv,
        delta=0.4,
        underlying_price=100,
        quote_timestamp=datetime(2026, 8, 28, tzinfo=UTC).isoformat(),
    )


def test_option_surface_uses_observed_history_and_quote_backed_contracts():
    features = option_surface_features(
        [
            _candidate("call", 14, 0.20),
            _candidate("put", 14, 0.24),
            _candidate("call", 28, 0.30),
            _candidate("put", 28, 0.34),
        ],
        current_iv=0.25,
        iv_history=[0.10 + index * 0.01 for index in range(20)],
    )
    assert features.iv_percentile == 80.0
    assert features.put_call_skew == 0.04
    assert features.near_term_iv == 0.22
    assert features.far_term_iv == 0.32
    assert features.term_structure == 0.1


def test_option_surface_refuses_to_fabricate_missing_history_or_contract_buckets():
    features = option_surface_features(
        [_candidate("call", 14, 0.20)], current_iv=0.2, iv_history=[]
    )
    assert features.iv_percentile is None
    assert features.put_call_skew is None
    assert features.term_structure is None
    assert features.iv_history_observations == 0
