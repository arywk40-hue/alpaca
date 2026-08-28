# Alpaca API — Consolidated Developer Documentation
*Compiled for the AI Trading Agents Hackathon (lablab.ai) — source: docs.alpaca.markets*

---

## 1. Welcome / Overview

Alpaca offers simple, modern API-first solutions that let individuals and businesses connect applications and build algorithms to buy and sell stocks or crypto.

Four main API surfaces:

| API | Purpose | Start here |
|---|---|---|
| **Broker API** | Build trading apps / brokerage services for end users (challenger banks, trading apps) | `getting-started-with-broker-api` |
| **Trading API** | Stock & crypto trading for individuals, algo/prop traders | `getting-started-with-trading-api` |
| **Market Data API** | Real-time + 6+ years historical data for stocks & crypto | `getting-started-with-alpaca-market-data` |
| **Connect API (OAuth2)** | Let any user with an Alpaca brokerage account connect to your app | `about-connect-api` |

There's also a responsive web trading dashboard for non-developers, and an **AI agent–optimized index** at `https://docs.alpaca.markets/us/llms.txt` — append `.md` to any docs URL to get its raw Markdown.

---

## 2. Authentication

Alpaca's APIs live under different domains depending on account type:

| Account type | Trading API | Market Data API | Broker API | Auth endpoint |
|---|---|---|---|---|
| Live | `api.alpaca.markets` | `data.alpaca.markets` | — | — |
| Paper | `paper-api.alpaca.markets` | `data.alpaca.markets` | — | — |
| Live broker partner | — | `data.alpaca.markets` | `broker-api.alpaca.markets` | `authx.alpaca.markets` |
| Sandbox broker partner | — | `data.sandbox.alpaca.markets` | `broker-api.sandbox.alpaca.markets` | `authx.sandbox.alpaca.markets` |

Credentials are **not interchangeable** across live/paper/correspondent accounts.

### Auth flow 1 — Client Credentials (Broker API; not yet available for Trading API)
Exchange a client ID + secret (or a signed `private_key_jwt` assertion) for a short-lived (15 min) bearer token.

```bash
curl -X POST "https://authx.alpaca.markets/v1/oauth2/token" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=client_credentials" \
     -d "client_id={YOUR_CLIENT_ID}" \
     -d "client_secret={YOUR_CLIENT_SECRET}"
```
Response:
```json
{ "access_token": "{TOKEN}", "expires_in": 899, "token_type": "Bearer" }
```
Use it:
```bash
curl -X GET "https://broker-api.alpaca.markets/v1/accounts" \
     -H "Authorization: Bearer {TOKEN}"
```
> Don't request a new token per call — cache and reuse until it expires.

### Auth flow 2 — Legacy (key ID + secret key)
Used directly with Trading/Market Data APIs via HTTP Basic Auth **or** custom headers:

```bash
curl -X GET "https://api.alpaca.markets/v2/account" \
     -H "APCA-API-KEY-ID: {YOUR_API_KEY_ID}" \
     -H "APCA-API-SECRET-KEY: {YOUR_API_SECRET_KEY}"
```

---

## 3. SDKs & Tools

