# VegaGuard Agent Landscape and Defensible Gap

**Research date:** 2026-08-25  
**Scope:** public Alpaca examples, the TradingAgents research framework, and publicly visible team ideas on the Alpaca AI Trading Agents Hackathon.  A team idea is evidence of what is being proposed, not proof that a working implementation exists.

## Executive decision

We should not compete as “another multi-agent stock picker.” That category is already crowded. The strongest defensible product is:

> **VegaGuard: an autonomous options desk that must earn the right to trade.**

The novelty is a closed-loop decision protocol, not a larger number of LLMs:

1. generate a structured opportunity;
2. select an options structure and quantify its costs;
3. attack the idea with adverse spot, volatility, liquidity, and fill scenarios;
4. allocate a limited risk budget across competing opportunities;
5. abstain, wait, or execute through Alpaca;
6. record the rejected alternative and compare it with the realized trade afterward.

The system is successful only if this protocol improves **net P&L after spread/slippage**, drawdown, and execution quality against a simpler baseline.

## What is already common

| Agent or capability | Status in public exemplars | Evidence | Decision for VegaGuard |
|---|---|---|---|
| Technical / momentum analyst | Common | TradingAgents lists technical analysts; Alpaca's CUSP system has a momentum agent. | Keep as deterministic signal features, not our headline novelty. |
| Fundamental / macro analyst | Common | TradingAgents includes fundamentals and news; CUSP uses macro data from FRED, VIX, and rates. | Optional context, not the core. |
| News / sentiment / social agent | Common | Agent M ingests news and social sources, scores credibility, and weights sentiment. Alpaca's bot roundup shows news-triggered and sentiment bots. | Do not pitch “AI reads news” as differentiation. |
| Bull-vs-bear debate / critic | Common | TradingAgents uses bullish and bearish researchers; CUSP uses a critic and investment-memo validation. | Use only if it blocks a measurable failure mode. |
| Portfolio risk governor | Common | TradingAgents has a risk team; CUSP has deterministic risk controls; public teams describe Greek, margin, and position caps. | Mandatory safety layer, not novelty. |
| Alpaca MCP / API execution | Common requirement | Alpaca's MCP exposes research, account, and trading workflows; multiple hackathon ideas explicitly use MCP. | Demonstrate it cleanly, but it cannot be the thesis. |
| Memory / RAG / knowledge graph | Already claimed | Agent M uses Qdrant RAG and portfolio context; LS101 proposes ZukuDB for decisions and outcomes; the community roundup highlights a portfolio knowledge graph. | Memory alone is not new. |
| Options trade selection | Emerging and crowded | AlphaLoop proposes options-chain/IV analysis and defined-risk strategies; ImperalX proposes event detection plus IV-vs-realized volatility; midas-gate proposes SPY credit spreads; SentixAlpha proposes directional calls/puts. | We must go beyond “choose a call/put/spread.” |
| Dashboard, reasoning trace, replay | Common product pattern | CUSP, AlphaLoop, and AlpacaSentry all emphasize logging, dashboards, or replay. | Required for judging, not differentiation. |

The role taxonomy is not speculative: TradingAgents explicitly describes fundamentals, sentiment, news, and technical analysts, bullish/bearish researchers, a trader, a risk team, and a fund manager. Alpaca's CUSP example similarly uses a regime screener, five isolated research agents, a critic, deterministic risk, execution, and monitoring. Agent M connects ingestion, event identification, credibility scoring, sentiment, RAG, and Alpaca execution. [TradingAgents role taxonomy](https://tradingagents-ai.github.io/), [TradingAgents paper](https://arxiv.org/abs/2412.20138), [CUSP multi-agent system](https://alpaca.markets/learn/building-a-multi-agent-ai-trading-system-on-alpaca), [Agent M](https://alpaca.markets/learn/agent-m-an-autonomous-multi-agent-trading-platform-using-alpaca)

## What is underrepresented (the opportunity)

“Not present” cannot be proven from public pages: the hackathon is live and teams may be building unpublished features. The following are therefore **defensible gaps in the sampled public landscape**, not exclusivity claims.

