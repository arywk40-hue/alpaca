from vegaguard.journal import DecisionJournal
from vegaguard.models import JournalEntry


def test_journal_round_trip(tmp_path):
    journal = DecisionJournal(tmp_path / "decisions.jsonl")
    journal.append(JournalEntry(event="tested", payload={"key": "value"}))
    assert journal.latest() == [journal.latest()[0]]
    assert journal.latest()[0]["event"] == "tested"
