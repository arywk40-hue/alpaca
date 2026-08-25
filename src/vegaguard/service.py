from typing import Any

from .alpaca_api import AlpacaRESTClient
from .config import Settings
from .execution import PaperExecutionAgent
from .models import OptionLeg, PositionIntent, Side, Thesis, TradePlan
from .risk import DeterministicRiskGate
from .scanner import OpportunityScanner, ScanResult
from .strategy.spread_builder import position_size
from .thesis import OpenAIThesisAgent


class AutonomousCycle:
    """Paper-only orchestration; deterministic scan always precedes an optional thesis."""

    def __init__(self, settings: Settings, executor: PaperExecutionAgent):
        self.settings = settings
        self.alpaca = AlpacaRESTClient(settings)
        self.scanner = OpportunityScanner(settings, self.alpaca)
        self.risk_gate = DeterministicRiskGate(settings)
        self.executor = executor
        self._thesis_agent: OpenAIThesisAgent | None = None

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

    async def run_once(self) -> dict[str, Any]:
        account, clock, positions = await self._account_state()
        for underlying in self.settings.universe:
            scan = await self.scanner.scan(underlying)
            if scan.opportunity is None or scan.spread is None:
                continue
            thesis = await self._thesis().evaluate(scan.opportunity)
            if thesis.action == "skip":
                return {
                    "status": "no_trade",
                    "reason": "thesis chose skip",
                    "scan": self._serialize_scan(scan),
                }
            plan = self._plan_from_spread(scan, thesis, float(account.get("equity", 0)))
            if plan is None:
                return {"status": "no_trade", "reason": "risk budget cannot fund one spread"}
            gate = self.risk_gate.assess(
                plan,
                market_open=bool(clock.get("is_open")),
                open_positions=len(positions),
                buying_power=float(account.get("buying_power", 0)),
            )
            result = await self.executor.submit(plan, gate)
            return {
                "underlying": underlying,
                "scan": self._serialize_scan(scan),
                "plan": plan.model_dump(mode="json"),
                "gate": gate.model_dump(),
                "result": result,
            }
        return {"status": "no_trade", "reason": "no ETF passed deterministic scan rules"}

    async def _account_state(self) -> tuple[dict, dict, list[dict]]:
        account, clock, positions = (
            await self.alpaca.account(),
            await self.alpaca.clock(),
            await self.alpaca.positions(),
        )
        return account, clock, positions

    def _thesis(self) -> OpenAIThesisAgent:
        if self._thesis_agent is None:
            self._thesis_agent = OpenAIThesisAgent(self.settings)
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
    def _serialize_scan(scan: ScanResult) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "underlying": scan.underlying,
            "score": scan.score.score if scan.score else None,
            "regime": scan.score.regime.value if scan.score else "no_trade",
            "reasons": list(scan.reasons),
        }
        if scan.spread:
            payload["spread"] = {
                "long_symbol": scan.spread.long_leg.symbol,
                "short_symbol": scan.spread.short_leg.symbol,
                "debit": scan.spread.debit,
                "width": scan.spread.width,
                "max_loss_per_contract": scan.spread.max_loss_per_contract,
            }
        return payload
