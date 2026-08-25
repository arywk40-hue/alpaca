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
        self.journal.append(JournalEntry(event="gate_evaluated", plan=plan, gate=gate))
        if not gate.approved:
            return {"status": "blocked", "reasons": gate.reasons}
        if not self.settings.allow_order_execution:
            return {"status": "observe_only", "reason": "ALLOW_ORDER_EXECUTION is false"}
        if not self.settings.alpaca_paper_trade:
            raise RuntimeError("Execution is only permitted with ALPACA_PAPER_TRADE=true")
        self.journal.append(JournalEntry(event="order_submission_intent", plan=plan, gate=gate))
        receipt = await self.mcp.call("place_option_order", plan.mcp_arguments())
        self.journal.append(
            JournalEntry(event="order_submission_receipt", plan=plan, gate=gate, payload=receipt)
        )
        return {"status": "submitted", "receipt": receipt}
