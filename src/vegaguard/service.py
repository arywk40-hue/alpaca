from datetime import UTC, datetime
from typing import Any

from .alpaca_api import AlpacaRESTClient
from .committee import (
    AdversarialRiskAgent,
    ExecutionAgent,
    RiskBudgetAllocator,
    StructureVolatilityAgent,
)
from .config import Settings
from .execution import PaperExecutionAgent
from .models import JournalEntry, OptionLeg, PositionIntent, Side, Thesis, TradePlan
from .monitoring import OrderLifecycle, PositionGuardian
from .risk import DeterministicRiskGate
from .scanner import OpportunityScanner, ScanResult
from .strategy.spread_builder import position_size
from .thesis import DeterministicThesisAgent, OpenAIThesisAgent, ThesisAgent


class AutonomousCycle:
    """Paper-only orchestration; deterministic scan always precedes an optional thesis."""

    def __init__(self, settings: Settings, executor: PaperExecutionAgent):
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
            result = await self.executor.submit_exit(exit_plan, reason=decision.reason)
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
            plan, filled_price=filled_price, source="rest_reconcile"
        )
        return filled_price

    async def run_once(self) -> dict[str, Any]:
        account, clock, positions = await self._account_state()
        if not bool(clock.get("is_open")):
            return {
                "status": "no_trade",
                "reason": "market_closed",
                "paper_only": self.settings.alpaca_paper_trade,
            }
        scans = [await self.scanner.scan(underlying) for underlying in self.settings.universe]
        for scan in scans:
            self._record_shadow_candidate(scan)
        candidates = [
            (scan, scan.spread.max_loss_per_contract)
            for scan in scans
            if scan.spread is not None and scan.opportunity is not None
        ]
        aggregate_budget = (
            float(account.get("equity", 0)) * self.settings.risk_fraction_per_trade * 3
        )
        allocations = self.allocator.allocate(candidates, risk_budget_usd=aggregate_budget)
        if not allocations:
            return {
                "status": "no_trade",
                "reason": "no ETF passed deterministic scan and budget rules",
            }
        selected = next(scan for scan in scans if scan.underlying == allocations[0].underlying)
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
        if thesis.action == "skip":
            return {
                "status": "no_trade",
                "reason": "thesis chose skip",
                "scan": self._serialize_scan(selected),
            }
        plan = self._plan_from_spread(selected, thesis, float(account.get("equity", 0)))
        if plan is None:
            return {"status": "no_trade", "reason": "risk budget cannot fund one spread"}
        gate = self.risk_gate.assess(
            plan,
            market_open=bool(clock.get("is_open")),
            open_positions=len(positions),
            buying_power=float(account.get("buying_power", 0)),
        )
        if gate.approved:
            self.executor.journal.register_shadow(
                plan,
                regime=selected.score.regime.value if selected.score else "unknown",
            )
        result = await self.executor.submit(plan, gate)
        payload = {
            "underlying": selected.underlying,
            "scan": self._serialize_scan(selected),
            "reviews": [review.__dict__ for review in reviews],
            "plan": plan.model_dump(mode="json"),
            "gate": gate.model_dump(),
            "result": result,
        }
        if result["status"] in {"dry_run", "observe_only"}:
            payload["order_preview"] = self._order_preview(selected, plan, gate)
        return payload

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
        return TradePlan(
            underlying=scan.underlying,
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
        )

    @staticmethod
    def _executable_exit_credit(plan: TradePlan, snapshots: dict[str, dict]) -> float | None:
        quotes: dict[str, dict] = {}
        for leg in plan.legs:
            quote = (snapshots.get(leg.symbol) or {}).get("latestQuote") or (
                snapshots.get(leg.symbol) or {}
            ).get("latest_quote")
            if not quote:
                return None
            quotes[leg.symbol] = quote
        long_leg = next(leg for leg in plan.legs if leg.side is Side.BUY)
        short_leg = next(leg for leg in plan.legs if leg.side is Side.SELL)
        long_bid = float(
            quotes[long_leg.symbol].get("bp", quotes[long_leg.symbol].get("bid_price", 0))
        )
        short_ask = float(
            quotes[short_leg.symbol].get("ap", quotes[short_leg.symbol].get("ask_price", 0))
        )
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
            "regime": scan.score.regime.value if scan.score else "no_trade",
            "confidence": round(abs(scan.score.score) / 100, 2) if scan.score else None,
            "data_timestamp": scan.data_timestamp.isoformat() if scan.data_timestamp else None,
            "reasons": list(scan.reasons),
        }
        if scan.spread:
            payload["spread"] = AutonomousCycle._spread_payload(scan.spread)
        if scan.shadow_spread and scan.shadow_spread != scan.spread:
            payload["shadow_candidate"] = AutonomousCycle._spread_payload(scan.shadow_spread)
        return payload

    def _record_shadow_candidate(self, scan: ScanResult) -> None:
        spread = scan.shadow_spread or scan.spread
        if scan.score is None:
            classification = "data_unavailable"
            reasons = list(scan.reasons)
        elif scan.score.regime.value == "neutral":
            classification = "below_threshold" if scan.score.score else "directionless"
            reasons = list(scan.score.reasons)
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
        self.executor.journal.record_shadow_candidate(
            underlying=scan.underlying,
            classification=classification,
            score=scan.score.score if scan.score else None,
            regime=scan.score.regime.value if scan.score else "no_trade",
            data_timestamp=scan.data_timestamp,
            reasons=reasons,
            quote_timestamps=quote_timestamps,
            spread=self._spread_payload(spread) if spread else None,
        )

    @staticmethod
    def _spread_payload(spread) -> dict[str, Any]:
        return {
            "long_symbol": spread.long_leg.symbol,
            "short_symbol": spread.short_leg.symbol,
            "debit": spread.debit,
            "width": spread.width,
            "max_loss_per_contract": spread.max_loss_per_contract,
            "iv_source": spread.long_leg.iv_source,
            "long_quote_timestamp": spread.long_leg.quote_timestamp,
            "short_quote_timestamp": spread.short_leg.quote_timestamp,
        }

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
