# VegaGuard architecture

VegaGuard is a bounded paper-options agent. `Settings` rejects `ALPACA_PAPER_TRADE=false`, order execution defaults off, and only atomic one-buy/one-sell debit spreads can reach the execution adapter.

```text
Dashboard / CLI
  → backend controller (session ID, heartbeat, arm, emergency stop)
  → market-hours scheduler + paper trade-update monitor
  → Alpaca paper REST market/account data
  → deterministic scanner and option-chain validation
  → optional explanatory thesis advisory
  → deterministic allocation, risk, liquidity and position gates
  → immutable five-minute plan_id
  → fresh exact-leg quote revalidation
  → Alpaca MCP place_option_order (explicitly armed paper session only)
  → REST/stream reconciliation and position guardian
  → atomic reverse-leg exit
  → JSONL + SQLite audit, paper P&L evidence and SSE dashboard
```

The scheduler can create candidates and plans but never directly submit an entry. A dashboard submission additionally requires paper configuration, `ALLOW_ORDER_EXECUTION=true`, `DRY_RUN=false`, a deliberate session arm, and the exact unexpired reviewed `plan_id`. The arm is consumed after one attempt. Emergency stop disarms entries and halts backend workers; it never makes an unreviewed external account-wide call.

Immediately before an approved plan can reach MCP, VegaGuard rechecks the paper clock, positions, buying power, maximum loss, exact leg symbols, quote age, bid/ask liquidity and conservative debit drift. The entry intent is journaled before MCP, so an ambiguous failure cannot be blindly retried with the same idempotent `client_order_id`.

The backend owns both scheduler and paper `trade_updates` tasks. Heartbeats persist the process/session ID, market state, cycle start/completion, next cycle, last success and last error. Temporary scheduler data errors are recorded and the next bounded cycle still runs. The API lifespan cancels its workers cleanly.

The optional OpenAI thesis is advisory: it cannot choose legs, size, approve a failed gate or alter the fixed production threshold. Durable IV history supplies prior-state and point-in-time research features; missing or future data causes abstention.

Evidence is separated by construction:

- `SIMULATION_REPLAY` uses sanitized fixtures and no Alpaca/MCP object.
- `HYPOTHETICAL` shadow reprices use ask-entry/bid-exit quotes plus declared costs.
- approved plans are not trades;
- `PAPER ORDER` and `PAPER FILL` require provider evidence;
- `REALIZED PAPER P&L` requires actual entry and exit fills. If provider fees are absent, net-after-fee P&L remains `null`.
