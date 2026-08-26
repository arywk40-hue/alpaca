# Operator runbook

Use a dedicated Alpaca paper account and keep these defaults in `.env`:

```dotenv
ALPACA_PAPER_TRADE=true
ALLOW_ORDER_EXECUTION=false
DRY_RUN=true
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

Actual paper submission requires the operator to deliberately set both `ALLOW_ORDER_EXECUTION=true` and `DRY_RUN=false`. Never use live keys. Monitor submitted paper trades and view audit/P&L information with:

```bash
vegaguard live monitor-trade-updates
vegaguard live lifecycle-evidence
uvicorn vegaguard.api:app --reload
```

`lifecycle-evidence` is an offline, read-only report. It includes only trades for which the durable journal proves an entry fill, exit fill, exit reason, and realized paper P&L. Do not claim P&L until this command reports a completed trade. When the market is closed or market data is insufficient, preserve the stated abstention reason.
