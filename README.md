# VegaGuard

VegaGuard is an autonomous **paper-options** agent built for the Alpaca AI Trading Agents Hackathon. It does not ask an LLM to freely trade. Instead it makes the work auditable:

`opportunity scanner → options validation → local/optional OpenAI thesis → deterministic risk gate → Alpaca MCP option order → position guardian → journal`

## Why this meets the brief

- **Autonomous agents:** the scanner, thesis agent, risk critic and position monitor run as an event loop.
- **Alpaca Trading API:** the official Alpaca MCP server is the execution and account/data boundary over Alpaca's Trading API.
- **MCP:** `uvx alpaca-mcp-server` is launched as a stdio MCP server; available tool schemas are discovered dynamically at runtime.
- **Options:** only option contracts can form a `TradePlan`; the execution adapter calls `place_option_order`.
- **Paper only:** the MCP environment is hard-wired to `ALPACA_PAPER_TRADE=true`. This project refuses an execution attempt if that is not true.
- **LLM boundary:** optional OpenAI output is journaled as an explanation/advisory only; deterministic scanner, spread, and risk gates—not the model—control whether a plan exists.

## First-run setup

1. Create the **new hackathon-only Alpaca paper account** and generate its paper API keys.
2. Copy the environment file and fill only the paper credentials:

   ```bash
   cp .env.example .env
   ```

   `ALPACA_ACCOUNT_ID` is optional in local development and is the secret-free identifier used for the final submission. Preflight verifies it against the paper account when supplied.

3. Create a virtual environment and install the project:

   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install -e '.[dev]'
   ```

4. Keep `ALLOW_ORDER_EXECUTION=false` initially. Check that MCP discovers the actual installed v2 tool schemas:

   ```bash
   vegaguard inspect-mcp
   vegaguard preflight
   ```

   `preflight` makes concurrent, read-only account, clock, option-snapshot, and MCP-schema checks.
   It writes a secret-free report to `data/mcp_preflight.json`; only set `ALLOW_ORDER_EXECUTION=true`
   after its status is `ready` and the tool set has been reviewed.

5. Run tests and the API:

   ```bash
   pytest -q
   uvicorn vegaguard.api:app --reload
   ```

6. Once paper credentials and the MCP schema are verified, set `ALLOW_ORDER_EXECUTION=true`. The risk gate still blocks non-paper, illiquid, near-expiry, over-sized, or duplicate trades.

### Credential-free demo bundle

Generate a reviewer-friendly bundle without credentials, network access, or execution capability:

```bash
vegaguard replay --output-dir results/offline_demo
```

It writes the deterministic replay, offline scorer/threshold comparison, and a
`SIMULATION_REPLAY` lifecycle showing scan → candidate → risk decision → simulated
entry → 15/30-minute monitoring → simulated 60-minute exit. Every artifact is
fixture-only; paper-order counters remain zero. This is a reproducible code-path
demo—not historical or paper-trading proof.

### Dashboard-managed operation

Start the API once; it owns the scheduler worker and stops it cleanly with the
server. No separate scheduler terminal is needed:

```bash
PYTHONPATH=src uvicorn vegaguard.api:app --host 127.0.0.1 --port 8000
```

The dashboard has controls for **Start Shadow Agent**, **Stop Agent**, **Start Simulation Replay**, **Arm/Disarm Paper Execution**, and **Emergency Stop**. It streams durable journal updates through SSE at `/events`; the backend also owns the paper trade-update monitor when credentials are configured. Shadow scans and simulations cannot submit an order. Paper submission requires all backend flags, a deliberate typed session arm, and a manually entered exact unexpired `plan_id`; that one-attempt arm is then consumed. The backend rechecks market, exact-leg quote freshness and price drift, liquidity, buying power, position limits and risk. Credentials are never returned to the browser.

### Deterministic replay

This uses only a sanitized fixture and validates the scoring and accounting path. It is **not** a historical-performance claim.

```bash
vegaguard replay
```

### Offline scorer A/B research

The production scanner remains on the baseline scorer. A conflict-tolerant alternative is available only for offline analysis; it cannot access Alpaca or execution code:

```bash
vegaguard strategy compare-scorers \
  --fixture tests/fixtures/strategy_replay_sanitized.json
```

Do not promote it without a separate, point-in-time out-of-sample historical option-data result that improves performance without unacceptable drawdown or execution-risk regression.

### Historical research (read-only)

The historical adapter uses Alpaca's stock-bars, option-bars, option-snapshots, and option-contracts
endpoints. Alpaca's documented options quote endpoint is latest-only; the historical
`/v1beta1/options/quotes` request returned `404 Not Found` during verification, so the fetcher records
that capability limitation and writes no fabricated quote history. It has no order-submission code.
Downloaded data is kept out of Git, along with a cache manifest that records request metadata and
request IDs when supplied.

```bash
vegaguard data fetch-history \
  --symbols SPY,QQQ,IWM \
  --start 2025-01-01 \
  --end 2025-03-31

