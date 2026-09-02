# VegaGuard — 10-slide demo deck

Keep the slides visual. The short text below is what belongs on screen; the narration carries the detail.

## 1 — Evidence before execution

**VegaGuard**

Auditable, paper-only ETF options

`1 completed Alpaca paper spread · +$2 gross before fees`

**Visual:** Product name beside the dashboard's paper-lifecycle strip.

## 2 — The risky part starts after the signal

**A signal is not an order.**

Stale quote · changed legs · hidden loss · duplicate order · unchecked model output

**Visual:** A candidate crossing five hazards before reaching Alpaca.

## 3 — One narrow, testable strategy

**SPY · QQQ · IWM**

Daily regime + intraday trend + volume + volatility + market alignment

Only defined-risk bull-call or bear-put debit spreads. Production threshold: **70**.

**Visual:** Five score components flowing into one two-leg vertical spread.

## 4 — Authority is deliberately split

`scanner → spread builder → risk critic → exact plan → Alpaca MCP`

The explainer writes words. Deterministic code owns score, legs, size and permission.

**Visual:** Put the optional OpenAI explainer above the path with a dotted, read-only arrow.

## 5 — The order boundary is exact

**PAPER ONLY · FRESH QUOTES · ONE CONTRACT · FIVE-MINUTE PLAN**

Recheck market, liquidity, DTE, buying power, position limits, price drift and maximum loss.

**Visual:** A locked `plan_id` card containing two OCC symbols and a limit debit.

## 6 — Built on Alpaca, end to end

- Trading + Market Data APIs
- Official Alpaca MCP order boundary
- CLI preflight, replay and evidence reports
- FastAPI control plane + SSE dashboard
- Durable journal + restart reconciliation

**Visual:** One compact system diagram, not technology logos scattered across the slide.

## 7 — The shadow ledger is the research loop

**Rejected trades still teach us.**

Same legs repriced at 15 / 30 / 60 minutes

Ask to enter · bid to exit · repeated scans grouped as one opportunity

**Visual:** Selected and rejected candidates branching into separate, clearly labelled evidence lanes.

## 8 — One real paper lifecycle

`approved → submitted → acknowledged → filled → monitored → exit filled`

IWM Sep. 25 292.5/284 bear-put spread · one contract

**Visual:** Use the sanitized dashboard timeline. Redact account, plan and provider IDs.

## 9 — P&L, without the victory lap

| Entry debit | Exit credit | Gross P&L | MAE | MFE |
| ---: | ---: | ---: | ---: | ---: |
| $2.62 | $2.64 | **+$2.00** | −$85 | +$20 |

Fees were not reported, so after-fee P&L is unknown. The exit was operator-authorized to complete the hackathon lifecycle.

**Visual:** The five numbers above, large and uncluttered.

## 10 — What VegaGuard proves

**Autonomy needs an audit trail, not a blank cheque.**

- Complete provider-backed paper workflow
- Simulation, shadow evidence and fills stay separate
- One trade does not change the production strategy

`186 tests · Ruff clean · execution locked by default`

**Visual:** Dashboard overview with the lifecycle complete and safety lock visible.

## Screenshot checklist

- Use the local `/social` view or the read-only dashboard state.
- Show `PAPER ONLY`, lifecycle completion and realized P&L in one frame.
- Crop all account IDs, bearer tokens, API keys, `plan_id` values and provider order IDs.
- Keep the operator token field empty.
- Do not show hypothetical P&L without its label.
