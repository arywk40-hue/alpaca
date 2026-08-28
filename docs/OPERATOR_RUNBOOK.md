# Operator runbook

Use a dedicated Alpaca paper account and keep these defaults in `.env`:

```dotenv
ALPACA_PAPER_TRADE=true
ALPACA_ACCOUNT_ID=
ALLOW_ORDER_EXECUTION=false
DRY_RUN=true
EXPLORATION_MODE=false
EXPLORATION_SCORE_THRESHOLD=40
DASHBOARD_BEARER_TOKEN=
```

## Dashboard API authentication

The dashboard page and read-only endpoints remain available for inspection. Every mutating
dashboard/API route is locked behind the backend-only `DASHBOARD_BEARER_TOKEN` setting:

`/agent/shadow/start`, `/agent/shadow/stop`, `/agent/simulation/start`, `/agent/paper/arm`,
`/agent/paper/disarm`, `/agent/paper/submit-approved`, `/agent/emergency-stop`, `/cycle/run`,
and `/lifecycle/manage`.

Send the token only in an HTTPS request `Authorization: Bearer …` header from a trusted operator
client. Requests with a missing, unset, or incorrect token receive `401 Unauthorized`. The API never
returns the configured value, and the dashboard HTML does not contain it. Keep the value in the
backend process environment or an equivalent secret manager; do not paste it into source, logs,
journal entries, screenshots, or Git. For example, with the value already present in the current
shell environment:

```bash
curl -H "Authorization: Bearer ${DASHBOARD_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"interval_seconds":900}' \
  http://127.0.0.1:8000/agent/shadow/start
```

Do not put the token in dashboard JavaScript or a URL. If a browser needs to operate these controls,
use an authenticated reverse proxy or another trusted mechanism that injects the header without
exposing the secret to the page. Read-only routes such as `/`, `/health`, `/preflight`,
`/dashboard/state`, `/events`, `/journal`, and `/agent/status` do not require this bearer token.

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
  vegaguard live submit-approved \
  --plan-id vg-plan-REPLACE_WITH_REVIEWED_ID \
  --arm-paper-execution
```

The command reloads the immutable dry-run plan without scanning again, rejects an expired plan or a prior
submission, and rechecks the current market, paper account, buying power, maximum loss, position gates, exact leg symbols, fresh quote age, liquidity, and debit drift. The CLI arm applies to this invocation only.

Every market-hours scheduler cycle also persists a shadow-candidate record for each ETF. It records below-threshold and rejected candidates with real data/quote timestamps without altering the live threshold or submitting an order:

```bash
vegaguard live shadow-candidates --limit 20
```

## Read-only live shadow evaluation

Every scanned candidate—production, exploration, below-threshold, or rejected—stores its score
components, rejection gates, available underlying/option quote evidence, DTE, IV, volume, and open
interest. During later market-hours scheduler cycles, VegaGuard reprices the exact recorded legs at 15,
30, and 60 minutes with fresh quotes. These entries are explicitly **hypothetical**, use conservative
ask-to-enter/bid-to-exit economics, and include only the configured fee/slippage assumptions; they are
never paper fills or realized P&L. If the worker misses a deadline, it persists an unavailable outcome
with the missed-deadline reason instead of using a later quote as though it existed at the horizon.

```bash
# Read-only: summarizes scans, failures, score distribution, and hypothetical threshold outcomes.
vegaguard live session-report
```

The dashboard also exposes a durable scheduler heartbeat. `waiting` means a continuous scheduler
completed its last cycle and has a recorded next run; `running` means a cycle is in progress;
`stopped` is expected after a bounded `--max-cycles` command; `error` shows the last cycle's durable
failure and error text; and `stale` means no heartbeat arrived within two intervals plus one minute.
The heartbeat also records process/session ID, market state, cycle start/completion, last success,
next run, and latest journal timestamp. Treat `stale` and `error` as operational failures, not market
decisions.

`SHADOW_FEE_PER_CONTRACT_USD` and `SHADOW_SLIPPAGE_PER_LEG_USD` default to zero. Set them only to
document an explicit research assumption; they do not modify orders, production scoring, or the fixed
70-point production threshold.

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

## Dashboard-managed shadow worker

Run the API server to start the dashboard-managed controller:

```bash
PYTHONPATH=src uvicorn vegaguard.api:app --host 127.0.0.1 --port 8000
```

Use **Start Shadow Agent** to create one backend scheduler worker; **Stop Agent**
cancels it and writes a `stopped` heartbeat. The dashboard receives durable event
updates through `/events` and shows `running`, `stopped`, `stale`, or `error` with
last cycle, next cycle, last error, and journal timestamp. **Start Simulation
Replay** writes only the sanitized `SIMULATION_REPLAY` bundle and does not change
paper counters.

The dashboard cannot change backend environment flags. Its submit button remains locked until the backend is paper configured and the operator types the exact arm confirmation. That arm permits one exact-plan attempt and is consumed afterward. **Disarm Paper Execution** relocks entry. **Emergency Stop** disarms and halts backend workers without making an account-wide order or cancellation call. Re-arming deliberately clears the in-process emergency latch. Stopping the API server stops its scheduler and trade-update monitor.

Actual paper submission requires both `ALLOW_ORDER_EXECUTION=true` and `DRY_RUN=false`, plus a dashboard or CLI session arm. Never use live keys. The dashboard-managed worker owns trade updates when paper credentials exist; the standalone monitor remains a diagnostic fallback. View audit/P&L information with:

```bash
vegaguard live monitor-trade-updates
vegaguard live lifecycle-evidence
uvicorn vegaguard.api:app --reload
```

`lifecycle-evidence` is an offline, read-only report. It includes only trades for which the durable journal proves an entry fill, exit fill, exit reason, and fill-to-fill realized paper P&L. Debit paid, credit received, multiplier, quantity, provider IDs, fill-to-limit slippage and observed MAE/MFE are retained. If Alpaca does not report fees, after-fee P&L remains `null`; never replace it with an assumption. Do not claim P&L until this command reports a completed trade. When the market is closed or market data is insufficient, preserve the stated abstention reason.
