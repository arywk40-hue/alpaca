# VegaGuard — 6–7 minute narration

Read this alongside `HACKATHON_DECK_10_SLIDES.md`. The timings are guidance; the
script is intentionally explicit about what is simulated and what is not yet a
provider-backed paper fill.

## 0:00–0:40 — Slide 1: Evidence before execution

VegaGuard is an auditable autonomous options risk committee. It looks for bounded
ETF options opportunities in SPY, QQQ, and IWM, but its job is not to manufacture
activity. Its job is to make a decision that can be inspected, challenged, and
stopped. The system is paper-only by design. It creates a defined-risk debit spread,
keeps the exact evidence used to approve it, and refuses to cross the execution
boundary until every independent gate is satisfied.

## 0:40–1:20 — Slide 2: The problem is not finding a trade

Finding a plausible signal is the easy part. The dangerous part is what happens
next: a quote can be stale, a spread can be assembled with the wrong legs, the
maximum loss can be hidden in a log, or a language model can turn a suggestion into
an order. VegaGuard treats all of those as authority-boundary problems. A useful
demo therefore includes an honest abstention and a complete evidence trail, not a
random order placed just to make a dashboard look active.

## 1:20–2:00 — Slide 3: A deterministic committee owns authority

The flow is scan, score, spread construction, risk review, exact plan creation, and
only then the paper execution boundary. The deterministic scanner owns the score.
The spread builder permits one long option and one short option with defined risk.
The risk gate checks the economics and the account constraints. The controller binds
the approved legs and quantity to a short-lived plan identifier. Alpaca MCP is used
only at that final boundary, and only through the allowlisted option-order path.

## 2:00–2:40 — Slide 4: Evidence travels with every candidate

Each candidate is more than a score. It carries the component breakdown, underlying
price, bid, ask, and midpoint for both legs, quote timestamps, spread width, implied
volatility, DTE, volume, open interest, and every rejection gate. A fresh quote is
required again immediately before submission. The shadow ledger keeps observations
inside one opportunity, so twelve five-minute scans do not masquerade as twelve
independent trades. This is the evidence needed to learn whether the system is too
conservative or correctly avoiding bad liquidity.

## 2:40–3:20 — Slide 5: Execution is locked behind independent gates

The visible labels are intentional: PAPER ONLY, DRY RUN, and exact-plan approval.
The account must be an Alpaca paper account, the US options market must be open,
quotes must be fresh and liquid, DTE and spread validation must pass, buying power
and maximum loss must fit the risk policy, and the position limits are one open
position and one whole contract. An operator must arm the session, and the submitted
plan must be the same unexpired plan that was reviewed. Changing a flag cannot bypass
the market clock, quote, spread, or risk gates.

## 3:20–4:00 — Slide 6: The dashboard makes state legible

The dashboard is the operator surface for that bounded workflow. It shows a heartbeat
with running, stopped, stale, or error state, the last and next cycle, and the latest
error. Server-sent events animate the timeline from scan to candidate to risk review
to plan and order status. Separate cards keep simulation, hypothetical shadow marks,
approved plans, acknowledged orders, fills, and realized P&L from being conflated.
The public view is read-only. A local operator can enter a bearer token manually;
the browser sends it only on mutation requests and never puts it in the HTML or
journal.

## 4:00–4:40 — Slide 7: OpenAI explains; it does not decide

There is one bounded OpenAI integration: the Trade Thesis & Risk Explainer. It sees
only structured, already-validated scanner, spread, and risk facts. Its response is
strict JSON with a thesis, supporting signals, risks, invalidation, and explanation.
It is advisory text. It cannot change a score, a threshold, the option legs, the
quantity, the risk decision, or execution. If there is no key or the API fails, the
deterministic fallback is clearly labelled. This preserves a useful explanation
without handing authority to an untrusted response.

## 4:40–5:20 — Slide 8: Offline replay proves accounting, not performance

For a credential-free demo, I run the sanitized replay fixture. It has three
observations and two simulated trades. The accounting path reports gross P&L of
50 dollars, 10 dollars of costs, and 40 dollars of net hypothetical P&L, with a
50-percent win rate, profit factor 1.6154, and maximum drawdown of negative 65
 dollars. Those numbers are fixture output, not live results. The lifecycle is
explicitly labelled SIMULATION_REPLAY, and the paper counters remain zero: there
are no submitted, acknowledged, filled, or realized paper trades in this demo.

## 5:20–6:00 — Slide 9: Research is honest about uncertainty

The production threshold stays at 70. Exploration and threshold comparisons are
separate research lanes; one trade cannot promote a threshold. Historical options
coverage is limited by the available Alpaca entitlement and cache, and a small
sanitized fixture cannot establish an edge. VegaGuard records missing quotes,
staleness, and liquidity failures instead of filling gaps with invented data. That
honesty matters: a conservative no-trade decision is evidence about the system, too.

## 6:00–6:40 — Slide 10: The next proof

The remaining proof is one complete, fresh paper lifecycle: scan, approve a short-
lived exact plan, submit it, receive acknowledgement, fill it, monitor the position,
submit the exit, close it, and journal realized provider-backed P&L. That has to happen
during market hours with the paper account and the operator explicitly approving the
same plan ID. Until the journal contains both entry and exit fills, VegaGuard will say
ready but not proven. That is the point of the project: bounded autonomy with evidence
before execution.

