import json
from pathlib import Path

from .models import JournalEntry


class DecisionJournal:
    def __init__(self, path: str | Path = "data/journal.jsonl"):
        self.path = Path(path)

    def append(self, entry: JournalEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")

    def latest(self, limit: int = 20) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in reversed(lines)]

    def has_client_order_id(self, client_order_id: str) -> bool:
        """Detect an idempotency key already journaled before an MCP submission."""
        if not self.path.exists():
            return False
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("plan", {}).get("client_order_id") == client_order_id:
                return True
        return False
