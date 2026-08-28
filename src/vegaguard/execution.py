import json
from typing import Any

from .config import Settings
from .journal import DecisionJournal
from .mcp_client import AlpacaMCPClient
from .models import GateResult, JournalEntry, TradePlan


class PaperExecutionAgent:
    def __init__(self, settings: Settings, journal: DecisionJournal, mcp: AlpacaMCPClient):
        self.settings = settings
        self.journal = journal
        self.mcp = mcp

    async def submit(self, plan: TradePlan, gate: GateResult) -> dict:
        return await self._submit(plan, gate, allow_dry_run_approval=False)

    async def submit_approved(self, plan: TradePlan, gate: GateResult) -> dict:
        """Submit a previously reviewed dry-run plan exactly once."""
        try:
            recorded = self.journal.approved_plan(plan.plan_id)
        except ValueError as exc:
            return {"status": "blocked", "reasons": [str(exc)]}
        if recorded.model_dump(mode="json") != plan.model_dump(mode="json"):
            return {"status": "blocked", "reasons": ["approved plan changed after review"]}
        return await self._submit(plan, gate, allow_dry_run_approval=True)

    async def _submit(
        self, plan: TradePlan, gate: GateResult, *, allow_dry_run_approval: bool
    ) -> dict:
        if self.journal.has_submitted_client_order_id(plan.client_order_id) or (
            not allow_dry_run_approval and self.journal.has_client_order_id(plan.client_order_id)
        ):
            return {"status": "blocked", "reasons": ["duplicate client_order_id"]}
        self.journal.append(JournalEntry(event="gate_evaluated", plan=plan, gate=gate))
        if not gate.approved:
            return {"status": "blocked", "reasons": gate.reasons}
        if not self.settings.allow_order_execution:
            return {"status": "observe_only", "reason": "ALLOW_ORDER_EXECUTION is false"}
        if self.settings.dry_run:
            self.journal.append(JournalEntry(event="dry_run_order", plan=plan, gate=gate))
            return {
                "status": "dry_run",
                "reason": "DRY_RUN is true",
                "mcp_arguments": plan.mcp_arguments(),
            }
        if not self.settings.alpaca_paper_trade:
            raise RuntimeError("Execution is only permitted with ALPACA_PAPER_TRADE=true")
        if not allow_dry_run_approval:
            # A scheduler or dashboard scan may construct a valid plan, but it
            # may never submit it directly. The operator must review this exact
            # ID and call submit_approved while quote-bound approval is valid.
            self.journal.append(JournalEntry(event="plan_approval_required", plan=plan, gate=gate))
            return {
                "status": "approval_required",
                "reason": "explicit unexpired plan_id approval is required before submission",
                "plan_id": plan.plan_id,
                "mcp_arguments": plan.mcp_arguments(),
            }
        self.journal.append(JournalEntry(event="order_submission_intent", plan=plan, gate=gate))
        try:
            receipt = await self.mcp.call("place_option_order", plan.mcp_arguments())
        except (OSError, RuntimeError, TimeoutError) as exc:
            self.journal.append(
                JournalEntry(
                    event="order_submission_error",
                    plan=plan,
                    gate=gate,
                    payload={"error_type": type(exc).__name__, "reason": str(exc)},
                )
            )
            raise
        self.journal.append(
            JournalEntry(event="order_submission_receipt", plan=plan, gate=gate, payload=receipt)
        )
        provider_status = self._provider_status(receipt)
        provider_order_id = self._provider_order_id(receipt)
        if provider_status in {"accepted", "new", "pending_new", "partially_filled", "filled"}:
            self.journal.append(
                JournalEntry(
                    event="order_acknowledged",
                    plan=plan,
                    gate=gate,
                    payload={
                        "provider_order_id": provider_order_id,
                        "provider_status": provider_status,
                    },
                )
            )
        return {
            "status": "rejected" if provider_status == "rejected" else "submitted",
            "provider_status": provider_status,
            "provider_order_id": provider_order_id,
            "receipt": receipt,
        }

    async def submit_exit(
        self, plan: TradePlan, *, reason: str, safety_gate: GateResult | None = None
    ) -> dict:
        """Submit only a guardian-created, atomic paper spread close."""
        if (
            not plan.is_closing
            or not plan.parent_client_order_id
            or plan.strategy != "debit_spread"
            or len(plan.legs) != 2
        ):
            return {"status": "blocked", "reasons": ["exit must close a tracked debit spread"]}
        parent = self.journal.plan_for_client_order_id(plan.parent_client_order_id)
        if parent is None or parent.is_closing or parent.strategy != "debit_spread":
            return {"status": "blocked", "reasons": ["exit parent debit spread is not tracked"]}
        expected = parent.closing_plan(executable_credit=abs(plan.limit_price))
        if (
            plan.underlying != expected.underlying
            or plan.qty != expected.qty
            or plan.legs != expected.legs
        ):
            return {"status": "blocked", "reasons": ["exit legs changed from tracked position"]}
        if self.journal.has_client_order_id(plan.client_order_id):
            return {"status": "blocked", "reasons": ["duplicate client_order_id"]}
        gate = safety_gate or GateResult(approved=True, reasons=[f"guardian exit: {reason}"])
        self.journal.append(
            JournalEntry(
                event="exit_gate_evaluated", plan=plan, gate=gate, payload={"reason": reason}
            )
        )
        if not self.settings.allow_order_execution:
            return {"status": "observe_only", "reason": "ALLOW_ORDER_EXECUTION is false"}
        if self.settings.dry_run:
            self.journal.append(
                JournalEntry(
                    event="dry_run_exit_order", plan=plan, gate=gate, payload={"reason": reason}
                )
            )
            return {
                "status": "dry_run",
                "reason": "DRY_RUN is true",
                "mcp_arguments": plan.mcp_arguments(),
            }
        if safety_gate is None or not safety_gate.approved:
            return {
                "status": "blocked",
                "reasons": (
                    safety_gate.reasons if safety_gate else ["current exit safety gate missing"]
                ),
            }
        if not self.settings.alpaca_paper_trade:
            raise RuntimeError("Exit execution is only permitted with ALPACA_PAPER_TRADE=true")
        self.journal.append(
            JournalEntry(
                event="exit_submission_intent", plan=plan, gate=gate, payload={"reason": reason}
            )
        )
        try:
            receipt = await self.mcp.call("place_option_order", plan.mcp_arguments())
        except (OSError, RuntimeError, TimeoutError) as exc:
            self.journal.append(
                JournalEntry(
                    event="exit_submission_error",
                    plan=plan,
                    gate=gate,
                    payload={
                        "reason": reason,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
            )
            raise
        self.journal.append(
            JournalEntry(
                event="exit_submission_receipt",
                plan=plan,
                gate=gate,
                payload={"reason": reason, "receipt": receipt},
            )
        )
        provider_status = self._provider_status(receipt)
        provider_order_id = self._provider_order_id(receipt)
        if provider_status in {"accepted", "new", "pending_new", "partially_filled", "filled"}:
            self.journal.append(
                JournalEntry(
                    event="exit_order_acknowledged",
                    plan=plan,
                    gate=gate,
                    payload={
                        "reason": reason,
                        "provider_order_id": provider_order_id,
                        "provider_status": provider_status,
                    },
                )
            )
        return {
            "status": "rejected" if provider_status == "rejected" else "submitted",
            "provider_status": provider_status,
            "provider_order_id": provider_order_id,
            "receipt": receipt,
        }

    @staticmethod
    def _provider_status(receipt: dict) -> str | None:
        order = PaperExecutionAgent._provider_order(receipt)
        value = order.get("status") if order else None
        return str(value).lower() if value is not None else None

    @staticmethod
    def _provider_order_id(receipt: dict) -> str | None:
        order = PaperExecutionAgent._provider_order(receipt)
        value = order.get("id") if order else None
        return str(value) if value is not None else None

    @staticmethod
    def _provider_order(payload: Any) -> dict[str, Any] | None:
        """Find an Alpaca order inside direct or MCP content-wrapped responses."""
        if isinstance(payload, str):
            try:
                return PaperExecutionAgent._provider_order(json.loads(payload))
            except json.JSONDecodeError:
                return None
        if isinstance(payload, list):
            for item in payload:
                if order := PaperExecutionAgent._provider_order(item):
                    return order
            return None
        if not isinstance(payload, dict):
            return None
        if "status" in payload and any(
            key in payload for key in ("id", "client_order_id", "symbol", "legs")
        ):
            return payload
        for key in ("order", "data", "result", "content"):
            if key in payload and (order := PaperExecutionAgent._provider_order(payload[key])):
                return order
        return None