vegaguard strategy backtest \
  --data-dir data/normalized \
  --symbols SPY,QQQ,IWM \
  --start 2025-01-01T00:00:00+00:00 \
  --end 2025-03-31T23:59:59+00:00 \
  --output results/historical_strategy_backtest.json
```

The historical replay enters at long-ask/short-bid and exits at long-bid/short-ask. Optional,
explicit research assumptions are additive and reported separately from that observed bid/ask cost:

```bash
vegaguard strategy backtest ... \
  --fee-per-contract-usd 1.00 \
  --slippage-per-leg-usd 0.25
```

Fees are charged once at entry and once at exit per contract; slippage covers all four option-leg
transactions in a complete debit-spread lifecycle. Neither parameter affects live orders.

For a fixed-horizon, point-in-time research comparison, add
`--exit-horizon-minutes 15`, `30`, or `60`. The replay uses the first fresh option
quote event at or after that horizon and labels the exit accordingly. It has no live
execution effect.

The replay rejects data observed after the decision timestamp, incomplete contract metadata,
stale/missing quotes or Greeks, and missing IV history. It will label output
`INCOMPLETE HISTORICAL DATASET` when the fetch manifest says historical option quotes are unavailable,
and otherwise uses `STOCK-SIGNAL-ONLY ANALYSIS` and **inconclusive** rather than claim option P&L if
the normalized inputs cannot support a real point-in-time option backtest. Alpaca's historical option
data starts in February 2024; free indicative data is delayed and modified relative to OPRA.

Each historical result reports win rate, profit factor, maximum drawdown, net expectancy per
completed trade, and the missing-data rate across decision attempts. Walk-forward reports compare
the same metrics at research thresholds 40, 50, 60, and 70; none changes the live threshold.

See [historical data limitations](docs/HISTORICAL_DATA_LIMITATIONS.md) for the current snapshot/IV
and contract-metadata boundary. The fetcher derives static OCC metadata from historical quotes only
when a supported quote-history source supplies them; Alpaca's current fetch is explicitly marked
unable to do so.

### Offline confidence calibration

Score strength is not a probability. Once a genuine normalized historical options cache contains
enough completed trades, VegaGuard can report empirical win-rate and net-P&L buckets by score and
regime. This is research-only: it cannot alter the production score of 70, sizing, risk gates, or
execution settings.

```bash
vegaguard strategy calibrate-confidence \
  --data-dir data/normalized \
  --symbols SPY,QQQ,IWM \
  --start 2025-01-01T00:00:00+00:00 \
  --end 2025-03-31T23:59:59+00:00 \
  --minimum-score 40
```

The command reports `insufficient_real_historical_evidence` unless the input is a genuine
point-in-time option backtest and a score/regime bucket reaches its configured sample minimum.

### Offline walk-forward threshold research

The live scanner remains fixed at 70. A historical cache can be evaluated at explicit research
thresholds only through a chronological train/test split; the later interval is held out from
selection and the command cannot access account, MCP, or execution code:

```bash
vegaguard strategy walk-forward \
  --data-dir data/normalized \
  --symbols SPY,QQQ,IWM \
  --start 2025-01-01T00:00:00+00:00 \
  --end 2025-03-31T23:59:59+00:00 \
  --thresholds 40,50,60,70 \
  --minimum-in-sample-trades 30
```

It selects a threshold only from real, sufficiently sized in-sample option evidence, then reports
the selected threshold's held-out performance. It never promotes that result into production; a
human must separately review out-of-sample drawdown, fill assumptions, and execution risk.

Live shadow evidence also records research-only IV percentile, put/call skew, and term-structure
features when the append-only observed IV history and fresh option chain are sufficient. They remain
`null` when unavailable and do not alter production scoring or risk gates.

### Read-only paper-account verification

This command queries paper account state and the full deterministic scan inputs, but does not call
OpenAI, MCP, or any order endpoint:

```bash
vegaguard live read-only-cycle
```

The first scan correctly reports no trade when it has IV/Greeks but needs a second fresh snapshot
observation to form an IV state. Each observation is journaled locally and remains valid for eight
hours, so use either a single long-lived process or a later one-off run during that window:

```bash
vegaguard live read-only-cycle --cycles 2 --interval-seconds 900
```

Keep `ALLOW_ORDER_EXECUTION=false`; a live plan, if ever separately authorized,
is a defined-risk bull-call or bear-put debit spread using the same scorer and spread builder as
the backtester.

### Paper-only exploration mode

Production remains fixed at the baseline 70-point threshold. `EXPLORATION_MODE=false` is the default;
when an operator explicitly enables it, the unchanged baseline score may be evaluated at
`EXPLORATION_SCORE_THRESHOLD=40`. Exploration is separately labelled, permits only one whole-contract
defined-risk debit spread with no other open position, and preserves every paper-account, fresh-quote,
liquidity, IV, DTE, buying-power, maximum-loss, and risk gate. Start with dry run only:

```bash
EXPLORATION_MODE=true EXPLORATION_SCORE_THRESHOLD=40 \
ALLOW_ORDER_EXECUTION=true DRY_RUN=true \
  vegaguard live run-scheduler --interval-seconds 900 --max-cycles 1
