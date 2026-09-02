# VegaGuard — demo narration

This script runs about six minutes at a natural pace. Speak to the dashboard and trade evidence; do not read the slides word for word.

## 0:00–0:35 — Evidence before execution

This is VegaGuard, a paper-only options agent I built around a simple idea: the important part of an autonomous trade is not just the signal. It is whether I can prove exactly what the system saw, why it approved the risk, what it sent to the broker, and what happened afterward.

VegaGuard has now completed one Alpaca paper spread from approval through exit. It made two dollars gross before fees. That is a small result, and I am going to present it as exactly that—one verified lifecycle, not a claim that one trade proves an edge.

## 0:35–1:10 — Why the signal is not enough

A plausible market direction can still become a bad order. Quotes age, option legs change, buying power moves, and a retry can accidentally create a duplicate. A language model can also produce confident text that should never be mistaken for trading authority.

VegaGuard treats those as engineering problems. Every trade has to survive the same deterministic path, and a clean no-trade decision is a valid outcome.

## 1:10–1:50 — Strategy

The universe is deliberately small: SPY, QQQ and IWM. The scanner combines daily regime, intraday trend, volume confirmation, volatility state and market alignment into a score from negative one hundred to positive one hundred.

The production threshold stays at seventy. A bullish score can create a bull-call debit spread; a bearish score can create a bear-put debit spread. Both structures have one long leg and one short leg with the same expiry, so the maximum loss is known at entry. VegaGuard does not sell naked options.

## 1:50–2:30 — Who is allowed to decide

The scanner owns direction. The spread builder owns contract selection. The risk critic checks the account and trade economics. The controller then binds the exact two legs, one-contract quantity and limit price to a five-minute plan.

There is an optional OpenAI thesis explainer, but it sits outside that authority path. It sees only validated facts and returns strict JSON: thesis, supporting signals, risks, invalidation and explanation. It cannot modify the score, threshold, legs, quantity or risk decision. If OpenAI is unavailable, the system labels and uses a deterministic fallback.

## 2:30–3:10 — Alpaca implementation

Alpaca's Market Data and Trading APIs provide the clock, paper account, positions, orders, option chain and quote evidence. The official Alpaca MCP server is the execution boundary. VegaGuard allowlists the option-order tool and submits the spread as one multi-leg limit order.

Immediately before that call, the backend checks the paper account again, verifies the market is open, refreshes the exact two quotes, limits price drift, checks liquidity and DTE, recalculates maximum loss, and checks buying power and position limits. A plan ID is single-use, and its client order ID makes the operation idempotent.

## 3:10–3:50 — Dashboard and durable state

The dashboard is an operator console, not a risk bypass. It streams journal events over server-sent events and separates simulation, hypothetical shadow outcomes, approved plans, acknowledged orders, fills and realized P&L.

The scheduler, trade-update stream and position guardian have independent heartbeats, so a stopped scanner cannot be confused with a stopped guardian. On restart, the guardian reconciles journaled spreads against Alpaca positions, including while the market is closed. Mutating controls require a bearer token entered locally in the browser; the token never appears in the page source or journal.

## 3:50–4:25 — The research loop

VegaGuard also learns from trades it does not take. Its shadow ledger saves the score breakdown, both leg quotes, timestamps, IV, DTE and rejection gates. It reprices the same legs after fifteen, thirty and sixty minutes using the ask to enter and the bid to exit.

Repeated scans of the same thesis and legs stay grouped as observations of one opportunity. That prevents five-minute scans from being counted as a pile of independent winning or losing trades. Shadow results are hypothetical and never appear as paper fills.

## 4:25–5:15 — The completed paper trade

Here is the provider-backed lifecycle. On August thirty-first, VegaGuard approved an exploration IWM bear-put spread: long the September twenty-fifth 292.5 put and short the 284 put, one contract each. The score was negative sixty-five against the separately labelled exploration threshold of forty.

The approved limit was a 2.65 debit. Alpaca acknowledged the exact multi-leg order and filled it at 2.62, or 262 dollars paid. While the position was open, the guardian recorded conservative executable marks. The worst observed mark was negative 85 dollars and the best was positive 20 dollars.

On September first, I explicitly authorized the exit to complete the hackathon lifecycle. Alpaca filled the closing spread at a 2.64 credit, or 264 dollars received. Gross realized paper P&L is positive two dollars. Alpaca did not report fees, so after-fee P&L remains unknown. This was an operator-authorized completion, not a profit-target or stop trigger.

## 5:15–5:50 — What the result means

The result proves the plumbing: a fresh candidate became a bounded plan, the plan crossed the MCP boundary once, Alpaca acknowledged and filled both legs, the guardian monitored the position, the exit filled, and the journal reconciled P&L from provider prices.

It does not prove the strategy is profitable. One trade has no statistical power, so VegaGuard does not change the production threshold based on it. Historical option quote coverage was not sufficient for a defensible optimization, and the system records that limitation instead of manufacturing a backtest.

## 5:50–6:10 — Close

For me, that is the point of VegaGuard. The model can make the trade understandable, but it cannot make the trade permissible. Alpaca supplies the market and broker truth; deterministic gates control authority; and the journal makes every claim reproducible.

VegaGuard is not a blank cheque for an AI trader. It is a small, inspectable system for bounded autonomy.
