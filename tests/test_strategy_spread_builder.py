from vegaguard.models import OptionCandidate
from vegaguard.strategy.scorer import Regime
from vegaguard.strategy.spread_builder import build_debit_spread, expected_move, position_size


def option(
    symbol: str, *, strike: float, delta: float, bid: float, ask: float, option_type: str = "call"
) -> OptionCandidate:
    return OptionCandidate(
        underlying="SPY",
        symbol=symbol,
        option_type=option_type,
        strike=strike,
        expiration="2026-09-18",
        dte=21,
        bid=bid,
        ask=ask,
        delta=delta,
        implied_volatility=0.2,
        underlying_price=640,
    )


def test_builds_conservative_bull_call_spread():
    spread = build_debit_spread(
        [
            option("SPY260918C00640000", strike=640, delta=0.46, bid=3.4, ask=3.5),
            option("SPY260918C00645000", strike=645, delta=0.24, bid=2.2, ask=2.3),
        ],
        Regime.BULLISH,
    )
    assert spread is not None
    assert spread.debit == 1.3
    assert spread.width == 5
    assert spread.max_loss_per_contract == 130


def test_rejects_wide_or_overpriced_spread():
    spread = build_debit_spread(
        [
            option("SPY260918C00640000", strike=640, delta=0.46, bid=3, ask=5),
            option("SPY260918C00645000", strike=645, delta=0.24, bid=2.2, ask=2.3),
        ],
        Regime.BULLISH,
    )
    assert spread is None


def test_expected_move_and_sizing_are_bounded():
    assert expected_move(100, 0.2, 25) > 0
    assert position_size(equity=100_000, max_loss_per_contract=290) == 1
    assert position_size(equity=100_000, max_loss_per_contract=600) == 0
