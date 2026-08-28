from dataclasses import asdict, dataclass
from math import sqrt
from statistics import stdev


@dataclass(frozen=True)
class ClosedTrade:
    symbol: str
    quantity: int
    entry_debit: float
    exit_value: float
    extra_cost_per_contract: float = 0.0

    @property
    def gross_pnl(self) -> float:
        return round((self.exit_value - self.entry_debit) * 100 * self.quantity, 2)

    @property
    def costs(self) -> float:
        return round(self.extra_cost_per_contract * self.quantity, 2)

    @property
    def net_pnl(self) -> float:
        return round(self.gross_pnl - self.costs, 2)


@dataclass(frozen=True)
class PerformanceSummary:
    trade_count: int
    gross_pnl: float
    costs: float
    net_pnl: float
    expectancy_usd_per_trade: float
    win_rate: float
    average_win: float
    average_loss: float
    profit_factor: float | None
    max_drawdown: float
    per_symbol_net_pnl: dict[str, float]

    def as_dict(self) -> dict:
        return asdict(self)


def max_drawdown(pnls: list[float]) -> float:
    peak = 0.0
    cumulative = 0.0
    worst = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return round(worst, 2)


def confidence_intervals(pnls: list[float]) -> dict:
    """Return transparent approximate 95% intervals without small-sample certainty."""
    count = len(pnls)
    if count == 0:
        return {
            "status": "INSUFFICIENT EVIDENCE",
            "win_rate_95pct_wilson": None,
            "expectancy_usd_95pct_normal": None,
        }
    wins = sum(pnl > 0 for pnl in pnls)
    proportion = wins / count
    z = 1.96
    denominator = 1 + z**2 / count
    center = (proportion + z**2 / (2 * count)) / denominator
    margin = z * sqrt((proportion * (1 - proportion) + z**2 / (4 * count)) / count) / denominator
    expectancy_interval = None
    if count >= 2:
        mean = sum(pnls) / count
        half_width = z * stdev(pnls) / sqrt(count)
        expectancy_interval = [round(mean - half_width, 2), round(mean + half_width, 2)]
    return {
        "status": "descriptive_only" if count < 30 else "approximate_95pct_intervals",
        "win_rate_95pct_wilson": [
            round(max(0.0, center - margin), 4),
            round(min(1.0, center + margin), 4),
        ],
        "expectancy_usd_95pct_normal": expectancy_interval,
    }


def summarize(trades: list[ClosedTrade]) -> PerformanceSummary:
    net_pnls = [trade.net_pnl for trade in trades]
    wins = [pnl for pnl in net_pnls if pnl > 0]
    losses = [pnl for pnl in net_pnls if pnl < 0]
    loss_total = abs(sum(losses))
    per_symbol: dict[str, float] = {}
    for trade in trades:
        per_symbol[trade.symbol] = round(per_symbol.get(trade.symbol, 0.0) + trade.net_pnl, 2)
    return PerformanceSummary(
        trade_count=len(trades),
        gross_pnl=round(sum(trade.gross_pnl for trade in trades), 2),
        costs=round(sum(trade.costs for trade in trades), 2),
        net_pnl=round(sum(net_pnls), 2),
        expectancy_usd_per_trade=round(sum(net_pnls) / len(trades), 2) if trades else 0.0,
        win_rate=round(len(wins) / len(trades), 4) if trades else 0.0,
        average_win=round(sum(wins) / len(wins), 2) if wins else 0.0,
        average_loss=round(sum(losses) / len(losses), 2) if losses else 0.0,
        profit_factor=round(sum(wins) / loss_total, 4) if loss_total else None,
        max_drawdown=max_drawdown(net_pnls),
        per_symbol_net_pnl=per_symbol,
    )
