from datetime import UTC, date, datetime
from math import sqrt

from .alpaca_api import AlpacaRESTClient
from .config import Settings
from .models import Opportunity, OptionCandidate


def parse_option_symbol(symbol: str) -> tuple[str, date, str, float] | None:
    """Parse OCC symbols such as SPY260918C00650000 without relying on a stale chain cache."""
    if len(symbol) < 15:
        return None
    try:
        tail = symbol[-15:]
        underlying, yymmdd, option_code, strike_millis = symbol[:-15], tail[:6], tail[6], tail[7:]
        expiry = datetime.strptime(yymmdd, "%y%m%d").replace(tzinfo=UTC).date()
        option_type = {"C": "call", "P": "put"}[option_code]
        return underlying, expiry, option_type, int(strike_millis) / 1000
    except (KeyError, ValueError):
        return None


def daily_return(closes: list[float], periods: int) -> float:
    if len(closes) <= periods:
        return 0.0
    return (closes[-1] / closes[-1 - periods] - 1) * 100


def realized_volatility(closes: list[float]) -> float:
    returns = [closes[index] / closes[index - 1] - 1 for index in range(1, len(closes))]
    if len(returns) < 2:
        return 0.0
    average = sum(returns) / len(returns)
    variance = sum((item - average) ** 2 for item in returns) / (len(returns) - 1)
    return sqrt(variance) * sqrt(252)


class OpportunityScanner:
    def __init__(self, settings: Settings, alpaca: AlpacaRESTClient):
        self.settings = settings
        self.alpaca = alpaca

    async def scan(self, underlying: str) -> Opportunity | None:
        bars, snapshots = (
            await self.alpaca.daily_bars(underlying),
            await self.alpaca.option_snapshots(underlying),
        )
        closes = [float(bar["c"]) for bar in bars if "c" in bar]
        if len(closes) < 8:
            return None
        one_day, five_day = daily_return(closes, 1), daily_return(closes, 5)
        direction = "call" if one_day >= 0 else "put"
        chosen = self._choose_contract(underlying, closes[-1], direction, snapshots)
        if chosen is None:
            return None
        evidence = [
            f"1-day underlying return: {one_day:.2f}%",
            f"5-day underlying return: {five_day:.2f}%",
            f"annualized realized volatility: {realized_volatility(closes):.2%}",
            f"option spread: {chosen.spread_pct:.2%}",
        ]
        return Opportunity(
            candidate=chosen,
            return_1d_pct=one_day,
            return_5d_pct=five_day,
            realized_volatility=realized_volatility(closes),
            evidence=evidence,
        )

    def _choose_contract(
        self, underlying: str, underlying_price: float, direction: str, snapshots: dict[str, dict]
    ) -> OptionCandidate | None:
        today = datetime.now(UTC).date()
        ranked: list[OptionCandidate] = []
        for symbol, snapshot in snapshots.items():
            parsed = parse_option_symbol(symbol)
            if parsed is None:
                continue
            contract_underlying, expiry, option_type, strike = parsed
            if contract_underlying != underlying or option_type != direction:
                continue
            dte = (expiry - today).days
            quote = snapshot.get("latestQuote") or snapshot.get("latest_quote") or {}
            bid, ask = (
                float(quote.get("bp", quote.get("bid_price", 0))),
                float(quote.get("ap", quote.get("ask_price", 0))),
            )
            if bid <= 0 or ask <= bid:
                continue
            greeks = snapshot.get("greeks") or {}
            candidate = OptionCandidate(
                underlying=underlying,
                symbol=symbol,
                option_type=option_type,
                strike=strike,
                expiration=expiry.isoformat(),
                dte=dte,
                bid=bid,
                ask=ask,
                implied_volatility=snapshot.get(
                    "impliedVolatility", snapshot.get("implied_volatility")
                ),
                delta=greeks.get("delta"),
                underlying_price=underlying_price,
            )
            if not self.settings.min_dte <= dte <= self.settings.max_dte:
                continue
            if candidate.spread_pct > self.settings.max_bid_ask_spread_pct:
                continue
            ranked.append(candidate)
        if not ranked:
            return None
        # Prefer an at-the-money contract with a useful but not extreme delta.
        return min(
            ranked,
            key=lambda item: (
                abs(abs(item.delta) - 0.45) if item.delta is not None else 2,
                abs(item.strike - underlying_price),
                item.spread_pct,
            ),
        )
