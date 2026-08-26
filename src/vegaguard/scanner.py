from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from .alpaca_api import AlpacaRESTClient
from .config import Settings
from .models import Opportunity, OptionCandidate
from .strategy.indicators import ema, percent_return, realized_volatility, volume_ratio, vwap
from .strategy.scorer import Regime, SignalInputs, SignalScore, score_signal
from .strategy.spread_builder import DebitSpread, build_debit_spread


def parse_option_symbol(symbol: str) -> tuple[str, date, str, float] | None:
    """Parse OCC symbols such as SPY260918C00650000 without a chain cache."""
    if len(symbol) < 15:
        return None
    try:
        tail = symbol[-15:]
        underlying, yymmdd, option_code, strike_millis = symbol[:-15], tail[:6], tail[6], tail[7:]
        expiry = datetime.strptime(yymmdd, "%y%m%d").replace(tzinfo=UTC).date()
        return underlying, expiry, {"C": "call", "P": "put"}[option_code], int(strike_millis) / 1000
    except (KeyError, ValueError):
        return None


def daily_return(closes: list[float], periods: int) -> float:
    return percent_return(closes, periods)


@dataclass(frozen=True)
class ScanResult:
    underlying: str
    score: SignalScore | None
    opportunity: Opportunity | None
    spread: DebitSpread | None
    reasons: tuple[str, ...]


