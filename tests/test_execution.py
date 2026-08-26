import pytest

from vegaguard.config import Settings
from vegaguard.execution import PaperExecutionAgent
from vegaguard.journal import DecisionJournal
from vegaguard.models import OptionCandidate, OptionLeg, PositionIntent, Side, Thesis, TradePlan
from vegaguard.risk import DeterministicRiskGate


class NoCallMCP:
    async def call(self, *_args):
        raise AssertionError("dry-run execution must not call MCP")


def plan() -> TradePlan:
    candidate = OptionCandidate(
        underlying="SPY",
        symbol="SPY260918C00650000",
        option_type="call",
        strike=650,
        expiration="2026-09-18",
        dte=21,
        bid=3.4,
        ask=3.5,
        delta=0.46,
        implied_volatility=0.2,
        underlying_price=640,
    )
    return TradePlan(
        underlying="SPY",
        strategy="debit_spread",
        legs=[
            OptionLeg(
                symbol=candidate.symbol,
                side=Side.BUY,
                position_intent=PositionIntent.BUY_TO_OPEN,
            ),
            OptionLeg(
                symbol="SPY260918C00655000",
                side=Side.SELL,
                position_intent=PositionIntent.SELL_TO_OPEN,
            ),
        ],
        qty=1,
        limit_price=1.3,
        max_loss_usd=130,
        candidate=candidate,
        thesis=Thesis(
            action="trade",
            confidence=0.8,
            rationale="The deterministic score and defined risk support this paper debit spread.",
            invalidation="Exit when deterministic risk, price, or liquidity signals invalidate it.",
            candidate_symbol=candidate.symbol,
        ),
        client_order_id="vg-test-idempotent",
    )


@pytest.mark.asyncio
async def test_dry_run_is_journaled_and_duplicate_client_id_is_blocked(tmp_path):
    settings = Settings(allow_order_execution=True, dry_run=True)
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    trade_plan = plan()
    gate = DeterministicRiskGate(settings).assess(
        trade_plan, market_open=True, open_positions=0, buying_power=10_000
    )
    agent = PaperExecutionAgent(settings, journal, NoCallMCP())
    result = await agent.submit(trade_plan, gate)
    assert result["status"] == "dry_run"
    assert result["mcp_arguments"]["order_class"] == "mleg"
    duplicate = await agent.submit(trade_plan, gate)
    assert duplicate == {"status": "blocked", "reasons": ["duplicate client_order_id"]}
    assert [entry["event"] for entry in journal.latest()] == ["dry_run_order", "gate_evaluated"]
