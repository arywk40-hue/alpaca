# Hackathon submission package

## Listing

- **Project title:** VegaGuard — Auditable Autonomous Options Risk Committee
- **Short description:** A paper-only autonomous agent that finds ETF options opportunities, constructs defined-risk debit spreads, enforces deterministic risk, executes through Alpaca MCP only after exact-plan approval, and preserves a live audit trail.
- **Technology tags:** Python, FastAPI, Alpaca Trading API, Alpaca MCP, options, SSE, SQLite, Pydantic, OpenAI (optional)
- **Category tags:** AI trading agents, risk management, developer tools, paper trading
- **Submission account ID:** sourced from `ALPACA_ACCOUNT_ID`; leave blank in public Git and supply the dedicated paper-account ID only in the submission form.

## Submission fields (copy/paste)

- **Project name:** VegaGuard — Auditable Autonomous Options Risk Committee
- **One-line pitch:** A paper-only options agent that turns fresh ETF signals into explainable, defined-risk plans without giving an LLM execution authority.
- **Demo URL:** Run locally with `vegaguard replay` and the FastAPI dashboard; no public deployment is required for the offline demo.
- **Repository:** This repository, with credentials supplied only through the local environment.
- **Cover image:** [`assets/vegaguard-cover-v1.png`](../assets/vegaguard-cover-v1.png)
- **Disclosure:** Replay and shadow numbers are hypothetical or simulated. One Alpaca paper entry fill is provider-backed; its P&L remains unrealized until a provider-backed exit fill is journaled.
- **Account ID:** enter the dedicated Alpaca paper-account ID in the private submission form only; never commit it or include API keys in the repository.

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
- [x] Provider order ID and acknowledgement are journaled for the IWM paper entry.
- [x] The IWM entry fill at a $2.62 debit is journaled and monitored.
- [ ] Exit provider fill and realized P&L are journaled.
- [ ] Any unverified item is described as readiness, not completed evidence.

## 10-slide outline and 6–7 minute video

Use [`HACKATHON_DECK_10_SLIDES.md`](HACKATHON_DECK_10_SLIDES.md) for the on-screen
copy and [`HACKATHON_NARRATION.md`](HACKATHON_NARRATION.md) for the complete script.
The ten beats are: problem; authority boundary; deterministic committee; evidence
ledger; independent safety gates; dashboard; bounded OpenAI explainer; offline
replay; honest research limits; and the next paper-lifecycle proof.

The replay can be shown in a shorter three-minute cut, but the supplied narration
is paced for approximately 6:40 and keeps every simulation and hypothetical result
clearly separate from paper fills.

## Honest limitations

No real-money path exists. Historical options evidence remains limited by the supplied Alpaca entitlement/cache. Small fixtures are deterministic accounting demonstrations, not performance claims. The first Alpaca paper entry is provider-backed, but the complete lifecycle remains open until `vegaguard live lifecycle-evidence` contains its provider-backed exit fill and realized P&L.
