from datetime import UTC, datetime, timedelta

import pytest

from vegaguard.config import Settings
from vegaguard.execution import PaperExecutionAgent
from vegaguard.journal import DecisionJournal
from vegaguard.service import AutonomousCycle
from vegaguard.storage import PaperLedger


class NoCallMCP:
    async def call(self, *_args):
        raise AssertionError("shadow evaluation must never call MCP")


def _spread() -> dict:
    return {
        "long_symbol": "SPY260918C00650000",
        "short_symbol": "SPY260918C00655000",
        "entry_quote": 1.3,
        "width": 5.0,
        "long_bid": 3.4,
        "long_ask": 3.5,
        "long_mid": 3.45,
        "long_iv": 0.2,
        "long_dte": 21,
        "long_volume": 125.0,
        "long_open_interest": 900.0,
        "short_bid": 2.2,
        "short_ask": 2.3,
        "short_mid": 2.25,
        "short_iv": 0.2,
        "short_dte": 21,
        "short_volume": 100.0,
        "short_open_interest": 800.0,
    }


def _record_candidate(
    journal: DecisionJournal,
    *,
    score: int = 65,
    observed_at: datetime | None = None,
    opportunity_id: str | None = None,
) -> int:
    return journal.record_shadow_candidate(
        underlying="SPY",
        classification="below_threshold",
        score=score,
        regime="neutral",
        baseline_regime="neutral",
        score_threshold=70,
        trade_mode="production",
        data_timestamp=observed_at or datetime.now(UTC),
        reasons=["score or agreement threshold was not met"],
        quote_timestamps=[datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()],
        spread=_spread(),
        evidence={
            "score_components": {"daily_regime": 25, "intraday_trend": 25},
            "rejection_gates": ["score or agreement threshold was not met"],
            "underlying_price": 640.0,
            "volume_ratio": 1.2,
        },
        opportunity_id=opportunity_id,
        observed_at=observed_at,
    )


