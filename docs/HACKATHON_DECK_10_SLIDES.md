# VegaGuard — 10-slide demo deck

This is the presentation-ready slide specification for the hackathon demo. It is
grounded in the checked-in replay artifacts and deliberately distinguishes
simulation, shadow evidence, approved plans, and provider-backed paper events.

## Slide 1 — Evidence before execution

**On screen:** VegaGuard — Auditable Autonomous Options Risk Committee

**Subtitle:** Paper-only, defined-risk ETF options with a visible authority boundary.

**Visual:** Shield over a small options decision pipeline; leave room for the title.

## Slide 2 — The problem is not finding a trade

**On screen:** A plausible signal is not an executable decision.

Show the failure modes: stale quotes, ambiguous legs, hidden risk, and an
LLM that can silently change the order. The demo goal is an auditable decision,
including a safe abstention.

## Slide 3 — A deterministic committee owns authority

**On screen:** Scan → score → spread → risk → exact plan → paper boundary

The scanner evaluates SPY, QQQ, and IWM. The strategy builds one-buy/one-sell
debit spreads. The controller, not a language model, owns approval and execution.

## Slide 4 — Evidence travels with every candidate

**On screen:** Score components | bid/ask/mid | quote time | IV | DTE | volume | OI

Every candidate keeps the component breakdown, both option legs, quote freshness,
spread economics, rejection gates, and a stable plan identifier. Repeated scans
are observations of one opportunity, not free extra trades.

## Slide 5 — Execution is locked behind independent gates

**On screen:** PAPER ONLY · DRY RUN · ARM · EXACT PLAN ID

The paper path also requires a paper account, an open market, fresh quotes,
liquidity and DTE checks, buying power, one contract, one open position, a valid
defined-risk debit spread, and maximum-loss approval. No flag bypasses a hard gate.

## Slide 6 — The dashboard makes state legible

**On screen:** RUNNING/STOPPED/STALE/ERROR heartbeat and SSE timeline

Separate cards show simulation, hypothetical shadow outcomes, approved plans,
acknowledged orders, fills, and realized P&L. The default dashboard is read-only;
operator mutations require a bearer token held only in browser memory/session storage.

## Slide 7 — OpenAI explains; it does not decide

**On screen:** Structured facts in → strict JSON explanation out

The optional Trade Thesis & Risk Explainer receives only validated scanner, spread,
and risk facts. It returns thesis, supporting signals, risks, invalidation, and
explanation. A deterministic fallback is labelled when the key is absent or the
API fails. The explanation cannot alter score, threshold, legs, quantity, risk, or
execution.

## Slide 8 — Offline replay proves accounting, not performance

**On screen:** `SIMULATION_REPLAY` · 3 observations · 2 simulated trades · net hypothetical $40

The sanitized fixture produces gross P&L $50, costs $10, net hypothetical P&L $40,
win rate 50%, profit factor 1.6154, and maximum drawdown -$65. Paper counters remain
zero: no submitted, acknowledged, filled, or realized paper trades.

## Slide 9 — Research is honest about uncertainty

**On screen:** Production threshold 70 remains fixed.

Threshold comparisons and shadow repricing are research evidence, not a promise of
edge. Historical options coverage is limited by the available Alpaca entitlement
and cache. Small sanitized fixtures are accounting demonstrations, not a claim of
live profitability. Missing data is recorded as missing, never invented.

## Slide 10 — The next proof is a complete paper lifecycle

**On screen:** Fresh scan → approved → submitted → acknowledged → filled → monitored → exited → realized P&L

The remaining external milestone is one fresh, reviewed, short-lived plan during
market hours, followed through the Alpaca paper account. Until provider-backed
entry and exit fills are journaled, VegaGuard reports readiness—not a completed
paper trade.

