import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .config import Settings


class AlpacaRESTClient:
    """Read-only trading/account and market-data client for the paper account."""

    trading_base_url = "https://paper-api.alpaca.markets"
    data_base_url = "https://data.alpaca.markets"

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def headers(self) -> dict[str, str]:
        if not self.settings.alpaca_api_key or not self.settings.alpaca_secret_key:
            raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env")
        return {
            "APCA-API-KEY-ID": self.settings.alpaca_api_key.get_secret_value(),
            "APCA-API-SECRET-KEY": self.settings.alpaca_secret_key.get_secret_value(),
        }

    async def _get(self, base_url: str, path: str, params: dict[str, Any] | None = None) -> dict:
        async with httpx.AsyncClient(base_url=base_url, timeout=20) as client:
            response = await client.get(path, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    async def account(self) -> dict:
        return await self._get(self.trading_base_url, "/v2/account")

    async def clock(self) -> dict:
        return await self._get(self.trading_base_url, "/v2/clock")

    async def positions(self) -> list[dict]:
        async with httpx.AsyncClient(base_url=self.trading_base_url, timeout=20) as client:
            response = await client.get("/v2/positions", headers=self.headers)
        response.raise_for_status()
        return response.json()

    async def orders(self) -> list[dict]:
        data = await self._get(self.trading_base_url, "/v2/orders", {"status": "all", "limit": 100})
        return data if isinstance(data, list) else []

    async def daily_bars(self, symbol: str, limit: int = 22) -> list[dict]:
        now = datetime.now(UTC)
        data = await self._get(
            self.data_base_url,
            f"/v2/stocks/{symbol}/bars",
            {
                "timeframe": "1Day",
                "start": (now - timedelta(days=max(45, limit * 2))).isoformat(),
                "end": now.isoformat(),
                "limit": limit,
                "feed": "iex",
                "sort": "desc",
            },
        )
        return list(reversed(self._bars_for_symbol(data, symbol)))

    async def intraday_bars(self, symbol: str, limit: int = 64) -> list[dict]:
        now = datetime.now(UTC)
        data = await self._get(
            self.data_base_url,
            f"/v2/stocks/{symbol}/bars",
            {
                "timeframe": "30Min",
                "start": (now - timedelta(days=14)).isoformat(),
                "end": now.isoformat(),
                "limit": limit,
                "feed": "iex",
                "sort": "desc",
            },
        )
        return list(reversed(self._bars_for_symbol(data, symbol)))

    async def option_snapshots(
        self, underlying: str, *, symbols: list[str] | None = None
    ) -> dict[str, dict]:
        today = datetime.now(UTC).date()
        params: dict[str, Any] = {"limit": 1000}
        if symbols:
            params["symbols"] = ",".join(symbols)
        else:
            # Alpaca defaults this endpoint to near expiries. Request the same
            # 14–28 DTE window that the defined-risk spread builder permits.
            params.update(
                {
                    "expiration_date_gte": (
                        today + timedelta(days=self.settings.min_dte)
                    ).isoformat(),
                    "expiration_date_lte": (
                        today + timedelta(days=self.settings.max_dte)
                    ).isoformat(),
                }
            )
        # Alpaca exposes the option chain and an exact-contract snapshot as
        # different endpoints.  The chain path accepts an underlying; the
        # multi-contract path requires `symbols` and has no underlying path.
        path = (
            "/v1beta1/options/snapshots" if symbols else f"/v1beta1/options/snapshots/{underlying}"
        )
        data = await self._get(self.data_base_url, path, params)
        snapshots = data.get("snapshots")
        return snapshots if isinstance(snapshots, dict) else {}

    @staticmethod
    def _bars_for_symbol(data: dict, symbol: str) -> list[dict]:
        """Normalize Alpaca's list/map/null bar response shapes to a safe list."""
        bars = data.get("bars")
        if isinstance(bars, dict):
            result = bars.get(symbol)
            return result if isinstance(result, list) else []
        return bars if isinstance(bars, list) else []

    async def market_snapshot(
        self, underlying: str
    ) -> tuple[list[dict], list[dict], list[dict], dict]:
        """Fetch the complete, read-only inputs required by the deterministic scanner."""
        market_symbol = "SPY" if underlying != "SPY" else underlying
        daily, intraday, market_daily, snapshots = await asyncio.gather(
            self.daily_bars(underlying, limit=30),
            self.intraday_bars(underlying, limit=64),
            self.daily_bars(market_symbol, limit=30),
            self.option_snapshots(underlying),
        )
        return daily, intraday, market_daily, snapshots