def test_shadow_candidate_persists_complete_evidence_and_due_horizons(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    candidate_id = _record_candidate(journal)
    candidate = journal.shadow_candidates()[0]
    assert candidate["id"] == candidate_id
    assert candidate["evidence"]["underlying_price"] == 640.0
    assert candidate["spread"]["long_mid"] == 3.45
    assert candidate["spread"]["short_open_interest"] == 800.0

    due = journal.due_shadow_reprices(datetime.now(UTC) + timedelta(minutes=60, seconds=1))
    assert {(item["candidate_id"], item["horizon_minutes"]) for item in due} == {
        (candidate_id, 15),
        (candidate_id, 30),
        (candidate_id, 60),
    }
    assert [item["deadline_status"] for item in due] == ["overdue", "overdue", "due"]


def test_hypothetical_reprice_uses_conservative_quotes_and_configured_costs(tmp_path):
    settings = Settings(shadow_fee_per_contract_usd=1.0, shadow_slippage_per_leg_usd=0.25)
    cycle = AutonomousCycle(
        settings,
        PaperExecutionAgent(settings, DecisionJournal(tmp_path / "journal.jsonl"), NoCallMCP()),
    )
    now = datetime.now(UTC)
    snapshots = {
        "SPY260918C00650000": {"latestQuote": {"t": now.isoformat(), "bp": 2.6, "ap": 2.7}},
        "SPY260918C00655000": {"latestQuote": {"t": now.isoformat(), "bp": 0.4, "ap": 0.5}},
    }
    outcome = cycle._hypothetical_reprice(_spread(), snapshots, now)
    assert outcome["hypothetical"] is True
    assert outcome["entry_debit"] == 1.3
    assert outcome["exit_credit"] == 2.1
    assert outcome["gross_hypothetical_pnl"] == 80.0
    assert outcome["total_costs_usd"] == 2.0
    assert outcome["net_hypothetical_pnl"] == 78.0
    assert "realized" not in outcome


def test_session_report_keeps_hypothetical_outcomes_separate(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    candidate_id = _record_candidate(journal)
    assert journal.record_shadow_reprice(
        candidate_id,
        15,
        repriced_at=datetime.now(UTC),
        outcome_bucket="shadow",
        outcome={"status": "priced", "hypothetical": True, "net_hypothetical_pnl": 25.0},
    )
    report = journal.shadow_session_report()
    assert report["outcomes_are_hypothetical"] is True
    assert report["scan_count"] == 1
    assert report["hypothetical_outcome_buckets"] == {"shadow": 1}
    assert report["hypothetical_pnl_by_threshold"]["40"]["net_hypothetical_pnl"] == 25.0
    assert report["hypothetical_pnl_by_threshold"]["40"]["expectancy_usd_per_opportunity"] == 25.0
    assert report["hypothetical_pnl_by_threshold"]["70"]["outcome_count"] == 0


@pytest.mark.asyncio
async def test_due_reprice_fetches_exact_legs_without_execution(tmp_path, monkeypatch):
    settings = Settings()
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    candidate_id = _record_candidate(journal)
    cycle = AutonomousCycle(settings, PaperExecutionAgent(settings, journal, NoCallMCP()))
    due = journal.due_shadow_reprices(datetime.now(UTC) + timedelta(minutes=15, seconds=1))[0]
    monkeypatch.setattr(journal, "due_shadow_reprices", lambda _now: [due])
    now = datetime.now(UTC)

    async def option_snapshots(underlying, *, symbols):
        assert underlying == "SPY"
        assert symbols == ["SPY260918C00650000", "SPY260918C00655000"]
        return {
            symbols[0]: {"latestQuote": {"t": now.isoformat(), "bp": 2.6, "ap": 2.7}},
            symbols[1]: {"latestQuote": {"t": now.isoformat(), "bp": 0.4, "ap": 0.5}},
        }

    monkeypatch.setattr(cycle.alpaca, "option_snapshots", option_snapshots)
    result = await cycle.reprice_shadow_candidates()
    assert result == [
        {
            "candidate_id": candidate_id,
            "horizon_minutes": 15,
            "stored": True,
            "outcome_bucket": "shadow",
            "status": "priced",
        }
    ]
    stored = journal.shadow_reprices()[0]
    assert stored["outcome"]["hypothetical"] is True


@pytest.mark.asyncio
async def test_reprice_request_failure_is_persisted_as_quote_unavailable(tmp_path, monkeypatch):
    settings = Settings()
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    _record_candidate(journal, observed_at=datetime.now(UTC) - timedelta(minutes=15))
    cycle = AutonomousCycle(settings, PaperExecutionAgent(settings, journal, NoCallMCP()))

    async def unavailable_quotes(_underlying, *, symbols):
        raise RuntimeError(f"unexpected quote request for {symbols!r}")

    monkeypatch.setattr(cycle.alpaca, "option_snapshots", unavailable_quotes)
    result = await cycle.reprice_shadow_candidates()

    assert result[0]["status"] == "unavailable"
    assert journal.shadow_reprices()[0]["outcome"] == {
        "status": "unavailable",
        "hypothetical": True,
        "reason": "exit quote retrieval failed: RuntimeError",
    }


@pytest.mark.asyncio
async def test_fake_clock_persists_complete_reprices_on_the_original_opportunity(
    tmp_path, monkeypatch
):
    start = datetime.now(UTC) - timedelta(hours=1)
    current = [start]
    settings = Settings(shadow_fee_per_contract_usd=1.0, shadow_slippage_per_leg_usd=0.25)
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    candidate_id = _record_candidate(
        journal, observed_at=start, opportunity_id="opp-spy-continuing"
    )
    cycle = AutonomousCycle(
        settings,
        PaperExecutionAgent(settings, journal, NoCallMCP()),
        now=lambda: current[0],
    )

    async def option_snapshots(_underlying, *, symbols):
        return {
            symbols[0]: {"latestQuote": {"t": current[0].isoformat(), "bp": 2.6, "ap": 2.7}},
            symbols[1]: {"latestQuote": {"t": current[0].isoformat(), "bp": 0.4, "ap": 0.5}},
        }

    monkeypatch.setattr(cycle.alpaca, "option_snapshots", option_snapshots)
    assert await cycle.reprice_shadow_candidates() == []
    for minutes, horizon in ((15, 15), (30, 30), (60, 60)):
        current[0] = start + timedelta(minutes=minutes)
        result = await cycle.reprice_shadow_candidates()
        assert [item["horizon_minutes"] for item in result] == [horizon]
        assert result[0]["stored"] is True

    candidate = journal.shadow_candidates()[0]
    assert candidate["id"] == candidate_id
    assert [item["horizon_minutes"] for item in candidate["reprices"]] == [15, 30, 60]
    assert candidate["spread"]["exit_quote"] == 2.1
    assert candidate["spread"]["pnl_usd"] == 78.0
    assert candidate["spread"]["pnl_label"] == "hypothetical"
    assert candidate["spread"]["exit_quote_timestamps"] == [
        current[0].isoformat(),
        current[0].isoformat(),
    ]
    assert candidate["reprice_status"]["status"] == "completed"


@pytest.mark.asyncio
async def test_partial_reprices_persist_stale_and_missing_quote_reasons(tmp_path, monkeypatch):
    start = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)
    current = [start + timedelta(minutes=15)]
    settings = Settings()
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    _record_candidate(journal, observed_at=start, opportunity_id="opp-spy-partial")
    cycle = AutonomousCycle(
        settings, PaperExecutionAgent(settings, journal, NoCallMCP()), now=lambda: current[0]
    )

    async def stale_quotes(_underlying, *, symbols):
        return {
            symbols[0]: {
                "latestQuote": {
                    "t": (current[0] - timedelta(minutes=16)).isoformat(),
                    "bp": 2.6,
                    "ap": 2.7,
                }
            },
            symbols[1]: {},
        }

    monkeypatch.setattr(cycle.alpaca, "option_snapshots", stale_quotes)
    result = await cycle.reprice_shadow_candidates()
    assert result[0]["status"] == "unavailable"
    stored = journal.shadow_reprices()[0]["outcome"]
    assert stored["reason"] == "long exit quote is stale; short exit quote missing"
    assert journal.shadow_candidates()[0]["reprice_status"]["status"] == "quote_unavailable"

    current[0] = start + timedelta(minutes=30)
    await cycle.reprice_shadow_candidates()
    assert [item["horizon_minutes"] for item in journal.shadow_reprices()] == [30, 15]


def test_repeated_observations_share_one_opportunity_and_session_report_is_fresh(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    start = datetime.now(UTC)
    origin_id = _record_candidate(journal, observed_at=start, opportunity_id="opp-spy-same-legs")
    repeated_id = _record_candidate(
        journal,
        observed_at=start + timedelta(minutes=5),
        opportunity_id="opp-spy-same-legs",
    )
    assert repeated_id != origin_id
    observations = journal.shadow_candidates()
    assert len(observations) == 2
    assert {item["opportunity_id"] for item in observations} == {"opp-spy-same-legs"}
    assert {item["origin_candidate_id"] for item in observations} == {origin_id}
    assert {item["observation_count"] for item in observations} == {2}
    due = journal.due_shadow_reprices(start + timedelta(minutes=60, seconds=1))
    assert {(item["candidate_id"], item["horizon_minutes"]) for item in due} == {
        (origin_id, 15),
        (origin_id, 30),
        (origin_id, 60),
        (repeated_id, 15),
        (repeated_id, 30),
    }

    due_for_both_observations = journal.due_shadow_reprices(start + timedelta(minutes=20))
    assert {
        (item["candidate_id"], item["horizon_minutes"]) for item in due_for_both_observations
    } == {
        (origin_id, 15),
        (repeated_id, 15),
    }

    before = journal.shadow_session_report()
    assert before["opportunity_count"] == 1
    assert before["observation_count"] == 2
    assert before["reprice_count"] == 0
    assert before["reprice_status_distribution"] == {"pending_15m": 1}
    assert journal.record_shadow_reprice(
        origin_id,
        15,
        repriced_at=start + timedelta(minutes=15),
        outcome_bucket="shadow",
        outcome={"status": "priced", "hypothetical": True, "net_hypothetical_pnl": 25.0},
    )
    after = journal.shadow_session_report()
    assert after["reprice_count"] == 1
    assert after["hypothetical_pnl_by_outcome_bucket"]["shadow"]["outcome_count"] == 1


def test_reopening_a_legacy_ledger_backfills_stable_opportunity_ids(tmp_path):
    path = tmp_path / "journal.jsonl"
    journal = DecisionJournal(path)
    _record_candidate(journal)
    assert journal.shadow_candidates()[0]["opportunity_id"] is None

    reopened = DecisionJournal(path)
    candidate = reopened.shadow_candidates()[0]
    assert candidate["opportunity_id"].startswith("opp-")
    assert candidate["origin_candidate_id"] == candidate["id"]


def test_reprice_status_marks_missed_windows_without_late_repricing():
    start = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)
    status = PaperLedger._reprice_status(start.isoformat(), [], start + timedelta(minutes=70))
    assert status["status"] == "overdue_15m"
    assert [item["status"] for item in status["horizons"]] == [
        "overdue_15m",
        "overdue_30m",
        "overdue_60m",
    ]