### Official client SDKs
| Language | Package |
|---|---|
| Python | [`alpaca-py`](https://alpaca.markets/sdks/python/) ([PyPI](https://pypi.org/project/alpaca-py/)) |
| .NET/C# | [`alpaca-trade-api-csharp`](https://github.com/alpacahq/alpaca-trade-api-csharp/) ([NuGet](https://www.nuget.org/packages/Alpaca.Markets/)) |
| Node/JS | [`alpaca-trade-api-js`](https://github.com/alpacahq/alpaca-trade-api-js/) ([npm](https://www.npmjs.com/package/@alpacahq/alpaca-trade-api)) |
| Go | [`alpaca-trade-api-go`](https://github.com/alpacahq/alpaca-trade-api-go/) |
| Java | [`alpaca-java`](https://github.com/alpacahq/alpaca-java) ([Maven](https://mvnrepository.com/artifact/markets.alpaca/alpaca-java)) |

Community SDKs also exist for Rust (`apca` / `apcacli`, `alpaca-rust`).

### OpenAPI specs
- Broker API: `https://docs.alpaca.markets/openapi/broker-api.json`
- Trading API: `https://docs.alpaca.markets/openapi/trading-api.json`
- Market Data API: `https://docs.alpaca.markets/openapi/market-data-api.json`

### alpaca-py (Python) capabilities
- **Market Data API** — live/historical data, 5000+ stocks, 20+ crypto
- **Trading API** — stock/crypto order execution
- **Broker API & Connect** — build robo-advisors/brokerages

---

## 4. Getting Started with Trading API

Install an SDK, create a free Alpaca account, grab API keys, and start submitting orders (stocks and crypto).

Every Trading API response includes an `X-Request-ID` header — persist these for support requests (they can't be looked up after the fact).

```bash
curl -v https://paper-api.alpaca.markets/v2/account
# ...
# < X-Request-ID: 649c5a79da1ab9cb20742ffdada0a7bb
```

Key sub-pages (all under `docs.alpaca.markets/us/docs/`):
- `working-with-account`, `working-with-assets`, `working-with-orders`, `working-with-positions`
- `paper-trading` — free simulated trading environment (recommended starting point)
- `account-plans`, `crypto-trading`, `options-trading`, `account-activities`
- `fractional-trading`, `margin-and-short-selling`, `orders-at-alpaca`
- `alpaca-elite-smart-router` (DMA Gateway / advanced order types)
- `user-protection`, `websocket-streaming`
- `regulatory-fees`

---

## 5. Getting Started with Market Data API

```bash
pip install alpaca-py                                     # Python
go get -u github.com/alpacahq/alpaca-trade-api-go/v3/alpaca  # Go
npm install --save @alpacahq/alpaca-trade-api               # Node
dotnet add package Alpaca.Markets                            # C#
```

Generate keys from the [Alpaca dashboard](https://app.alpaca.markets/brokerage/dashboard/overview) → API Keys panel.

Example — historical crypto bars (Python):

```python
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

client = CryptoHistoricalDataClient()  # no keys needed for crypto data

request_params = CryptoBarsRequest(
    symbol_or_symbols=["BTC/USD"],
    timeframe=TimeFrame.Day,
    start=datetime(2022, 9, 1),
    end=datetime(2022, 9, 7),
)

btc_bars = client.get_crypto_bars(request_params)
btc_bars.df  # pandas DataFrame
```

Sub-pages: `historical-api` (stocks/crypto/options/news history), `streaming-market-data` (WebSocket: real-time stock, crypto, news, options), `market-data-faq`.

---

## 6. Trading CLI (`alpacahq/cli`) — Alpha Preview

A terminal-native interface to Trading + Market Data APIs. Apache 2.0, actively evolving (commands/flags may change).

### Install
```bash
go install github.com/alpacahq/cli/cmd/alpaca@latest   # Go
brew install alpacahq/tap/cli                           # Homebrew
alpaca version && alpaca doctor                         # verify
```

### Authenticate
```bash
alpaca profile login                       # OAuth, paper (default), browser flow
alpaca profile login --api-key             # API keys, paper
alpaca profile login --api-key --live      # API keys, live

alpaca profile list
alpaca profile switch <name>
alpaca profile logout <name>

# CI / agents:
export ALPACA_API_KEY=PK...
export ALPACA_SECRET_KEY=...
alpaca account get
```

### Config env vars
`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_LIVE_TRADE`, `ALPACA_PROFILE`, `ALPACA_OUTPUT` (`json`|`csv`), `ALPACA_CONFIG_DIR`. Creds stored in `~/.config/alpaca/profiles/` (0600 perms).

### Output
```bash
alpaca position list                  # JSON (default)
alpaca position list --csv
alpaca position list --jq '[.[] | {symbol, qty, unrealized_pl}]'
alpaca account get --quiet
```

### Command reference
```bash
# Account & portfolio
alpaca account get
alpaca account config get / set
alpaca account activity list
alpaca account portfolio

# Orders
alpaca order submit --symbol AAPL --side buy --qty 10 --type market
alpaca order submit --symbol AAPL --side buy --qty 10 --type limit --limit-price 185
alpaca order submit --symbol AAPL --side buy --qty 10 --type market --dry-run   # preview only
alpaca order list [--status all]
alpaca order get --order-id <id>
alpaca order replace --order-id <id> --qty 20
alpaca order cancel --order-id <id>
alpaca order cancel-all

# Positions
alpaca position list
alpaca position get --symbol AAPL
alpaca position close --symbol AAPL
alpaca position close-all

# Options
alpaca option contracts --underlying-symbol AAPL
alpaca option get --symbol-or-id AAPL250620C00200000
alpaca option exercise / do-not-exercise --symbol-or-id <contract>

# Market data — stocks
alpaca data bars --symbol AAPL --start 2025-01-01 --timeframe 1Day
alpaca data quotes / trades --symbol AAPL --start 2025-06-01
alpaca data latest-bar / latest-quote / latest-trade / snapshot --symbol AAPL
alpaca data screener most-actives / movers

# Market data — crypto
alpaca data crypto bars --symbol BTC/USD --start 2025-01-01 --timeframe 1Day
alpaca data crypto latest-quotes --symbol BTC/USD,ETH/USD
alpaca data crypto snapshots / crypto-orderbook --symbol BTC/USD

# Market data — options
alpaca data option chain --underlying-symbol AAPL
alpaca data option snapshot / latest-quotes --symbol AAPL250620C00200000

# Market data — other
alpaca data news --symbol AAPL
alpaca data corporate-actions --symbols AAPL --types dividend
alpaca data forex rates --currency-pairs USD/EUR
alpaca clock
alpaca calendar

# Watchlists
alpaca watchlist create --name "Tech Stocks" --symbols AAPL,MSFT,NVDA
alpaca watchlist list / get / add / remove / delete

# Assets
alpaca asset list
alpaca asset get --symbol AAPL

# Raw API access (any endpoint)
alpaca api GET /v2/account
echo '{"symbol":"AAPL","qty":"1","side":"buy","type":"market","time_in_force":"day"}' \
  | alpaca api POST /v2/orders
```

### Discoverability
```bash
alpaca --help / --help-all
alpaca order submit --help
alpaca order list --schema     # response shape, no API call
```

### Built for AI agents
- No confirmation prompts (immediate execution)
- Structured JSON errors on stderr, exit codes `0`=ok, `1`=error, `2`=auth failure
- Auto-retry on 429/5xx (max 3, honors `Retry-After`)
- `--dry-run` to preview orders
- `--schema` to inspect response shapes without calling the API
- `--client-order-id` for idempotent order submission:

```bash
CLIENT_ORDER_ID="$(uuidgen)"
alpaca order submit --symbol AAPL --side buy --qty 10 --type market \
  --client-order-id "$CLIENT_ORDER_ID"
alpaca order get-by-client-id --client-order-id "$CLIENT_ORDER_ID"
```

> Whitelisting CLI commands in an MCP client (Cursor/Claude) to skip confirmations removes a safety layer — an agent with whitelisted order commands can trade unsupervised.

### CLI vs. MCP Server
| Aspect | CLI | MCP Server |
|---|---|---|
| Invocation | One command, exits | Background process, whole session |
| Context cost | Just the command string | Full tool schemas in context |
| Output | Pipeable to scripts/files | Returned through MCP to the model |
| AI host needed | No | Yes |
| Best for | Scripts, cron, CI, focused actions | Long-lived multi-tool AI sessions |

**Important:** paper trading is the default; live requires explicit `--live` / `ALPACA_LIVE_TRADE=true`. No confirmation on destructive commands (`order cancel-all`, `position close-all`). Rate limits apply.

---

## 7. Trading MCP Server (`alpaca-mcp-server`) — for AI agents / Claude, Cursor, VS Code, etc.

Turns natural language into real trading actions: **"Buy 10 shares of AAPL at market price."**

### What you can do
- **Account & portfolio**: balances, buying power, positions, history, activity
- **Trade**: stocks, options, crypto — market/limit/stop/trailing-stop/brackets/multi-leg
- **Market data**: bars, quotes, trades, snapshots, option chains + Greeks
- **Discover**: most-active stocks, movers, news, corporate actions
- **Organize**: watchlists

### Prerequisites
- Python 3.10+, `uv`/`uvx`
- Alpaca API keys (a free paper account is enough)
- An MCP client: Claude Desktop, Cursor, VS Code, Claude Code, Gemini CLI, PyCharm, etc.

### Setup (example: Claude Desktop / Cursor / VS Code)
```json
{
  "mcpServers": {
    "alpaca": {
      "command": "uvx",
      "args": ["alpaca-mcp-server"],
      "env": {
        "ALPACA_API_KEY": "your_alpaca_api_key",
        "ALPACA_SECRET_KEY": "your_alpaca_secret_key"
      }
    }
  }
}
```

Claude Code (CLI):
```bash
claude mcp add alpaca --scope user --transport stdio uvx alpaca-mcp-server \
  --env ALPACA_API_KEY=your_alpaca_api_key \
  --env ALPACA_SECRET_KEY=your_alpaca_secret_key
```

Docker:
```bash
git clone https://github.com/alpacahq/alpaca-mcp-server.git
cd alpaca-mcp-server
docker build -t mcp/alpaca:latest .
docker run -e ALPACA_API_KEY=your_key -e ALPACA_SECRET_KEY=your_secret mcp/alpaca:latest
```

**Verify:** restart your MCP client and ask *"What is my Alpaca account balance and buying power?"*

### Configuration (env vars)
| Variable | Required | Default | Description |
|---|---|---|---|
| `ALPACA_API_KEY` | Yes | — | API key ID |
| `ALPACA_SECRET_KEY` | Yes | — | Secret key |
| `ALPACA_PAPER_TRADE` | No | `true` | `false` = live trading |
| `ALPACA_TOOLSETS` | No | all | Comma-separated toolset filter |

Toolsets: `account`, `trading`, `watchlists`, `assets`, `stock-data`, `crypto-data`, `options-data`, `corporate-actions`, `news`, `fixed-income-data`, `index-data`.

Example — read-only market data agent:
```json
{ "env": { "ALPACA_TOOLSETS": "account,stock-data,crypto-data,options-data,news" } }
```

### Supported clients
Claude Desktop, VS Code, Cursor, PyCharm, Claude Code (CLI), Gemini CLI — all local or remote.

### 65 tools across the API surface
**Account & Portfolio**: `get_account_info`, `get_account_config`, `update_account_config`, `get_portfolio_history`, `get_account_activities`, `get_account_activities_by_type`

**Orders**: `place_stock_order`, `place_crypto_order`, `place_option_order`, `get_orders`, `get_order_by_id`, `get_order_by_client_id`, `replace_order_by_id`, `cancel_order_by_id`, `cancel_all_orders`

**Positions**: `get_all_positions`, `get_open_position`, `close_position`, `close_all_positions`, `exercise_options_position`, `do_not_exercise_options_position`

**Watchlists**: `create_watchlist`, `get_watchlists`, `get_watchlist_by_id`, `update_watchlist_by_id`, `delete_watchlist_by_id`, `add_asset_to_watchlist_by_id`, `remove_asset_from_watchlist_by_id`

**Assets & Market Info**: `get_all_assets`, `get_asset`, `get_option_contracts`, `get_option_contract`, `get_calendar`, `get_clock`, `get_corporate_action_announcements`, `get_corporate_action_announcement`

**Stock Data**: `get_stock_bars`, `get_stock_quotes`, `get_stock_trades`, `get_stock_latest_bar`, `get_stock_latest_quote`, `get_stock_latest_trade`, `get_stock_snapshot`, `get_most_active_stocks`, `get_market_movers`

**Crypto Data**: `get_crypto_bars`, `get_crypto_quotes`, `get_crypto_trades`, `get_crypto_latest_bar`, `get_crypto_latest_quote`, `get_crypto_latest_trade`, `get_crypto_snapshot`, `get_crypto_latest_orderbook`

**Options Data**: `get_option_bars`, `get_option_trades`, `get_option_latest_trade`, `get_option_latest_quote`, `get_option_snapshot`, `get_option_chain`, `get_option_exchange_codes`

**Fixed Income**: `get_fixed_income_latest_quotes`

**Index Data**: `get_index_latest_values`, `get_index_values`

**Corporate Actions & News**: `get_corporate_actions`, `get_news`

### Example prompts
- *"What's my current account balance and buying power?"*
- *"Buy 10 shares of AAPL at market price."*
- *"Place a limit order to sell 50 shares of TSLA at $350."*
- *"Set a trailing stop on my NVDA position at 5%."*
- *"Show me AAPL's daily price bars for the last week."*
- *"What are the Greeks for this TSLA 300 put?"*
- *"Create a watchlist called Tech Earnings with AAPL, MSFT, NVDA, and GOOGL."*

### Important considerations
- Never paste API keys into chat — set them only in the MCP client's `env` block or an OS secret store.
- Orders execute directly against live Trading API endpoints — review AI-suggested orders before confirming.
- Defaults to paper trading; set `ALPACA_PAPER_TRADE=false` with live keys for real capital.
- Subject to Alpaca's per-account rate limits.
- Some real-time data may require an **Algo Trader Plus** subscription.
- V2 is **not** a drop-in replacement for V1 (tool names/params changed); pin `alpaca-mcp-server==1.x.x` if you need V1.

> *Disclosure: Insights generated by the MCP server and connected AI agents are educational/informational only — not investment advice.*

---

## 8. Quick Reference — What to Use When

| Goal | Use |
|---|---|
| Build a custom trading bot in Python/JS/Go/C#/Java | Official SDK (`alpaca-py`, etc.) |
| Give an LLM/agent live "hands" on your account (Claude, Cursor, etc.) | **Trading MCP Server** |
| Script, cron job, CI pipeline, or lightweight agent action | **Trading CLI** |
| Raw HTTP integration / custom language | REST endpoints + OpenAPI specs directly |
| Test strategies without risking capital | Paper trading (`paper-api.alpaca.markets`, `ALPACA_PAPER_TRADE=true`) |

### Useful links
- Docs home: https://docs.alpaca.markets
- API Reference: https://docs.alpaca.markets/us/reference
- Trading MCP Server repo: https://github.com/alpacahq/alpaca-mcp-server
- Trading CLI repo: https://github.com/alpacahq/cli
- Paper trading dashboard: https://app.alpaca.markets/paper/dashboard/overview
- Alpaca GitHub org: https://github.com/alpacahq/
- Status page: https://status.alpaca.markets/
- Slack community: https://alpaca.markets/slack

---

*Sources: docs.alpaca.markets/us/docs/{getting-started, authentication, sdks-and-tools, getting-started-with-trading-api, getting-started-with-alpaca-market-data, alpacas-cli, alpaca-mcp-server} — retrieved for the lablab.ai AI Trading Agents Hackathon, August 2026.*
