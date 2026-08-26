import pytest

from vegaguard.config import Settings
from vegaguard.execution import PaperExecutionAgent
from vegaguard.journal import DecisionJournal
from vegaguard.models import OptionCandidate, Thesis
from vegaguard.scanner import ScanResult
from vegaguard.service import AutonomousCycle
from vegaguard.strategy.scorer import Regime, SignalScore
from vegaguard.strategy.spread_builder import DebitSpread


class NoopExecutor:
    async def submit(self, *_args):  # pragma: no cover - not used by these unit tests
        raise AssertionError("read-only plan construction must not submit an order")


class NoCallMCP:
    async def call(self, *_args):
        raise AssertionError("end-to-end dry run must not invoke MCP")


def _scan() -> ScanResult:
    long_leg = OptionCandidate(
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
    short_leg = OptionCandidate(
        underlying="SPY",
        symbol="SPY260918C00655000",
        option_type="call",
        strike=655,
        expiration="2026-09-18",
        dte=21,
        bid=2.2,
        ask=2.3,
        delta=0.24,
        implied_volatility=0.2,
        underlying_price=640,
    )
    score = SignalScore(100, Regime.BULLISH, 25, 25, 20, 15, 15, 5, ())
    spread = DebitSpread(Regime.BULLISH, long_leg, short_leg, 1.3, 5, 130, 10)
    from vegaguard.models import Opportunity

    opportunity = Opportunity(
        candidate=long_leg,
        return_1d_pct=1,
        return_5d_pct=3,
        realized_volatility=0.2,
        evidence=["deterministic score: 100"],
    )
    return ScanResult("SPY", score, opportunity, spread, ())


def test_live_plan_uses_the_same_defined_risk_debit_spread_as_backtest():
    cycle = AutonomousCycle(Settings(), NoopExecutor())
    thesis = Thesis(
        action="trade",
        confidence=0.8,
        rationale="Aligned deterministic signals support a narrow defined-risk paper spread.",
        invalidation="Exit on signal reversal, degraded liquidity, or deterministic stop.",
        candidate_symbol="SPY260918C00650000",
    )
    plan = cycle._plan_from_spread(_scan(), thesis, equity=100_000)
    assert plan is not None
    assert plan.strategy == "debit_spread"
    assert [leg.side.value for leg in plan.legs] == ["buy", "sell"]
    assert plan.limit_price == 1.3
    assert plan.max_loss_usd == 130


@pytest.mark.asyncio
async def test_end_to_end_cycle_produces_dry_run_without_order_submission(tmp_path, monkeypatch):
    settings = Settings(underlying_universe="SPY", allow_order_execution=True, dry_run=True)
    executor = PaperExecutionAgent(
        settings, DecisionJournal(tmp_path / "journal.jsonl"), NoCallMCP()
    )
    cycle = AutonomousCycle(settings, executor)

    async def account_state():
        return {"equity": "100000", "buying_power": "100000"}, {"is_open": True}, []

    async def scan(_underlying):
        return _scan()

    monkeypatch.setattr(cycle, "_account_state", account_state)
    monkeypatch.setattr(cycle.scanner, "scan", scan)
    result = await cycle.run_once()
    assert result["result"]["status"] == "dry_run"
    assert result["plan"]["strategy"] == "debit_spread"


@pytest.mark.asyncio
async def test_closed_market_returns_before_scanning_or_an_llm_call(monkeypatch):
    cycle = AutonomousCycle(Settings(underlying_universe="SPY"), NoopExecutor())

    async def account_state():
        return {"equity": "100000", "buying_power": "100000"}, {"is_open": False}, []

    async def scan(_underlying):
        raise AssertionError("a closed market must not scan or call an agent")

    monkeypatch.setattr(cycle, "_account_state", account_state)
    monkeypatch.setattr(cycle.scanner, "scan", scan)
    assert await cycle.run_once() == {
        "status": "no_trade",
        "reason": "market_closed",
        "paper_only": True,
    }


@pytest.mark.asyncio
async def test_local_thesis_agent_runs_without_an_openai_key():
    cycle = AutonomousCycle(Settings(), NoopExecutor())
    scan = _scan()
    assert scan.opportunity is not None
    thesis = await cycle._thesis().evaluate(scan.opportunity)
    assert thesis.action == "trade"
    assert thesis.candidate_symbol == scan.opportunity.candidate.symbol
