# Hackathon demo

1. Show `.env.example`: VegaGuard is paper-only by construction and execution is off by default.
2. Run `vegaguard preflight` to show the paper account, option-data access, and discovered Alpaca MCP tools.
3. Run `vegaguard live read-only-cycle --cycles 2 --interval-seconds 60` during US market hours. Show SPY, QQQ, and IWM scans, durable IV state, numeric score/regime where data supports it, or honest reason codes where it does not.
4. Explain the bounded pipeline: data and scanner, options validation, optional OpenAI/local thesis, deterministic risk, MCP adapter, lifecycle monitor, guardian, and P&L journal.
5. With `ALLOW_ORDER_EXECUTION=true` and `DRY_RUN=true`, show the complete dry-run order preview and exact multi-leg MCP payload. No order is submitted.
6. If a paper order is deliberately authorized, demonstrate reconciliation, `trade_updates`, guardian exit, and dashboard journal. Otherwise state that no P&L has been generated.

The autonomous claim is bounded autonomy: the system evaluates, selects, risk-checks, plans, journals, monitors, and exits within deterministic paper-trading constraints. It is not unconstrained discretionary trading.
