from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from httpx import HTTPError

from .alpaca_api import AlpacaRESTClient
from .committee import (
    AdversarialRiskAgent,
    ExecutionAgent,
    RiskBudgetAllocator,
    StructureVolatilityAgent,
)
from .config import Settings
from .execution import PaperExecutionAgent
from .models import GateResult, JournalEntry, OptionLeg, PositionIntent, Side, Thesis, TradePlan
from .monitoring import OrderLifecycle, PositionGuardian
from .risk import DeterministicRiskGate
from .scanner import OpportunityScanner, ScanResult
from .strategy.spread_builder import position_size
from .thesis import DeterministicThesisAgent, OpenAIThesisAgent, ThesisAgent


class AutonomousCycle:
    """Paper-only orchestration; deterministic scan always precedes an optional thesis."""

    def __init__(
        self,
        settings: Settings,
        executor: PaperExecutionAgent,
        *,
        now: Callable[[], datetime] | None = None,
    ):
        self.settings = settings
        self.alpaca = AlpacaRESTClient(settings)
        self.scanner = OpportunityScanner(
            settings, self.alpaca, iv_store=getattr(executor, "journal", None)
        )
        self.risk_gate = DeterministicRiskGate(settings)
        self.executor = executor
        self._thesis_agent: ThesisAgent | None = None
        self.structure_agent = StructureVolatilityAgent()
        self.adversarial_risk_agent = AdversarialRiskAgent()
        self.allocator = RiskBudgetAllocator()
        self.execution_agent = ExecutionAgent()
        self._now = now or (lambda: datetime.now(UTC))

    async def run_read_only(self) -> dict[str, Any]:
        """Verify account/data access without OpenAI calls or any order submission."""
        account, clock, positions = await self._account_state()
        scans = [await self.scanner.scan(underlying) for underlying in self.settings.universe]
        return {
            "mode": "read_only",
            "paper_only": self.settings.alpaca_paper_trade,
            "execution_enabled": self.settings.allow_order_execution,
            "account": {
                "status": account.get("status"),
                "equity": account.get("equity"),
                "buying_power": account.get("buying_power"),
            },
            "market_open": bool(clock.get("is_open")),
            "open_positions": len(positions),
            "scans": [self._serialize_scan(scan) for scan in scans],
        }

    async def reconcile_orders(self, lifecycle: OrderLifecycle) -> dict[str, Any]:
        """Read current paper-order state after a stream reconnect; never submits an order."""
        states = lifecycle.reconcile(await self.alpaca.orders())
        return {
            "mode": "read_only_reconciliation",
            "orders_seen": len(states),
            "states": [
                {
                    "client_order_id": state.client_order_id,
                    "status": state.status,
                    "filled_qty": state.filled_qty,
                }
                for state in states
            ],
        }

    async def manage_open_spreads(self) -> dict[str, Any]:
        """Evaluate filled tracked spreads and submit only deterministic close orders."""
        _, clock, _ = await self._account_state()
        if not bool(clock.get("is_open")):
            return {"status": "market_closed", "managed": []}
        guardian = PositionGuardian()
        managed: list[dict[str, Any]] = []
        for order in await self.alpaca.orders():
            if str(order.get("status")) != "filled":
                continue
            client_order_id = str(order.get("client_order_id") or "")
            if not client_order_id or self.executor.journal.has_exit_for(client_order_id):
                continue
            plan = self.executor.journal.plan_for_client_order_id(client_order_id)
            if plan is None or plan.is_closing or plan.strategy != "debit_spread":
                continue
            entry_debit = self._recorded_entry_debit(plan, order)
            snapshots = await self.alpaca.option_snapshots(plan.underlying)
            credit = self._executable_exit_credit(plan, snapshots)
            if credit is None:
                managed.append({"client_order_id": client_order_id, "status": "no_quote"})
                continue
            unrealized_pnl = round((credit - entry_debit) * 100 * plan.qty, 2)
            self.executor.journal.append(
                JournalEntry(
                    event="position_mark",
                    plan=plan,
                    payload={
                        "entry_debit": entry_debit,
                        "executable_exit_credit": credit,
                        "unrealized_pnl": unrealized_pnl,
                        "costs_usd": None,
                        "pnl_after_costs": None,
                    },
                )
            )
            entered_at = self._order_timestamp(order.get("filled_at"))
            expiration = datetime.fromisoformat(plan.candidate.expiration).replace(tzinfo=UTC)
            decision = guardian.evaluate(
                entry_debit=entry_debit,
                executable_exit_value=credit,
                entered_at=entered_at,
                expiration=expiration,
                now=self._now(),
            )
            if decision.action == "hold":
                managed.append(
                    {
                        "client_order_id": client_order_id,
                        "status": "hold",
                        "reason": decision.reason,
                    }
                )
                continue
            exit_plan = guardian.closing_plan(plan, executable_exit_value=credit)
            exit_gate = GateResult(
                approved=self.settings.alpaca_paper_trade and bool(clock.get("is_open")),
                reasons=["paper account, open market, tracked legs, and fresh exit quotes passed"],
            )
            result = await self.executor.submit_exit(
                exit_plan, reason=decision.reason, safety_gate=exit_gate
            )
            managed.append(
                {
                    "client_order_id": client_order_id,
                    "status": result["status"],
                    "reason": decision.reason,
                    "exit_client_order_id": exit_plan.client_order_id,
                }
            )
        return {"status": "ok", "managed": managed}

    def _recorded_entry_debit(self, plan: TradePlan, order: dict) -> float:
        recorded = self.executor.journal.entry_debit_for(plan.client_order_id)
        if recorded is not None:
            return recorded
        try:
            filled_price = abs(float(order.get("filled_avg_price")))
        except (TypeError, ValueError):
            filled_price = plan.limit_price
        self.executor.journal.record_entry_fill(
            plan,
            filled_price=filled_price,
            source="rest_reconcile",
            filled_at=self._order_timestamp(order.get("filled_at")),
            provider_order_id=str(order.get("id")) if order.get("id") is not None else None,
            fees_usd=self._provider_fees(order),
        )
        return filled_price

    @staticmethod
    def _provider_fees(order: dict[str, Any]) -> float | None:
        for key in ("commission", "fees", "fee"):
            value = order.get(key)
            if value is None:
                continue
            try:
                return abs(float(value))
            except (TypeError, ValueError):
                return None
        return None

    async def run_once(self) -> dict[str, Any]:
        account, clock, positions = await self._account_state()
        if not bool(clock.get("is_open")):
            return {
                "status": "no_trade",
                "reason": "market_closed",
                "paper_only": self.settings.alpaca_paper_trade,
            }
        shadow_reprices = await self.reprice_shadow_candidates()
        scans = [await self.scanner.scan(underlying) for underlying in self.settings.universe]
        candidate_ids = {scan.underlying: self._record_shadow_candidate(scan) for scan in scans}
        eligible_scans = self._eligible_scans(scans)
        if self.settings.exploration_mode and positions:
            return {
                "status": "no_trade",
                "reason": "exploration_open_position_limit",
                "open_positions": len(positions),
                "shadow_reprices": shadow_reprices,
            }
        aggregate_budget = (
            float(account.get("equity", 0)) * self.settings.risk_fraction_per_trade * 3
        )
        buying_power = float(account.get("buying_power", 0))
        equity = float(account.get("equity", 0))
        candidates: list[tuple[ScanResult, float]] = []
        risk_budget_rejections: list[dict[str, Any]] = []
        for scan in eligible_scans:
            if scan.spread is None or scan.opportunity is None:
                continue
            diagnostic = self._risk_budget_diagnostic(
                required_max_loss_usd=scan.spread.max_loss_per_contract,
                equity=equity,
                buying_power=buying_power,
                remaining_portfolio_risk_budget_usd=aggregate_budget,
            )
            if diagnostic["failed_comparisons"]:
                risk_budget_rejections.append(
                    self._record_risk_budget_rejection(
                        scan, candidate_ids.get(scan.underlying), diagnostic
                    )
                )
                continue
            candidates.append((scan, scan.spread.max_loss_per_contract))
        allocations = self.allocator.allocate(candidates, risk_budget_usd=aggregate_budget)
        allocated_underlyings = {allocation.underlying for allocation in allocations}
        remaining_after_allocations = aggregate_budget - sum(
            allocation.max_loss_usd for allocation in allocations
        )
        for scan, required_max_loss_usd in candidates:
            if scan.underlying in allocated_underlyings:
                continue
            diagnostic = self._risk_budget_diagnostic(
                required_max_loss_usd=required_max_loss_usd,
                equity=equity,
                buying_power=buying_power,
                remaining_portfolio_risk_budget_usd=remaining_after_allocations,
            )
            if diagnostic["failed_comparisons"]:
                risk_budget_rejections.append(
                    self._record_risk_budget_rejection(
                        scan, candidate_ids.get(scan.underlying), diagnostic
                    )
                )
        if not allocations:
            payload = {
                "status": "no_trade",
                "reason": (
                    "risk budget cannot fund one spread"
                    if risk_budget_rejections
                    else "no ETF passed deterministic scan and budget rules"
                ),
                "shadow_reprices": shadow_reprices,
            }
            if risk_budget_rejections:
                payload["risk_budget_rejections"] = risk_budget_rejections
            return payload
        selected = next(
            scan for scan in eligible_scans if scan.underlying == allocations[0].underlying
        )
        assert selected.spread is not None and selected.opportunity is not None
        reviews = [
            self.structure_agent.review(selected.spread),
            self.adversarial_risk_agent.review(selected.spread),
        ]
        execution_choice = self.execution_agent.choose(
            market_open=bool(clock.get("is_open")), reviews=reviews
        )
        if execution_choice != "limit":
            return {
                "status": "no_trade",
                "reason": execution_choice,
                "scan": self._serialize_scan(selected),
                "reviews": [review.__dict__ for review in reviews],
            }
        thesis = await self._thesis().evaluate(selected.opportunity)
        self.executor.journal.append(
            JournalEntry(
                event="thesis_advisory",
                payload={
                    "agent_action": thesis.action,
                    "confidence": thesis.confidence,
                    "candidate_symbol": thesis.candidate_symbol,
                    "rationale": thesis.rationale,
                    "invalidation": thesis.invalidation,
                    "deterministic_candidate_status": "passed_pre_plan_gates",
                },
            )
        )
        plan = self._plan_from_spread(selected, self._execution_thesis(thesis), equity)
        if plan is None:
            diagnostic = self._risk_budget_diagnostic(
                required_max_loss_usd=selected.spread.max_loss_per_contract,
                equity=equity,
                buying_power=buying_power,
                remaining_portfolio_risk_budget_usd=aggregate_budget,
            )
            rejection = self._record_risk_budget_rejection(
                selected, candidate_ids.get(selected.underlying), diagnostic
            )
            return {
                "status": "no_trade",
                "reason": "risk budget cannot fund one spread",
                "risk_budget_rejections": [rejection],
            }
        selected_candidate_id = candidate_ids.get(selected.underlying)
        if selected_candidate_id is not None:
            self.executor.journal.link_candidate_plan(selected_candidate_id, plan)
        gate = self.risk_gate.assess(
            plan,
            market_open=bool(clock.get("is_open")),
            open_positions=len(positions),
            buying_power=buying_power,
        )
        if gate.approved:
            self.executor.journal.register_shadow(
                plan,
                regime=selected.execution_regime
                or (selected.score.regime.value if selected.score else "unknown"),
            )
        result = await self.executor.submit(plan, gate)
        payload = {
            "underlying": selected.underlying,
            "scan": self._serialize_scan(selected),
            "reviews": [review.__dict__ for review in reviews],
            "plan": plan.model_dump(mode="json"),
            "gate": gate.model_dump(),
            "result": result,
            "shadow_reprices": shadow_reprices,
        }
        if result["status"] in {"approval_required", "dry_run", "observe_only"}:
            payload["order_preview"] = self._order_preview(selected, plan, gate)
        return payload

    @staticmethod
    def _execution_thesis(advisory: Thesis) -> Thesis:
        """Normalize an optional model assessment so it cannot approve or veto a plan."""
        if advisory.action == "trade":
            return advisory
        rationale = (
            "Deterministic scanner, spread validation, and risk reviews passed. "
            "Advisory model expressed caution: "
            f"{advisory.rationale}"
        )[:800]
        return advisory.model_copy(update={"action": "trade", "rationale": rationale})

    def _risk_budget_diagnostic(
        self,
        *,
        required_max_loss_usd: float,
        equity: float,
        buying_power: float,
        remaining_portfolio_risk_budget_usd: float,
    ) -> dict[str, Any]:
        """Return the exact checks used before a debit spread can be sized.

        This is deliberately informational: it never adjusts limits, account
        values, or candidate structures. The effective per-trade cap is the
        lower of the configured hard cap and the equity-derived risk amount.
        """
        required = round(required_max_loss_usd, 2)
        configured = round(self.settings.max_trade_risk_usd, 2)
        equity_derived = round(equity * self.settings.risk_fraction_per_trade, 2)
        effective = round(min(configured, equity_derived), 2)
        available_buying_power = round(buying_power, 2)
        remaining = round(max(remaining_portfolio_risk_budget_usd, 0), 2)
        failed: list[str] = []
        if required > effective:
            failed.append(
                f"required_max_loss_usd (${required:.2f}) > effective_maximum_risk_per_trade_usd (${effective:.2f})"
            )
        if required > available_buying_power:
            failed.append(
                f"required_max_loss_usd (${required:.2f}) > available_alpaca_buying_power_usd (${available_buying_power:.2f})"
            )
        if required > remaining:
            failed.append(
                f"required_max_loss_usd (${required:.2f}) > remaining_portfolio_risk_budget_usd (${remaining:.2f})"
            )
        return {
            "required_max_loss_usd": required,
            "configured_maximum_risk_per_trade_usd": configured,
            "equity_derived_risk_per_trade_usd": equity_derived,
            "effective_maximum_risk_per_trade_usd": effective,
            "available_alpaca_buying_power_usd": available_buying_power,
            "remaining_portfolio_risk_budget_usd": remaining,
            "failed_comparisons": failed,
        }

    def _record_risk_budget_rejection(
        self, scan: ScanResult, candidate_id: int | None, diagnostic: dict[str, Any]
    ) -> dict[str, Any]:
        self.executor.journal.record_risk_budget_rejection(
            candidate_id=candidate_id,
            underlying=scan.underlying,
            score=scan.score.score if scan.score else None,
            trade_mode="exploration" if self.settings.exploration_mode else "production",
            diagnostic=diagnostic,
        )
        return {"underlying": scan.underlying, "candidate_id": candidate_id, **diagnostic}

    async def reprice_shadow_candidates(self) -> list[dict[str, Any]]:
        """Record due 15/30/60-minute evidence marks without touching execution.

        These are conservative ask-to-enter/bid-to-exit counterfactuals, never
        fills, orders, or realized paper P&L.
        """
        now = self._now()
        results: list[dict[str, Any]] = []
        for candidate in self.executor.journal.due_shadow_reprices(now):
            spread = candidate["spread"]
            symbols = [spread["long_symbol"], spread["short_symbol"]]
            if candidate.get("deadline_status") == "overdue":
                outcome = {
                    "status": "unavailable",
                    "hypothetical": True,
                    "reason": "reprice deadline passed before the worker observed a valid quote",
                    "due_at": candidate.get("due_at"),
                }
            else:
                try:
                    snapshots = await self.alpaca.option_snapshots(
                        candidate["underlying"], symbols=symbols
                    )
                    outcome = self._hypothetical_reprice(spread, snapshots, now)
                except (HTTPError, RuntimeError) as exc:
                    # Shadow evidence must fail closed per candidate. A bad
                    # response is useful evidence, never a priced outcome.
                    outcome = {
                        "status": "unavailable",
                        "hypothetical": True,
                        "reason": f"exit quote retrieval failed: {type(exc).__name__}",
                    }
            bucket = self._outcome_bucket(candidate)
            stored = self.executor.journal.record_shadow_reprice(
                int(candidate["candidate_id"]),
                int(candidate["horizon_minutes"]),
                repriced_at=now,
                outcome_bucket=bucket,
                outcome=outcome,
            )
            results.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "horizon_minutes": candidate["horizon_minutes"],
                    "stored": stored,
                    "outcome_bucket": bucket,
                    "status": outcome["status"],
                }
            )
        return results

    def _eligible_scans(self, scans: list[ScanResult]) -> list[ScanResult]:
        """Return production candidates or the opt-in exploration candidates.

        Exploration deliberately reuses the baseline score and the production
        spread builder. It only broadens the acceptance threshold after all
        quote, liquidity, DTE, IV, and defined-risk checks have already passed.
        """
        if not self.settings.exploration_mode:
            return [
                scan for scan in scans if scan.spread is not None and scan.opportunity is not None
            ]
        eligible: list[ScanResult] = []
        for scan in scans:
            if (
                scan.score is None
                or abs(scan.score.score) < self.settings.exploration_score_threshold
            ):
                continue
            if scan.spread is not None and scan.opportunity is not None:
                eligible.append(
                    replace(
                        scan,
                        execution_regime=f"{scan.spread.regime.value}_exploration",
                    )
                )
                continue
            if scan.shadow_spread is not None and scan.shadow_opportunity is not None:
                eligible.append(
                    replace(
                        scan,
                        spread=scan.shadow_spread,
                        opportunity=scan.shadow_opportunity,
                        reasons=(),
                        execution_regime=f"{scan.shadow_spread.regime.value}_exploration",
                    )
                )
        return eligible

    async def _account_state(self) -> tuple[dict, dict, list[dict]]:
        account, clock, positions = (
            await self.alpaca.account(),
            await self.alpaca.clock(),
            await self.alpaca.positions(),
        )
        return account, clock, positions

    def _thesis(self) -> ThesisAgent:
        if self._thesis_agent is None:
            self._thesis_agent = (
                OpenAIThesisAgent(self.settings)
                if self.settings.openai_api_key
                else DeterministicThesisAgent()
            )
        return self._thesis_agent

    def _plan_from_spread(
        self, scan: ScanResult, thesis: Thesis, equity: float
    ) -> TradePlan | None:
        assert scan.spread is not None and scan.opportunity is not None
        spread = scan.spread
        quantity = min(
            self.settings.max_contracts_per_trade,
            position_size(
                equity=equity,
                max_loss_per_contract=spread.max_loss_per_contract,
                risk_fraction=self.settings.risk_fraction_per_trade,
                hard_max_risk=self.settings.max_trade_risk_usd,
            ),
        )
        if quantity < 1:
            return None
        if self.settings.exploration_mode:
            quantity = 1
        return TradePlan(
            underlying=scan.underlying,
            trade_mode="exploration" if self.settings.exploration_mode else "production",
            score_threshold=(
                self.settings.exploration_score_threshold if self.settings.exploration_mode else 70
            ),
            strategy="debit_spread",
            legs=[
                OptionLeg(
                    symbol=spread.long_leg.symbol,
                    side=Side.BUY,
                    position_intent=PositionIntent.BUY_TO_OPEN,
                ),
                OptionLeg(
                    symbol=spread.short_leg.symbol,
                    side=Side.SELL,
                    position_intent=PositionIntent.SELL_TO_OPEN,
                ),
            ],
            qty=quantity,
            limit_price=spread.debit,
            max_loss_usd=spread.max_loss_per_contract * quantity,
            candidate=scan.opportunity.candidate,
            thesis=thesis,
            approval_expires_at=datetime.now(UTC)
            + timedelta(seconds=self.settings.plan_approval_ttl_seconds),
            quote_timestamps=[
                timestamp
                for timestamp in (
                    spread.long_leg.quote_timestamp,
                    spread.short_leg.quote_timestamp,
                )
                if timestamp
            ],
        )

    async def submit_approved_plan(self, plan_id: str) -> dict[str, Any]:
        """Submit the exact, unexpired plan previously produced by dry run.

        This deliberately does not scan again: a later scanner pass could pick
        different legs or a different debit. Current account/market gates are
        re-evaluated immediately before the one permitted MCP submission.
        """
        plan = self.executor.journal.approved_plan(plan_id)
        account, clock, positions = await self._account_state()
        deterministic_gate = self.risk_gate.assess(
            plan,
            market_open=bool(clock.get("is_open")),
            open_positions=len(positions),
            buying_power=float(account.get("buying_power", 0)),
        )
        quote_evidence: dict[str, Any] = {}
        quote_reasons: list[str] = []
        try:
            snapshots = await self.alpaca.option_snapshots(
                plan.underlying, symbols=[leg.symbol for leg in plan.legs]
            )
            quote_reasons, quote_evidence = self._approval_quote_review(
                plan, snapshots, self._now()
            )
        except (HTTPError, OSError, RuntimeError, TimeoutError) as exc:
            quote_reasons = [f"fresh exact-leg quote retrieval failed: {type(exc).__name__}"]
        reasons = (
            [] if deterministic_gate.approved else deterministic_gate.reasons
        ) + quote_reasons
        gate = GateResult(
            approved=deterministic_gate.approved and not quote_reasons,
            reasons=reasons or ["all deterministic and fresh exact-leg checks passed"],
        )
        self.executor.journal.append(
            JournalEntry(
                event="approved_plan_revalidated",
                plan=plan,
                gate=gate,
                payload=quote_evidence,
            )
        )
        result = await self.executor.submit_approved(plan, gate)
        return {
            "plan_id": plan.plan_id,
            "plan": plan.model_dump(mode="json"),
            "gate": gate.model_dump(),
            "quote_revalidation": quote_evidence,
            "result": result,
        }

    def _approval_quote_review(
        self, plan: TradePlan, snapshots: dict[str, dict], now: datetime
    ) -> tuple[list[str], dict[str, Any]]:
        quotes: dict[str, dict[str, Any]] = {}
        reasons: list[str] = []
        for leg in plan.legs:
            snapshot = snapshots.get(leg.symbol) or {}
            quote = self._snapshot_quote(
                snapshot,
                now,
                max_age_seconds=self.settings.max_execution_quote_age_seconds,
            )
            if quote is None:
                reasons.append(
                    f"{leg.symbol} fresh quote {self._quote_failure_reason(snapshot, now, max_age_seconds=self.settings.max_execution_quote_age_seconds)}"
                )
                continue
            midpoint = (quote["bid"] + quote["ask"]) / 2
            spread_pct = (quote["ask"] - quote["bid"]) / midpoint if midpoint else 1.0
            quote["spread_pct"] = round(spread_pct, 6)
            if spread_pct > self.settings.max_bid_ask_spread_pct:
                reasons.append(
                    f"{leg.symbol} bid-ask spread {spread_pct:.4f} exceeds {self.settings.max_bid_ask_spread_pct:.4f}"
                )
            quotes[leg.symbol] = quote
        fresh_debit: float | None = None
        debit_change_pct: float | None = None
        if len(quotes) == 2:
            long_leg = next(leg for leg in plan.legs if leg.side is Side.BUY)
            short_leg = next(leg for leg in plan.legs if leg.side is Side.SELL)
            fresh_debit = round(quotes[long_leg.symbol]["ask"] - quotes[short_leg.symbol]["bid"], 4)
            if fresh_debit <= 0 or (
                plan.spread_width is not None and fresh_debit >= plan.spread_width
            ):
                reasons.append("fresh exact-leg quotes no longer form a valid debit spread")
            else:
                debit_change_pct = abs(fresh_debit - plan.limit_price) / plan.limit_price
                if debit_change_pct > self.settings.max_plan_debit_change_pct:
                    reasons.append(
                        f"fresh debit change {debit_change_pct:.4f} exceeds configured tolerance {self.settings.max_plan_debit_change_pct:.4f}"
                    )
        evidence = {
            "exact_plan_id": plan.plan_id,
            "exact_leg_symbols": [leg.symbol for leg in plan.legs],
            "approved_limit_debit": plan.limit_price,
            "fresh_conservative_debit": fresh_debit,
            "debit_change_pct": round(debit_change_pct, 6)
            if debit_change_pct is not None
            else None,
            "maximum_debit_change_pct": self.settings.max_plan_debit_change_pct,
            "maximum_quote_age_seconds": self.settings.max_execution_quote_age_seconds,
            "quotes": quotes,
        }
        return reasons, evidence

    def _executable_exit_credit(self, plan: TradePlan, snapshots: dict[str, dict]) -> float | None:
        quotes: dict[str, dict] = {}
        for leg in plan.legs:
            quote = self._snapshot_quote(
                snapshots.get(leg.symbol) or {},
                self._now(),
                max_age_seconds=self.settings.max_execution_quote_age_seconds,
            )
            if not quote:
                return None
            quotes[leg.symbol] = quote
        long_leg = next(leg for leg in plan.legs if leg.side is Side.BUY)
        short_leg = next(leg for leg in plan.legs if leg.side is Side.SELL)
        long_bid = float(quotes[long_leg.symbol]["bid"])
        short_ask = float(quotes[short_leg.symbol]["ask"])
        credit = round(long_bid - short_ask, 4)
        return credit if credit > 0 else None

    @staticmethod
    def _order_timestamp(value: object) -> datetime:
        if not value:
            return datetime.now(UTC)
        parsed = datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    @staticmethod
    def _serialize_scan(scan: ScanResult) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "underlying": scan.underlying,
            "score": scan.score.score if scan.score else None,
            "regime": scan.execution_regime
            or (scan.score.regime.value if scan.score else "no_trade"),
            "confidence": round(abs(scan.score.score) / 100, 2) if scan.score else None,
            "data_timestamp": scan.data_timestamp.isoformat() if scan.data_timestamp else None,
            "reasons": list(scan.reasons),
        }
        if scan.execution_regime and scan.score:
            payload["baseline_regime"] = scan.score.regime.value
        if scan.surface_features:
            payload["surface_features"] = scan.surface_features.as_dict()
        if scan.spread:
            payload["spread"] = AutonomousCycle._spread_payload(scan.spread)
        if scan.shadow_spread and scan.shadow_spread != scan.spread:
            payload["shadow_candidate"] = AutonomousCycle._spread_payload(scan.shadow_spread)
        return payload

    def _record_shadow_candidate(self, scan: ScanResult) -> int:
        spread = scan.shadow_spread or scan.spread
        exploration_threshold_passed = (
            self.settings.exploration_mode
            and scan.score is not None
            and bool(scan.score.score)
            and abs(scan.score.score) >= self.settings.exploration_score_threshold
        )
        exploration_eligible = exploration_threshold_passed and spread is not None
        if scan.score is None:
            classification = "data_unavailable"
            reasons = list(scan.reasons)
        elif exploration_threshold_passed and spread is None:
            classification = "exploration_rejected_no_valid_spread"
            reasons = self._exploration_reasons(scan, valid_spread=False)
        elif scan.score.regime.value == "neutral":
            if not scan.score.score:
                classification = "directionless"
            elif exploration_eligible:
                classification = "exploration_eligible"
            else:
                classification = "below_threshold"
            reasons = (
                self._exploration_reasons(scan)
                if exploration_eligible
                else list(scan.score.reasons)
            )
        elif spread is None:
            classification = "rejected_spread"
            reasons = list(scan.reasons)
        else:
            classification = "qualifying_candidate"
            reasons = []
        quote_timestamps = (
            [
                timestamp
                for timestamp in (
                    spread.long_leg.quote_timestamp,
                    spread.short_leg.quote_timestamp,
                )
                if timestamp
            ]
            if spread
            else []
        )
        execution_regime = (
            f"{'bullish' if scan.score.score > 0 else 'bearish'}_exploration"
            if exploration_threshold_passed and scan.score is not None
            else scan.score.regime.value
            if scan.score
            else "no_trade"
        )
        opportunity_id = self._opportunity_id(scan, spread, execution_regime)
        return self.executor.journal.record_shadow_candidate(
            underlying=scan.underlying,
            classification=classification,
            score=scan.score.score if scan.score else None,
            regime=execution_regime,
            baseline_regime=scan.score.regime.value if scan.score else "no_trade",
            score_threshold=(
                self.settings.exploration_score_threshold if self.settings.exploration_mode else 70
            ),
            trade_mode="exploration" if self.settings.exploration_mode else "production",
            data_timestamp=scan.data_timestamp,
            reasons=reasons,
            quote_timestamps=quote_timestamps,
            spread=self._spread_payload(spread) if spread else None,
            evidence=self._candidate_evidence(scan, reasons, spread),
            opportunity_id=opportunity_id,
            observed_at=self._now(),
            production_threshold=70,
            exploration_threshold=self.settings.exploration_score_threshold,
        )

    def _opportunity_id(self, scan: ScanResult, spread, execution_regime: str) -> str:
        """Group continuing scans only when their executable directional legs match."""
        legs = (
            f"{spread.long_leg.symbol}:{spread.short_leg.symbol}"
            if spread is not None
            else "no_valid_spread"
        )
        mode = "exploration" if self.settings.exploration_mode else "production"
        key = f"{scan.underlying}|{mode}|{execution_regime}|{legs}"
        return f"opp-{sha256(key.encode()).hexdigest()[:20]}"

    def _candidate_evidence(self, scan: ScanResult, reasons: list[str], spread) -> dict[str, Any]:
        score = scan.score
        inputs = scan.signal_inputs
        return {
            "score_components": (
                {
                    "daily_regime": score.daily_regime,
                    "intraday_trend": score.intraday_trend,
                    "volume_confirmation": score.volume_confirmation,
                    "volatility_state": score.volatility_state,
                    "market_alignment": score.market_alignment,
                    "agreeing_components": score.agreeing_components,
                }
                if score
                else None
            ),
            "rejection_gates": reasons,
            "rationale": reasons or ["candidate passed scanner and spread construction"],
            "production_threshold": 70,
            "exploration_threshold": self.settings.exploration_score_threshold,
            "underlying_price": inputs.price if inputs else None,
            "volume_ratio": inputs.volume_ratio if inputs else None,
            "realized_volatility": inputs.realized_volatility if inputs else None,
            "implied_volatility": inputs.implied_volatility if inputs else None,
            "candidate_spread_available": spread is not None,
            "option_surface": scan.surface_features.as_dict() if scan.surface_features else None,
            "fee_assumption_per_contract_usd": self.settings.shadow_fee_per_contract_usd,
            "slippage_assumption_per_leg_usd": self.settings.shadow_slippage_per_leg_usd,
        }

    def _exploration_reasons(self, scan: ScanResult, *, valid_spread: bool = True) -> list[str]:
        assert scan.score is not None
        production_threshold_reasons = {
            "below 70",
            "score or agreement threshold was not met",
        }
        retained = []
        for reason in [*scan.score.reasons, *scan.reasons]:
            if reason not in production_threshold_reasons and reason not in retained:
                retained.append(reason)
        return [
            *retained,
            (
                "production baseline remains neutral below its fixed 70-point threshold"
                if scan.score.regime.value == "neutral"
                else f"production baseline regime remains {scan.score.regime.value}"
            ),
            (
                "exploration threshold "
                f"{self.settings.exploration_score_threshold} accepted the quote-backed directional candidate"
                if valid_spread
                else (
                    "exploration threshold "
                    f"{self.settings.exploration_score_threshold} passed but no valid "
                    "defined-risk spread was available"
                )
            ),
        ]

    @staticmethod
    def _spread_payload(spread) -> dict[str, Any]:
        return {
            "long_symbol": spread.long_leg.symbol,
            "short_symbol": spread.short_leg.symbol,
            "option_type": spread.long_leg.option_type,
            "expiration": spread.long_leg.expiration,
            "long_strike": spread.long_leg.strike,
            "short_strike": spread.short_leg.strike,
            "debit": spread.debit,
            "width": spread.width,
            "max_loss_per_contract": spread.max_loss_per_contract,
            "max_profit_per_contract": round((spread.width - spread.debit) * 100, 2),
            "breakeven": round(
                spread.long_leg.strike + spread.debit
                if spread.regime.value == "bullish"
                else spread.long_leg.strike - spread.debit,
                4,
            ),
            "iv_source": spread.long_leg.iv_source,
            "long_quote_timestamp": spread.long_leg.quote_timestamp,
            "short_quote_timestamp": spread.short_leg.quote_timestamp,
            "long_bid": spread.long_leg.bid,
            "long_ask": spread.long_leg.ask,
            "long_mid": spread.long_leg.midpoint,
            "long_bid_ask_spread_pct": spread.long_leg.spread_pct,
            "long_iv": spread.long_leg.implied_volatility,
            "long_dte": spread.long_leg.dte,
            "long_volume": spread.long_leg.volume,
            "long_open_interest": spread.long_leg.open_interest,
            "short_bid": spread.short_leg.bid,
            "short_ask": spread.short_leg.ask,
            "short_mid": spread.short_leg.midpoint,
            "short_bid_ask_spread_pct": spread.short_leg.spread_pct,
            "short_iv": spread.short_leg.implied_volatility,
            "short_dte": spread.short_leg.dte,
            "short_volume": spread.short_leg.volume,
            "short_open_interest": spread.short_leg.open_interest,
            # This is an executable quote estimate, not an actual fill.
            "entry_quote": spread.debit,
            "exit_quote": None,
            "costs_usd": None,
            "pnl_usd": None,
        }

    def _hypothetical_reprice(
        self, spread: dict[str, Any], snapshots: dict[str, dict], now: datetime
    ) -> dict[str, Any]:
        long_quote = self._snapshot_quote(snapshots.get(spread["long_symbol"]) or {}, now)
        short_quote = self._snapshot_quote(snapshots.get(spread["short_symbol"]) or {}, now)
        if long_quote is None or short_quote is None:
            unavailable_legs = []
            if long_quote is None:
                unavailable_legs.append(
                    f"long exit quote {self._quote_failure_reason(snapshots.get(spread['long_symbol']) or {}, now)}"
                )
            if short_quote is None:
                unavailable_legs.append(
                    f"short exit quote {self._quote_failure_reason(snapshots.get(spread['short_symbol']) or {}, now)}"
                )
            return {
                "status": "unavailable",
                "reason": "; ".join(unavailable_legs),
                "hypothetical": True,
            }
        exit_credit = round(long_quote["bid"] - short_quote["ask"], 4)
        if exit_credit <= 0:
            return {
                "status": "unavailable",
                "reason": "conservative bid-to-exit credit is non-positive",
                "hypothetical": True,
                "long_exit_bid": long_quote["bid"],
                "short_exit_ask": short_quote["ask"],
            }
        entry_debit = float(spread["entry_quote"])
        fees = self.settings.shadow_fee_per_contract_usd
        slippage = self.settings.shadow_slippage_per_leg_usd * 4
        gross_pnl = round((exit_credit - entry_debit) * 100, 2)
        total_costs = round(fees + slippage, 2)
        return {
            "status": "priced",
            "hypothetical": True,
            "entry_method": "opening long ask minus short bid",
            "exit_method": "closing long bid minus short ask",
            "entry_debit": entry_debit,
            "exit_credit": exit_credit,
            "gross_hypothetical_pnl": gross_pnl,
            "fees_usd": fees,
            "slippage_usd": slippage,
            "total_costs_usd": total_costs,
            "net_hypothetical_pnl": round(gross_pnl - total_costs, 2),
            "long_exit_bid": long_quote["bid"],
            "long_exit_ask": long_quote["ask"],
            "short_exit_bid": short_quote["bid"],
            "short_exit_ask": short_quote["ask"],
            "long_quote_timestamp": long_quote["timestamp"],
            "short_quote_timestamp": short_quote["timestamp"],
        }

    @staticmethod
    def _snapshot_quote(
        snapshot: dict[str, Any], now: datetime, *, max_age_seconds: int = 900
    ) -> dict[str, Any] | None:
        quote = snapshot.get("latestQuote") or snapshot.get("latest_quote") or {}
        timestamp = quote.get("t") or quote.get("timestamp")
        try:
            bid = float(quote.get("bp", quote.get("bid_price", 0)))
            ask = float(quote.get("ap", quote.get("ask_price", 0)))
        except (TypeError, ValueError):
            return None
        if not timestamp or bid <= 0 or ask <= bid:
            return None
        try:
            observed_at = datetime.fromisoformat(str(timestamp))
            observed_at = (
                observed_at.replace(tzinfo=UTC)
                if observed_at.tzinfo is None
                else observed_at.astimezone(UTC)
            )
        except ValueError:
            return None
        if observed_at > now or now - observed_at > timedelta(seconds=max_age_seconds):
            return None
        return {
            "bid": bid,
            "ask": ask,
            "timestamp": str(timestamp),
            "age_seconds": round((now - observed_at).total_seconds(), 3),
        }

    @staticmethod
    def _quote_failure_reason(
        snapshot: dict[str, Any], now: datetime, *, max_age_seconds: int = 900
    ) -> str:
        quote = snapshot.get("latestQuote") or snapshot.get("latest_quote") or {}
        timestamp = quote.get("t") or quote.get("timestamp")
        if not timestamp:
            return "missing"
        try:
            observed_at = datetime.fromisoformat(str(timestamp))
            observed_at = (
                observed_at.replace(tzinfo=UTC)
                if observed_at.tzinfo is None
                else observed_at.astimezone(UTC)
            )
        except ValueError:
            return "has an invalid timestamp"
        if observed_at > now:
            return "is from the future"
        if now - observed_at > timedelta(seconds=max_age_seconds):
            return "is stale"
        return "is missing or invalid"

    @staticmethod
    def _outcome_bucket(candidate: dict[str, Any]) -> str:
        if candidate["trade_mode"] == "exploration":
            return "exploration"
        if candidate["classification"] == "qualifying_candidate":
            return "selected"
        return "shadow"

    @staticmethod
    def _order_preview(scan: ScanResult, plan: TradePlan, gate) -> dict[str, Any]:
        """Expose the complete dry-run decision without creating an order."""
        assert scan.spread is not None
        spread = scan.spread
        debit = plan.limit_price
        max_profit = round((spread.width - debit) * 100 * plan.qty, 2)
        breakeven = round(
            spread.long_leg.strike + debit
            if spread.regime.value == "bullish"
            else spread.long_leg.strike - debit,
            4,
        )
        return {
            "plan_id": plan.plan_id,
            "approval_expires_at": (
                plan.approval_expires_at.isoformat() if plan.approval_expires_at else None
            ),
            "quote_timestamps": plan.quote_timestamps,
            "trade_mode": plan.trade_mode,
            "score": scan.score.score if scan.score else None,
            "score_threshold": plan.score_threshold,
            "selected_symbol": plan.underlying,
            "strategy": "bull_call_debit_spread"
            if spread.regime.value == "bullish"
            else "bear_put_debit_spread",
            "option_legs": [leg.model_dump(mode="json") for leg in plan.legs],
            "quantity": plan.qty,
            "entry_debit": debit,
            "maximum_loss": plan.max_loss_usd,
            "maximum_profit": max_profit,
            "breakeven": breakeven,
            "stop_loss_exit_value": round(debit * 0.65, 4),
            "profit_target_exit_value": round(debit * 1.5, 4),
            "expiration": spread.long_leg.expiration,
            "risk_approval": gate.model_dump(),
            "mcp_payload": plan.mcp_arguments(),
        }
