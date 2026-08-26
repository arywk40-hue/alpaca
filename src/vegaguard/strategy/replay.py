import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .metrics import ClosedTrade, PerformanceSummary, summarize
from .scorer import SignalInputs, SignalScore, score_signal


@dataclass(frozen=True)
class ReplayObservation:
    timestamp: datetime
    symbol: str
    inputs: SignalInputs
    # Recorded after the entry decision. A replay caller must provide this only for completed trades.
    exit_value: float | None = None
    entry_debit: float | None = None
    quantity: int = 1
    extra_cost_per_contract: float = 0.0


@dataclass(frozen=True)
class ReplayResult:
    decisions: list[SignalScore]
    trades: list[ClosedTrade]
    summary: PerformanceSummary


def run_replay(
    observations: list[ReplayObservation],
    *,
    scorer: Callable[[SignalInputs], SignalScore] = score_signal,
) -> ReplayResult:
    ordered = sorted(observations, key=lambda item: item.timestamp)
    decisions: list[SignalScore] = []
    trades: list[ClosedTrade] = []
    for item in ordered:
        decision = scorer(item.inputs)
        decisions.append(decision)
        if decision.regime.value not in {"bullish", "bearish"}:
            continue
        if item.entry_debit is None or item.exit_value is None:
            continue
        trades.append(
            ClosedTrade(
                symbol=item.symbol,
                quantity=item.quantity,
                entry_debit=item.entry_debit,
                exit_value=item.exit_value,
                extra_cost_per_contract=item.extra_cost_per_contract,
            )
        )
    return ReplayResult(decisions=decisions, trades=trades, summary=summarize(trades))


def load_observations(path: str | Path) -> list[ReplayObservation]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    observations: list[ReplayObservation] = []
    for row in raw["observations"]:
        observations.append(
            ReplayObservation(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                symbol=row["symbol"],
                inputs=SignalInputs(**row["inputs"]),
                entry_debit=row.get("entry_debit"),
                exit_value=row.get("exit_value"),
                quantity=row.get("quantity", 1),
                extra_cost_per_contract=row.get("extra_cost_per_contract", 0.0),
            )
        )
    return observations


def write_report(
    result: ReplayResult, path: str | Path, *, data_source: str, limitations: list[str]
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    no_trade_count = sum(
        decision.regime.value not in {"bullish", "bearish"} for decision in result.decisions
    )
    payload = {
        "data_source": data_source,
        "observations": len(result.decisions),
        "trades": result.summary.trade_count,
        "no_trade_count": no_trade_count,
        "performance": result.summary.as_dict(),
        "limitations": limitations,
    }
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
