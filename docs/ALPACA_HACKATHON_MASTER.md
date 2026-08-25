# Alpaca AI Trading Agents Hackathon — Master Build Reference

This is the single reference used to build VegaGuard. It keeps only the material relevant to this hackathon; Broker API, transfers, crypto, and live-account onboarding are deliberately excluded.

## 1. Non-negotiable requirements

| Requirement | How VegaGuard proves it |
| --- | --- |
| Autonomous AI agent | A scheduled, event-driven loop scans a universe, forms a thesis, produces a structure, passes a deterministic risk review, and manages an open position. |
| Alpaca Trading API | Account, clock, positions, assets, option contracts, market data, orders, and activities are all read or executed through Alpaca. |
| MCP or CLI | The official Alpaca MCP v2 server is used as the execution boundary. `place_option_order` is the only order-submit tool exposed to the agent. |
| Options trading | Every approved trade is an option position. The target strategy is a defined-risk debit vertical spread. |
| Paper environment | A brand-new hackathon-only paper account is mandatory. `ALPACA_PAPER_TRADE=true` is required and live mode is rejected by code. |

## 2. Official source map

Read in this order:

1. [Hackathon overview](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon)
2. [Paper trading](https://docs.alpaca.markets/us/docs/paper-trading)
3. [Trading API](https://docs.alpaca.markets/us/docs/trading-api)
4. [Options trading](https://docs.alpaca.markets/us/docs/options-trading)
5. [Options orders](https://docs.alpaca.markets/us/docs/options-orders)
6. [Options Level 3 / multi-leg orders](https://docs.alpaca.markets/us/docs/options-level-3-trading)
7. [Trading MCP Server](https://docs.alpaca.markets/us/docs/alpaca-mcp-server)
8. [WebSocket streaming / trade updates](https://docs.alpaca.markets/us/docs/websocket-streaming)
9. [Historical option data](https://docs.alpaca.markets/us/docs/historical-option-data)
10. [Real-time option data](https://docs.alpaca.markets/us/docs/real-time-option-data)
11. [API reference](https://docs.alpaca.markets/reference)
12. [Alpaca docs LLM index](https://docs.alpaca.markets/us/llms.txt)

The LLM index is the complete official documentation map. Add `.md` to a docs page URL to obtain that page in Markdown.

## 3. Credentials and environment

Paper and live keys are separate. Use only paper keys in the new account:

```bash
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_PAPER_TRADE=true
ALPACA_TOOLSETS=account,trading,assets,stock-data,options-data
ALLOW_ORDER_EXECUTION=false
```

- Paper Trading REST base: `https://paper-api.alpaca.markets`
- Market Data REST base: `https://data.alpaca.markets`
- Paper trade-update stream: `wss://paper-api.alpaca.markets/stream`
- Keep secrets in `.env`; `.env` must never be committed or pasted into chat.

## 4. The Alpaca surfaces VegaGuard uses

| Need | API / MCP capability | Purpose |
| --- | --- | --- |
| Buying power / status | `GET /v2/account` / `get_account_info` | Gate an order before it exists. |
| Market hours | `GET /v2/clock` / `get_clock` | No entries when markets are closed. |
| Current exposure | `GET /v2/positions` / `get_all_positions` | Enforce portfolio limits. |
| Eligible underlyings | Assets with `options_enabled` | Restrict the universe to optionable liquid names. |
| Contract discovery | `GET /v2/options/contracts` / `get_option_contracts` | Validate expiration, strike and contract symbol at runtime. |
| Chain / Greeks | option snapshots / `get_option_chain` | Quote quality, implied volatility, delta, liquidity. |
| Underlying signal | stock bars / `get_stock_bars` | Regime, trend, realized volatility, volume. |
| Submit plan | `POST /v2/orders` via `place_option_order` | Submit a single-leg or `mleg` order. |
| State monitoring | `trade_updates`, orders, activities | Fill, partial fill, reject, cancel, exit and journal reconciliation. |

## 5. Options rules the code must enforce

- Option quantities are whole contracts; do not use `notional`.
- Single-leg option orders support `day`/`gtc`; extended-hours option orders are unsupported.
- Never hard-code a contract symbol. Discover and validate it on every cycle.
- The contracts endpoint defaults to a small near-expiry result set; explicitly filter expiration and strike.
- A multi-leg order uses `order_class: "mleg"`, a `legs` array, and a limit price. This is the correct way to enter a vertical spread atomically.
- Do not open a naked short option. VegaGuard permits only long single legs during testing and defined-risk debit spreads for the actual strategy.
- Stop opening new positions near expiry. In-the-money options can be auto-exercised and paper assignments must be reconciled with REST activity/positions.
- Option data can be delayed or subscription-dependent. The agent must reject stale, missing, or excessively wide quotes.

## 6. MCP v2 setup and safe tool boundary

The official server is launched locally with `uvx alpaca-mcp-server`. MCP v2 dynamically exposes tool schemas, so older v1 tutorial tool parameters must not be copied.

The agent only needs these toolsets: `account,trading,assets,stock-data,options-data`.

Allowed execution surface:

- `get_account_info`, `get_clock`, `get_all_positions`
- `get_option_contracts`, `get_option_chain`, `get_option_snapshot`
- `place_option_order`, `get_orders`, `get_order_by_client_id`, `cancel_order_by_id`

Never expose `close_all_positions` or `cancel_all_orders` to the free-form LLM. They are deliberately outside its tool budget.

## 7. Reliability contract

1. Create a unique `client_order_id` before submitting a trade.
2. Persist the candidate, thesis, risk result and intent to the journal **before** MCP execution.
3. Treat `trade_updates` as the order-state source of truth; REST orders/positions/activities reconcile reconnects.
4. Back off on rate limits; do not poll the entire option chain at high frequency.
5. Persist Alpaca request IDs when available so errors are traceable.

## 8. Paper-trading limits

Paper data gives a live-like build environment, but it does not simulate market impact, queue position, latency slippage, price improvement, fees, dividends, or information leakage. Contest paper P&L is useful evidence, not proof of a deployable live strategy.

## 9. Do not waste build time on

- Broker API / Connect / customer onboarding
- transfers, KYC, funding, ACATS, custodial accounts
- crypto, forex, IPOs, FIX
- a generic chatbot over stock prices
- manual trade approvals that break the autonomous-agent requirement

