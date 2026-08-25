# VegaGuard P&L Strategy — Volatility-Filtered ETF Debit Spreads

## Objective

Generate risk-adjusted paper P&L during the competition through a narrow, testable strategy—not through unconstrained LLM predictions. Agents explain, challenge and execute the strategy; the strategy itself creates the edge hypothesis.

## Why this strategy

We need trades that are liquid enough to execute, options structures with defined loss, and enough opportunities over a one-week competition. Broad ETFs meet that better than random single-stock earnings bets.

**Universe:** `SPY, QQQ, IWM, XLK, XLF, XLE`

We will start with SPY/QQQ/IWM and add sector ETFs only after the position monitor is stable.

## Alpha hypothesis

When a liquid ETF has aligned medium-term and intraday momentum **and** volatility is expanding without an excessively expensive option chain, its next 1–3 trading day directional move is more likely to exceed the cost of a defined-risk vertical spread.

This is falsifiable. We track signal score, expected move, actual move, spread P&L, and the no-trade alternatives.

## Signal: regime + momentum + volatility

Run every 15 minutes while the market is open. Each eligible ETF receives a score from -100 to +100.

| Component | Bullish condition | Bearish condition | Weight |
| --- | --- | --- | --- |
| Daily regime | 5-day return positive and price above 20-day EMA | 5-day return negative and price below 20-day EMA | 25 |
| Intraday trend | 30-min EMA(8) above EMA(21), price above VWAP | inverse | 25 |
| Confirmation | volume above its intraday baseline and return direction agrees | inverse | 20 |
| Volatility state | realized volatility rising but IV not extremely rich versus recent IV | inverse directional setup | 15 |
| Market alignment | SPY and candidate direction agree | opposite direction penalized | 15 |

Only trade when absolute score is at least **70**, at least three components agree, and no data-quality or liquidity rule fails.

## Options structure

| Signal | Order | Contract selection |
| --- | --- | --- |
| Score ≥ +70 | Bull call debit spread | Buy call delta ~0.45; sell call delta ~0.25; same expiry, 14–28 DTE. |
| Score ≤ -70 | Bear put debit spread | Buy put delta ~-0.45; sell put delta ~-0.25; same expiry, 14–28 DTE. |
| Otherwise | No trade | Log the rejection and continue scanning. |

Submit a single Alpaca `mleg` **limit** order. The maximum loss is the debit paid; the short leg is part of the spread, never naked.

## Entry filters

- Market must be open; do not enter during the first or last 30 minutes.
- Underlying has a valid option chain and option quotes are fresh.
- Both legs have a bid/ask spread no wider than 8% of midpoint.
- Spread debit must be less than 40% of the strike width.
- No duplicate plan, existing position in the same underlying, or order already open.
- Do not open inside 7 DTE or later than 28 DTE.

## Position sizing

The old $125 maximum loss is a demo limit, not a competitive paper-portfolio policy.

- Initial risk budget: **0.5% of current account equity per trade**.
- Hard maximum: **$500 risk per trade** until the first five reconciled trades complete.
- Maximum three open spreads, and no more than 1.5% of equity aggregate risk.
- Quantity = floor(risk budget / (spread debit × 100)), minimum one contract.
- If minimum size breaches the risk budget, skip the trade.

This is enough exposure to produce meaningful P&L while keeping the demo defensible.

## Exits and position management

| Event | Action |
| --- | --- |
| Spread reaches +50% of debit | Take profit and journal the reason. |
| Spread reaches -35% of debit | Exit to cap a failed thesis. |
| Signal reverses below / above -40 / +40 | Exit or reduce at the next liquid quote. |
| 3 trading days without follow-through | Time-stop exit. |
| 2 trading days before expiry | Mandatory exit; no exercise/assignment risk. |
| Quote quality deteriorates | Stop adding; guardian decides a safe limit exit. |

## Agent responsibilities

- **Signal Agent:** computes the score from Alpaca bars, quotes and snapshots. No order tool.
- **Structure Agent:** chooses valid legs and estimates debit, strike width, delta and expected move. No order tool.
- **Risk Critic:** checks every condition above and can veto.
- **Execution Agent:** receives only an approved typed multi-leg plan, uses MCP `place_option_order`, and records the receipt.
- **Position Guardian:** evaluates exits from live order/position updates.
- **Shadow Auditor:** records the rejected alternative and evaluates whether the committee added value after exit.

## Metrics that make the demo credible

- realized paper P&L and P&L per trade
- win rate, average win/loss, profit factor, max drawdown
- entry signal score versus realized outcome
- plan rejection reasons and avoided loss estimate
- fill time, execution price versus midpoint, and quote spread
- actual trade versus shadow alternative P&L

## What will disprove the strategy

If a sufficient sample of eligible signals has negative profit factor after simulated bid/ask costs, or if the shadow alternative consistently outperforms the chosen structure, we lower confidence / stop taking that class of trade. The agent must be able to decide **no trade**.

