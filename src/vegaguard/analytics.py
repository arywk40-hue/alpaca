"""Auditable paper-trading metrics; synthetic fixtures are never labelled as real P&L."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PaperTradeOutcome:
    symbol: str
    gross_pnl: float
    costs: float
    max_risk_usd: float
    fill_slippage_usd: float = 0.0
    regime: str = "unknown"

    @property
    def net_pnl(self) -> float:
        return round(self.gross_pnl - self.costs, 2)


@dataclass(frozen=True)
class PaperMetrics:
    trade_count: int
    gross_pnl: float
    net_pnl: float
    costs: float
    win_rate: float
    profit_factor: float | None
    maximum_drawdown: float
    return_on_risk: float
    fill_rate: float
    average_slippage_usd: float
    per_regime_net_pnl: dict[str, float]
    rejected_opportunity_pnl: float

    def as_dict(self) -> dict:
        return asdict(self)


def summarize_paper_metrics(
    outcomes: list[PaperTradeOutcome],
    *,
    orders_submitted: int,
    orders_filled: int,
    rejected_opportunity_pnl: float = 0.0,
) -> PaperMetrics:
    net_pnls = [outcome.net_pnl for outcome in outcomes]
    wins = [pnl for pnl in net_pnls if pnl > 0]
    losses = [pnl for pnl in net_pnls if pnl < 0]
    gross = round(sum(outcome.gross_pnl for outcome in outcomes), 2)
    costs = round(sum(outcome.costs for outcome in outcomes), 2)
    total_risk = sum(outcome.max_risk_usd for outcome in outcomes)
    cumulative = peak = max_drawdown = 0.0
    for pnl in net_pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    per_regime: dict[str, float] = {}
    for outcome in outcomes:
        per_regime[outcome.regime] = round(per_regime.get(outcome.regime, 0) + outcome.net_pnl, 2)
    return PaperMetrics(
        trade_count=len(outcomes),
        gross_pnl=gross,
        net_pnl=round(sum(net_pnls), 2),
        costs=costs,
        win_rate=round(len(wins) / len(outcomes), 4) if outcomes else 0.0,
        profit_factor=round(sum(wins) / abs(sum(losses)), 4) if losses else None,
        maximum_drawdown=round(max_drawdown, 2),
        return_on_risk=round(sum(net_pnls) / total_risk, 4) if total_risk else 0.0,
        fill_rate=round(orders_filled / orders_submitted, 4) if orders_submitted else 0.0,
        average_slippage_usd=round(
            sum(outcome.fill_slippage_usd for outcome in outcomes) / len(outcomes), 2
        )
        if outcomes
        else 0.0,
        per_regime_net_pnl=per_regime,
        rejected_opportunity_pnl=round(rejected_opportunity_pnl, 2),
    )
