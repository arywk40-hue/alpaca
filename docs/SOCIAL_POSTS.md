# VegaGuard — five social posts

These posts are written for LinkedIn, X, Threads or a hackathon community page.
Keep the disclosures intact. Before publishing a screenshot, crop out account IDs,
API keys, bearer tokens, provider order IDs and exact plan IDs.

## Live UI for screenshots

Open `http://127.0.0.1:8001/social`. This dedicated read-only view shows the animated
agent heartbeat, market state, last/next cycle, durable event count, opportunities,
reprices, paper entry fill, open unrealized P&L, lifecycle progress and sanitized live
timeline. It contains no operator controls or identifiers.

Use these five crops with the posts below:

1. Full hero and `PAPER ONLY` badges.
2. Heartbeat plus the six evidence metrics.
3. Paper lifecycle strip ending at `EXIT PENDING`.
4. Live agent timeline during an open-market scan.
5. Production-threshold and hypothetical-research strip.

## Post 1 — Project launch

**Visual:** `assets/vegaguard-cover-v1.png`

I’m building **VegaGuard** for the Alpaca AI Trading Hackathon: a paper-only options
agent designed around one principle—evidence before execution.

It scans liquid ETFs, structures defined-risk debit spreads, applies deterministic
risk gates, and can always decide **no trade**. An LLM explains the thesis and risks,
but it cannot change the score, legs, quantity or execution decision.

The goal is not unconstrained prediction. It is bounded autonomy with an auditable
trail from market data to risk review to paper execution.

#AlpacaHackathon #AITrading #FinTech #OptionsTrading #PaperTrading

**Alt text:** Blue digital shield over market charts representing a risk-controlled
trading system.

## Post 2 — The operator dashboard

**Visual:** Dashboard overview showing `PAPER ONLY`, agent heartbeat, safety state and
event timeline. Keep the operator token field empty.

VegaGuard’s dashboard is an operator console—not a button that bypasses risk.

The live timeline shows:

`scan → candidate → risk review → approved plan → order status → monitoring → exit → P&L`

Simulation, hypothetical shadow results and Alpaca paper fills are displayed in
separate lanes. Mutation controls require a bearer token, paper execution starts
locked, and the dashboard cannot bypass market hours, quote freshness, liquidity,
position limits or maximum-loss checks.

That separation makes the demo understandable—and the agent accountable.

#AgenticAI #TradingSystems #RiskManagement #FastAPI #AlpacaHackathon

**Alt text:** VegaGuard operator dashboard with paper-only status, agent heartbeat
and a live event timeline.

## Post 3 — The strategy and safety boundary

**Visual:** Strategy/risk section of the dashboard or a clean slide containing the
five score components and defined-risk spread diagram.

The VegaGuard strategy is intentionally narrow and falsifiable.

It scores SPY, QQQ and IWM using daily regime, intraday trend, volume confirmation,
volatility state and market alignment. The production threshold stays fixed at 70.
Eligible signals can create only one-contract, defined-risk debit spreads using fresh
quotes and passing liquidity, DTE, buying-power and maximum-loss checks.

No naked options. No real-money path. No threshold changes based on one lucky trade.

#QuantTrading #OptionsSpreads #RiskFirst #PaperTrading #BuildInPublic

**Alt text:** Five market-signal components feeding a deterministic risk gate before
a defined-risk options spread.

## Post 4 — First provider-backed paper entry

**Visual:** Sanitized lifecycle timeline showing acknowledged, filled and monitored.
Do not show the provider order ID or account identifier.

VegaGuard has completed the entry half of its first genuine Alpaca paper lifecycle.

The reviewed IWM bear-put debit spread—long the 292.5 put and short the 284 put,
expiring September 25—was acknowledged and filled as one two-leg order at a $2.62
debit for one contract. The approved limit was $2.65.

At the August 31 close, its conservative executable mark was $2.35: **−$27
unrealized**. The guardian correctly held because neither the documented profit
target nor stop had triggered.

This is not a profit claim. Realized paper P&L remains zero until Alpaca reports a
provider-backed exit fill.

#Alpaca #PaperTrading #OptionsTrading #TradingTech #Auditability

**Alt text:** Sanitized paper-trade lifecycle showing an IWM spread acknowledged,
filled and under monitoring, with exit pending.

## Post 5 — What the evidence changed

**Visual:** Shadow-evaluation/session-report card showing opportunity count, reprices
and threshold comparison. Label all values `HYPOTHETICAL`.

The most useful result from VegaGuard’s live shadow lane was not a winning screenshot.
It was evidence against forcing more trades.

The August 31 session recorded 48 observations grouped into 16 opportunities and 86
quote-backed reprices. Five threshold-40 outcomes produced **−$225.90 hypothetical
net P&L** under conservative ask-to-enter and bid-to-exit accounting.

That sample is too small to optimize a strategy—but it is enough to avoid pretending
that a lower threshold is automatically better. Production remains at 70 while the
agent collects more independent evidence.

Honest abstention is a feature.

#MachineLearning #TradingResearch #EvidenceBased #FinTech #AlpacaHackathon

**Alt text:** Research report comparing hypothetical outcomes across trading-score
thresholds, with production threshold 70 unchanged.

## Suggested publishing order

1. Project launch and cover image.
2. Dashboard/operator controls.
3. Strategy and deterministic safety gates.
4. Provider-backed entry evidence with the unrealized-P&L disclosure.
5. Shadow research and why the production threshold did not change.

After the IWM position closes, update Post 4 with the provider-reported exit fill,
fees if available, and realized paper P&L. Never replace the word `unrealized` before
that evidence exists.
