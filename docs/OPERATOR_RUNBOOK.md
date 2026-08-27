# Operator runbook

Use a dedicated Alpaca paper account and keep these defaults in `.env`:

```dotenv
ALPACA_PAPER_TRADE=true
ALLOW_ORDER_EXECUTION=false
DRY_RUN=true
EXPLORATION_MODE=false
EXPLORATION_SCORE_THRESHOLD=40
```

`OPENAI_API_KEY` is optional. Without it, a local deterministic bounded thesis is used.

Install and verify without placing an order:

```bash
uv sync --extra dev
ruff check .
ruff format --check .
pytest -q
vegaguard preflight
vegaguard live read-only-cycle --cycles 2 --interval-seconds 60
```

The read-only command reuses one scanner process and also writes a durable IV observation, so later scanner processes can use a fresh prior observation. It prints each underlying's score, regime, confidence, data timestamp, and explicit abstention reasons. It cannot submit an order.

To review a paper order payload, first deliberately set only `ALLOW_ORDER_EXECUTION=true` and retain `DRY_RUN=true`. Run one market-hours scheduler cycle:

```bash
vegaguard live run-scheduler --interval-seconds 900 --max-cycles 1
```

The output includes the selected spread, legs, quantity, debit, maximum loss/profit, breakeven, guardian exits, risk approval, and the exact MCP payload. Review it before any further change.

Each approved dry run now includes a `plan_id`, both quote timestamps, and an `approval_expires_at` time
five minutes later. Do not rerun the scheduler to submit it: that could choose different legs. After an
operator explicitly approves that exact ID, with the monitor already running, submit it once using:

```bash
EXPLORATION_MODE=true ALLOW_ORDER_EXECUTION=true DRY_RUN=false \
  vegaguard live submit-approved --plan-id vg-plan-REPLACE_WITH_REVIEWED_ID
```

The command reloads the immutable dry-run plan without scanning again, rejects an expired plan or a prior
submission, and rechecks the current market, paper-account, buying-power, maximum-loss, and position gates.

Every market-hours scheduler cycle also persists a shadow-candidate record for each ETF. It records below-threshold and rejected candidates with real data/quote timestamps without altering the live threshold or submitting an order:

```bash
vegaguard live shadow-candidates --limit 20
```

## Paper-only exploration mode

Exploration is an opt-in, separately labelled paper experiment. It does not change the production
baseline scorer or its 70-point threshold. With `EXPLORATION_MODE=true`, VegaGuard may consider a
40-point-or-higher baseline score only after the existing fresh-quote, IV, liquidity, DTE, defined-risk
spread, buying-power, maximum-loss, and paper-account gates pass. It permits exactly one whole-contract
debit spread and refuses entry when any position is already open.

Start with a preview only; `DRY_RUN=true` prevents every MCP order call:

```bash
EXPLORATION_MODE=true EXPLORATION_SCORE_THRESHOLD=40 \
ALLOW_ORDER_EXECUTION=true DRY_RUN=true \
  vegaguard live run-scheduler --interval-seconds 900 --max-cycles 1
```

The journal and dashboard mark these records with `trade_mode: exploration`, the applicable score and
threshold, conservative candidate/entry quote, real quote timestamps, and a rejection reason when there
is no approved plan. Subsequent fill and position-mark events record observed exit quotes and P&L only
when available; costs and post-cost P&L remain `null` when Alpaca has not reported them. Do not use a
single exploration trade to alter the production threshold.

The dashboard calls a dry-run decision an **Approved exploration plan**, never a trade. Its paper-trade
counters require an Alpaca acknowledgement or an observed fill. For an exploration-qualified direction,
it shows a label such as `bullish_exploration` alongside `baseline_regime: neutral`; this distinguishes
the unchanged 70-point production classification from the separately configured exploration threshold.

Actual paper submission requires the operator to deliberately set both `ALLOW_ORDER_EXECUTION=true` and `DRY_RUN=false`. Never use live keys. Monitor submitted paper trades and view audit/P&L information with:

```bash
vegaguard live monitor-trade-updates
vegaguard live lifecycle-evidence
uvicorn vegaguard.api:app --reload
```

`lifecycle-evidence` is an offline, read-only report. It includes only trades for which the durable journal proves an entry fill, exit fill, exit reason, and realized paper P&L. Do not claim P&L until this command reports a completed trade. When the market is closed or market data is insufficient, preserve the stated abstention reason.
