"""Validated normalization of Alpaca payloads into replay-friendly JSON records."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .alpaca import HistoricalDataError, normalize_timestamp

_OCC_SYMBOL = re.compile(r"^[A-Z]{1,5}\d{6,7}[CP]\d{8}$")


def is_valid_option_symbol(value: str) -> bool:
    """Return whether a symbol matches Alpaca's queryable OCC format."""

    return bool(_OCC_SYMBOL.fullmatch(value))


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise HistoricalDataError(f"Expected '{key}' to be a list after pagination")
    return [row for row in value if isinstance(row, dict)]


def normalize_bars(payload: dict[str, Any], *, timeframe: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in _rows(payload, "bars"):
        try:
            records.append(
                {
                    "symbol": str(row["symbol"]),
                    "timestamp": normalize_timestamp(str(row["t"])),
                    "open": float(row["o"]),
                    "high": float(row["h"]),
                    "low": float(row["l"]),
                    "close": float(row["c"]),
                    "volume": float(row["v"]),
                    "timeframe": timeframe,
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalDataError(f"Malformed bar: {row!r}") from exc
    return sorted(records, key=lambda item: (item["symbol"], item["timestamp"]))


def normalize_option_contracts(
    payload: dict[str, Any], *, observed_at: str | None = None
) -> list[dict[str, Any]]:
    observed = observed_at or datetime.now(UTC).isoformat()
    records: list[dict[str, Any]] = []
    for row in _rows(payload, "option_contracts"):
        try:
            symbol = str(row["symbol"])
            if not is_valid_option_symbol(symbol):
                # Keep malformed provider rows in the raw cache, but never send
                # them back to an endpoint that rejects the entire symbol batch.
                continue
            records.append(
                {
                    "symbol": symbol,
                    "underlying": str(row["underlying_symbol"]),
                    "option_type": str(row["type"]),
                    "strike": float(row["strike_price"]),
                    "expiration": str(row["expiration_date"]),
                    # This is deliberately preserved. Backtest code will reject metadata
                    # observed after its decision timestamp instead of leaking it backward.
                    "observed_at": normalize_timestamp(observed),
                    "status": str(row.get("status", "unknown")),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalDataError(f"Malformed option contract: {row!r}") from exc
    return sorted(records, key=lambda item: item["symbol"])


def normalize_option_quotes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in _rows(payload, "quotes"):
        try:
            symbol = str(row["symbol"])
            if not is_valid_option_symbol(symbol):
                continue
            records.append(
                {
                    "symbol": symbol,
                    "timestamp": normalize_timestamp(str(row["t"])),
                    "bid": float(row["bp"]),
                    "ask": float(row["ap"]),
                    "bid_size": float(row.get("bs", 0)),
                    "ask_size": float(row.get("as", 0)),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalDataError(f"Malformed option quote: {row!r}") from exc
    return sorted(records, key=lambda item: (item["symbol"], item["timestamp"]))


def normalize_option_snapshots(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize snapshots; rows without a quote or usable Greeks remain absent."""
    records: list[dict[str, Any]] = []
    for row in _rows(payload, "snapshots"):
        quote = row.get("latestQuote") or row.get("latest_quote")
        greeks = row.get("greeks")
        if not isinstance(quote, dict) or not isinstance(greeks, dict):
            continue
        timestamp = quote.get("t") or quote.get("timestamp")
        try:
            records.append(
                {
                    "symbol": str(row["symbol"]),
                    "timestamp": normalize_timestamp(str(timestamp)),
                    "bid": float(quote.get("bp", quote.get("bid_price"))),
                    "ask": float(quote.get("ap", quote.get("ask_price"))),
                    "delta": float(greeks["delta"]),
                    "implied_volatility": float(
                        row.get("impliedVolatility", row.get("implied_volatility"))
                    ),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(records, key=lambda item: (item["symbol"], item["timestamp"]))


def contracts_observed_in_historical_quotes(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive immutable OCC metadata from the first real historical quote.

    A contract's OCC symbol encodes its underlying, expiry, type, and strike. A
    historical quote proves that this immutable metadata was observable at that
    quote timestamp, avoiding a current contracts-search response leaking into
    a historical decision. This does not manufacture Greeks or IV.
    """
    observed: dict[str, dict[str, Any]] = {}
    for quote in quotes:
        symbol = str(quote.get("symbol", ""))
        if not is_valid_option_symbol(symbol) or not quote.get("timestamp"):
            continue
        try:
            tail = symbol[-15:]
            underlying = symbol[:-15]
            expiry = datetime.strptime(tail[:6], "%y%m%d").replace(tzinfo=UTC).date().isoformat()
            option_type = {"C": "call", "P": "put"}[tail[6]]
            strike = int(tail[7:]) / 1000
            timestamp = normalize_timestamp(str(quote["timestamp"]))
        except (KeyError, ValueError):
            continue
        existing = observed.get(symbol)
        if existing is None or timestamp < existing["observed_at"]:
            observed[symbol] = {
                "symbol": symbol,
                "underlying": underlying,
                "option_type": option_type,
                "strike": strike,
                "expiration": expiry,
                "observed_at": timestamp,
                "status": "observed_in_historical_quote",
            }
    return sorted(observed.values(), key=lambda item: item["symbol"])
