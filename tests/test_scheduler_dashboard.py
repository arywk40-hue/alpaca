from datetime import UTC, datetime, timedelta

import pytest

from vegaguard.dashboard import dashboard_html, dashboard_state
from vegaguard.journal import DecisionJournal
from vegaguard.models import (
    JournalEntry,
    OptionCandidate,
    OptionLeg,
    PositionIntent,
    Side,
    Thesis,
    TradePlan,
)
from vegaguard.scheduler import MarketHoursScheduler


def _plan() -> TradePlan:
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
                symbol=candidate.symbol, side=Side.BUY, position_intent=PositionIntent.BUY_TO_OPEN
            ),
            OptionLeg(
                symbol="SPY260918C00655000",
                side=Side.SELL,
                position_intent=PositionIntent.SELL_TO_OPEN,
            ),
        ],
        limit_price=1.3,
        max_loss_usd=130,
        candidate=candidate,
        thesis=Thesis(
            action="trade",
            confidence=0.8,
            rationale="A narrow, deterministic spread has passed all evidence and risk checks.",
            invalidation="Exit on the documented risk, price, time, or liquidity triggers.",
            candidate_symbol=candidate.symbol,
        ),
        client_order_id="vg-shadow-test",
    )


def test_shadow_ledger_is_immutable_and_dashboard_reads_it(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    assert journal.register_shadow(_plan(), regime="bullish")
    assert not journal.register_shadow(_plan(), regime="bearish")
    assert journal.record_shadow_outcome(
        "vg-shadow-test", selected_net_pnl=40, shadow_net_pnl=0, close_reason="take_profit"
    )
    assert not journal.record_shadow_outcome(
        "vg-shadow-test", selected_net_pnl=-10, shadow_net_pnl=20, close_reason="rewritten"
    )
    state = dashboard_state(journal)
    assert state["summary"] == {
        "shadow_candidate_count": 0,
        "shadow_opportunity_count": 0,
        "exploration_candidate_count": 0,
        "exploration_opportunity_count": 0,
        "approved_production_plan_count": 1,
        "approved_exploration_plan_count": 0,
        "acknowledged_paper_order_count": 0,
        "filled_paper_trade_count": 0,
        "realized_paper_trade_count": 0,
        "realized_paper_pnl_before_fees": 0,
        "realized_paper_pnl_after_fees": None,
        "hypothetical_reprice_count": 0,
        "overdue_reprice_count": 0,
        "risk_budget_rejection_count": 0,
        "completed_shadow_audits": 1,
        "selected_minus_shadow_pnl": 40.0,
        "selected_hypothetical_pnl": 0.0,
        "exploration_hypothetical_pnl": 0.0,
        "rejected_shadow_hypothetical_pnl": 0.0,
        "selected_minus_rejected_shadow_hypothetical_pnl": 0.0,
        "open_position_unrealized_pnl": 0,
    }
    assert state["shadows"][0]["regime"] == "bullish"


def test_dashboard_exposes_shadow_candidate_ledger(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    journal.record_shadow_candidate(
        underlying="SPY",
        classification="below_threshold",
        score=65,
        regime="neutral",
        baseline_regime="neutral",
        score_threshold=40,
        trade_mode="exploration",
        data_timestamp=None,
        reasons=["score threshold"],
        quote_timestamps=["2026-08-26T15:30:00+00:00"],
        spread={"debit": 1.2},
    )
    state = dashboard_state(journal)
    assert state["summary"]["shadow_candidate_count"] == 1
    assert state["summary"]["exploration_candidate_count"] == 1
    assert state["shadow_candidates"][0]["classification"] == "below_threshold"
    assert state["shadow_candidates"][0]["trade_mode"] == "exploration"
    assert "reasons_json" not in state["shadow_candidates"][0]


def test_dashboard_displays_risk_budget_rejection_diagnostics(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    journal.record_risk_budget_rejection(
        candidate_id=None,
        underlying="IWM",
        score=65,
        trade_mode="exploration",
        diagnostic={
            "required_max_loss_usd": 231.0,
            "configured_maximum_risk_per_trade_usd": 500.0,
            "available_alpaca_buying_power_usd": 10_000.0,
            "remaining_portfolio_risk_budget_usd": 600.0,
            "failed_comparisons": ["required maximum loss exceeds effective risk budget"],
        },
    )
    state = dashboard_state(journal)
    assert state["summary"]["risk_budget_rejection_count"] == 1
    assert state["risk_budget_rejections"][0]["underlying"] == "IWM"
    assert state["risk_budget_rejections"][0]["diagnostic"]["required_max_loss_usd"] == 231.0
    assert "Risk-budget rejections" in dashboard_html()


def test_dashboard_distinguishes_approved_plans_from_actual_paper_trades(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    exploration_plan = _plan().model_copy(
        update={"trade_mode": "exploration", "score_threshold": 40}
    )
    assert journal.register_shadow(exploration_plan, regime="bullish_exploration")
    summary = dashboard_state(journal)["summary"]
    assert summary["approved_exploration_plan_count"] == 1
    assert summary["acknowledged_paper_order_count"] == 0
    assert summary["filled_paper_trade_count"] == 0

    journal.append(
        JournalEntry(
            event="order_acknowledged",
            plan=exploration_plan,
            payload={"provider_status": "accepted"},
        )
    )
    journal.record_entry_fill(exploration_plan, filled_price=1.3, source="trade_updates")
    summary = dashboard_state(journal)["summary"]
    assert summary["acknowledged_paper_order_count"] == 1
    assert summary["filled_paper_trade_count"] == 1
    assert "Approved exploration plans" in dashboard_html()


def test_dashboard_displays_latest_trade_thesis_explanation(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEntry(
            event="trade_thesis_explanation",
            payload={
                "advisory_only": True,
                "source": "deterministic_fallback",
                "fallback_reason": "OPENAI_API_KEY is not configured",
                "explanation": {
                    "thesis": "Validated facts are insufficient for a directional claim.",
                    "supporting_signals": ["score unavailable"],
                    "risks": ["missing evidence"],
                    "invalidation": "Require fresh validated facts.",
                    "explanation": "Deterministic fallback summary.",
                },
                "deterministic_controls": {"score": None, "risk_approved": False},
            },
        )
    )
    state = dashboard_state(journal)
    assert state["latest_thesis_explanation"]["source"] == "deterministic_fallback"
    assert state["latest_thesis_explanation"]["explanation"]["risks"] == ["missing evidence"]
    assert "Trade Thesis &amp; Risk Explainer" in dashboard_html()
    assert "ADVISORY ONLY" in dashboard_html()


def test_dashboard_reports_the_latest_open_position_mark(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    trade_plan = _plan()
    journal.append(
        JournalEntry(event="position_mark", plan=trade_plan, payload={"unrealized_pnl": 42.5})
    )
    assert dashboard_state(journal)["summary"]["open_position_unrealized_pnl"] == 42.5


def test_dashboard_reports_scheduler_never_started_and_stale_states(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    assert dashboard_state(journal)["scheduler"] == {
        "status": "never_started",
        "last_heartbeat_at": None,
        "last_journal_timestamp": None,
        "last_error": None,
        "session_id": None,
        "process_id": None,
        "market_open": None,
        "last_cycle_started_at": None,
        "last_cycle_completed_at": None,
        "last_successful_cycle_at": None,
    }
    heartbeat_at = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)
    journal.append(
        JournalEntry(
            timestamp=heartbeat_at,
            event="scheduler_heartbeat",
            payload={"status": "waiting", "interval_seconds": 60, "cycle_number": 2},
        )
    )
    status = journal.scheduler_status(now=heartbeat_at + timedelta(seconds=181))
    assert status["status"] == "stale"
    assert status["cycle_number"] == 2
    assert "Scheduler heartbeat" in dashboard_html()
    assert "hypothetical evidence" in dashboard_html()
    assert "Start Shadow Agent" in dashboard_html()
    assert "Start Simulation Replay" in dashboard_html()
    assert "Arm Paper Execution" in dashboard_html()
    assert "Disarm Paper Execution" in dashboard_html()
    assert "Emergency Stop" in dashboard_html()
    assert "Submit exact approved plan" in dashboard_html()
    assert "EventSource('/events')" in dashboard_html()


def test_dashboard_operator_mode_wires_controls_without_embedding_secrets():
    html = dashboard_html()
    for fragment in (
        "Local operator mode",
        "operator-token",
        "save-token",
        "clear-token",
        "sessionStorage",
        "Authorization",
        "Bearer ",
        "SIMULATION",
        "HYPOTHETICAL SHADOW RESULTS",
        "APPROVED PLANS",
        "ACKNOWLEDGED ORDERS",
        "FILLS",
        "REALIZED P&amp;L",
        "Live event timeline",
    ):
        assert fragment in html
    assert "dashboard-test-token" not in html
    assert "wrong-dashboard-token" not in html


class _Cycle:
    def __init__(self):
        self.calls = 0

    async def run_once(self):
        self.calls += 1
        return {"status": "no_trade", "reason": "market_closed"}


@pytest.mark.asyncio
async def test_scheduler_runs_bounded_cycles_and_journals_outcomes(tmp_path):
    sleeps: list[float] = []

    async def sleep(seconds: float):
        sleeps.append(seconds)

    journal = DecisionJournal(tmp_path / "journal.jsonl")
    cycle = _Cycle()
    started_at = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)
    result = await MarketHoursScheduler(
        cycle, journal, interval_seconds=60, sleep=sleep, now=lambda: started_at
    ).run(max_cycles=2)
    assert len(result) == 2
    assert cycle.calls == 2
    assert sleeps == [60]
    assert [entry["event"] for entry in journal.latest()] == [
        "scheduler_heartbeat",
        "scheduled_cycle",
        "scheduler_heartbeat",
        "scheduler_heartbeat",
        "scheduled_cycle",
        "scheduler_heartbeat",
    ]
    assert journal.scheduler_status(now=started_at)["status"] == "stopped"
    assert journal.scheduler_status(now=started_at)["last_cycle_status"] == "no_trade"
    assert journal.scheduler_status(now=started_at)["last_error"] is None
    assert journal.scheduler_status(now=started_at)["market_open"] is False
    assert journal.scheduler_status(now=started_at)["last_cycle_started_at"]
    assert journal.scheduler_status(now=started_at)["last_cycle_completed_at"]


@pytest.mark.asyncio
async def test_scheduler_preserves_an_empty_timeout_type_in_the_audit(tmp_path):
    class TimeoutCycle:
        async def run_once(self):
            raise TimeoutError()

    journal = DecisionJournal(tmp_path / "journal.jsonl")
    result = await MarketHoursScheduler(TimeoutCycle(), journal, interval_seconds=60).run(
        max_cycles=1
    )
    assert result == [
        {"status": "cycle_error", "error_type": "TimeoutError", "reason": "TimeoutError"}
    ]
    status = journal.scheduler_status()
    assert status["status"] == "error"
    assert status["last_error"] == "TimeoutError"
    assert status["last_cycle_status"] == "cycle_error"
    assert status["last_journal_timestamp"] is not None


@pytest.mark.asyncio
async def test_scheduler_recovers_after_a_temporary_cycle_error(tmp_path):
    class FlakyCycle:
        calls = 0

        async def run_once(self):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary data timeout")
            return {"status": "no_trade", "reason": "no qualifying setup"}

    async def no_sleep(_seconds):
        return None

    journal = DecisionJournal(tmp_path / "journal.jsonl")
    outcomes = await MarketHoursScheduler(
        FlakyCycle(), journal, interval_seconds=60, sleep=no_sleep
    ).run(max_cycles=2)
    assert outcomes[0]["status"] == "cycle_error"
    assert outcomes[1]["status"] == "no_trade"
    status = journal.scheduler_status()
    assert status["status"] == "stopped"
    assert status["last_error"] is None
    assert status["last_successful_cycle_at"]


def test_scheduler_refuses_an_overly_fast_loop(tmp_path):
    with pytest.raises(ValueError, match="at least 60"):
        MarketHoursScheduler(
            _Cycle(), DecisionJournal(tmp_path / "journal.jsonl"), interval_seconds=59
        )