```

The journal and dashboard separate `exploration` from `production` records. They retain the score,
threshold, candidate economics, quote timestamps, observed P&L, and rejection reasons; fields without
an observed Alpaca value remain `null`. Exploration metrics for thresholds 40, 50, 60, and 70 appear in
the offline `strategy compare-scorers` report. A trade never changes the production threshold.

`OPENAI_API_KEY` is optional. When it is absent, VegaGuard uses a bounded deterministic thesis over
the same validated opportunity; it cannot alter legs, size, or any deterministic risk rule.

When Alpaca omits IV/Greeks, VegaGuard can deterministically derive them from a fresh observed
bid/ask, the OCC contract metadata, and the configured risk-free rate using Black–Scholes inversion.
These are labeled quote-derived inputs, not forecasts or LLM output. If the scan still says no
fresh solvable quote-derived IV, the session is closed/stale or the account's available data cannot
support this IV-filtered strategy; VegaGuard will abstain rather than invent inputs.

### Autonomous scheduler and dashboard

The scheduler asks Alpaca's paper clock on each cycle. It runs the bounded cycle only while the
market is open and journals the outcome into both `data/journal.jsonl` and a queryable
`data/journal.sqlite3` audit store. Start with one safe cycle:

```bash
vegaguard live run-scheduler --interval-seconds 900 --max-cycles 1
uvicorn vegaguard.api:app --reload
```

Open `http://127.0.0.1:8000/` for the demo dashboard. It shows the journal, shadow evidence, plan/order/fill counters, lifecycle P&L and backend controls. Controls cannot alter environment safety flags or bypass any deterministic gate. Every gate-approved plan receives a shadow record before the executor can emit its dry-run result.

The dashboard's scheduler card is a durable liveness signal, not a trade control: `waiting`,
`running`, `stopped`, `never_started`, and `stale` are derived from journaled heartbeat events. A
continuous scheduler becomes `stale` if it misses two scheduled intervals plus one minute.

When paper execution is separately authorized, retain `DRY_RUN=true` first. VegaGuard journals the exact validated `mleg` payload without calling MCP. After review, the dashboard path additionally requires its explicit session arm; a scheduler cycle still cannot submit an entry directly. At each scheduled market-hours cycle, the guardian checks
filled, journaled spreads against conservative long-bid/short-ask exit value. A profit, stop, time,
or expiry trigger can create only an atomic reversed-leg close order (`sell_to_close` plus
`buy_to_close`); it follows the same execution and dry-run gates as entry. The trade-update monitor
closes the immutable shadow record only after that close is filled:

```bash
vegaguard live monitor-trade-updates
```

## Current scope

The current implementation includes a shared live/replay deterministic scorer, defined-risk debit
spread construction, a read-only Alpaca paper-data cycle, and a paper `trade_updates` monitor that
journals lifecycle events and emits deterministic exit decisions. Credentials and recorded
read-only output are still required to claim any Alpaca/OpenAI integration was externally verified.
Use the [paper acceptance checklist](docs/PAPER_ACCEPTANCE_CHECKLIST.md) to produce that evidence
without ever enabling live trading.

## Important controls

- The LLM cannot choose an arbitrary size, ignore buying power, bypass a failed gate, or call destructive portfolio-wide tools.
- All executable plans use a unique `client_order_id` and get written to `data/journal.jsonl` before submission.
- The risk gate accepts only defined-risk debit spreads; no naked option-selling strategy is in scope.
- Do not use live keys. The MCP server defaults to paper, but the app also validates the paper setting explicitly.

## Official references

- [Alpaca MCP Server](https://docs.alpaca.markets/us/docs/alpaca-mcp-server)
- [Options trading](https://docs.alpaca.markets/us/docs/options-trading)
- [Multi-leg options](https://docs.alpaca.markets/us/docs/options-level-3-trading)
- [Paper trading](https://docs.alpaca.markets/us/docs/paper-trading)

## Build documents

- [Architecture](docs/ARCHITECTURE.md)
- [Strategy and risk rules](docs/STRATEGY.md)
- [Operator runbook](docs/OPERATOR_RUNBOOK.md)
- [Hackathon demo](docs/HACKATHON_DEMO.md)
- [Hackathon submission package](docs/HACKATHON_SUBMISSION.md)
- [Master Alpaca hackathon reference](docs/ALPACA_HACKATHON_MASTER.md)
- [P&L trading strategy](docs/TRADING_STRATEGY.md)
- [Architecture and implementation plan](docs/ARCHITECTURE_AND_IMPLEMENTATION_PLAN.md)
- [Winning product specification](docs/VEGAGUARD_WINNING_SPEC.md)
