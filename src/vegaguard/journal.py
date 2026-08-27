import json
from datetime import UTC, datetime, timedelta
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
            if (entry.get("plan") or {}).get("client_order_id") == client_order_id:
                return True
        return False

    def has_submitted_client_order_id(self, client_order_id: str) -> bool:
        """A dry-run preview is not an Alpaca submission and may be approved later."""
        return self._has_event("order_submission_intent", client_order_id) or self._has_event(
            "order_submission_receipt", client_order_id
        )

    def approved_plan(self, plan_id: str, *, now: datetime | None = None) -> TradePlan:
        """Recover one exact dry-run plan while its quote-bound approval is valid."""
        if not self.path.exists():
            raise ValueError("approved plan was not found")
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                entry = json.loads(line)
                raw_plan = entry.get("plan")
                if entry.get("event") != "dry_run_order" or not raw_plan:
                    continue
                plan = TradePlan.model_validate(raw_plan)
            except (json.JSONDecodeError, ValueError):
                continue
            if plan.plan_id != plan_id:
                continue
            if not entry.get("gate", {}).get("approved"):
                raise ValueError("approved plan failed its recorded risk gate")
            if plan.approval_expires_at is None or len(plan.quote_timestamps) != 2:
                raise ValueError("approved plan lacks a two-leg quote-bound expiry")
            current = (now or datetime.now(UTC)).astimezone(UTC)
            expires_at = plan.approval_expires_at.astimezone(UTC)
            if current >= expires_at:
                raise ValueError("approved plan has expired; run a fresh dry-run")
            try:
                quote_times = [
                    datetime.fromisoformat(value).astimezone(UTC) for value in plan.quote_timestamps
                ]
            except ValueError as exc:
                raise ValueError("approved plan has invalid quote timestamps") from exc
            if any(current - quote_time > timedelta(minutes=5) for quote_time in quote_times):
                raise ValueError("approved plan has stale quote timestamps; run a fresh dry-run")
            if self.has_submitted_client_order_id(plan.client_order_id):
                raise ValueError("approved plan was already submitted")
            return plan
        raise ValueError("approved plan was not found")

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

    def record_shadow_candidate(
        self,
        *,
        underlying: str,
        classification: str,
        score: int | None,
        regime: str,
        baseline_regime: str,
        score_threshold: int,
        trade_mode: str,
        data_timestamp: datetime | None,
        reasons: list[str],
        quote_timestamps: list[str],
        spread: dict | None,
    ) -> None:
        observed_at = datetime.now(UTC)
        payload = {
            "underlying": underlying,
            "classification": classification,
            "score": score,
            "regime": regime,
            "baseline_regime": baseline_regime,
            "score_threshold": score_threshold,
            "trade_mode": trade_mode,
            "data_timestamp": data_timestamp.isoformat() if data_timestamp else None,
            "reasons": reasons,
            "quote_timestamps": quote_timestamps,
            "spread": spread,
        }
        self.ledger.record_shadow_candidate(observed_at=observed_at, **payload)
        self.append(JournalEntry(timestamp=observed_at, event="shadow_candidate", payload=payload))

    def shadow_candidates(self, limit: int = 20) -> list[dict]:
        return self.ledger.shadow_candidates(limit)

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

    def record_entry_fill(self, plan: TradePlan, *, filled_price: float, source: str) -> bool:
        """Persist the actual paper fill once, for recovery and realized P&L."""
        if self._has_event("position_entry_filled", plan.client_order_id):
            return False
        self.append(
            JournalEntry(
                event="position_entry_filled",
                plan=plan,
                payload={
                    "filled_price": filled_price,
                    "costs_usd": None,
                    "costs_status": "not_reported_by_alpaca",
                    "source": source,
                },
            )
        )
        return True

    def entry_debit_for(self, client_order_id: str) -> float | None:
        """Return the recorded actual entry debit, never an inferred market mark."""
        if not self.path.exists():
            return None
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                entry.get("event") == "position_entry_filled"
                and (entry.get("plan") or {}).get("client_order_id") == client_order_id
            ):
                try:
                    return float((entry.get("payload") or {}).get("filled_price"))
                except (TypeError, ValueError):
                    return None
        return None

    def complete_trade_evidence(self) -> list[dict]:
        """Return only journal-proven, filled-and-exited paper trade records."""
        if not self.path.exists():
            return []
        entries: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        entry_fills = {
            (entry.get("plan") or {}).get("client_order_id"): entry
            for entry in entries
            if entry.get("event") == "position_entry_filled"
            and (entry.get("plan") or {}).get("client_order_id")
        }
        exits = {
            (entry.get("plan") or {}).get("parent_client_order_id"): entry
            for entry in entries
            if entry.get("event") == "exit_fill_reconciled"
            and (entry.get("plan") or {}).get("parent_client_order_id")
        }
        outcomes = {
            str((entry.get("payload") or {}).get("parent_client_order_id")): entry
            for entry in entries
            if entry.get("event") == "shadow_outcome_recorded"
            and (entry.get("payload") or {}).get("parent_client_order_id")
        }
        evidence: list[dict] = []
        for client_order_id, entry_fill in entry_fills.items():
            exit_fill = exits.get(client_order_id)
            outcome = outcomes.get(client_order_id)
            if not exit_fill or not outcome:
                continue
            plan = entry_fill["plan"]
            evidence.append(
                {
                    "client_order_id": client_order_id,
                    "underlying": plan["underlying"],
                    "trade_mode": plan.get("trade_mode", "production"),
                    "score_threshold": plan.get("score_threshold", 70),
                    "strategy": plan["strategy"],
                    "quantity": plan["qty"],
                    "entry_filled_at": entry_fill["timestamp"],
                    "entry_debit": entry_fill["payload"]["filled_price"],
                    "exit_filled_at": exit_fill["timestamp"],
                    "exit_credit": exit_fill["payload"]["filled_price"],
                    "exit_reason": exit_fill["payload"]["reason"],
                    "costs_usd": None,
                    "pnl_after_costs": None,
                    "realized_pnl": outcome["payload"]["selected_net_pnl"],
                }
            )
        return evidence

    def _has_event(self, event: str, client_order_id: str) -> bool:
        if not self.path.exists():
            return False
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                entry.get("event") == event
                and (entry.get("plan") or {}).get("client_order_id") == client_order_id
            ):
                return True
        return False

    def latest_iv_observation(self, underlying: str) -> tuple[datetime, float] | None:
        return self.ledger.latest_iv_observation(underlying)

    def record_iv_observation(
        self,
        underlying: str,
        observed_at: datetime,
        implied_volatility: float,
        *,
        source: str = "official",
        freshness_seconds: float | None = None,
    ) -> None:
        timestamp = observed_at.astimezone(UTC)
        self.ledger.record_iv_observation(
            underlying,
            timestamp,
            implied_volatility,
            source=source,
            freshness_seconds=freshness_seconds,
        )
        self.append(
            JournalEntry(
                timestamp=timestamp,
                event="iv_observation",
                payload={
                    "underlying": underlying,
                    "implied_volatility": implied_volatility,
                    "source": source,
                    "freshness_seconds": freshness_seconds,
                },
            )
        )
