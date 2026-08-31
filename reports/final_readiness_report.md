# VegaGuard Final Readiness Report

Updated: 2026-09-01

## Outcome

VegaGuard is implemented as a judge-ready, paper-only options system with safe defaults, a backend-managed control plane, exact-plan approval, defined-risk debit-spread validation, durable lifecycle evidence, shadow evaluation and an offline deterministic demo. Production scoring remains unchanged at 70. Exploration remains disabled by default and uses a configurable threshold of 40.

Implementation and automated verification submitted no orders. Afterward, the operator
explicitly approved one short-lived IWM exploration plan for Alpaca paper execution.

## Implemented capabilities

- Backend-owned shadow scheduler and trade-update monitor with start, stop, stale/error heartbeat, clean shutdown and recovery from temporary cycle failures.
- Dashboard controls for shadow operation, visibly separate simulation replay, deliberate paper-session arm/disarm and emergency stop.
- A one-attempt session arm that requires the literal confirmation and is consumed after an exact-plan submission attempt.
- Stable, expiring plan IDs. Submission reloads the reviewed plan and rechecks paper account, market clock, exact option legs, quote freshness, quote drift, liquidity, buying power, position limits and full-debit maximum loss.
- Strict OCC debit-spread structure checks, one whole contract and one exploration position at a time.
- Order intent persisted before the MCP boundary, acknowledgement/error evidence afterward, idempotent client order IDs and no blind retry after an ambiguous submission.
- Canonical submitted/accepted/partially-filled/filled/cancelled/rejected tracking, exact spread exits and provider-attributed timestamps, IDs, fills and fees.
- Actual P&L only from provider entry/exit fills; unknown fees remain unknown. Simulation and hypothetical shadow results are separately labelled and never counted as paper fills or realized P&L.
- Durable candidate evidence with score components, rejection gates, risk-budget comparisons, exact leg quotes, IV, DTE, volume, open interest and 15/30/60-minute conservative repricing outcomes.
- Repeated scans grouped under one opportunity while preserving individual quote observations.
- Session reporting across thresholds 40/50/60/70, selected/exploration/shadow buckets, qualification and rejection distributions, quote/liquidity failures, win rate, profit factor, drawdown and explicit insufficient-evidence intervals.
- Historical option-surface cache, chronological replay, walk-forward research, cost/slippage sensitivity and deterministic offline replay.

## Main files changed

- Control and API: `src/vegaguard/controller.py`, `api.py`, `scheduler.py`, `dashboard.py`, `cli.py`.
- Safety and execution: `models.py`, `risk.py`, `service.py`, `execution.py`, `monitoring.py`, `preflight.py`, `mcp_client.py`.
- Evidence and research: `journal.py`, `storage.py`, `shadow_reporting.py`, `demo.py`, `strategy/backtest.py`, `strategy/metrics.py`, `strategy/research.py`, `strategy/option_surface.py`.
- Operator/submission material: `README.md`, `docs/ARCHITECTURE.md`, `docs/OPERATOR_RUNBOOK.md`, `docs/PAPER_ACCEPTANCE_CHECKLIST.md`, `docs/HACKATHON_DEMO.md`, `docs/HACKATHON_SUBMISSION.md`.
- Tests cover control-plane state, safety gates, exact-plan submission, lifecycle accounting, shadow repricing, replay and research behavior.

## Verification evidence

Commands completed:

```text
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/vegaguard replay
.venv/bin/vegaguard preflight
EXPLORATION_MODE=true ALLOW_ORDER_EXECUTION=true DRY_RUN=true \
  .venv/bin/vegaguard live run-scheduler --max-cycles 1
.venv/bin/vegaguard live lifecycle-evidence
```

Results:

- Ruff formatting: 87 files already formatted.
- Ruff lint: all checks passed.
- Tests: 174 passed. One dependency deprecation warning from FastAPI's Starlette test client; no test failures.
- Offline replay: three sanitized observations, two simulated plans and exits; all paper submitted/acknowledged/filled/realized counters remained zero.
- Redacted live readiness check on 2026-08-31: paper account active, provider account ID present, market open, 1,000 SPY option snapshots, 53 available MCP tools and no missing required tools. No account identifier or API credential was printed or persisted.
- Restart verification on 2026-09-01: preflight remained `ready` with the market
  closed, the configured paper-account match confirmed, 1,000 SPY option snapshots
  and all 53 MCP tools available. The Alpaca MCP/FastMCP compatibility pair is now
  pinned so a fresh `uvx` resolution cannot silently pull the incompatible FastMCP 4.
- Two live read-only observations established current IV state. The latest production results were SPY `0`, QQQ `-40` and IWM `-65`; all remained neutral below the fixed production threshold or failed agreement checks.
- Bounded exploration dry-runs: a one-contract SPY 764/750 bear-put spread passed deterministic risk at a $3.93 debit and $393 maximum loss; a later IWM 292.5/284 bear-put spread passed at a $2.67 debit and $267 maximum loss. Both five-minute plans expired without reuse, and `DRY_RUN=true` prevented every MCP order call.
- August 31 live shadow report: 48 observations grouped into 16 opportunities with
  86 quote-backed reprices. Five threshold-40 outcomes produced -$225.90 hypothetical
  net P&L under conservative ask-to-enter/bid-to-exit accounting. This small negative
  sample does not justify a threshold change; the fixed production threshold remains 70.
- Paper lifecycle evidence: one exact IWM bear-put spread was acknowledged and filled
  at a $2.62 debit on 2026-08-31. Its exit remains pending, so completed-trade count
  and realized P&L remain zero.

The full preflight schema is stored locally in `data/mcp_preflight.json`. Deterministic demo artifacts are in `results/offline_demo/`.

## Paper-trade readiness and remaining limitation

The execution plumbing has completed the entry half of a deliberately authorized
Alpaca paper lifecycle. Alpaca acknowledged and filled one IWM 292.5/284 bear-put
debit spread, expiring 2026-09-25, at $2.62 for one contract. At the 2026-08-31
close, the last conservative executable mark was $2.35, or -$27 unrealized. The
guardian correctly held because neither the +50% target nor -35% stop had triggered.
The full external lifecycle is not complete until the provider acknowledges and fills
the closing spread; realized P&L must remain zero until then.

Research evidence is also limited. The bundled fixture is sanitized and tiny, so its P&L is demonstration output rather than evidence of expected live performance. Threshold comparisons must not automatically alter the production threshold.

The historical Alpaca fetch was rechecked on 2026-08-29 with a valid local paper-account credential. The attempted
`GET /v1beta1/options/quotes` request returned `404 Not Found`; Alpaca documents latest option quotes
at `/v1beta1/options/quotes/latest`, not historical quote history at that path. The fetcher now records
this capability limitation and marks the resulting cache incomplete, so it cannot optimize thresholds
or claim historical options P&L.

## Exact operator sequence for completing the open paper lifecycle

Keep the dashboard, scheduler and trade-update monitor running. VegaGuard resumes
one-minute guardian checks when the U.S. options session opens. Do not create or
submit a second entry while the IWM spread is open; the one-position gate also
enforces this.

```bash
vegaguard live monitor-trade-updates
vegaguard live run-scheduler --interval-seconds 900
```

The next acceptance milestone is provider-backed evidence for
`approved -> submitted -> acknowledged -> filled -> monitored -> exit submitted -> closed -> actual fill-derived P&L`.
Any manual intervention must use the broker paper account and be journaled; it must
not bypass VegaGuard's deterministic exit or safety gates.
