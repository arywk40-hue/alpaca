from datetime import UTC, datetime, timedelta

import pytest

from vegaguard.alpaca_api import AlpacaRESTClient
from vegaguard.config import Settings


@pytest.mark.asyncio
async def test_bars_and_snapshots_normalize_null_api_payloads(monkeypatch):
    client = AlpacaRESTClient(Settings())

    async def empty_response(*_args, **_kwargs):
        return {"bars": None, "snapshots": None}

    monkeypatch.setattr(client, "_get", empty_response)
    assert await client.daily_bars("SPY") == []
    assert await client.intraday_bars("SPY") == []
    assert await client.option_snapshots("SPY") == {}


@pytest.mark.asyncio
async def test_bars_support_alpaca_map_and_list_response_shapes(monkeypatch):
    client = AlpacaRESTClient(Settings())
    responses = iter(({"bars": {"SPY": [{"c": 2}, {"c": 1}]}}, {"bars": [{"c": 4}, {"c": 3}]}))
    requests: list[dict] = []

    async def response(*args, **kwargs):
        requests.append(args[2] if len(args) > 2 else kwargs["params"])
        return next(responses)

    monkeypatch.setattr(client, "_get", response)
    assert await client.daily_bars("SPY") == [{"c": 1}, {"c": 2}]
    assert await client.intraday_bars("SPY") == [{"c": 3}, {"c": 4}]
    assert all(request["sort"] == "desc" for request in requests)
    assert all("start" in request and "end" in request for request in requests)


@pytest.mark.asyncio
async def test_option_snapshots_requests_the_configured_dte_window(monkeypatch):
    client = AlpacaRESTClient(Settings(min_dte=14, max_dte=28))
    requests: list[dict] = []

    async def response(*args, **kwargs):
        requests.append(args[2] if len(args) > 2 else kwargs["params"])
        return {"snapshots": {}}

    monkeypatch.setattr(client, "_get", response)
    assert await client.option_snapshots("SPY") == {}
    assert requests[0]["limit"] == 1000
    today = datetime.now(UTC).date()
    assert requests[0]["expiration_date_gte"] == (today + timedelta(days=14)).isoformat()
    assert requests[0]["expiration_date_lte"] == (today + timedelta(days=28)).isoformat()
