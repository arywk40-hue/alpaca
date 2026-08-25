from datetime import UTC, datetime

import httpx
import pytest

from vegaguard.data.alpaca import AlpacaHistoricalDataProvider, HistoricalDataError
from vegaguard.data.cache import LocalMarketDataCache
from vegaguard.data.normalize import (
    contracts_observed_in_historical_quotes,
    normalize_bars,
    normalize_option_quotes,
)


@pytest.mark.asyncio
async def test_stock_bar_pagination_is_flattened_and_request_ids_are_retained():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert request.url.params["symbols"] == "SPY"
            return httpx.Response(
                200,
                headers={"x-request-id": "first"},
                json={"bars": {"SPY": [{"t": "2026-01-01T00:00:00Z"}]}, "next_page_token": "n"},
            )
        assert request.url.params["page_token"] == "n"
        return httpx.Response(
            200,
            headers={"x-request-id": "second"},
            json={"bars": {"SPY": [{"t": "2026-01-02T00:00:00Z"}]}, "next_page_token": None},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AlpacaHistoricalDataProvider("key", "secret", client=client)
        payload = await provider.stock_bars(symbols="SPY", timeframe="1Day")
    assert [row["symbol"] for row in payload["bars"]] == ["SPY", "SPY"]
    assert provider.request_ids == ["first", "second"]


@pytest.mark.asyncio
async def test_rate_limit_is_retried_and_malformed_json_is_rejected():
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"bars": {"SPY": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AlpacaHistoricalDataProvider("key", "secret", client=client)
        assert await provider.stock_bars(symbols="SPY", timeframe="1Day") == {"bars": []}
    assert calls == 2

    async def malformed(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    async with httpx.AsyncClient(transport=httpx.MockTransport(malformed)) as client:
        provider = AlpacaHistoricalDataProvider("key", "secret", client=client)
        with pytest.raises(HistoricalDataError, match="malformed JSON"):
            await provider.stock_bars(symbols="SPY", timeframe="1Day")


def test_normalizers_reject_bad_bars_and_missing_quote_fields():
    with pytest.raises(HistoricalDataError, match="Malformed bar"):
        normalize_bars({"bars": [{"symbol": "SPY", "t": "2026-01-01T00:00:00Z"}]}, timeframe="1Day")
    with pytest.raises(HistoricalDataError, match="Malformed option quote"):
        normalize_option_quotes(
            {"quotes": [{"symbol": "SPY260116C00600000", "t": "2026-01-01T00:00:00Z"}]}
        )


def test_normalized_bars_preserve_utc_timestamp():
    records = normalize_bars(
        {
            "bars": [
                {
                    "symbol": "SPY",
                    "t": "2026-01-01T10:00:00Z",
                    "o": 1,
                    "h": 2,
                    "l": 1,
                    "c": 2,
                    "v": 3,
                }
            ]
        },
        timeframe="30Min",
    )
    assert datetime.fromisoformat(records[0]["timestamp"]).tzinfo == UTC


def test_cache_manifest_captures_research_provenance(tmp_path):
    cache = LocalMarketDataCache(tmp_path / "data")
    cache.write_raw(
        "stock_daily",
        {"bars": []},
        endpoint="/v2/stocks/bars",
        symbols=["SPY"],
        start="2026-01-01",
        end="2026-01-31",
        feed="iex",
        data_kind="stock-bars",
        request_id="request-123",
    )
    manifest = (tmp_path / "data" / "cache_manifest.json").read_text()
    assert '"request_id": "request-123"' in manifest
    assert '"data_kind": "stock-bars"' in manifest
    assert '"path": "raw/stock_daily.json"' in manifest


def test_historical_quote_derives_only_point_in_time_occ_contract_metadata():
    contracts = contracts_observed_in_historical_quotes(
        [
            {"symbol": "SPY260918C00650000", "timestamp": "2026-08-20T14:00:00Z"},
            {"symbol": "SPY260918C00650000", "timestamp": "2026-08-19T14:00:00Z"},
        ]
    )
    assert contracts == [
        {
            "symbol": "SPY260918C00650000",
            "underlying": "SPY",
            "option_type": "call",
            "strike": 650.0,
            "expiration": "2026-09-18",
            "observed_at": "2026-08-19T14:00:00+00:00",
            "status": "observed_in_historical_quote",
        }
    ]
