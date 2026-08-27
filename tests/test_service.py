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
        quote_timestamp="2026-08-26T15:30:00+00:00",
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
        quote_timestamp="2026-08-26T15:30:01+00:00",
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


def _score_40_exploration_scan() -> ScanResult:
    source = _scan()
    assert source.spread is not None and source.opportunity is not None
    score = SignalScore(40, Regime.NEUTRAL, 25, 25, 0, 0, -10, 3, ("below 70",))
    return ScanResult(
        "SPY",
        score,
        None,
        None,
        score.reasons,
        shadow_spread=source.spread,
        shadow_opportunity=source.opportunity,
    )


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
    assert result["order_preview"]["maximum_loss"] == 130
    assert result["order_preview"]["maximum_profit"] == 370.0
    assert result["order_preview"]["mcp_payload"]["order_class"] == "mleg"
    assert result["order_preview"]["plan_id"].startswith("vg-plan-")
    assert result["order_preview"]["approval_expires_at"]
    assert len(result["order_preview"]["quote_timestamps"]) == 2


@pytest.mark.asyncio
async def test_score_40_is_accepted_only_by_opt_in_exploration_dry_run(tmp_path, monkeypatch):
    settings = Settings(
        underlying_universe="SPY",
        allow_order_execution=True,
        dry_run=True,
        exploration_mode=True,
        exploration_score_threshold=40,
    )
    executor = PaperExecutionAgent(
        settings, DecisionJournal(tmp_path / "journal.jsonl"), NoCallMCP()
    )
    cycle = AutonomousCycle(settings, executor)

    async def account_state():
        return {"equity": "100000", "buying_power": "100000"}, {"is_open": True}, []

    async def scan(_underlying):
        return _score_40_exploration_scan()

    monkeypatch.setattr(cycle, "_account_state", account_state)
    monkeypatch.setattr(cycle.scanner, "scan", scan)
    result = await cycle.run_once()
    assert result["result"]["status"] == "dry_run"
    assert result["plan"]["trade_mode"] == "exploration"
    assert result["plan"]["score_threshold"] == 40
    assert result["plan"]["qty"] == 1
    assert result["order_preview"]["trade_mode"] == "exploration"
    assert result["scan"]["regime"] == "bullish_exploration"
    assert result["scan"]["baseline_regime"] == "neutral"
    candidate = executor.journal.shadow_candidates()[0]
    assert candidate["classification"] == "exploration_eligible"
    assert candidate["regime"] == "bullish_exploration"
    assert candidate["baseline_regime"] == "neutral"
    assert candidate["trade_mode"] == "exploration"
    assert candidate["score_threshold"] == 40
    assert candidate["spread"]["entry_quote"] == 1.3
    assert candidate["spread"]["pnl_usd"] is None
    assert candidate["reasons"] == [
        "production baseline remains neutral below its fixed 70-point threshold",
        "exploration threshold 40 accepted the quote-backed directional candidate",
    ]


@pytest.mark.asyncio
async def test_score_40_is_rejected_by_unchanged_production_threshold(tmp_path, monkeypatch):
    settings = Settings(underlying_universe="SPY", allow_order_execution=True, dry_run=True)
    executor = PaperExecutionAgent(
        settings, DecisionJournal(tmp_path / "journal.jsonl"), NoCallMCP()
    )
    cycle = AutonomousCycle(settings, executor)

    async def account_state():
        return {"equity": "100000", "buying_power": "100000"}, {"is_open": True}, []

    async def scan(_underlying):
        return _score_40_exploration_scan()

    monkeypatch.setattr(cycle, "_account_state", account_state)
    monkeypatch.setattr(cycle.scanner, "scan", scan)
    result = await cycle.run_once()
    assert result == {
        "status": "no_trade",
        "reason": "no ETF passed deterministic scan and budget rules",
    }
    candidate = executor.journal.shadow_candidates()[0]
    assert candidate["trade_mode"] == "production"
    assert candidate["score_threshold"] == 70


@pytest.mark.asyncio
async def test_exploration_refuses_a_new_trade_when_any_position_is_open(tmp_path, monkeypatch):
    settings = Settings(
        underlying_universe="SPY", exploration_mode=True, allow_order_execution=True, dry_run=True
    )
    executor = PaperExecutionAgent(
        settings, DecisionJournal(tmp_path / "journal.jsonl"), NoCallMCP()
    )
    cycle = AutonomousCycle(settings, executor)

    async def account_state():
        return {"equity": "100000", "buying_power": "100000"}, {"is_open": True}, [{"x": 1}]

    async def scan(_underlying):
        return _score_40_exploration_scan()

    monkeypatch.setattr(cycle, "_account_state", account_state)
    monkeypatch.setattr(cycle.scanner, "scan", scan)
    assert await cycle.run_once() == {
        "status": "no_trade",
        "reason": "exploration_open_position_limit",
        "open_positions": 1,
    }


def test_serialized_scan_distinguishes_missing_data_from_neutral_signal():
    scan = _scan()
    payload = AutonomousCycle._serialize_scan(scan)
    assert payload["regime"] == "bullish"
    assert payload["confidence"] == 1.0
    assert payload["data_timestamp"] is None

    missing = ScanResult("SPY", None, None, None, ("missing_iv",))
    missing_payload = AutonomousCycle._serialize_scan(missing)
    assert missing_payload["regime"] == "no_trade"
    assert missing_payload["confidence"] is None


def test_shadow_candidate_ledger_records_below_threshold_spread_with_quote_times(tmp_path):
    settings = Settings()
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    cycle = AutonomousCycle(settings, PaperExecutionAgent(settings, journal, NoCallMCP()))
    source = _scan()
    neutral = ScanResult(
        "SPY",
        SignalScore(-65, Regime.NEUTRAL, -25, -25, 0, 0, -15, 3, ("weak",)),
        None,
        None,
        ("weak",),
        shadow_spread=source.spread,
    )
    cycle._record_shadow_candidate(neutral)
    candidate = journal.shadow_candidates()[0]
    assert candidate["classification"] == "below_threshold"
    assert candidate["score"] == -65
    assert candidate["quote_timestamps"] == [
        "2026-08-26T15:30:00+00:00",
        "2026-08-26T15:30:01+00:00",
    ]
    assert candidate["spread"]["debit"] == 1.3
    assert candidate["score_threshold"] == 70
    assert candidate["trade_mode"] == "production"


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
