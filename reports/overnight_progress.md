# VegaGuard overnight progress

Date: 2026-08-28

## Delivered research and safety work

- Durable, append-only IV observations support research-only IV percentile, put/call skew, term structure, source labels, and quote-freshness evidence. Scanner reads are explicitly filtered as-of their timestamp, excluding future-dated observations and quotes.
- The shadow ledger groups repeated scans under stable `opportunity_id` values while preserving individual observations. It records pending, priced, unavailable, and overdue 15/30/60-minute reprice states.
- Shadow outcomes remain separate from selected and exploration outcomes. Conservative hypothetical P&L is always labelled hypothetical and is never included in paper-fill or realized-P&L counters.
- Dashboard health now exposes `running`, `waiting`, `stopped`, `stale`, and `error` states with last-cycle status, next run, last error, and latest journal timestamp. Its visible banner labels shadow/reprice P&L as hypothetical evidence.
- Historical replay uses only local normalized records, point-in-time contract/quote metadata, ask-side entry and bid-side exit economics, declared fees/slippage, and explicit missing-data rejections. It reports expectancy per completed trade and a missing-data rate in addition to win rate, profit factor, and drawdown.
- Replay now has an optional fixed `--exit-horizon-minutes {15,30,60}` mode. It uses the first fresh option-quote event at or after the selected horizon; it has no live-execution effect.
- Failed historical downloads now leave an auditable `started`/`failed` lifecycle in `cache_manifest.json`. Replays from that cache are labelled `INCOMPLETE HISTORICAL DATASET`, not historical options performance.
- `vegaguard demo` now creates a credential-free `SIMULATION_REPLAY` lifecycle artifact: scan → candidate → deterministic risk decision → simulated entry → simulated 15/30-minute monitoring → simulated 60-minute exit. It is wholly sourced from the sanitized fixture and keeps paper counters at zero.

## Files changed

Primary implementation and tests include:

- `src/vegaguard/data/cache.py`, `src/vegaguard/data/fetch.py`
- `src/vegaguard/strategy/backtest.py`, `src/vegaguard/strategy/research.py`
- `src/vegaguard/service.py`, `src/vegaguard/storage.py`, `src/vegaguard/shadow_reporting.py`
- `src/vegaguard/dashboard.py`, `src/vegaguard/scheduler.py`, `src/vegaguard/journal.py`
- `src/vegaguard/demo.py`, `src/vegaguard/cli.py`
- `src/vegaguard/api.py`, `src/vegaguard/controller.py`
- `tests/test_historical_data.py`, `tests/test_historical_backtest.py`, `tests/test_shadow_evaluation.py`, `tests/test_demo.py`, plus the existing safety and scheduler suites
- `tests/test_controller.py`
- `tests/fixtures/strategy_replay_sanitized.json`
- `README.md`, `docs/STRATEGY.md`, `docs/HISTORICAL_DATA_LIMITATIONS.md`, and `docs/OPERATOR_RUNBOOK.md`

## Commands added or extended

```bash
# Credential-free, fixture-only lifecycle evidence.
vegaguard demo --output-dir results/offline_demo

# Point-in-time research only; optional fixed exit at 15, 30, or 60 minutes.
vegaguard strategy backtest ... --exit-horizon-minutes 15
vegaguard strategy walk-forward ... --exit-horizon-minutes 30
vegaguard strategy calibrate-confidence ... --exit-horizon-minutes 60

# Read-only live shadow evidence (never a paper-fill report).
vegaguard live shadow-candidates --limit 20
vegaguard live session-report

# Backend-managed dashboard controller and SSE event stream.
PYTHONPATH=src uvicorn vegaguard.api:app --host 127.0.0.1 --port 8000
```

`vegaguard demo` writes `simulated_lifecycle.json` with `mode: SIMULATION_REPLAY` and explicit zero values for submitted, acknowledged, filled, and realized paper trades.

## Verification performed

```text
PYTHONPATH=src .venv/bin/vegaguard demo --output-dir /private/tmp/vegaguard_demo_verify
.venv/bin/ruff format --check src tests
.venv/bin/ruff check src tests
.venv/bin/pytest
```

Results:

- Demo: 3 sanitized observations, 2 simulated plans, 2 simulated exits, and all paper counters equal to zero.
- Ruff format: 65 files already formatted.
- Ruff lint: all checks passed.
- Pytest: 127 passed.

## Genuinely verified

- Deterministic fixture replay and simulated lifecycle work without Alpaca credentials or network access.
- The fixed-horizon replay path, historical-fetch failure classification, duplicate opportunity grouping, partial/completed repricing, fee/slippage accounting, heartbeat state, and execution safety gates are covered by tests.
- Dashboard-controller integration tests verify start/stop, server-lifespan shutdown, stale/error heartbeat visibility, fixture-only replay, locked submission, market-closed rejection, and exact-plan approval routing.
- Production scoring remains fixed at 70; research thresholds are separate and cannot promote themselves.

## Still unverified / external dependencies

- A genuine, sufficiently large point-in-time historical options cache is not available locally. The verified historical option-quotes request (`GET /v1beta1/options/quotes`) returned `404 Not Found`; Alpaca documents latest option quotes but not historical quote history at that path. The fetcher now records this capability limitation and makes no out-of-sample strategy-performance claim.
- No real paper order lifecycle has been performed or claimed. It requires a fresh market-hours plan and separate explicit operator authorization, and is outside this unattended safety run.
- Live shadow reprices and dashboard updates require a market-hours process plus fresh Alpaca quotes; fixture simulation does not substitute for them.

## Safety confirmation

No Alpaca order was submitted, no MCP execution tool was called, no command used `DRY_RUN=false`, and no production threshold or risk limit was changed during this work.
