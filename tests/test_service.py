from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from vegaguard.config import Settings
from vegaguard.execution import PaperExecutionAgent
from vegaguard.journal import DecisionJournal
from vegaguard.models import GateResult, JournalEntry, OptionCandidate, Thesis
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


def _exploration_scan_without_valid_spread() -> ScanResult:
    source = _score_40_exploration_scan()
    assert source.score is not None
    score = SignalScore(
        65,
        Regime.NEUTRAL,
        25,
        25,
        0,
        0,
        15,
        3,
        ("below 70", "score or agreement threshold was not met"),
    )
    return replace(
        source,
        score=score,
        shadow_spread=None,
        shadow_opportunity=None,
        reasons=("fresh quotes could not form a defined-risk spread",),
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
    candidate = executor.journal.shadow_candidates()[0]
    assert candidate["plan_id"] == result["plan"]["plan_id"]
    assert candidate["production_threshold"] == 70
    assert candidate["exploration_threshold"] == 40
    assert candidate["spread"]["max_profit_per_contract"] == 370.0
    assert candidate["spread"]["breakeven"] == 651.3


@pytest.mark.asyncio
async def test_thesis_skip_is_a_journaled_advisory_not_an_execution_veto(tmp_path, monkeypatch):
    settings = Settings(underlying_universe="SPY", allow_order_execution=True, dry_run=True)
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    cycle = AutonomousCycle(settings, PaperExecutionAgent(settings, journal, NoCallMCP()))

    async def account_state():
        return {"equity": "100000", "buying_power": "100000"}, {"is_open": True}, []

    async def scan(_underlying):
        return _scan()

    class CautiousAdvisory:
        async def evaluate(self, _opportunity):
            return Thesis(
                action="skip",
                confidence=0.1,
                rationale="The advisory model is cautious despite the deterministic validated inputs.",
                invalidation="Preserve deterministic risk and liquidity gates.",
                candidate_symbol="SPY260918C00650000",
            )

    monkeypatch.setattr(cycle, "_account_state", account_state)
    monkeypatch.setattr(cycle.scanner, "scan", scan)
    cycle._thesis_agent = CautiousAdvisory()
    result = await cycle.run_once()
    assert result["result"]["status"] == "dry_run"
    assert result["plan"]["thesis"]["action"] == "trade"
    advisory = next(entry for entry in journal.latest() if entry["event"] == "thesis_advisory")
    assert advisory["payload"]["agent_action"] == "skip"


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
        "shadow_reprices": [],
    }
    candidate = executor.journal.shadow_candidates()[0]
    assert candidate["trade_mode"] == "production"
    assert candidate["score_threshold"] == 70


def test_risk_budget_diagnostics_explain_iwm_and_qqq_boundaries():
    cycle = AutonomousCycle(Settings(), NoopExecutor())
    iwm_rejected = cycle._risk_budget_diagnostic(
        required_max_loss_usd=231,
        equity=40_000,
        buying_power=10_000,
        remaining_portfolio_risk_budget_usd=600,
    )
    assert iwm_rejected["configured_maximum_risk_per_trade_usd"] == 500
    assert iwm_rejected["effective_maximum_risk_per_trade_usd"] == 200
    assert iwm_rejected["failed_comparisons"] == [
        "required_max_loss_usd ($231.00) > effective_maximum_risk_per_trade_usd ($200.00)"
    ]

    iwm_accepted = cycle._risk_budget_diagnostic(
        required_max_loss_usd=231,
        equity=50_000,
        buying_power=10_000,
        remaining_portfolio_risk_budget_usd=750,
    )
    assert iwm_accepted["effective_maximum_risk_per_trade_usd"] == 250
    assert iwm_accepted["failed_comparisons"] == []

    qqq_rejected = cycle._risk_budget_diagnostic(
        required_max_loss_usd=592,
        equity=100_000,
        buying_power=10_000,
        remaining_portfolio_risk_budget_usd=1_500,
    )
    assert qqq_rejected["effective_maximum_risk_per_trade_usd"] == 500
    assert qqq_rejected["failed_comparisons"] == [
        "required_max_loss_usd ($592.00) > effective_maximum_risk_per_trade_usd ($500.00)"
    ]


def test_exploration_threshold_passed_without_spread_has_accurate_journal_reason(tmp_path):
    settings = Settings(exploration_mode=True, exploration_score_threshold=40)
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    cycle = AutonomousCycle(settings, PaperExecutionAgent(settings, journal, NoCallMCP()))
    cycle._record_shadow_candidate(_exploration_scan_without_valid_spread())
    candidate = journal.shadow_candidates()[0]
    assert candidate["classification"] == "exploration_rejected_no_valid_spread"
    assert candidate["regime"] == "bullish_exploration"
    assert candidate["baseline_regime"] == "neutral"
    assert "score or agreement threshold was not met" not in candidate["reasons"]
    assert candidate["reasons"][-1] == (
        "exploration threshold 40 passed but no valid defined-risk spread was available"
    )


