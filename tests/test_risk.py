from vegaguard.config import Settings
from vegaguard.models import (
    OptionCandidate,
    OptionLeg,
    PositionIntent,
    Side,
    Thesis,
    TradePlan,
)
from vegaguard.risk import DeterministicRiskGate


def plan(*, dte: int = 14, bid: float = 2.0, ask: float = 2.1, qty: int = 1) -> TradePlan:
    candidate = OptionCandidate(
        underlying="SPY",
        symbol="SPY260918C00650000",
        option_type="call",
        strike=650,
        expiration="2026-09-18",
        dte=dte,
        bid=bid,
        ask=ask,
        underlying_price=640,
    )
    thesis = Thesis(
        action="trade",
        confidence=0.72,
        rationale="The supplied short and medium return evidence supports a narrowly defined directional paper trade.",
        invalidation="Exit if the signal reverses or option liquidity degrades.",
        candidate_symbol=candidate.symbol,
    )
    return TradePlan(
        underlying="SPY",
        strategy="single_leg",
        legs=[
            OptionLeg(
                symbol=candidate.symbol, side=Side.BUY, position_intent=PositionIntent.BUY_TO_OPEN
            )
        ],
        qty=qty,
        limit_price=2.05,
        max_loss_usd=105,
        candidate=candidate,
        thesis=thesis,
    )


def test_approves_small_liquid_paper_trade():
    result = DeterministicRiskGate(Settings()).assess(
        plan(), market_open=True, open_positions=0, buying_power=5_000
    )
    assert result.approved


def test_blocks_wide_spread_and_expiry_risk():
    result = DeterministicRiskGate(Settings()).assess(
        plan(dte=2, bid=1, ask=2), market_open=True, open_positions=0, buying_power=5_000
    )
    assert not result.approved
    assert any("DTE" in reason for reason in result.reasons)
    assert any("spread" in reason for reason in result.reasons)
