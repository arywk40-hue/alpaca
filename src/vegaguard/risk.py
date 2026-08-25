from .config import Settings
from .models import GateResult, TradePlan


class DeterministicRiskGate:
    """Rules that an LLM cannot override."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def assess(
        self, plan: TradePlan, *, market_open: bool, open_positions: int, buying_power: float
    ) -> GateResult:
        reasons: list[str] = []
        candidate = plan.candidate
        if not self.settings.alpaca_paper_trade:
            reasons.append("refusing non-paper execution")
        if not market_open:
            reasons.append("market is closed")
        if plan.thesis.action != "trade":
            reasons.append("thesis explicitly chose skip")
        if plan.thesis.candidate_symbol != candidate.symbol:
            reasons.append("thesis/candidate contract mismatch")
        if plan.qty > self.settings.max_contracts_per_trade:
            reasons.append("contract quantity exceeds configured limit")
        if plan.max_loss_usd > self.settings.max_trade_risk_usd:
            reasons.append("maximum loss exceeds configured per-trade risk")
        if not self.settings.min_dte <= candidate.dte <= self.settings.max_dte:
            reasons.append("expiration falls outside configured DTE window")
        if candidate.spread_pct > self.settings.max_bid_ask_spread_pct:
            reasons.append("option bid-ask spread is too wide")
        if open_positions >= self.settings.max_open_positions:
            reasons.append("maximum open positions reached")
        if buying_power < plan.max_loss_usd:
            reasons.append("insufficient buying power for defined maximum loss")
        if plan.strategy != "debit_spread":
            reasons.append("VegaGuard execution only permits defined-risk debit spreads")
        elif {leg.side.value for leg in plan.legs} != {"buy", "sell"}:
            reasons.append("debit spread must include one bought and one sold option leg")
        return GateResult(
            approved=not reasons, reasons=reasons or ["all deterministic checks passed"]
        )