| Gap | Why it matters to options P&L | How we make it testable |
|---|---|---|
| **Opportunity auction / capital allocator** | Several signals can be correct but still compete for the same finite risk budget. A fixed one-trade-per-scan rule can choose a weaker trade or over-concentrate correlated underlyings. | Rank candidates by expected value per dollar of worst-case loss, correlation, liquidity, and current exposure; compare against equal-size or first-signal baselines. |
| **Adversarial pre-trade stress agent** | Options can lose despite a correct directional thesis because of IV crush, spread widening, gap risk, or a bad fill. | Re-price each candidate under spot, IV, time, skew, and fill shocks; reject if expected value collapses or max loss breaches the budget. |
| **Execution-quality agent** | A paper P&L result is contaminated if the system assumes mid-price fills. Limit-vs-wait-vs-cancel decisions affect realized P&L. | Log quote width, chosen limit, time-to-fill, fill probability, slippage, and adverse selection; run a realistic fill simulator. |
| **Calibrated abstention** | “No trade” is an action. The agent should know when its forecast is unreliable instead of forcing activity during a four-day contest. | Maintain predicted win probability and realized outcome by strategy, regime, and agent; measure calibration, abstention rate, and P&L avoided by rejected trades. |
| **Counterfactual trade ledger** | Without the rejected alternative, we cannot tell whether an outcome came from skill, luck, or simply avoiding a worse trade. | Persist every candidate, selected plan, rejected plan, shadow fill, and later mark-to-market outcome; report selected-vs-shadow and trade-vs-no-trade deltas. |
| **Position lifecycle / repair** | An entry agent is not autonomous if it cannot manage partial fills, stale orders, profit-taking, stop logic, or a spread that no longer matches the thesis. | Model positions as state machines and test reconciliation, exit, roll, cancel/replace, and circuit-breaker paths. |
| **Regime-conditional reliability** | A signal can work in trend markets and fail in range markets. A global confidence score hides this. | Score each component by regime and update weights only from out-of-sample, closed trades. |

Recent research makes this gap especially important: a 2026 audit of LLM trading work identifies temporal integrity, real-world frictions, counterfactual robustness, calibration, and execution semantics as unresolved evidence problems. That is a strong reason to make our audit trail a product feature rather than a post-hoc chart. [Reported Alpha from LLM Trading Agents Should Not Be Treated as Deployment Evidence](https://arxiv.org/html/2605.16895v1), [Agentic Trading evidence map](https://arxiv.org/abs/2605.19337)

## The proposed agent set

The LLM should coordinate and challenge structured evidence; deterministic code should calculate prices, Greeks, limits, sizing, and P&L.

### 1. Opportunity Scout

Consumes the existing ETF/underlying feature set and produces a typed thesis: direction, horizon, catalyst or regime, invalidation level, and confidence. It may propose no trade.

### 2. Structure & Volatility Agent

Converts the thesis into a defined-risk option structure. It compares debit spread, credit spread, or no-trade using expected move, IV-versus-realized volatility, skew, days-to-expiry, Greeks, bid/ask width, open interest, and maximum loss. The output is an order-independent plan, not an order.

### 3. Adversarial Risk Agent

Attempts to break the plan with adverse spot movement, IV shock, time decay, spread widening, partial fill, and correlated portfolio exposure. It returns explicit rejection reasons and a stress table.

### 4. Risk-Budget Auctioneer

Compares all surviving candidates and allocates a fixed daily risk budget. It penalizes correlation and existing exposure, so the system can choose **zero, one, or several small trades** rather than blindly taking the first signal.

### 5. Execution-Quality Agent

Chooses patient limit, aggressive limit, wait, cancel, or no-trade based on quote quality and the plan's edge after costs. Every decision records the assumed fill and the realized fill.

### 6. Position Guardian + Counterfactual Auditor

The Guardian manages the full lifecycle. The Auditor stores the selected and rejected plans, updates reliability by regime, and produces the selected-vs-shadow P&L report. This is the learning loop; it must never rewrite historical decisions.

## Architecture change from the current repository

The current deterministic scorer, spread builder, cost model, and replay harness remain the foundation. We add the novelty in this order:

```text
market snapshot
    -> opportunity scout
    -> structure & volatility
    -> adversarial stress
    -> risk-budget auction
    -> execution-quality decision
    -> Alpaca paper order
    -> position guardian
    -> counterfactual audit + calibration
```

The first implementation should be deterministic and replayable. LLM calls are only allowed to summarize evidence, challenge a plan, or select among already-calculated candidates. No LLM may invent a price, override a hard risk limit, or submit an unvalidated order.

## Proof plan for the hackathon

Run ablations on the same historical/replay fixtures and then shadow/paper trade:

1. fixed rule-based spread baseline;
2. baseline + structure selection;
3. + adversarial stress;
4. + risk-budget auction;
5. + execution-quality model;
6. + lifecycle guardian and counterfactual audit.

Report net P&L after estimated costs, return on risk, maximum drawdown, profit factor, fill rate, average slippage, rejected-opportunity P&L, and calibration by regime. The claim we want to prove is narrow:

> **VegaGuard improves risk-adjusted, cost-aware paper-trading outcomes by knowing when not to trade and by allocating risk across option structures.**

Do not claim that the agent predicts the market better until the ablation demonstrates it. The judging demo should show one live opportunity, its chosen spread, the adversarial scenarios that nearly killed it, the capital budget decision, the Alpaca order, and the later selected-vs-shadow audit.

## Bottom line

The market is full of analyst agents. It is less full of agents that can prove that a particular **options decision** was better than the available alternatives after costs and risk. That is the wedge we should own.

