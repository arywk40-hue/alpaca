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
        if self.journal.has_client_order_id(plan.client_order_id):
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
        self.journal.append(JournalEntry(event="order_submission_intent", plan=plan, gate=gate))
        receipt = await self.mcp.call("place_option_order", plan.mcp_arguments())
        self.journal.append(
            JournalEntry(event="order_submission_receipt", plan=plan, gate=gate, payload=receipt)
        )
        return {"status": "submitted", "receipt": receipt}

    async def submit_exit(self, plan: TradePlan, *, reason: str) -> dict:
        """Submit only a guardian-created, atomic paper spread close."""
        if not plan.is_closing or not plan.parent_client_order_id:
            return {"status": "blocked", "reasons": ["exit must close a tracked debit spread"]}
        if self.journal.has_client_order_id(plan.client_order_id):
            return {"status": "blocked", "reasons": ["duplicate client_order_id"]}
        gate = GateResult(approved=True, reasons=[f"guardian exit: {reason}"])
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
        if not self.settings.alpaca_paper_trade:
            raise RuntimeError("Exit execution is only permitted with ALPACA_PAPER_TRADE=true")
        self.journal.append(
            JournalEntry(
                event="exit_submission_intent", plan=plan, gate=gate, payload={"reason": reason}
            )
        )
        receipt = await self.mcp.call("place_option_order", plan.mcp_arguments())
        self.journal.append(
            JournalEntry(
                event="exit_submission_receipt",
                plan=plan,
                gate=gate,
                payload={"reason": reason, "receipt": receipt},
            )
        )
        return {"status": "submitted", "receipt": receipt}
