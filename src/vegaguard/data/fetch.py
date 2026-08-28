"""Read-only download orchestration for reproducible historical research."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from .alpaca import HistoricalMarketDataProvider
from .cache import LocalMarketDataCache
from .normalize import (
    contracts_observed_in_historical_quotes,
    normalize_bars,
    normalize_option_contracts,
    normalize_option_quotes,
    normalize_option_snapshots,
)


async def fetch_history(
    provider: HistoricalMarketDataProvider,
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache_root: str | Path = "data",
    stock_feed: str = "iex",
    include_options: bool = True,
) -> dict[str, int]:
    """Fetch and preserve a terminal manifest status even when access fails."""
    cache = LocalMarketDataCache(cache_root)
    cache.record_fetch_status(
        "started",
        symbols=symbols,
        start=start,
        end=end,
        include_options=include_options,
    )
    try:
        result = await _fetch_history(
            provider,
            symbols=symbols,
            start=start,
            end=end,
            cache=cache,
            stock_feed=stock_feed,
            include_options=include_options,
        )
    except Exception as exc:
        cache.record_fetch_status(
            "failed",
            symbols=symbols,
            start=start,
            end=end,
            include_options=include_options,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    cache.record_fetch_status(
        "completed",
        symbols=symbols,
        start=start,
        end=end,
        include_options=include_options,
        counts=result,
    )
    return result


async def _fetch_history(
    provider: HistoricalMarketDataProvider,
    *,
    symbols: list[str],
    start: str,
    end: str,
    cache: LocalMarketDataCache,
    stock_feed: str,
    include_options: bool,
) -> dict[str, int]:
    """Download stock bars and cache a safe, explicitly limited option-data scaffold.

    Alpaca does not expose an as-of timestamp on the contracts search endpoint.
    We cache the observation time and the replay refuses to use metadata observed
    after a decision. Consequently a fresh contracts fetch alone cannot become a
    historical-options performance claim; it is retained for auditability and
    future recordings whose metadata was captured at the decision time.
    """
    common = {
        "symbols": ",".join(symbols),
        "start": start,
        "end": end,
        "limit": 10_000,
        "sort": "asc",
    }
    daily_payload = await provider.stock_bars(timeframe="1Day", feed=stock_feed, **common)
    daily_request_id = _response_ids(provider)
    intraday_payload = await provider.stock_bars(timeframe="30Min", feed=stock_feed, **common)
    intraday_request_id = _response_ids(provider)
    cache.write_raw(
        "stock_daily",
        daily_payload,
        endpoint="/v2/stocks/bars",
        symbols=symbols,
        start=start,
        end=end,
        feed=stock_feed,
        data_kind="stock-bars",
        request_id=daily_request_id,
    )
    cache.write_raw(
        "stock_30min",
        intraday_payload,
        endpoint="/v2/stocks/bars",
        symbols=symbols,
        start=start,
        end=end,
        feed=stock_feed,
        data_kind="stock-bars",
        request_id=intraday_request_id,
    )
    daily = normalize_bars(daily_payload, timeframe="1Day")
    intraday = normalize_bars(intraday_payload, timeframe="30Min")
    cache.write_normalized(
        "stock_daily",
        daily,
        endpoint="/v2/stocks/bars",
        symbols=symbols,
        start=start,
        end=end,
        feed=stock_feed,
        data_kind="stock-bars",
    )
    cache.write_normalized(
        "stock_30min",
        intraday,
        endpoint="/v2/stocks/bars",
        symbols=symbols,
        start=start,
        end=end,
        feed=stock_feed,
        data_kind="stock-bars",
    )

    # Contract discovery is read-only. A recent historical window can refer to
    # still-active expiries, while an older one needs inactive contracts. Fetch
    # both status classes and deduplicate by OCC symbol. `observed_at` still
    # prevents the current search response from leaking backward into replay.
    start_date = date.fromisoformat(start[:10])
    end_date = date.fromisoformat(end[:10])
    contract_params = {
        "underlying_symbols": ",".join(symbols),
        "expiration_date_gte": (start_date + timedelta(days=14)).isoformat(),
        "expiration_date_lte": (end_date + timedelta(days=28)).isoformat(),
        "limit": 10_000,
    }
    active_contracts_payload = await provider.option_contracts(status="active", **contract_params)
    active_contracts_request_id = _response_ids(provider)
    inactive_contracts_payload = await provider.option_contracts(
        status="inactive", **contract_params
    )
    inactive_contracts_request_id = _response_ids(provider)
    contracts_payload = _merge_contract_payloads(
        active_contracts_payload, inactive_contracts_payload
    )
    contracts_request_id = (
        ",".join(
            value for value in (active_contracts_request_id, inactive_contracts_request_id) if value
        )
        or None
    )
    observed_at = datetime.now().astimezone().isoformat()
    cache.write_raw(
        "option_contracts",
        contracts_payload,
        endpoint="/v2/options/contracts",
        symbols=symbols,
        start=start,
        end=end,
        feed=None,
        data_kind="option-chain",
        request_id=contracts_request_id,
    )
    contracts = normalize_option_contracts(contracts_payload, observed_at=observed_at)
    cache.write_normalized(
        "option_contracts",
        contracts,
        endpoint="/v2/options/contracts",
        symbols=symbols,
        start=start,
        end=end,
        feed=None,
        data_kind="option-chain",
    )

    option_bars: list[dict] = []
    option_quotes: list[dict] = []
    option_snapshots: list[dict] = []
    raw_option_bars: list[dict] = []
    raw_option_quotes: list[dict] = []
    raw_option_snapshots: list[dict] = []
    if include_options:
        # Alpaca options endpoints accept up to 100 contract symbols per request.
        # These are historical responses, not synthetic data. Their use in replay is
        # still gated on point-in-time contract metadata and contemporaneous Greeks/IV.
        option_symbols = [contract["symbol"] for contract in contracts]
        for offset in range(0, len(option_symbols), 100):
            chunk = option_symbols[offset : offset + 100]
            if not chunk:
                continue
            option_common = {
                "symbols": ",".join(chunk),
                "start": start,
                "end": end,
                "limit": 10_000,
                "sort": "asc",
            }
            bars_payload = await provider.option_bars(timeframe="30Min", **option_common)
            bars_request_ids = _response_ids(provider)
            quotes_payload = await provider.option_quotes(**option_common)
            quotes_request_ids = _response_ids(provider)
            snapshots_payload = await provider.option_snapshots(
                symbols=option_common["symbols"], limit=1_000
            )
            snapshots_request_ids = _response_ids(provider)
            raw_option_bars.append({"request_ids": bars_request_ids, "response": bars_payload})
            raw_option_quotes.append(
                {"request_ids": quotes_request_ids, "response": quotes_payload}
            )
            raw_option_snapshots.append(
                {"request_ids": snapshots_request_ids, "response": snapshots_payload}
            )
            option_bars.extend(normalize_bars(bars_payload, timeframe="30Min"))
            option_quotes.extend(normalize_option_quotes(quotes_payload))
            option_snapshots.extend(normalize_option_snapshots(snapshots_payload))
        cache.write_raw(
            "option_bars",
            raw_option_bars,
            endpoint="/v1beta1/options/bars",
            symbols=symbols,
            start=start,
            end=end,
            feed="indicative_or_opra",
            data_kind="option-bars",
            request_id=_bundle_request_ids(raw_option_bars),
        )
        cache.write_raw(
            "option_quotes",
            raw_option_quotes,
            endpoint="/v1beta1/options/quotes",
            symbols=symbols,
            start=start,
            end=end,
            feed="indicative_or_opra",
            data_kind="option-quote",
            request_id=_bundle_request_ids(raw_option_quotes),
        )
        cache.write_raw(
            "option_snapshots",
            raw_option_snapshots,
            endpoint="/v1beta1/options/snapshots",
            symbols=symbols,
            start=start,
            end=end,
            feed="indicative_or_opra",
            data_kind="option-snapshot",
            request_id=_bundle_request_ids(raw_option_snapshots),
        )
        cache.write_normalized(
            "option_bars",
            option_bars,
            endpoint="/v1beta1/options/bars",
            symbols=symbols,
            start=start,
            end=end,
            feed="indicative_or_opra",
            data_kind="option-bars",
        )
        cache.write_normalized(
            "option_quotes",
            option_quotes,
            endpoint="/v1beta1/options/quotes",
            symbols=symbols,
            start=start,
            end=end,
            feed="indicative_or_opra",
            data_kind="option-quote",
        )
        cache.write_normalized(
            "option_snapshots",
            option_snapshots,
            endpoint="/v1beta1/options/snapshots",
            symbols=symbols,
            start=start,
            end=end,
            feed="indicative_or_opra",
            data_kind="option-snapshot",
        )
        # A historical quote proves its OCC metadata existed at that timestamp.
        # Preserve the future-observed contracts response too for auditability, but
        # make these point-in-time records available to the replay engine.
        derived_contracts = contracts_observed_in_historical_quotes(option_quotes)
        contracts_by_symbol = {contract["symbol"]: contract for contract in contracts}
        contracts_by_symbol.update({contract["symbol"]: contract for contract in derived_contracts})
        contracts = sorted(contracts_by_symbol.values(), key=lambda contract: contract["symbol"])
        cache.write_normalized(
            "option_contracts",
            contracts,
            endpoint="/v2/options/contracts + OCC metadata observed in /v1beta1/options/quotes",
            symbols=symbols,
            start=start,
            end=end,
            feed="indicative_or_opra",
            data_kind="option-chain",
        )
    return {
        "daily_bars": len(daily),
        "intraday_bars": len(intraday),
        "contracts": len(contracts),
        "option_bars": len(option_bars),
        "option_quotes": len(option_quotes),
        "option_snapshots": len(option_snapshots),
    }


def _response_ids(provider: HistoricalMarketDataProvider) -> str | None:
    request_ids = getattr(provider, "last_request_ids", [])
    return ",".join(request_ids) if request_ids else None


def _bundle_request_ids(pages: list[dict]) -> str | None:
    request_ids = [
        request_id
        for page in pages
        for request_id in str(page.get("request_ids") or "").split(",")
        if request_id
    ]
    return ",".join(request_ids) if request_ids else None


def _merge_contract_payloads(*payloads: dict) -> dict[str, list[dict]]:
    """Deduplicate active/inactive contract responses without altering raw quotes."""
    by_symbol: dict[str, dict] = {}
    for payload in payloads:
        rows = payload.get("option_contracts", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("symbol"):
                by_symbol.setdefault(str(row["symbol"]), row)
    return {"option_contracts": list(by_symbol.values())}
