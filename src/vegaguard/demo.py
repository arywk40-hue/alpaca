"""Build a credential-free VegaGuard demonstration bundle."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from .strategy.replay import load_observations, run_replay, write_report
from .strategy.research import compare_replay_scorers


def _simulated_lifecycle(fixture: str | Path, observations, decisions) -> dict:
    """Build a visibly synthetic lifecycle from fixture-only data.

    This deliberately does not instantiate a journal, Alpaca client, execution
    agent, or a paper-order counter. The fixture supplies all simulated option
    economics and the result is useful only as a deterministic code-path demo.
    """
    raw = json.loads(Path(fixture).read_text(encoding="utf-8"))
    decision_by_key = {
        (observation.timestamp.isoformat(), observation.symbol): decision
        for observation, decision in zip(observations, decisions, strict=True)
    }
    events: list[dict] = []
    simulated_plans = 0
    simulated_exits = 0
    for row in raw["observations"]:
        timestamp = row["timestamp"]
        symbol = row["symbol"]
        decision = decision_by_key[(timestamp, symbol)]
        event_prefix = {
            "mode": "SIMULATION_REPLAY",
            "source": "sanitized_fixture",
            "timestamp": timestamp,
            "symbol": symbol,
        }
        events.append(
            {
                **event_prefix,
                "stage": "scan",
                "score": decision.score,
                "regime": decision.regime.value,
                "reasons": list(decision.reasons),
            }
        )
        simulation = row.get("simulation")
        if decision.regime.value not in {"bullish", "bearish"}:
            events.append(
                {
                    **event_prefix,
                    "stage": "candidate",
                    "status": "rejected",
                    "reason": "simulated scan did not meet directional threshold",
                }
            )
            continue
        if not isinstance(simulation, dict):
            events.append(
                {
                    **event_prefix,
                    "stage": "candidate",
                    "status": "rejected",
                    "reason": "sanitized fixture has no simulated defined-risk spread",
                }
            )
            continue
        entry = simulation["entry_quotes"]
        exit_quotes = simulation["exit_quotes"]
        quantity = int(simulation["quantity"])
        entry_debit = round(float(entry["long_ask"]) - float(entry["short_bid"]), 4)
        exit_credit = round(float(exit_quotes["long_bid"]) - float(exit_quotes["short_ask"]), 4)
        if entry_debit != float(row["entry_debit"]) or exit_credit != float(row["exit_value"]):
            raise ValueError("simulated fixture economics must match replay entry and exit values")
        max_loss = round(entry_debit * 100 * quantity, 2)
        allowed_risk = float(simulation["maximum_risk_usd"])
        candidate = {
            "strategy": "defined_risk_debit_spread",
            "long_symbol": simulation["long_symbol"],
            "short_symbol": simulation["short_symbol"],
            "width": float(simulation["width"]),
            "quantity": quantity,
            "entry_debit": entry_debit,
            "max_loss_usd": max_loss,
            "quote_economics": {"entry": entry, "exit": exit_quotes},
        }
        events.append({**event_prefix, "stage": "candidate", "status": "constructed", **candidate})
        approved = max_loss <= allowed_risk
        events.append(
            {
                **event_prefix,
                "stage": "risk_decision",
                "status": "approved" if approved else "rejected",
                "maximum_risk_usd": allowed_risk,
                "required_max_loss_usd": max_loss,
                "comparison": f"{max_loss:.2f} <= {allowed_risk:.2f}",
            }
        )
        if not approved:
            continue
        simulated_plans += 1
        observed_at = observations[[item.symbol for item in observations].index(symbol)].timestamp
        events.extend(
            [
                {
                    **event_prefix,
                    "stage": "simulated_order",
                    "status": "simulated_not_submitted",
                    "paper_order_submitted": False,
                },
                {
                    **event_prefix,
                    "stage": "simulated_fill",
                    "status": "simulated",
                    "entry_debit": entry_debit,
                    "pnl_label": "HYPOTHETICAL",
                    "paper_order_submitted": False,
                },
                {
                    **event_prefix,
                    "stage": "simulated_monitoring",
                    "status": "pending_simulated_reprice",
                    "simulated_at": (observed_at + timedelta(minutes=15)).isoformat(),
                },
                {
                    **event_prefix,
                    "stage": "simulated_monitoring",
                    "status": "pending_simulated_reprice",
                    "simulated_at": (observed_at + timedelta(minutes=30)).isoformat(),
                },
            ]
        )
        costs = float(row.get("extra_cost_per_contract", 0.0)) * quantity
        gross = round((exit_credit - entry_debit) * 100 * quantity, 2)
        events.append(
            {
                **event_prefix,
                "stage": "simulated_exit",
                "status": "simulated",
                "simulated_at": (observed_at + timedelta(minutes=60)).isoformat(),
                "exit_credit": exit_credit,
                "gross_simulated_pnl": gross,
                "costs": costs,
                "net_simulated_pnl": round(gross - costs, 2),
                "pnl_label": "HYPOTHETICAL",
                "paper_order_submitted": False,
                "realized_paper_pnl": None,
            }
        )
        simulated_exits += 1
    return {
        "mode": "SIMULATION_REPLAY",
        "source": "sanitized_fixture",
        "events": events,
        "simulated_plan_count": simulated_plans,
        "simulated_exit_count": simulated_exits,
        "paper_trade_counters": {"submitted": 0, "acknowledged": 0, "filled": 0, "realized": 0},
        "limitations": [
            "All events, option legs, quotes, and P&L are fixture-defined simulation values.",
            "No Alpaca request, MCP call, journal mutation, or order submission occurred.",
        ],
    }


def build_offline_demo(*, fixture: str | Path, output_dir: str | Path) -> dict:
    """Write reproducible, explicitly non-live evidence from a sanitized fixture."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    observations = load_observations(fixture)
    replay = run_replay(observations)
    limitations = [
        "Sanitized deterministic fixture only; it is not historical or live performance evidence.",
        "No network, Alpaca account, MCP tool, or order-submission path is used.",
        "Production scoring remains fixed at 70; scorer comparisons are offline research only.",
    ]
    write_report(
        replay,
        destination / "strategy_replay.json",
        data_source="sanitized fixture",
        limitations=limitations,
    )
    comparison = compare_replay_scorers(observations)
    (destination / "scorer_comparison.json").write_text(
        json.dumps(comparison, indent=2) + "\n", encoding="utf-8"
    )
    lifecycle = _simulated_lifecycle(fixture, observations, replay.decisions)
    (destination / "simulated_lifecycle.json").write_text(
        json.dumps(lifecycle, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        "mode": "offline_reproducible_demo",
        "live_execution": "disabled_by_design",
        "fixture": str(fixture),
        "observation_count": len(observations),
        "replay_summary": replay.summary.as_dict(),
        "simulated_lifecycle": {
            "plan_count": lifecycle["simulated_plan_count"],
            "exit_count": lifecycle["simulated_exit_count"],
            "paper_trade_counters": lifecycle["paper_trade_counters"],
        },
        "artifacts": {
            "replay": "strategy_replay.json",
            "research": "scorer_comparison.json",
            "simulated_lifecycle": "simulated_lifecycle.json",
            "guide": "README.md",
        },
        "limitations": limitations,
    }
    (destination / "demo_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    (destination / "README.md").write_text(
        "# VegaGuard offline demo\n\n"
        "This bundle is credential-free and does not contact Alpaca or submit orders.\n\n"
        "- `strategy_replay.json` shows deterministic fixture accounting.\n"
        "- `scorer_comparison.json` compares offline scorers and thresholds.\n"
        "- `simulated_lifecycle.json` shows the fixture-only scan → candidate → risk → "
        "simulated entry → monitoring → simulated exit path.\n"
        "- `demo_summary.json` summarizes generated artifacts and limitations.\n\n"
        "It is not a claim of historical or paper-trading performance. See `docs/ARCHITECTURE.md` "
        "and `docs/HISTORICAL_DATA_LIMITATIONS.md` in the repository for the evidence boundary.\n",
        encoding="utf-8",
    )
    return summary
