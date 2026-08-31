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

## Slide 8 — The first paper entry crossed every boundary

**On screen:** IWM bear put spread · 1 contract · $2.62 fill · $262 debit at risk

On August 31, Alpaca acknowledged and filled the exact reviewed exploration plan:
long the 292.5 put and short the 284 put, expiring September 25. The approved debit
was $2.65 and the provider-backed fill was $2.62, three dollars better for one
contract. This is one two-leg spread—not two trades. Provider fees were not reported.

## Slide 9 — Live evidence argues against forcing more trades

**On screen:** 16 opportunities · 86 reprices · threshold 40: 5 outcomes, −$225.90

At the August 31 close, the open IWM spread had a conservative executable credit of
$2.35: −$27 unrealized, or −10.3%, with no exit trigger. Five independent threshold-40
outcomes had 0% wins and −$45.18 expectancy. The sample is still too small to optimize,
but it is strong evidence not to lower the fixed production threshold of 70.

## Slide 10 — One provider-backed exit completes the proof

**On screen:** Approved → submitted → acknowledged → filled → monitored → **exit pending**

The entry half is proven. VegaGuard resumes one-minute guardian checks when Alpaca
opens September 1 at 9:30 AM ET / 7:00 PM IST. It will close only on the existing
+50% target, −35% stop, time/expiry rule, or another documented deterministic exit.
Until Alpaca reports the exit fill, P&L remains unrealized and the lifecycle remains
open. No second spread can enter while this one is open.
