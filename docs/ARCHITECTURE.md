# VegaGuard architecture

VegaGuard is a paper-only, bounded options agent. It never enables live trading: configuration rejects `ALPACA_PAPER_TRADE=false` at startup.

```text
Alpaca market data
  -> deterministic signal scanner
  -> option-chain / liquidity validation
  -> local thesis (or optional OpenAI adapter)
  -> deterministic risk gate and order planner
  -> Alpaca MCP paper-order adapter
  -> REST + trade-update reconciliation
  -> position guardian / atomic exit
  -> JSONL + SQLite P&L audit and dashboard
```

Each component has a narrow responsibility. The thesis adapter may only trade or skip a scanner-selected candidate; it cannot choose contracts, quantity, or bypass the risk gate. The execution adapter accepts only a complete, defined-risk debit-spread plan and is disabled unless both operator controls are deliberately enabled.

IV observations are durable in the local decision journal (JSONL and SQLite). Each observation records its underlying, observation time, IV, source (`official` or `quote_derived`), and quote freshness. A prior observation older than eight hours is never used.

The dashboard is read-only. It reads journaled events and immutable selected-versus-no-trade shadow records; it cannot submit an order.
