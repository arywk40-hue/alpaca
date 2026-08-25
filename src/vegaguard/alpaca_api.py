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

    async def daily_bars(self, symbol: str, limit: int = 22) -> list[dict]:
        data = await self._get(
            self.data_base_url,
            f"/v2/stocks/{symbol}/bars",
            {"timeframe": "1Day", "limit": limit, "feed": "iex"},
        )
        return data.get("bars", {}).get(symbol, [])

    async def option_snapshots(self, underlying: str) -> dict[str, dict]:
        data = await self._get(self.data_base_url, f"/v1beta1/options/snapshots/{underlying}")
        return data.get("snapshots", {})
