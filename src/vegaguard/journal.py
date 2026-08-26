import json
from pathlib import Path

from .models import JournalEntry, TradePlan
from .storage import PaperLedger


class DecisionJournal:
    def __init__(self, path: str | Path = "data/journal.jsonl"):
        self.path = Path(path)
        self.ledger = PaperLedger(self.path.with_suffix(".sqlite3"))

    def append(self, entry: JournalEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")
        self.ledger.append_event(entry)

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

    def register_shadow(self, plan, *, regime: str, shadow_kind: str = "no_trade") -> bool:
        return self.ledger.register_shadow(plan, regime=regime, shadow_kind=shadow_kind)

    def record_shadow_outcome(
        self,
        client_order_id: str,
        *,
        selected_net_pnl: float,
        shadow_net_pnl: float,
        close_reason: str,
    ) -> bool:
        return self.ledger.record_shadow_outcome(
            client_order_id,
            selected_net_pnl=selected_net_pnl,
            shadow_net_pnl=shadow_net_pnl,
            close_reason=close_reason,
        )

    def shadows(self, limit: int = 20) -> list[dict]:
        return self.ledger.shadows(limit)

    def plan_for_client_order_id(self, client_order_id: str) -> TradePlan | None:
        """Recover the immutable original plan needed to close a filled spread."""
        if not self.path.exists():
            return None
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                plan = json.loads(line).get("plan")
                if plan and plan.get("client_order_id") == client_order_id:
                    return TradePlan.model_validate(plan)
            except (json.JSONDecodeError, ValueError):
                continue
        return None

    def has_exit_for(self, parent_client_order_id: str) -> bool:
        if not self.path.exists():
            return False
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                plan = json.loads(line).get("plan") or {}
            except json.JSONDecodeError:
                continue
            if plan.get("parent_client_order_id") == parent_client_order_id:
                return True
        return False
