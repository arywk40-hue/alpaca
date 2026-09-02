# VegaGuard hackathon submission

## Submission fields

**Project name**

VegaGuard — Auditable Autonomous Options Risk Committee

**One-line pitch**

VegaGuard turns fresh ETF signals into defined-risk paper option spreads while keeping the model outside the execution authority boundary.

**Short description**

VegaGuard scans SPY, QQQ and IWM, validates live option quotes, builds one-contract debit spreads, applies deterministic risk checks, and routes an explicitly approved plan through Alpaca MCP. A live dashboard shows every decision, rejection, order update and P&L event without mixing simulation, shadow research and paper fills.

**Repository**

Use this repository URL in the submission form.

**Cover image**

[`assets/vegaguard-cover-v1.png`](../assets/vegaguard-cover-v1.png)

**Account ID**

Enter the dedicated Alpaca paper-account ID only in the private submission field. Do not add it to Git, screenshots or video.

## Long description

Most trading-agent demos focus on the signal. VegaGuard focuses on the handoff between a signal and an order—the point where stale data, changed legs or an unchecked model response can turn a plausible idea into the wrong trade.

The scanner scores liquid ETFs from daily regime, intraday trend, volume confirmation, volatility state and market alignment. A qualifying direction can create only a defined-risk vertical debit spread. The risk critic then checks quote age, liquidity, DTE, buying power, position limits, spread structure and maximum loss. Approval is tied to the exact legs and quantity in a five-minute `plan_id`; submission revalidates those legs against fresh quotes.

Alpaca's Trading and Market Data APIs provide account, clock, position, order and quote evidence. The official Alpaca MCP server is the order boundary, limited to the option-order tool. The CLI handles preflight, replay, live scans, lifecycle evidence and session reports. FastAPI powers the local operator dashboard, and server-sent events keep its timeline live.

The optional OpenAI explainer receives only validated facts and returns a strict JSON thesis, signals, risks, invalidation and explanation. It is advisory. It cannot change the score, threshold, legs, size, risk result or execution state. With no key or on failure, VegaGuard uses a labelled deterministic fallback.

VegaGuard also keeps a counterfactual shadow ledger. Repeated scans of the same legs are grouped as observations of one opportunity, then repriced after 15, 30 and 60 minutes using conservative ask-to-enter and bid-to-exit accounting. Those results are always labelled hypothetical and remain separate from Alpaca fills.

## Verified paper result

VegaGuard completed one Alpaca paper lifecycle:

| Item | Verified value |
| --- | --- |
| Structure | IWM 292.5/284 bear-put debit spread, Sep. 25 expiry |
| Size | One spread / one contract per leg |
| Plan | Exploration, score −65, threshold 40 |
| Entry | $2.62 debit on Aug. 31, 2026 at 16:44:20 UTC |
| Exit | $2.64 credit on Sep. 1, 2026 at 14:47:30 UTC |
| Gross realized paper P&L | **+$2.00** |
| Fees | Not reported by Alpaca; after-fee P&L is unknown |
| Observed MAE / MFE | −$85 / +$20 |
| Exit reason | Operator-authorized hackathon lifecycle completion |

This is a complete provider-backed paper workflow, not evidence that the strategy has a durable edge. The result is presented without an annualized return, win-rate claim or invented fees. Production remains at its original threshold of 70.

Public artifacts redact account and provider identifiers. The local append-only journal retains the `plan_id`, client order IDs, Alpaca order IDs, fill timestamps and reconciliation events. Run `vegaguard live lifecycle-evidence` to reproduce the report from that journal.

## Why it stands out

- **Performance:** one completed, positive paper lifecycle with fill-derived gross P&L and explicit fee uncertainty.
- **Technology:** Alpaca data and trading APIs, official Alpaca MCP execution, CLI operations, FastAPI/SSE control plane and durable reconciliation.
- **Originality:** a model can explain a trade but cannot authorize one; the shadow ledger evaluates rejected alternatives without pretending they were fills.
- **Execution:** one dashboard tells the story from scan to plan, order, monitoring, exit and P&L, with simulation and paper evidence visibly separated.

## Three-minute demo route

1. Open the dashboard and point out `PAPER ONLY`, the safety state and separate evidence counters.
2. Run `vegaguard replay` and show that simulation never increments paper fills.
3. Open one candidate to show score components, option quotes, risk math and exact-plan binding.
4. Show the Alpaca paper lifecycle timeline and the `+$2.00 before fees` result.
5. Run `vegaguard live lifecycle-evidence` and close on the authority boundary: explanation is flexible; execution is deterministic.

## Reproduce locally

```bash
uv sync --extra dev
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/vegaguard replay
PYTHONPATH=src .venv/bin/python -m uvicorn vegaguard.api:app \
  --host 127.0.0.1 --port 8000
```

The replay is a fixture-backed code-path demonstration, not historical performance. With the local paper journal present, this read-only command reports completed provider-backed trades:

```bash
.venv/bin/vegaguard live lifecycle-evidence
```

## Honest limitations

- One completed trade is not a statistically useful performance sample.
- Alpaca did not report fees for the completed lifecycle, so after-fee P&L is unknown.
- The historical quote endpoint available to this account did not provide the point-in-time option history needed for defensible threshold optimization.
- The demonstrated exit was operator-authorized to complete the hackathon lifecycle; automated exit rules and restart reconciliation are implemented and tested, but that exit was not triggered by a profit, stop or time rule.
- VegaGuard is paper-only and has no real-money execution path.
