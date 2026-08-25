from .alpaca_api import AlpacaRESTClient
from .config import Settings
from .execution import PaperExecutionAgent
from .models import OptionLeg, PositionIntent, Side, TradePlan
from .risk import DeterministicRiskGate
from .scanner import OpportunityScanner
from .thesis import OpenAIThesisAgent


class AutonomousCycle:
    def __init__(self, settings: Settings, executor: PaperExecutionAgent):
        self.settings = settings
        self.alpaca = AlpacaRESTClient(settings)
        self.scanner = OpportunityScanner(settings, self.alpaca)
        self.thesis_agent = OpenAIThesisAgent(settings)
        self.risk_gate = DeterministicRiskGate(settings)
        self.executor = executor

    async def run_once(self) -> dict:
        account, clock, positions = await self.alpaca.account(), await self.alpaca.clock(), await self.alpaca.positions()
        for underlying in self.settings.universe:
            opportunity = await self.scanner.scan(underlying)
            if opportunity is None:
                continue
            thesis = await self.thesis_agent.evaluate(opportunity)
            if thesis.action == "skip":
                continue
            candidate = opportunity.candidate
            plan = TradePlan(
                underlying=candidate.underlying,
                strategy="single_leg",
                legs=[
                    OptionLeg(
                        symbol=candidate.symbol,
                        side=Side.BUY,
                        position_intent=PositionIntent.BUY_TO_OPEN,
                    )
                ],
                qty=1,
                limit_price=candidate.midpoint,
                max_loss_usd=candidate.midpoint * 100,
                candidate=candidate,
                thesis=thesis,
            )
            gate = self.risk_gate.assess(
                plan,
                market_open=bool(clock.get("is_open")),
                open_positions=len(positions),
                buying_power=float(account.get("buying_power", 0)),
            )
            result = await self.executor.submit(plan, gate)
            return {"underlying": underlying, "plan": plan.model_dump(mode="json"), "gate": gate.model_dump(), "result": result}
        return {"status": "no_trade", "reason": "no contract passed scanner and thesis criteria"}