class OpportunityScanner:
    """Read-only scanner that shares the backtest score and debit-spread builder."""

    def __init__(self, settings: Settings, alpaca: AlpacaRESTClient):
        self.settings = settings
        self.alpaca = alpaca
        self._iv_history: dict[str, tuple[datetime, float]] = {}

    async def scan(self, underlying: str) -> ScanResult:
        daily, intraday, market_daily, snapshots = await self.alpaca.market_snapshot(underlying)
        now = datetime.now(UTC)
        inputs, input_reasons = self._signal_inputs(
            underlying, daily, intraday, market_daily, snapshots, now
        )
        if inputs is None:
            return ScanResult(underlying, None, None, None, tuple(input_reasons))
        score = score_signal(inputs)
        if score.regime == Regime.NO_TRADE:
            return ScanResult(underlying, score, None, None, score.reasons)
        candidates = self._option_candidates(underlying, inputs.price, snapshots, now)
        if not candidates:
            return ScanResult(
                underlying,
                score,
                None,
                None,
                ("no fresh liquid contracts with Greeks were available",),
            )
        spread = build_debit_spread(
            candidates,
            score.regime,
            min_dte=self.settings.min_dte,
            max_dte=self.settings.max_dte,
            max_leg_spread_pct=self.settings.max_bid_ask_spread_pct,
        )
        if spread is None:
            return ScanResult(
                underlying, score, None, None, ("no valid defined-risk debit spread was available",)
            )
        opportunity = Opportunity(
            candidate=spread.long_leg,
            return_1d_pct=percent_return([float(item["c"]) for item in daily], 1),
            return_5d_pct=inputs.return_5d_pct,
            realized_volatility=inputs.realized_volatility,
            evidence=[
                f"deterministic score: {score.score}",
                f"daily regime contribution: {score.daily_regime}",
                f"intraday trend contribution: {score.intraday_trend}",
                f"volume confirmation contribution: {score.volume_confirmation}",
                f"volatility contribution: {score.volatility_state}",
                f"market alignment contribution: {score.market_alignment}",
                f"conservative spread debit: {spread.debit:.2f}",
            ],
        )
        return ScanResult(underlying, score, opportunity, spread, ())

    def _signal_inputs(
        self,
        underlying: str,
        daily: list[dict],
        intraday: list[dict],
        market_daily: list[dict],
        snapshots: dict[str, dict],
        now: datetime,
    ) -> tuple[SignalInputs | None, list[str]]:
        # An unavailable/empty provider response is a no-trade condition, not a crash.
        daily = daily or []
        intraday = intraday or []
        market_daily = market_daily or []
        snapshots = snapshots or {}
        daily_closes = [float(row["c"]) for row in daily if "c" in row]
        intraday_rows = sorted(
            [row for row in intraday if {"c", "h", "l", "v", "t"}.issubset(row)],
            key=lambda row: row["t"],
        )
        intraday_closes = [float(row["c"]) for row in intraday_rows]
        market_closes = [float(row["c"]) for row in market_daily if "c" in row]
        reasons: list[str] = []
        if len(daily_closes) < 22:
            reasons.append("insufficient completed daily bars")
        if len(intraday_rows) < 21:
            reasons.append("insufficient completed 30-minute bars")
        if len(market_closes) < 2:
            reasons.append("insufficient SPY market-alignment bars")
        iv = self._current_iv(underlying, snapshots, now)
        if iv is None:
            reasons.append("implied-volatility state requires two fresh scanner observations")
        if reasons:
            return None, reasons
        assert iv is not None
        session = [
            row
            for row in intraday_rows
            if self._parse_timestamp(str(row["t"])).date() == now.date()
            and self._parse_timestamp(str(row["t"])) + timedelta(minutes=30) <= now
        ]
        if not session:
            return None, ["no completed intraday bars in the current session"]
        return (
            SignalInputs(
                price=intraday_closes[-1],
                ema_20=ema(daily_closes, 20)[-1],
                return_5d_pct=percent_return(daily_closes, 5),
                ema_fast=ema(intraday_closes, 8)[-1],
                ema_slow=ema(intraday_closes, 21)[-1],
                vwap=vwap(
                    [float(row["h"]) for row in session],
                    [float(row["l"]) for row in session],
                    [float(row["c"]) for row in session],
                    [float(row["v"]) for row in session],
                ),
                volume_ratio=volume_ratio([float(row["v"]) for row in intraday_rows]),
                realized_volatility=realized_volatility(daily_closes[-21:]),
                prior_realized_volatility=realized_volatility(daily_closes[-22:-1]),
                implied_volatility=iv[0],
                prior_implied_volatility=iv[1],
                market_return_1d_pct=percent_return(market_closes, 1),
            ),
            [],
        )

    def _current_iv(
        self, underlying: str, snapshots: dict[str, dict], now: datetime
    ) -> tuple[float, float] | None:
        values = [
            float(snapshot["impliedVolatility"])
            for snapshot in snapshots.values()
            if snapshot.get("impliedVolatility") is not None
        ]
        if not values:
            return None
        current = sorted(values)[len(values) // 2]
        previous = self._iv_history.get(underlying)
        self._iv_history[underlying] = (now, current)
        if previous is None or now - previous[0] > timedelta(hours=8):
            return None
        return current, previous[1]

    def _option_candidates(
        self, underlying: str, underlying_price: float, snapshots: dict[str, dict], now: datetime
    ) -> list[OptionCandidate]:
        candidates: list[OptionCandidate] = []
        for symbol, snapshot in snapshots.items():
            parsed = parse_option_symbol(symbol)
            if parsed is None:
                continue
            contract_underlying, expiry, option_type, strike = parsed
            if contract_underlying != underlying:
                continue
            quote = snapshot.get("latestQuote") or snapshot.get("latest_quote") or {}
            quote_timestamp = quote.get("t") or quote.get("timestamp")
            if not quote_timestamp or now - self._parse_timestamp(str(quote_timestamp)) > timedelta(
                minutes=15
            ):
                continue
            bid = float(quote.get("bp", quote.get("bid_price", 0)))
            ask = float(quote.get("ap", quote.get("ask_price", 0)))
            greeks = snapshot.get("greeks") or {}
            delta = greeks.get("delta")
            iv = snapshot.get("impliedVolatility", snapshot.get("implied_volatility"))
            dte = (expiry - now.date()).days
            if bid <= 0 or ask <= bid or delta is None or iv is None:
                continue
            candidate = OptionCandidate(
                underlying=underlying,
                symbol=symbol,
                option_type=option_type,
                strike=strike,
                expiration=expiry.isoformat(),
                dte=dte,
                bid=bid,
                ask=ask,
                implied_volatility=float(iv),
                delta=float(delta),
                underlying_price=underlying_price,
            )
            if (
                self.settings.min_dte <= dte <= self.settings.max_dte
                and candidate.spread_pct <= self.settings.max_bid_ask_spread_pct
            ):
                candidates.append(candidate)
        return candidates

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        timestamp = datetime.fromisoformat(value)
        return (
            timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
        )
