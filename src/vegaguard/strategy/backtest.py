"""Point-in-time, conservative replay of normalized historical market data.

This module accepts only local normalized files. It never contacts Alpaca and never
submits an order. Missing option quotes, Greeks, or point-in-time contract metadata
are rejections, never substitutions with stock prices.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..models import OptionCandidate
from .indicators import ema, percent_return, realized_volatility, volume_ratio, vwap
from .scorer import Regime, SignalInputs, score_signal
from .spread_builder import DebitSpread, build_debit_spread, position_size

MAX_QUOTE_AGE = timedelta(minutes=15)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone(UTC)


def _load_records(directory: Path, name: str) -> list[dict[str, Any]]:
    path = directory / f"{name}.json"
    if not path.exists():
        return []
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise TypeError(f"{path} must contain a JSON list")
    return [row for row in loaded if isinstance(row, dict)]


@dataclass(frozen=True)
class RejectedOpportunity:
    timestamp: str
    symbol: str
    reason: str
    score: int | None = None


@dataclass(frozen=True)
class HistoricalTrade:
    symbol: str
    regime: str
    entry_timestamp: str
    exit_timestamp: str
    quantity: int
    long_symbol: str
    short_symbol: str
    entry_debit: float
    exit_value: float
    gross_pnl: float
    estimated_bid_ask_cost: float
    net_pnl: float
    exit_reason: str
    holding_minutes: int


@dataclass
class _OpenPosition:
    symbol: str
    regime: Regime
    spread: DebitSpread
    quantity: int
    entry_at: datetime
    entry_mid_debit: float


@dataclass(frozen=True)
class HistoricalBacktestResult:
    data_classification: str
    observations: int
    eligible_opportunities: int
    no_trade_decisions: int
    missing_data_count: int
    trades: list[HistoricalTrade]
    rejected: list[RejectedOpportunity]
    maximum_simultaneous_exposure: int
    per_symbol_net_pnl: dict[str, float]
    per_regime_net_pnl: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        gross = round(sum(trade.gross_pnl for trade in self.trades), 2)
        costs = round(sum(trade.estimated_bid_ask_cost for trade in self.trades), 2)
        net = round(sum(trade.net_pnl for trade in self.trades), 2)
        pnls = [trade.net_pnl for trade in self.trades]
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl < 0]
        cumulative = peak = drawdown = 0.0
        for pnl in pnls:
            cumulative += pnl
            peak = max(peak, cumulative)
            drawdown = min(drawdown, cumulative - peak)
        rejected_reasons: dict[str, int] = {}
        for rejection in self.rejected:
            rejected_reasons[rejection.reason] = rejected_reasons.get(rejection.reason, 0) + 1
        return {
            "classification": self.data_classification,
            "observations": self.observations,
            "eligible_opportunities": self.eligible_opportunities,
            "no_trade_decisions": self.no_trade_decisions,
            "missing_data_count": self.missing_data_count,
            "trade_count": len(self.trades),
            "bullish_trades": sum(trade.regime == "bullish" for trade in self.trades),
            "bearish_trades": sum(trade.regime == "bearish" for trade in self.trades),
            "gross_pnl": gross,
            "estimated_bid_ask_cost": costs,
            "net_pnl": net,
            "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
            "average_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "average_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
            "maximum_drawdown": round(drawdown, 2),
            "per_symbol_net_pnl": self.per_symbol_net_pnl,
            "per_regime_net_pnl": self.per_regime_net_pnl,
            "average_holding_minutes": round(
                sum(trade.holding_minutes for trade in self.trades) / len(self.trades), 1
            )
            if self.trades
            else 0.0,
            "maximum_simultaneous_exposure": self.maximum_simultaneous_exposure,
            "rejected_trade_reasons": rejected_reasons,
            "statistically_meaningful": len(self.trades) >= 30,
            "trades": [asdict(trade) for trade in self.trades],
            "rejected_opportunities": [asdict(item) for item in self.rejected],
        }


class HistoricalBacktester:
    def __init__(
        self,
        data_dir: str | Path,
        *,
        symbols: list[str],
        start: datetime,
        end: datetime,
        initial_equity: float = 100_000.0,
        max_open_positions: int = 3,
        max_contracts_per_trade: int = 1,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.symbols = [symbol.upper() for symbol in symbols]
        self.start = start.astimezone(UTC)
        self.end = end.astimezone(UTC)
        self.initial_equity = initial_equity
        if max_open_positions < 1 or max_contracts_per_trade < 1:
            raise ValueError("position limits must be positive")
        self.max_open_positions = max_open_positions
        self.max_contracts_per_trade = max_contracts_per_trade

    def run(self) -> HistoricalBacktestResult:
        daily = self._records("stock_daily")
        intraday = self._records("stock_30min")
        contracts = self._records("option_contracts")
        quotes = self._records("option_quotes")
        snapshots = self._records("option_snapshots")
        quotes = self._merge_quote_greeks(quotes, snapshots)
        decision_times = sorted(
            {
                _bar_close_timestamp(row)
                for row in intraday
                if row.get("symbol") in self.symbols
                and self.start <= _bar_close_timestamp(row) <= self.end
            }
        )
        trades: list[HistoricalTrade] = []
        rejected: list[RejectedOpportunity] = []
        open_positions: list[_OpenPosition] = []
        observations = eligible = no_trade = missing = max_exposure = 0

        for now in decision_times:
            closed = self._close_positions(open_positions, quotes, now)
            for position, trade in closed:
                open_positions.remove(position)
                trades.append(trade)
            for symbol in self.symbols:
                feature = self._signal_inputs(symbol, now, daily, intraday, snapshots)
                if feature is None:
                    rejected.append(
                        RejectedOpportunity(now.isoformat(), symbol, "incomplete_signal_data")
                    )
                    missing += 1
                    continue
                observations += 1
                decision = score_signal(feature)
                if decision.regime == Regime.NO_TRADE:
                    no_trade += 1
                    rejected.append(
                        RejectedOpportunity(
                            now.isoformat(), symbol, "no_trade_signal", decision.score
                        )
                    )
                    continue
                eligible += 1
                if any(item.symbol == symbol for item in open_positions):
                    rejected.append(
                        RejectedOpportunity(
                            now.isoformat(), symbol, "overlapping_position", decision.score
                        )
                    )
                    continue
                if len(open_positions) >= self.max_open_positions:
                    rejected.append(
                        RejectedOpportunity(
                            now.isoformat(), symbol, "maximum_open_positions", decision.score
                        )
                    )
                    continue
                candidates, candidate_reason = self._candidates_at(
                    symbol, now, contracts, quotes, feature.price
                )
                if candidate_reason:
                    rejected.append(
                        RejectedOpportunity(
                            now.isoformat(), symbol, candidate_reason, decision.score
                        )
                    )
                    missing += 1
                    continue
                spread = build_debit_spread(candidates, decision.regime)
                if spread is None:
                    rejected.append(
                        RejectedOpportunity(
                            now.isoformat(), symbol, "invalid_debit_spread", decision.score
                        )
                    )
                    continue
                quantity = min(
                    self.max_contracts_per_trade,
                    position_size(
                        equity=self.initial_equity + sum(trade.net_pnl for trade in trades),
                        max_loss_per_contract=spread.max_loss_per_contract,
                    ),
                )
                if quantity < 1:
                    rejected.append(
                        RejectedOpportunity(
                            now.isoformat(), symbol, "position_size_limit", decision.score
                        )
                    )
                    continue
                open_positions.append(
                    _OpenPosition(
                        symbol=symbol,
                        regime=decision.regime,
                        spread=spread,
                        quantity=quantity,
                        entry_at=now,
                        entry_mid_debit=round(
                            spread.long_leg.midpoint - spread.short_leg.midpoint, 4
                        ),
                    )
                )
                max_exposure = max(max_exposure, len(open_positions))

        # A position with no later executable quote is not counted as a completed trade.
        for position in open_positions:
            rejected.append(
                RejectedOpportunity(
                    position.entry_at.isoformat(), position.symbol, "no_later_executable_exit_quote"
                )
            )
        classification = (
            "REAL HISTORICAL OPTION BACKTEST"
            if trades and contracts and quotes
            else "STOCK-SIGNAL-ONLY ANALYSIS"
        )
        per_symbol: dict[str, float] = {}
        per_regime: dict[str, float] = {}
        for trade in trades:
            per_symbol[trade.symbol] = round(per_symbol.get(trade.symbol, 0) + trade.net_pnl, 2)
            per_regime[trade.regime] = round(per_regime.get(trade.regime, 0) + trade.net_pnl, 2)
        return HistoricalBacktestResult(
            data_classification=classification,
            observations=observations,
            eligible_opportunities=eligible,
            no_trade_decisions=no_trade,
            missing_data_count=missing,
            trades=trades,
            rejected=rejected,
            maximum_simultaneous_exposure=max_exposure,
            per_symbol_net_pnl=per_symbol,
            per_regime_net_pnl=per_regime,
        )

    def _records(self, name: str) -> list[dict[str, Any]]:
        return [
            row
            for row in _load_records(self.data_dir, name)
            if "timestamp" not in row
            or self.start - timedelta(days=60) <= _timestamp(str(row["timestamp"])) <= self.end
        ]

    @staticmethod
    def _merge_quote_greeks(
        quotes: list[dict[str, Any]], snapshots: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        # Snapshot data is valid only when its own timestamp is at or before the quote.
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for snapshot in snapshots:
            by_symbol.setdefault(str(snapshot.get("symbol")), []).append(snapshot)
        merged: list[dict[str, Any]] = []
        for quote in quotes:
            matching = [
                snapshot
                for snapshot in by_symbol.get(str(quote.get("symbol")), [])
                if _timestamp(str(snapshot["timestamp"])) <= _timestamp(str(quote["timestamp"]))
            ]
            latest = max(matching, key=lambda item: item["timestamp"]) if matching else {}
            merged.append(
                {
                    **quote,
                    **{
                        key: latest[key] for key in ("delta", "implied_volatility") if key in latest
                    },
                    **({"greeks_timestamp": latest["timestamp"]} if latest else {}),
                }
            )
        return merged

    def _signal_inputs(
        self,
        symbol: str,
        now: datetime,
        daily: list[dict[str, Any]],
        intraday: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
    ) -> SignalInputs | None:
        # A daily bar's timestamp alone does not prove its close was known intraday.
        # Use completed prior sessions only, preventing the current day's close leak.
        prior_daily = sorted(
            [
                row
                for row in daily
                if row.get("symbol") == symbol and _timestamp(row["timestamp"]).date() < now.date()
            ],
            key=lambda item: item["timestamp"],
        )
        current = sorted(
            [
                row
                for row in intraday
                if row.get("symbol") == symbol and _bar_close_timestamp(row) <= now
            ],
            key=lambda item: item["timestamp"],
        )
        spy_daily = sorted(
            [
                row
                for row in daily
                if row.get("symbol") == "SPY" and _timestamp(row["timestamp"]).date() < now.date()
            ],
            key=lambda item: item["timestamp"],
        )
        iv_history = self._implied_volatility_history(symbol, now, snapshots)
        if len(prior_daily) < 22 or len(current) < 21 or len(spy_daily) < 2 or iv_history is None:
            return None
        implied_volatility, prior_implied_volatility = iv_history
        closes = [float(row["close"]) for row in prior_daily]
        intraday_closes = [float(row["close"]) for row in current]
        today = [row for row in current if _timestamp(row["timestamp"]).date() == now.date()]
        if not today:
            return None
        return SignalInputs(
            price=float(current[-1]["close"]),
            ema_20=ema(closes, 20)[-1],
            return_5d_pct=percent_return(closes, 5),
            ema_fast=ema(intraday_closes, 8)[-1],
            ema_slow=ema(intraday_closes, 21)[-1],
            vwap=vwap(
                [float(row["high"]) for row in today],
                [float(row["low"]) for row in today],
                [float(row["close"]) for row in today],
                [float(row["volume"]) for row in today],
            ),
            volume_ratio=volume_ratio([float(row["volume"]) for row in current]),
            realized_volatility=realized_volatility(closes[-21:]),
            prior_realized_volatility=realized_volatility(closes[-22:-1]),
            implied_volatility=implied_volatility,
            prior_implied_volatility=prior_implied_volatility,
            market_return_1d_pct=percent_return([float(row["close"]) for row in spy_daily], 1),
        )

    @staticmethod
    def _implied_volatility_history(
        symbol: str, now: datetime, snapshots: list[dict[str, Any]]
    ) -> tuple[float, float] | None:
        """Return current/prior IV using observations made no later than ``now``."""
        history = sorted(
            [
                snapshot
                for snapshot in snapshots
                if str(snapshot.get("symbol", "")).startswith(symbol)
                and snapshot.get("implied_volatility") is not None
                and _timestamp(str(snapshot["timestamp"])) <= now
            ],
            key=lambda item: item["timestamp"],
        )
        if not history or now - _timestamp(str(history[-1]["timestamp"])) > MAX_QUOTE_AGE:
            return None
        latest_timestamp = history[-1]["timestamp"]
        prior = [row for row in history if row["timestamp"] < latest_timestamp]
        if not prior:
            return None
        return float(history[-1]["implied_volatility"]), float(prior[-1]["implied_volatility"])

    def _candidates_at(
        self,
        symbol: str,
        now: datetime,
        contracts: list[dict[str, Any]],
        quotes: list[dict[str, Any]],
        underlying_price: float,
    ) -> tuple[list[OptionCandidate], str | None]:
        available_contracts = [
            contract
            for contract in contracts
            if contract.get("underlying") == symbol
            and _timestamp(str(contract.get("observed_at", "9999-01-01T00:00:00+00:00"))) <= now
        ]
        if not available_contracts:
            return [], "option_contract_metadata_not_observed_at_decision"
        quote_by_symbol: dict[str, dict[str, Any]] = {}
        for quote in quotes:
            timestamp = _timestamp(str(quote["timestamp"]))
            if timestamp <= now and now - timestamp <= MAX_QUOTE_AGE:
                prior = quote_by_symbol.get(str(quote["symbol"]))
                if prior is None or prior["timestamp"] < quote["timestamp"]:
                    quote_by_symbol[str(quote["symbol"])] = quote
        candidates: list[OptionCandidate] = []
        for contract in available_contracts:
            quote = quote_by_symbol.get(str(contract["symbol"]))
            if (
                not quote
                or quote.get("delta") is None
                or quote.get("implied_volatility") is None
                or quote.get("greeks_timestamp") is None
                or now - _timestamp(str(quote["greeks_timestamp"])) > MAX_QUOTE_AGE
                or float(quote.get("bid_size", 1)) <= 0
                or float(quote.get("ask_size", 1)) <= 0
            ):
                continue
            expiration = date.fromisoformat(str(contract["expiration"]))
            dte = (expiration - now.date()).days
            if not 14 <= dte <= 28:
                continue
            try:
                candidates.append(
                    OptionCandidate(
                        underlying=symbol,
                        symbol=str(contract["symbol"]),
                        option_type=str(contract["option_type"]),
                        strike=float(contract["strike"]),
                        expiration=expiration.isoformat(),
                        dte=dte,
                        bid=float(quote["bid"]),
                        ask=float(quote["ask"]),
                        delta=float(quote["delta"]),
                        implied_volatility=float(quote["implied_volatility"]),
                        underlying_price=underlying_price,
                    )
                )
            except (TypeError, ValueError):
                continue
        return (
            (candidates, None) if candidates else ([], "missing_or_stale_option_quotes_or_greeks")
        )

    @staticmethod
    def _close_positions(
        positions: list[_OpenPosition], quotes: list[dict[str, Any]], now: datetime
    ) -> list[tuple[_OpenPosition, HistoricalTrade]]:
        closed: list[tuple[_OpenPosition, HistoricalTrade]] = []
        for position in positions:
            if now <= position.entry_at:
                continue
            long_quote = _latest_quote(position.spread.long_leg.symbol, quotes, now)
            short_quote = _latest_quote(position.spread.short_leg.symbol, quotes, now)
            if long_quote is None or short_quote is None:
                continue
            exit_value = round(float(long_quote["bid"]) - float(short_quote["ask"]), 4)
            if exit_value <= 0:
                continue
            elapsed = now - position.entry_at
            pct_return = (exit_value - position.spread.debit) / position.spread.debit
            expiration = date.fromisoformat(position.spread.long_leg.expiration)
            if pct_return >= 0.50:
                reason = "take_profit"
            elif pct_return <= -0.35:
                reason = "stop_loss"
            elif elapsed >= timedelta(days=3):
                reason = "time_stop"
            elif (expiration - now.date()).days <= 2:
                reason = "expiry_exit"
            else:
                continue
            exit_mid = position.spread.long_leg.midpoint - position.spread.short_leg.midpoint
            # Use the contemporaneous midpoint to quantify the bid/ask penalty on exit.
            exit_mid = (float(long_quote["bid"]) + float(long_quote["ask"])) / 2 - (
                (float(short_quote["bid"]) + float(short_quote["ask"])) / 2
            )
            cost = max(0.0, position.spread.debit - position.entry_mid_debit) + max(
                0.0, exit_mid - exit_value
            )
            gross = round((exit_value - position.spread.debit) * 100 * position.quantity, 2)
            estimated_cost = round(cost * 100 * position.quantity, 2)
            closed.append(
                (
                    position,
                    HistoricalTrade(
                        symbol=position.symbol,
                        regime=position.regime.value,
                        entry_timestamp=position.entry_at.isoformat(),
                        exit_timestamp=now.isoformat(),
                        quantity=position.quantity,
                        long_symbol=position.spread.long_leg.symbol,
                        short_symbol=position.spread.short_leg.symbol,
                        entry_debit=position.spread.debit,
                        exit_value=exit_value,
                        gross_pnl=gross,
                        estimated_bid_ask_cost=estimated_cost,
                        net_pnl=round(gross - estimated_cost, 2),
                        exit_reason=reason,
                        holding_minutes=int(elapsed.total_seconds() // 60),
                    ),
                )
            )
        return closed


def _latest_quote(
    symbol: str, quotes: list[dict[str, Any]], now: datetime
) -> dict[str, Any] | None:
    valid = [
        quote
        for quote in quotes
        if quote.get("symbol") == symbol
        and _timestamp(str(quote["timestamp"])) <= now
        and now - _timestamp(str(quote["timestamp"])) <= MAX_QUOTE_AGE
    ]
    return max(valid, key=lambda item: item["timestamp"]) if valid else None


def _bar_close_timestamp(row: dict[str, Any]) -> datetime:
    """Return when a normalized bar's close is known to the strategy.

    Alpaca bar timestamps identify the beginning of the aggregation interval.  A
    30-minute bar is therefore only available at its timestamp plus 30 minutes.
    Daily bars are handled separately as completed prior sessions.
    """
    return _timestamp(str(row["timestamp"])) + timedelta(minutes=30)


def write_historical_report(
    result: HistoricalBacktestResult,
    *,
    path: str | Path,
    symbols: list[str],
    start: str,
    end: str,
) -> None:
    payload = result.as_dict()
    title = result.data_classification
    limitation = (
        "No real historical option P&L is claimed: point-in-time option contract metadata, "
        "quotes, Greeks, and IV were not all available in the normalized input."
        if title != "REAL HISTORICAL OPTION BACKTEST"
        else "Historical option prices are marked using conservative executable bid/ask quotes."
    )
    no_observations = (
        "- No normalized market observations were available. No external data was downloaded by this "
        "run (for example, credentials may be absent), so this is an empty report scaffold, not a "
        "historical-performance result."
        if result.observations == 0
        else None
    )
    lines = [
        f"# {title}",
        "",
        "## Scope",
        "",
        f"- Date range: {start} to {end}",
        f"- Symbols: {', '.join(symbols)}",
        (
            "- Data source/endpoints: Alpaca `/v2/stocks/bars`, `/v1beta1/options/quotes`, "
            "`/v1beta1/options/snapshots`, and `/v2/options/contracts`."
        ),
        (
            "- Feed limitations: stock feed selection is recorded in `data/cache_manifest.json`; "
            "historical options are available only from February 2024 and indicative quotes are "
            "modified/delayed when OPRA is unavailable."
        ),
        f"- {limitation}",
        "",
        "## Results",
        "",
    ]
    if no_observations:
        lines.insert(lines.index("## Results"), no_observations)
        lines.insert(lines.index("## Results"), "")
    for key in (
        "observations",
        "eligible_opportunities",
        "no_trade_decisions",
        "trade_count",
        "bullish_trades",
        "bearish_trades",
        "gross_pnl",
        "estimated_bid_ask_cost",
        "net_pnl",
        "win_rate",
        "average_win",
        "average_loss",
        "profit_factor",
        "maximum_drawdown",
        "average_holding_minutes",
        "maximum_simultaneous_exposure",
        "missing_data_count",
        "statistically_meaningful",
    ):
        lines.append(f"- {key.replace('_', ' ')}: {payload[key]}")
    lines += [
        "",
        "## Attribution and rejections",
        "",
        f"- Per-symbol net P&L: {payload['per_symbol_net_pnl']}",
        f"- Per-regime net P&L: {payload['per_regime_net_pnl']}",
        f"- Rejected trade reasons: {payload['rejected_trade_reasons']}",
        "",
        "## Conclusion",
        "",
        (
            "**Inconclusive.** A conclusion of profitability requires a sufficient sample of real, "
            "point-in-time historical option quotes, Greeks, IV and contract metadata. Synthetic "
            "fixtures and stock-only signals are not included in the options P&L number."
        ),
        "",
    ]
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")
