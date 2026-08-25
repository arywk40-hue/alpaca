"""Validated normalization of Alpaca payloads into replay-friendly JSON records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .alpaca import HistoricalDataError, normalize_timestamp


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
            records.append(
                {
                    "symbol": str(row["symbol"]),
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
            records.append(
                {
                    "symbol": str(row["symbol"]),
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
