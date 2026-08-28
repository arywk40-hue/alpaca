# Hackathon submission package

## Listing

- **Project title:** VegaGuard — Auditable Autonomous Options Risk Committee
- **Short description:** A paper-only autonomous agent that finds ETF options opportunities, constructs defined-risk debit spreads, enforces deterministic risk, executes through Alpaca MCP only after exact-plan approval, and preserves a live audit trail.
- **Technology tags:** Python, FastAPI, Alpaca Trading API, Alpaca MCP, options, SSE, SQLite, Pydantic, OpenAI (optional)
- **Category tags:** AI trading agents, risk management, developer tools, paper trading
- **Submission account ID:** sourced from `ALPACA_ACCOUNT_ID`; leave blank in public Git and supply the dedicated paper-account ID only in the submission form.

## Long description

VegaGuard separates reasoning from authority. A deterministic scanner evaluates SPY, QQQ and IWM, validates fresh option quotes and constructs only one-buy/one-sell debit spreads. An optional language model explains an already bounded opportunity; it cannot override the scanner, select arbitrary contracts or bypass risk. Allocation and execution remain deterministic.

Alpaca paper REST provides account, clock, position and market evidence. Alpaca MCP is the sole entry/exit order boundary and only `place_option_order` is allowed for execution. Every entry is bound to a short-lived `plan_id`, an idempotent `client_order_id`, and its exact reviewed legs. The backend revalidates the market and fresh quote economics immediately before an explicitly armed submission.

The dashboard owns the scheduler and paper update monitor, streams the JSONL/SQLite timeline over SSE, and exposes start, stop, simulation, arm, disarm and emergency-stop controls. It clearly separates fixture simulation, hypothetical shadow outcomes, plans, acknowledged paper orders, fills and fill-derived realized P&L.

## Safety and P&L claims

- The application refuses non-paper configuration and hardcodes the Alpaca paper endpoint.
- Defaults are `ALLOW_ORDER_EXECUTION=false`, `DRY_RUN=true`, `EXPLORATION_MODE=false` and production threshold 70.
- Exploration is separately labelled, one contract, one open position, and retains every hard gate.
- Actual gross P&L is `(exit fill credit − entry fill debit) × 100 × quantity`.
- Provider fees are subtracted only when reported; otherwise net P&L remains unknown.
- Fill-to-limit slippage and observed quote-mark MAE/MFE are separate fields.
- Simulation and shadow results are never paper fills or realized P&L.

## Reproducible judge demo

```bash
uv sync --extra dev
ruff format --check .
ruff check .
pytest -q
vegaguard replay
PYTHONPATH=src uvicorn vegaguard.api:app --host 127.0.0.1 --port 8000
```

`vegaguard replay` is credential-free and deterministically shows `SIMULATION_REPLAY → scan → candidate → risk decision → simulated order → simulated fill → monitoring → simulated exit → HYPOTHETICAL P&L`. Its paper counters remain zero.

With dedicated paper credentials, run `vegaguard preflight` and a read-only cycle. A live dry-run may generate a reviewed plan without invoking MCP. Follow `docs/OPERATOR_RUNBOOK.md` for the external paper acceptance sequence.

## Judge evidence checklist

- [ ] Public README setup succeeds without secrets.
- [ ] Tests and deterministic replay pass offline.
- [ ] Dashboard labels simulation, hypothetical and paper evidence separately.
- [ ] Preflight confirms paper account, clock, option data and required MCP schemas.
- [ ] Scanner shows numeric score components or explicit abstention reasons.
- [ ] Plan shows exact legs, quotes, DTE, IV, debit, loss/profit, breakeven and risk math.
- [ ] Arm/disarm and emergency stop are visible; defaults remain locked.
- [ ] If externally accepted: provider order ID and acknowledgement are journaled.
- [ ] If filled: entry/exit provider fills and realized P&L are journaled.
- [ ] Any unverified item is described as readiness, not completed evidence.

## Slide outline

1. Problem: autonomous trading without an auditable authority boundary.
2. Solution: bounded options committee and exact-plan execution.
3. Architecture: controller, deterministic strategy/risk, Alpaca MCP, audit store.
4. Safety: paper-only, debit spreads, two locks plus arm, emergency stop.
5. Research: point-in-time data, shadow repricing, threshold 40/50/60/70 evidence.
6. Demo: deterministic replay, live dashboard, fresh dry-run plan.
7. Honest results: verified tests/replay versus pending external paper lifecycle.
8. Next proof: one reviewed paper fill and automatic close during market hours.

## Three-minute video storyboard

1. **0:00–0:20:** State the problem and show the paper-only defaults.
2. **0:20–0:50:** Run `vegaguard replay`; point to simulation labels and zero paper counters.
3. **0:50–1:25:** Start the dashboard worker; show heartbeat, scan components and rejection math.
4. **1:25–1:55:** Open one dry-run plan and explain its exact legs, quotes and maximum loss.
5. **1:55–2:20:** Show arm/disarm, emergency stop and exact-plan quote revalidation without submitting.
6. **2:20–2:45:** Show lifecycle and shadow ledgers; distinguish hypothetical from fill-derived P&L.
7. **2:45–3:00:** State precisely whether a complete Alpaca paper lifecycle has been externally verified.

## Honest limitations

No real-money path exists. Historical options evidence remains limited by the supplied Alpaca entitlement/cache. Small fixtures are deterministic accounting demonstrations, not performance claims. Until `vegaguard live lifecycle-evidence` contains provider-backed entry and exit fills, a complete paper lifecycle is ready but not proven.
