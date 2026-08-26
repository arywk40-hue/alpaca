import pytest

from vegaguard.dashboard import dashboard_state
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
        "shadow_trade_count": 1,
        "completed_shadow_audits": 1,
        "selected_minus_shadow_pnl": 40.0,
        "open_position_unrealized_pnl": 0,
    }
    assert state["shadows"][0]["regime"] == "bullish"


def test_dashboard_reports_the_latest_open_position_mark(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    trade_plan = _plan()
    journal.append(
        JournalEntry(event="position_mark", plan=trade_plan, payload={"unrealized_pnl": 42.5})
    )
    assert dashboard_state(journal)["summary"]["open_position_unrealized_pnl"] == 42.5


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
    result = await MarketHoursScheduler(cycle, journal, interval_seconds=60, sleep=sleep).run(
        max_cycles=2
    )
    assert len(result) == 2
    assert cycle.calls == 2
    assert sleeps == [60]
    assert [entry["event"] for entry in journal.latest()] == ["scheduled_cycle", "scheduled_cycle"]


@pytest.mark.asyncio
async def test_scheduler_preserves_an_empty_timeout_type_in_the_audit(tmp_path):
    class TimeoutCycle:
        async def run_once(self):
            raise TimeoutError()

    result = await MarketHoursScheduler(
        TimeoutCycle(), DecisionJournal(tmp_path / "journal.jsonl"), interval_seconds=60
    ).run(max_cycles=1)
    assert result == [
        {"status": "cycle_error", "error_type": "TimeoutError", "reason": "TimeoutError"}
    ]


def test_scheduler_refuses_an_overly_fast_loop(tmp_path):
    with pytest.raises(ValueError, match="at least 60"):
        MarketHoursScheduler(
            _Cycle(), DecisionJournal(tmp_path / "journal.jsonl"), interval_seconds=59
        )
