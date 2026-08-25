# Historical options data limitations

VegaGuard's historical pipeline retrieves stock bars, option bars, option quotes,
option contracts, and current option snapshots from the documented Alpaca endpoints.
It is intentionally strict about what can support a historical options P&L claim.

## Contract point-in-time handling

Alpaca's contracts-search response is observed at download time. The replay will
not use that response for an earlier decision. Instead, when a historical option
quote exists, VegaGuard derives the immutable OCC metadata (underlying, expiry,
call/put, and strike) from that quote's contract symbol and records the earliest
quote timestamp as `observed_at`. A historical quote proves that this metadata was
available at that point in time.

## Greeks and implied volatility

The snapshots endpoint is a current-state endpoint. It is cached for a read-only
live scanner but is not silently treated as historical IV or Greeks. The replay
requires point-in-time Greeks and a prior IV observation; if either is unavailable,
it rejects the opportunity and reports `STOCK-SIGNAL-ONLY ANALYSIS` rather than
inventing an options result.

## Feed limits

Alpaca offers historical option data from February 2024. The free indicative feed
is delayed and derived from OPRA; OPRA is subscription-dependent. Cache manifests
record the selected feed, request time, data kind, endpoint, and request IDs when
available. Downloaded data is excluded from Git.

## Current research conclusion

Until credentials are supplied and a reproducible cache contains the required
point-in-time option quote, Greek, IV, and contract observations, VegaGuard's
options performance conclusion is **inconclusive**. No synthetic fixture or
stock-only signal is included in an options P&L number.
