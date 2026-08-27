from datetime import UTC, datetime, timedelta

import pytest

from vegaguard.config import Settings
from vegaguard.execution import PaperExecutionAgent
from vegaguard.journal import DecisionJournal
from vegaguard.models import OptionCandidate, OptionLeg, PositionIntent, Side, Thesis, TradePlan
from vegaguard.risk import DeterministicRiskGate


class NoCallMCP:
    async def call(self, *_args):
        raise AssertionError("dry-run execution must not call MCP")


class CaptureMCP:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool: str, arguments: dict):
        self.calls.append((tool, arguments))
        return {"id": "paper-order-1", "status": "accepted"}


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


@pytest.mark.asyncio
async def test_exact_unexpired_dry_run_plan_can_be_submitted_once(tmp_path):
    dry_settings = Settings(allow_order_execution=True, dry_run=True)
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    trade_plan = plan().model_copy(
        update={
            "approval_expires_at": datetime.now(UTC) + timedelta(minutes=5),
            "quote_timestamps": [
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ],
        }
    )
    dry_gate = DeterministicRiskGate(dry_settings).assess(
        trade_plan, market_open=True, open_positions=0, buying_power=10_000
    )
    assert (
        await PaperExecutionAgent(dry_settings, journal, NoCallMCP()).submit(trade_plan, dry_gate)
    )["status"] == "dry_run"

    recovered = journal.approved_plan(trade_plan.plan_id)
    assert recovered.model_dump(mode="json") == trade_plan.model_dump(mode="json")
    live_settings = Settings(allow_order_execution=True, dry_run=False)
    live_gate = DeterministicRiskGate(live_settings).assess(
        recovered, market_open=True, open_positions=0, buying_power=10_000
    )
    mcp = CaptureMCP()
    result = await PaperExecutionAgent(live_settings, journal, mcp).submit_approved(
        recovered, live_gate
    )
    assert result["status"] == "submitted"
    assert mcp.calls == [("place_option_order", trade_plan.mcp_arguments())]
    with pytest.raises(ValueError, match="already submitted"):
        journal.approved_plan(trade_plan.plan_id)


@pytest.mark.asyncio
async def test_expired_dry_run_plan_cannot_be_recovered_for_submission(tmp_path):
    settings = Settings(allow_order_execution=True, dry_run=True)
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    trade_plan = plan().model_copy(
        update={
            "approval_expires_at": datetime.now(UTC) - timedelta(seconds=1),
            "quote_timestamps": [datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()],
        }
    )
    gate = DeterministicRiskGate(settings).assess(
        trade_plan, market_open=True, open_positions=0, buying_power=10_000
    )
    await PaperExecutionAgent(settings, journal, NoCallMCP()).submit(trade_plan, gate)
    with pytest.raises(ValueError, match="has expired"):
        journal.approved_plan(trade_plan.plan_id)


@pytest.mark.asyncio
async def test_guardian_exit_reverses_legs_atomically_and_stays_dry_run(tmp_path):
    settings = Settings(allow_order_execution=True, dry_run=True)
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    exit_plan = plan().closing_plan(executable_credit=1.8)
    result = await PaperExecutionAgent(settings, journal, NoCallMCP()).submit_exit(
        exit_plan, reason="take_profit"
    )
    assert result["status"] == "dry_run"
    assert result["mcp_arguments"]["order_class"] == "mleg"
    assert result["mcp_arguments"]["limit_price"] == "-1.8"
    assert [leg["position_intent"] for leg in result["mcp_arguments"]["legs"]] == [
        "sell_to_close",
        "buy_to_close",
    ]
