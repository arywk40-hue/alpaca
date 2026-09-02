# VegaGuard

VegaGuard is a paper-only ETF options agent built for the Alpaca AI Trading Agents Hackathon. It scans liquid ETFs, constructs defined-risk debit spreads, challenges each plan with deterministic risk checks and records the full path from market evidence to realized paper P&L.

The central design choice is simple: **the model can explain a trade, but it cannot authorize one.**

```text
Alpaca data → scanner → spread builder → risk critic → exact plan
                                                        ↓
journal ← position guardian ← Alpaca MCP paper execution
   ↓
dashboard + shadow research
```

## Verified result

VegaGuard completed one provider-backed Alpaca paper lifecycle:

| Trade | Entry | Exit | Gross P&L |
| --- | ---: | ---: | ---: |
| IWM Sep. 25 292.5/284 bear-put spread, one contract | $2.62 debit | $2.64 credit | **+$2.00** |

The position entered on August 31, 2026 and exited on September 1. Alpaca did not report fees, so after-fee P&L is unknown. The observed maximum adverse and favorable excursions were −$85 and +$20. The exit was operator-authorized to complete the hackathon lifecycle; it was not triggered by a strategy profit target or stop.

One trade proves the workflow, not a durable edge. VegaGuard does not annualize this result, report a one-trade win rate or change its production threshold because of it.

## What is different

- **Exact-plan execution:** an approval expires after five minutes and binds the reviewed OCC symbols, quantity and limit debit. Submission refreshes those exact quotes.
- **Bounded model role:** the optional OpenAI explainer receives validated facts and returns strict JSON. It cannot change score, threshold, legs, quantity, risk or execution.
- **Counterfactual evidence:** rejected and below-threshold spreads are repriced at 15, 30 and 60 minutes. Repeated scans stay grouped as one opportunity.
- **Restart-safe monitoring:** the position guardian reconciles durable plans against Alpaca positions instead of relying on process memory.
- **Honest accounting:** simulation, hypothetical shadow results, plans, acknowledgements, fills, unrealized marks and realized P&L have separate labels and counters.

## Alpaca implementation

- Alpaca Market Data API: stock bars, option chains, snapshots and fresh leg quotes.
- Alpaca Trading API: paper account, clock, buying power, positions and order reconciliation.
- Official Alpaca MCP server: allowlisted `place_option_order` calls for atomic multi-leg paper orders.
- VegaGuard CLI: preflight, replay, scheduler, monitor, session reports and lifecycle evidence.
- FastAPI + SSE: local operator dashboard and live event timeline.
- JSONL + SQLite: append-only audit events and queryable candidate/repricing evidence.

The MCP dependency pair is pinned and its tool schemas are discovered during preflight. VegaGuard refuses a non-paper configuration.

## Strategy

The production scanner covers SPY, QQQ and IWM. It combines:

- daily regime — 25 points;
- intraday trend — 25 points;
- volume confirmation — 20 points;
- volatility state — 15 points;
- market alignment — 15 points.

The production threshold is fixed at 70. A bullish signal may create a bull-call debit spread; a bearish signal may create a bear-put debit spread. Every plan still has to pass quote freshness, liquidity, DTE, spread validation, buying-power, position-limit and maximum-loss checks.

Exploration is disabled by default and separately labelled. It never changes the production scorer or threshold.

## Safe local demo

Install and verify:

```bash
cp .env.example .env
uv sync --extra dev
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/pytest -q
```

Generate the credential-free replay:

```bash
.venv/bin/vegaguard replay --output-dir results/offline_demo
```

This replay is fixture-backed `SIMULATION_REPLAY` evidence. It exercises the lifecycle without an Alpaca order and never increments paper-fill counters.

Start the local dashboard:

```bash
PYTHONPATH=src .venv/bin/python -m uvicorn vegaguard.api:app \
  --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. The default view is read-only. Mutation requests require a bearer token entered manually in local operator mode; the token stays in browser session memory and is never embedded in HTML or journal events.

## Read-only evidence commands

```bash
.venv/bin/vegaguard preflight
.venv/bin/vegaguard live read-only-cycle --cycles 2 --interval-seconds 60
.venv/bin/vegaguard live session-report
.venv/bin/vegaguard live lifecycle-evidence
```

`lifecycle-evidence` includes only trades with journaled provider entry and exit fills. Missing fees remain `null`.

## Safety defaults

```dotenv
ALPACA_PAPER_TRADE=true
ALLOW_ORDER_EXECUTION=false
DRY_RUN=true
EXPLORATION_MODE=false
```

Paper submission also requires an open market, fresh quotes, valid spread economics, passed risk gates, an explicit session arm and the exact unexpired `plan_id`. No dashboard control can bypass those checks. Credentials remain on the backend.

## Research boundary

The live shadow ledger uses real quote timestamps and conservative ask-to-enter/bid-to-exit marks. Those outcomes are hypothetical, not fills.

Historical threshold research is intentionally inconclusive when point-in-time option quotes are unavailable. During verification, the attempted Alpaca historical option quote route was unavailable while the documented endpoint supported latest quotes. VegaGuard marks the cache incomplete rather than using it to optimize the production threshold.

## Project guide

- [Submission copy](docs/HACKATHON_SUBMISSION.md)
- [10-slide deck](docs/HACKATHON_DECK_10_SLIDES.md)
- [Demo narration](docs/HACKATHON_NARRATION.md)
- [Three-minute demo route](docs/HACKATHON_DEMO.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Strategy and risk rules](docs/TRADING_STRATEGY.md)
- [Operator runbook](docs/OPERATOR_RUNBOOK.md)
- [Historical-data limitations](docs/HISTORICAL_DATA_LIMITATIONS.md)

## Scope

VegaGuard is an engineering and research project for Alpaca paper trading. It has no real-money execution path, and its single completed paper trade is not investment advice or evidence of expected returns.
