"""Read-only Alpaca historical API adapter.

Endpoint paths are intentionally kept here, not in strategy code:
* ``GET https://data.alpaca.markets/v2/stocks/bars``
* ``GET https://data.alpaca.markets/v1beta1/options/bars``
* ``GET https://data.alpaca.markets/v1beta1/options/snapshots``
* ``GET https://paper-api.alpaca.markets/v2/options/contracts``

Alpaca's documented latest quote path is
``https://data.alpaca.markets/v1beta1/options/quotes/latest``. There is no
historical quote-history method here because ``/v1beta1/options/quotes`` was
verified to return ``404 Not Found``.

The adapter has no trading methods and cannot submit an order.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, Self

import httpx

HISTORICAL_OPTION_QUOTES_PATH = "/v1beta1/options/quotes"
LATEST_OPTION_QUOTES_PATH = "/v1beta1/options/quotes/latest"
HISTORICAL_OPTION_QUOTES_LIMITATION = (
    "Alpaca does not expose historical option bid/ask quotes at "
    f"{HISTORICAL_OPTION_QUOTES_PATH}; the verified GET request returned 404 Not Found. "
    f"The documented quote endpoint is {LATEST_OPTION_QUOTES_PATH} (latest only), "
    "so this cache cannot support point-in-time option threshold optimization."
)


class HistoricalDataError(RuntimeError):
    pass


class HistoricalMarketDataProvider(Protocol):
    async def stock_bars(self, **params: Any) -> dict[str, Any]: ...

    async def option_bars(self, **params: Any) -> dict[str, Any]: ...

    async def option_contracts(self, **params: Any) -> dict[str, Any]: ...

    async def option_snapshots(self, **params: Any) -> dict[str, Any]: ...


class AlpacaHistoricalDataProvider:
    market_data_url = "https://data.alpaca.markets"
    trading_url = "https://paper-api.alpaca.markets"

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
    ) -> None:
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
        self._client = client or httpx.AsyncClient(headers=self._headers, timeout=30.0)
        self._owns_client = client is None
        self.max_retries = max_retries
        self.request_ids: list[str] = []
        self.last_request_ids: list[str] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def stock_bars(self, **params: Any) -> dict[str, Any]:
        return await self._paginate("/v2/stocks/bars", params, market_data=True)

    async def option_bars(self, **params: Any) -> dict[str, Any]:
        return await self._paginate("/v1beta1/options/bars", params, market_data=True)

    async def option_snapshots(self, **params: Any) -> dict[str, Any]:
        return await self._paginate("/v1beta1/options/snapshots", params, market_data=True)

    async def option_contracts(self, **params: Any) -> dict[str, Any]:
        return await self._paginate("/v2/options/contracts", params, market_data=False)

    async def _paginate(
        self, path: str, params: Mapping[str, Any], *, market_data: bool
    ) -> dict[str, Any]:
        self.last_request_ids = []
        url = f"{self.market_data_url if market_data else self.trading_url}{path}"
        page_params = {key: value for key, value in params.items() if value is not None}
        collected: dict[str, list[Any]] = {}
        while True:
            body = await self._get_json(url, page_params)
            for key, value in body.items():
                if key == "next_page_token":
                    continue
                if isinstance(value, dict):
                    target = collected.setdefault(key, [])
                    for symbol, rows in value.items():
                        if isinstance(rows, list):
                            target.extend({"symbol": symbol, **row} for row in rows)
                        elif isinstance(rows, dict):
                            target.append({"symbol": symbol, **rows})
                        else:
                            raise HistoricalDataError(
                                f"Unexpected {key} payload for {symbol}: expected list or object"
                            )
                elif isinstance(value, list):
                    collected.setdefault(key, []).extend(value)
                else:
                    collected.setdefault(key, []).append(value)
            token = body.get("next_page_token")
            if not token:
                return collected
            page_params["page_token"] = token

    async def _get_json(self, url: str, params: Mapping[str, Any]) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            response = await self._client.get(url, params=params, headers=self._headers)
            request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
            if request_id:
                self.request_ids.append(request_id)
                self.last_request_ids.append(request_id)
            if response.status_code == 429 and attempt < self.max_retries:
                retry_after = response.headers.get("retry-after")
                delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                await asyncio.sleep(delay)
                continue
            if response.is_error:
                raise HistoricalDataError(
                    f"Alpaca historical request failed ({response.status_code}) for {response.url}: "
                    f"{response.text[:300]}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise HistoricalDataError("Alpaca returned malformed JSON") from exc
            if not isinstance(payload, dict):
                raise HistoricalDataError("Alpaca response must be a JSON object")
            return payload
        raise HistoricalDataError("Alpaca rate limit retries exhausted")


def normalize_timestamp(value: str) -> str:
    """Normalize Alpaca RFC-3339 timestamps to UTC ISO-8601 strings."""
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone(UTC).isoformat()
