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

    def scheduler_status(self, *, now: datetime | None = None) -> dict:
        """Return the latest durable scheduler heartbeat without contacting Alpaca."""
        heartbeat = self.ledger.latest_event("scheduler_heartbeat")
        if heartbeat is None:
            return {
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
        timestamp = datetime.fromisoformat(str(heartbeat["timestamp"]))
        timestamp = (
            timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
        )
        payload = heartbeat.get("payload") or {}
        interval_seconds = int(payload.get("interval_seconds") or 900)
        current = (now or datetime.now(UTC)).astimezone(UTC)
        age_seconds = max(0.0, (current - timestamp).total_seconds())
        status = str(payload.get("status") or "unknown")
        if status in {"running", "waiting"} and age_seconds > interval_seconds * 2 + 60:
            status = "stale"
        latest_entries = self.latest(1)
        return {
            "status": status,
            "last_heartbeat_at": timestamp.isoformat(),
            "age_seconds": round(age_seconds, 1),
            "interval_seconds": interval_seconds,
            "cycle_number": payload.get("cycle_number"),
            "last_cycle_status": payload.get("last_cycle_status"),
            "next_run_at": payload.get("next_run_at"),
            "last_error": payload.get("last_error"),
            "session_id": payload.get("session_id"),
            "process_id": payload.get("process_id"),
            "market_open": payload.get("market_open"),
            "last_cycle_started_at": payload.get("last_cycle_started_at"),
            "last_cycle_completed_at": payload.get("last_cycle_completed_at"),
            "last_successful_cycle_at": payload.get("last_successful_cycle_at"),
            "last_journal_timestamp": latest_entries[0].get("timestamp")
            if latest_entries
            else None,
        }

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
                if (
                    entry.get("event") not in {"dry_run_order", "plan_approval_required"}
                    or not raw_plan
                ):
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
        evidence: dict | None = None,
        opportunity_id: str | None = None,
        observed_at: datetime | None = None,
        plan_id: str | None = None,
        production_threshold: int = 70,
        exploration_threshold: int | None = None,
    ) -> int:
        observed_at = observed_at or datetime.now(UTC)
        payload = {
            "underlying": underlying,
            "classification": classification,
            "score": score,
            "regime": regime,
            "baseline_regime": baseline_regime,
            "score_threshold": score_threshold,
            "trade_mode": trade_mode,
            "opportunity_id": opportunity_id,
            "plan_id": plan_id,
            "production_threshold": production_threshold,
            "exploration_threshold": exploration_threshold,
            "data_timestamp": data_timestamp.isoformat() if data_timestamp else None,
            "reasons": reasons,
            "quote_timestamps": quote_timestamps,
            "spread": spread,
            "evidence": evidence or {},
        }
        candidate_id = self.ledger.record_shadow_candidate(observed_at=observed_at, **payload)
        payload["candidate_id"] = candidate_id
        self.append(JournalEntry(timestamp=observed_at, event="shadow_candidate", payload=payload))
        return candidate_id

    def link_candidate_plan(self, candidate_id: int, plan: TradePlan) -> bool:
        linked = self.ledger.link_candidate_plan(candidate_id, plan.plan_id)
        if linked:
            self.append(
                JournalEntry(
                    event="candidate_plan_linked",
                    payload={
                        "candidate_id": candidate_id,
                        "plan_id": plan.plan_id,
                        "client_order_id": plan.client_order_id,
                    },
                )
            )
        return linked

    def shadow_candidates(self, limit: int = 20) -> list[dict]:
        return self.ledger.shadow_candidates(limit)

    def record_risk_budget_rejection(
        self,
        *,
        candidate_id: int | None,
        underlying: str,
        score: int | None,
        trade_mode: str,
        diagnostic: dict,
    ) -> int:
        """Persist a rejected candidate with the exact non-mutating budget comparison."""
        observed_at = datetime.now(UTC)
        rejection_id = self.ledger.record_risk_budget_rejection(
            observed_at=observed_at,
            candidate_id=candidate_id,
            underlying=underlying,
            score=score,
            trade_mode=trade_mode,
            diagnostic=diagnostic,
        )
        self.append(
            JournalEntry(
                timestamp=observed_at,
                event="risk_budget_rejection",
                payload={
                    "rejection_id": rejection_id,
                    "candidate_id": candidate_id,
                    "underlying": underlying,
                    "score": score,
                    "trade_mode": trade_mode,
                    "diagnostic": diagnostic,
                },
            )
        )
        return rejection_id

    def risk_budget_rejections(self, limit: int = 20) -> list[dict]:
        return self.ledger.risk_budget_rejections(limit)

    def due_shadow_reprices(self, now: datetime) -> list[dict]:
        return self.ledger.due_shadow_reprices(now)

    def record_shadow_reprice(
        self,
        candidate_id: int,
        horizon_minutes: int,
        *,
        repriced_at: datetime,
        outcome_bucket: str,
        outcome: dict,
    ) -> bool:
        stored = self.ledger.record_shadow_reprice(
            candidate_id,
            horizon_minutes,
            repriced_at=repriced_at,
            outcome_bucket=outcome_bucket,
            outcome=outcome,
        )
        if stored:
            self.append(
                JournalEntry(
                    timestamp=repriced_at,
                    event="shadow_reprice",
                    payload={
                        "candidate_id": candidate_id,
                        "horizon_minutes": horizon_minutes,
                        "outcome_bucket": outcome_bucket,
                        "outcome": outcome,
                    },
                )
            )
        return stored

    def shadow_reprices(self, limit: int = 100) -> list[dict]:
        return self.ledger.shadow_reprices(limit)

    def shadow_session_report(self, limit: int = 10_000) -> dict:
        from .shadow_reporting import build_session_report

        session_date = datetime.now(UTC).date().isoformat()
        report = build_session_report(
            self.ledger.session_shadow_candidates(session_date, limit),
            self.ledger.session_shadow_reprices(session_date, limit * 3),
        )
        return {"session_date": session_date, **report}

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

    def record_entry_fill(
        self,
        plan: TradePlan,
        *,
        filled_price: float,
        source: str,
        filled_at: datetime | None = None,
        provider_order_id: str | None = None,
        fees_usd: float | None = None,
    ) -> bool:
        """Persist the actual paper fill once, for recovery and realized P&L."""
        if self._has_event("position_entry_filled", plan.client_order_id):
            return False
        timestamp = (filled_at or datetime.now(UTC)).astimezone(UTC)
        entry_slippage = round((filled_price - plan.limit_price) * 100 * plan.qty, 2)
        self.append(
            JournalEntry(
                timestamp=timestamp,
                event="position_entry_filled",
                plan=plan,
                payload={
                    "filled_price": filled_price,
                    "debit_paid_usd": round(filled_price * 100 * plan.qty, 2),
                    "contract_multiplier": 100,
                    "quantity": plan.qty,
                    "provider_order_id": provider_order_id,
                    "fees_usd": fees_usd,
                    "fees_status": "reported_by_provider"
                    if fees_usd is not None
                    else "not_reported_by_alpaca",
                    "entry_slippage_vs_approved_limit_usd": entry_slippage,
                    "source": source,
                },
            )
        )
        return True

    def entry_fill_for(self, client_order_id: str) -> dict | None:
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
                return entry
        return None

    def entry_debit_for(self, client_order_id: str) -> float | None:
        """Return the recorded actual entry debit, never an inferred market mark."""
        entry = self.entry_fill_for(client_order_id)
        try:
            return float((entry or {}).get("payload", {}).get("filled_price"))
        except (TypeError, ValueError):
            return None

    def exit_reason_for(self, exit_client_order_id: str) -> str | None:
        if not self.path.exists():
            return None
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                entry.get("event") in {"exit_submission_intent", "dry_run_exit_order"}
                and (entry.get("plan") or {}).get("client_order_id") == exit_client_order_id
            ):
                reason = (entry.get("payload") or {}).get("reason")
                return str(reason) if reason else None
        return None

    def position_excursions(self, client_order_id: str) -> tuple[float | None, float | None]:
        """Return observed quote-mark MAE/MFE; absence remains unknown, never zero."""
        if not self.path.exists():
            return None, None
        marks: list[float] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                entry.get("event") == "position_mark"
                and (entry.get("plan") or {}).get("client_order_id") == client_order_id
            ):
                try:
                    marks.append(float((entry.get("payload") or {}).get("unrealized_pnl")))
                except (TypeError, ValueError):
                    continue
        return (min(marks), max(marks)) if marks else (None, None)

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
                    "debit_paid_usd": entry_fill["payload"].get("debit_paid_usd"),
                    "exit_filled_at": exit_fill["timestamp"],
                    "exit_credit": exit_fill["payload"]["filled_price"],
                    "exit_reason": exit_fill["payload"]["reason"],
                    "credit_received_usd": exit_fill["payload"].get("credit_received_usd"),
                    "contract_multiplier": exit_fill["payload"].get("contract_multiplier", 100),
                    "provider_entry_order_id": entry_fill["payload"].get("provider_order_id"),
                    "provider_exit_order_id": exit_fill["payload"].get("provider_order_id"),
                    "entry_fees_usd": exit_fill["payload"].get("entry_fees_usd"),
                    "exit_fees_usd": exit_fill["payload"].get("exit_fees_usd"),
                    "total_fees_usd": exit_fill["payload"].get("total_fees_usd"),
                    "fees_status": exit_fill["payload"].get("fees_status"),
                    "slippage_vs_limits_usd": exit_fill["payload"].get("slippage_vs_limits_usd"),
                    "maximum_adverse_excursion_usd": exit_fill["payload"].get(
                        "maximum_adverse_excursion_usd"
                    ),
                    "maximum_favorable_excursion_usd": exit_fill["payload"].get(
                        "maximum_favorable_excursion_usd"
                    ),
                    "realized_pnl_before_fees": exit_fill["payload"].get(
                        "realized_pnl_before_fees"
                    ),
                    "realized_pnl_after_fees": exit_fill["payload"].get("realized_pnl_after_fees"),
                    # Backward-compatible alias: fill-to-fill realized P&L before
                    # unreported fees, never hypothetical quote P&L.
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

    def latest_iv_observation(
        self, underlying: str, *, as_of: datetime | None = None
    ) -> tuple[datetime, float] | None:
        return self.ledger.latest_iv_observation(underlying, as_of=as_of)

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

    def iv_observation_history(
        self, underlying: str, *, as_of: datetime | None = None, limit: int = 252
    ) -> list[float]:
        return self.ledger.iv_observation_history(underlying, as_of=as_of, limit=limit)
