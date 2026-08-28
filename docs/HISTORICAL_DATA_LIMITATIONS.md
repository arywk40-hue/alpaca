# Historical options data limitations

VegaGuard's historical pipeline retrieves stock bars, option bars, option quotes,
option contracts, and current option snapshots from the documented Alpaca endpoints.
It is intentionally strict about what can support a historical options P&L claim.

## Dataset integrity

`data fetch-history` records `started`, `completed`, or `failed` in
`cache_manifest.json`. A failed fetch is retained for audit and debugging, but a
replay from that cache is labelled `INCOMPLETE HISTORICAL DATASET`, never a valid
historical-options result. The failure records its request error but no credentials.

## Contract point-in-time handling

Alpaca's contracts-search response is observed at download time. The replay will
not use that response for an earlier decision. Instead, when a historical option
quote exists, VegaGuard derives the immutable OCC metadata (underlying, expiry,
call/put, and strike) from that quote's contract symbol and records the earliest
quote timestamp as `observed_at`. A historical quote proves that this metadata was
available at that point in time.

## Greeks and implied volatility

The snapshots endpoint is a current-state endpoint. It is cached for a read-only
live scanner but is not silently treated as historical IV or Greeks. For a historical
quote without contemporaneous official Greeks, the replay may derive IV from that
quote's observed midpoint and Black–Scholes delta from the derived IV. It uses only
the most recent underlying 30-minute bar already complete at the option quote
timestamp, the OCC expiry/type/strike, and the declared risk-free rate. These
values are explicitly tagged `quote_derived`; later bars and current snapshots are
never substituted. If neither official point-in-time data nor this strict transform
is available, the replay rejects the opportunity and reports `STOCK-SIGNAL-ONLY
ANALYSIS` rather than inventing an options result.

## Feed limits

Alpaca offers historical option data from February 2024. The free indicative feed
is delayed and derived from OPRA; OPRA is subscription-dependent. Historical
option-bars and option-quotes requests may require an OPRA agreement and do not
accept a feed override. A 403 entitlement response is a data-access blocker, not
a strategy result. Cache manifests record the selected feed where the endpoint
supports one, plus request time, data kind, endpoint, and request IDs when
available. Downloaded data is excluded from Git.

## Current research conclusion

Until credentials are supplied and a reproducible cache contains the required
point-in-time option quote, Greek, IV, and contract observations, VegaGuard's
options performance conclusion is **inconclusive**. No synthetic fixture or
stock-only signal is included in an options P&L number.

## Fill-cost assumptions

The replay uses the observed executable long-ask/short-bid entry and long-bid/short-ask exit first.
It can then apply declared per-contract fees and per-leg slippage as separate cost columns. Those
assumptions are never treated as observed fills, never modify paper orders, and must be shown beside
every reported net P&L figure.
