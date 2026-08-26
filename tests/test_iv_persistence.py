from datetime import UTC, datetime, timedelta

from vegaguard.config import Settings
from vegaguard.journal import DecisionJournal
from vegaguard.scanner import OpportunityScanner


def _snapshots(now: datetime, iv: float = 0.2) -> dict:
    return {
        "SPY260918C00560000": {
            "latestQuote": {"t": now.isoformat(), "bp": 3.4, "ap": 3.5},
            "greeks": {"delta": 0.46},
            "impliedVolatility": iv,
        }
    }


def test_iv_observation_survives_a_new_scanner_process_within_freshness_window(tmp_path):
    now = datetime(2026, 8, 26, 15, 30, tzinfo=UTC)
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    first = OpportunityScanner(Settings(), object(), iv_store=journal)
    assert first._current_iv("SPY", _snapshots(now), now) is None
    assert journal.latest_iv_observation("SPY") == (now, 0.2)

    second = OpportunityScanner(Settings(), object(), iv_store=journal)
    observed = second._current_iv(
        "SPY", _snapshots(now + timedelta(minutes=5), 0.23), now + timedelta(minutes=5)
    )
    assert observed == (0.23, 0.2)
    assert journal.latest()[0]["event"] == "iv_observation"


def test_stale_persisted_iv_observation_cannot_be_used_as_current_state(tmp_path):
    now = datetime(2026, 8, 26, 15, 30, tzinfo=UTC)
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    journal.record_iv_observation("SPY", now - timedelta(hours=9), 0.2)
    scanner = OpportunityScanner(Settings(), object(), iv_store=journal)
    assert scanner._current_iv("SPY", _snapshots(now), now) is None