@pytest.mark.asyncio
async def test_risk_budget_rejection_is_recorded_in_the_journal(tmp_path, monkeypatch):
    settings = Settings(
        underlying_universe="IWM",
        exploration_mode=True,
        exploration_score_threshold=40,
        allow_order_execution=False,
        dry_run=True,
    )
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    cycle = AutonomousCycle(settings, PaperExecutionAgent(settings, journal, NoCallMCP()))
    source = _score_40_exploration_scan()
    assert source.shadow_spread is not None
    scan = replace(
        source,
        underlying="IWM",
        shadow_spread=replace(source.shadow_spread, max_loss_per_contract=231),
    )

    async def account_state():
        return {"equity": "40000", "buying_power": "10000"}, {"is_open": True}, []

    async def scanner(_underlying):
        return scan

    monkeypatch.setattr(cycle, "_account_state", account_state)
    monkeypatch.setattr(cycle.scanner, "scan", scanner)
    result = await cycle.run_once()
    assert result["reason"] == "risk budget cannot fund one spread"
    assert result["risk_budget_rejections"][0]["required_max_loss_usd"] == 231
    rejection = journal.risk_budget_rejections()[0]
    assert rejection["underlying"] == "IWM"
    assert rejection["diagnostic"]["available_alpaca_buying_power_usd"] == 10_000


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
        "shadow_reprices": [],
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
async def test_exact_plan_revalidation_rejects_changed_quote_assumptions(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    cycle = AutonomousCycle(
        Settings(allow_order_execution=True, dry_run=False, max_plan_debit_change_pct=0.10),
        PaperExecutionAgent(
            Settings(allow_order_execution=True, dry_run=False), journal, NoCallMCP()
        ),
        now=lambda: now,
    )
    thesis = Thesis(
        action="trade",
        confidence=0.8,
        rationale="The deterministic score and defined risk support this reviewed paper spread.",
        invalidation="Exit when the deterministic stop or time limit is reached.",
        candidate_symbol="SPY260918C00650000",
    )
    approved = cycle._plan_from_spread(_scan(), thesis, equity=100_000)
    assert approved is not None
    approved = approved.model_copy(
        update={
            "approval_expires_at": now + timedelta(minutes=5),
            "quote_timestamps": [now.isoformat(), now.isoformat()],
        }
    )
    journal.append(
        JournalEntry(
            event="dry_run_order",
            plan=approved,
            gate=GateResult(approved=True, reasons=["reviewed"]),
        )
    )

    async def account_state():
        return {"buying_power": "100000"}, {"is_open": True}, []

    async def snapshots(_underlying, *, symbols):
        assert symbols == [leg.symbol for leg in approved.legs]
        return {
            approved.legs[0].symbol: {"latestQuote": {"bp": 3.9, "ap": 4.0, "t": now.isoformat()}},
            approved.legs[1].symbol: {"latestQuote": {"bp": 2.0, "ap": 2.1, "t": now.isoformat()}},
        }

    monkeypatch.setattr(cycle, "_account_state", account_state)
    monkeypatch.setattr(cycle.alpaca, "option_snapshots", snapshots)
    result = await cycle.submit_approved_plan(approved.plan_id)
    assert result["gate"]["approved"] is False
    assert any("fresh debit change" in reason for reason in result["gate"]["reasons"])
    assert result["result"]["status"] == "blocked"
    assert result["quote_revalidation"]["fresh_conservative_debit"] == 2.0


def test_exact_plan_revalidation_rejects_stale_leg_quotes():
    now = datetime.now(UTC)
    settings = Settings(max_execution_quote_age_seconds=60)
    cycle = AutonomousCycle(settings, NoopExecutor(), now=lambda: now)
    thesis = Thesis(
        action="trade",
        confidence=0.8,
        rationale="The deterministic score and defined risk support this reviewed paper spread.",
        invalidation="Exit when the deterministic stop or time limit is reached.",
        candidate_symbol="SPY260918C00650000",
    )
    approved = cycle._plan_from_spread(_scan(), thesis, equity=100_000)
    assert approved is not None
    stale_at = (now - timedelta(seconds=61)).isoformat()
    reasons, evidence = cycle._approval_quote_review(
        approved,
        {
            approved.legs[0].symbol: {"latestQuote": {"bp": 3.4, "ap": 3.5, "t": stale_at}},
            approved.legs[1].symbol: {"latestQuote": {"bp": 2.2, "ap": 2.3, "t": stale_at}},
        },
        now,
    )
    assert len(reasons) == 2
    assert all("is stale" in reason for reason in reasons)
    assert evidence["fresh_conservative_debit"] is None


@pytest.mark.asyncio
async def test_local_thesis_agent_runs_without_an_openai_key():
    cycle = AutonomousCycle(Settings(), NoopExecutor())
    scan = _scan()
    assert scan.opportunity is not None
    thesis = await cycle._thesis().evaluate(scan.opportunity)
    assert thesis.action == "trade"
    assert thesis.candidate_symbol == scan.opportunity.candidate.symbol
