# VegaGuard

VegaGuard is an autonomous **paper-options** agent built for the Alpaca AI Trading Agents Hackathon. It does not ask an LLM to freely trade. Instead it makes the work auditable:

`opportunity scanner → LLM thesis → deterministic risk gate → Alpaca MCP option order → order monitor → journal`

## Why this meets the brief

- **Autonomous agents:** the scanner, thesis agent, risk critic and position monitor run as an event loop.
- **Alpaca Trading API:** the official Alpaca MCP server is the execution and account/data boundary over Alpaca's Trading API.
- **MCP:** `uvx alpaca-mcp-server` is launched as a stdio MCP server; available tool schemas are discovered dynamically at runtime.
- **Options:** only option contracts can form a `TradePlan`; the execution adapter calls `place_option_order`.
- **Paper only:** the MCP environment is hard-wired to `ALPACA_PAPER_TRADE=true`. This project refuses an execution attempt if that is not true.

## First-run setup

1. Create the **new hackathon-only Alpaca paper account** and generate its paper API keys.
2. Copy the environment file and fill only the paper credentials:

   ```bash
   cp .env.example .env
   ```

3. Create a virtual environment and install the project:

   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install -e '.[dev]'
   ```

4. Keep `ALLOW_ORDER_EXECUTION=false` initially. Check that MCP discovers the actual installed v2 tool schemas:

   ```bash
   vegaguard inspect-mcp
   ```

5. Run tests and the API:

   ```bash
   pytest -q
   uvicorn vegaguard.api:app --reload
   ```

6. Once paper credentials and the MCP schema are verified, set `ALLOW_ORDER_EXECUTION=true`. The risk gate still blocks non-paper, illiquid, near-expiry, over-sized, or duplicate trades.

## Current scope

The first slice implements the safety-critical domain model, deterministic risk gate, durable decision journal, OpenAI thesis-agent contract, and a real MCP stdio client that dynamically discovers and calls Alpaca v2 tools. The next slice wires live option-chain normalization and `trade_updates` into the API cycle.

## Important controls

- The LLM cannot choose an arbitrary size, ignore buying power, bypass a failed gate, or call destructive portfolio-wide tools.
- All executable plans use a unique `client_order_id` and get written to `data/journal.jsonl` before submission.
- The agent should use defined-risk debit spreads once live chain selection is wired; no naked option-selling strategy is in scope.
- Do not use live keys. The MCP server defaults to paper, but the app also validates the paper setting explicitly.

## Official references

- [Alpaca MCP Server](https://docs.alpaca.markets/us/docs/alpaca-mcp-server)
- [Options trading](https://docs.alpaca.markets/us/docs/options-trading)
- [Multi-leg options](https://docs.alpaca.markets/us/docs/options-level-3-trading)
- [Paper trading](https://docs.alpaca.markets/us/docs/paper-trading)

## Build documents

- [Master Alpaca hackathon reference](docs/ALPACA_HACKATHON_MASTER.md)
- [P&L trading strategy](docs/TRADING_STRATEGY.md)
- [Architecture and implementation plan](docs/ARCHITECTURE_AND_IMPLEMENTATION_PLAN.md)
- [Winning product specification](docs/VEGAGUARD_WINNING_SPEC.md)
