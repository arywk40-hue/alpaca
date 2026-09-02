# Hackathon demo

Target: three minutes, one story, no live order submission.

## Before recording

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/vegaguard replay
PYTHONPATH=src .venv/bin/python -m uvicorn vegaguard.api:app \
  --host 127.0.0.1 --port 8000
```

Keep execution locked. Hide `.env`, account identifiers, tokens, plan IDs and provider order IDs.

## Recording route

1. **Open with the result.** Show the dashboard's completed IWM paper lifecycle and `+$2.00 gross before fees`. Say that one trade proves the workflow, not the strategy.
2. **Show one candidate.** Point to the five score components, both option legs, quote timestamps, DTE, debit and maximum loss.
3. **Show the authority boundary.** Explain that the OpenAI/fallback thesis is advisory; deterministic risk and an exact five-minute plan own execution.
4. **Show Alpaca usage.** Briefly show preflight, the discovered MCP option-order boundary and the provider-backed acknowledgement/fill events. Do not run an order.
5. **Show the research lane.** Open the 15/30/60-minute shadow reprices and make the `HYPOTHETICAL` label visible.
6. **Run the proof command.** Use `.venv/bin/vegaguard live lifecycle-evidence` and point out entry debit, exit credit, gross P&L and unknown fees.
7. **Close on safety.** Show execution locked and say: “The model explains; the deterministic system decides.”

## Claims to avoid

- Do not call the `+$2.00` result net profit; Alpaca did not report fees.
- Do not report a win rate from one trade.
- Do not describe the operator-authorized exit as an autonomous strategy trigger.
- Do not mix replay or shadow P&L with Alpaca paper P&L.
- Do not imply the production threshold changed; it remains 70.
