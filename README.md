# VegaGuard

VegaGuard is an autonomous **paper-options** agent built for the Alpaca AI Trading Agents Hackathon. It does not ask an LLM to freely trade. Instead it makes the work auditable:

`opportunity scanner → LLM thesis → deterministic risk gate → Alpaca MCP option order → order monitor → journal`

## Why this meets the brief

- **Autonomous agents:** the scanner, thesis agent, risk critic and position monitor run as an event loop.
- **Alpaca Trading API:** the official Alpaca MCP server is the execution and account/data boundary over Alpaca's Trading API.
- **MCP:** `uvx alpaca-mcp-server` is launched as a stdio MCP server; available tool schemas are discovered dynamically at runtime.
- **Options:** only option contracts can form a `TradePlan`; the execution adapter calls `place_option_order`.
- **Paper only:** the MCP environment is hard-wired to `ALPACA_PAPER_TRADE=true`. This project refuses an execution attempt if that is not true.

## First-run setup

1. Create the **new hackathon-only Alpaca paper account** and generate its paper API keys.
2. Copy the environment file and fill only the paper credentials:

   ```bash
   cp .env.example .env
   ```

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

### Deterministic replay

This uses only a sanitized fixture and validates the scoring and accounting path. It is **not** a historical-performance claim.

```bash
vegaguard replay \
  --fixture tests/fixtures/strategy_replay_sanitized.json \
  --output results/strategy_replay.json
```

### Historical research (read-only)

The historical adapter uses Alpaca's stock-bars, option-bars, option-quotes, option-snapshots,
and option-contracts endpoints. It has no order-submission code. Downloaded data is kept out of
Git, along with a cache manifest that records request metadata and request IDs when supplied.

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

The replay rejects data observed after the decision timestamp, incomplete contract metadata,
stale/missing quotes or Greeks, and missing IV history. It will label output
`STOCK-SIGNAL-ONLY ANALYSIS` and **inconclusive** rather than claim option P&L if the normalized
inputs cannot support a real point-in-time option backtest. Alpaca's historical option data starts
in February 2024; free indicative data is delayed and modified relative to OPRA.

See [historical data limitations](docs/HISTORICAL_DATA_LIMITATIONS.md) for the current snapshot/IV
and contract-metadata boundary. The fetcher derives static OCC metadata only from a historical
quote that proves the contract existed at the decision time.

### Read-only paper-account verification

This command queries paper account state and the full deterministic scan inputs, but does not call
OpenAI, MCP, or any order endpoint:

```bash
vegaguard live read-only-cycle
```

The first scan correctly reports no trade because it needs a second fresh snapshot observation to
form an IV state. Keep `ALLOW_ORDER_EXECUTION=false`; a live plan, if ever separately authorized,
is a defined-risk bull-call or bear-put debit spread using the same scorer and spread builder as
the backtester.

### Autonomous scheduler and dashboard

The scheduler asks Alpaca's paper clock on each cycle. It runs the bounded cycle only while the
market is open and journals the outcome into both `data/journal.jsonl` and a queryable
`data/journal.sqlite3` audit store. Start with one safe cycle:

```bash
vegaguard live run-scheduler --interval-seconds 900 --max-cycles 1
uvicorn vegaguard.api:app --reload
```

Open `http://127.0.0.1:8000/` for the demo dashboard. It contains no trade controls: it shows the
journal, immutable selected-vs-no-trade shadow records, and completed audit deltas. Every
gate-approved plan receives a shadow record before the executor can emit its dry-run or MCP result.

When paper execution is separately authorized, retain `DRY_RUN=true` first. VegaGuard will journal
the exact validated `mleg` payload without calling MCP. Only after that output is reviewed should a
paper-only operator set `DRY_RUN=false`. At each scheduled market-hours cycle, the guardian checks
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

- [Master Alpaca hackathon reference](docs/ALPACA_HACKATHON_MASTER.md)
- [P&L trading strategy](docs/TRADING_STRATEGY.md)
- [Architecture and implementation plan](docs/ARCHITECTURE_AND_IMPLEMENTATION_PLAN.md)
- [Winning product specification](docs/VEGAGUARD_WINNING_SPEC.md)
