# Hackathon demo

1. Show `.env.example`: paper mode is mandatory; execution, exploration and session arming are off by default.
2. Run `vegaguard replay`. Show the deterministic `SIMULATION_REPLAY` lifecycle and zero paper counters.
3. Start the API and use **Start Shadow Agent**. Show session/process heartbeat, last/next cycle, market status and SSE timeline.
4. With paper credentials, run `vegaguard preflight` to show account-ID validation, option data and discovered Alpaca MCP tools without an order call.
5. During market hours, show SPY/QQQ/IWM score components or honest abstention reasons. Open one dry-run plan and explain exact legs, quote timestamps, debit, loss/profit, buying-power and risk calculations.
6. Demonstrate arm, disarm and emergency-stop behavior without submitting. Explain the fresh exact-leg quote/debit-drift revalidation and one-attempt arm.
7. Show 15/30/60-minute `HYPOTHETICAL` shadow evidence separately from provider-backed paper lifecycle evidence.
8. Show `vegaguard live lifecycle-evidence`. If it lacks actual entry and exit fills, state that the paper lifecycle is ready but not externally proven; never substitute simulation P&L.

The autonomous claim is bounded autonomy: the system evaluates, selects, risk-checks, plans, journals, monitors, and exits within deterministic paper-trading constraints. It is not unconstrained discretionary trading.
