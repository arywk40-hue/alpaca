import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from websockets.exceptions import WebSocketException

from .config import get_settings
from .data.alpaca import AlpacaHistoricalDataProvider
from .data.fetch import fetch_history
from .demo import build_offline_demo
from .execution import PaperExecutionAgent
from .journal import DecisionJournal
from .mcp_client import AlpacaMCPClient
from .models import JournalEntry
from .monitoring import OrderLifecycle, PaperTradeUpdateMonitor
from .preflight import PaperPreflight
from .scheduler import MarketHoursScheduler
from .service import AutonomousCycle
from .strategy.backtest import HistoricalBacktester, write_historical_report
from .strategy.replay import load_observations
from .strategy.research import (
    compare_replay_scorers,
    confidence_calibration_study,
    walk_forward_threshold_study,
)


async def _inspect_mcp() -> None:
    tools = await AlpacaMCPClient(get_settings()).tool_schemas()
    print(json.dumps(tools, indent=2))


async def _fetch_history(args: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        raise RuntimeError(
            "Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env; no request was made"
        )
    symbols = _symbols(args.symbols)
    async with AlpacaHistoricalDataProvider(
        settings.alpaca_api_key.get_secret_value(), settings.alpaca_secret_key.get_secret_value()
    ) as provider:
        counts = await fetch_history(
            provider,
            symbols=symbols,
            start=args.start,
            end=args.end,
            cache_root=args.data_dir,
            stock_feed=args.feed,
        )
    print(json.dumps(counts, indent=2))


async def _read_only_cycle(cycles: int = 1, interval_seconds: int = 900) -> None:
    if cycles < 1:
        raise ValueError("cycles must be at least one")
    if cycles > 1 and interval_seconds < 60:
        raise ValueError("interval must be at least 60 seconds")
    settings = get_settings()
    executor = PaperExecutionAgent(settings, DecisionJournal(), AlpacaMCPClient(settings))
    cycle = AutonomousCycle(settings, executor)
    results = []
    for number in range(cycles):
        results.append(await cycle.run_read_only())
        if number + 1 < cycles:
            await asyncio.sleep(interval_seconds)
    print(json.dumps(results[0] if cycles == 1 else {"cycles": results}, indent=2))


async def _monitor_trade_updates(
    *,
    retry_seconds: float = 5.0,
    max_connection_attempts: int | None = None,
    monitor_factory: Any = None,
    journal: DecisionJournal | None = None,
) -> None:
    settings = get_settings()
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env")
    if max_connection_attempts is not None and max_connection_attempts < 1:
        raise ValueError("max_connection_attempts must be at least one")
    production_monitor = monitor_factory is None
    monitor_factory = monitor_factory or PaperTradeUpdateMonitor
    journal = journal or DecisionJournal()
    cycle = None
    if production_monitor:
        executor = PaperExecutionAgent(settings, journal, AlpacaMCPClient(settings))
        cycle = AutonomousCycle(settings, executor)
    attempts = 0
    next_event: asyncio.Task[Any] | None = None
    while True:
        attempts += 1
        try:
            if cycle is not None:
                journal.append(
                    JournalEntry(
                        event="trade_update_monitor_heartbeat",
                        payload={
                            "status": "reconciling",
                            "interval_seconds": 30,
                            "connection_attempt": attempts,
                        },
                    )
                )
                await cycle.reconcile_orders(OrderLifecycle(journal))
            monitor = monitor_factory(settings, journal)
            journal.append(
                JournalEntry(
                    event="trade_update_monitor_heartbeat",
                    payload={
                        "status": "connected",
                        "interval_seconds": 30,
                        "connection_attempt": attempts,
                    },
                )
            )
            iterator = monitor.events().__aiter__()
            next_event = asyncio.create_task(anext(iterator))
            while True:
                done, _ = await asyncio.wait({next_event}, timeout=30)
                if not done:
                    journal.append(
                        JournalEntry(
                            event="trade_update_monitor_heartbeat",
                            payload={
                                "status": "connected_idle",
                                "interval_seconds": 30,
                                "connection_attempt": attempts,
                            },
                        )
                    )
                    continue
                try:
                    event = next_event.result()
                except StopAsyncIteration as exc:
                    raise RuntimeError("paper trade-update stream ended") from exc
                print(json.dumps(event, indent=2))
                journal.append(
                    JournalEntry(
                        event="trade_update_monitor_heartbeat",
                        payload={
                            "status": "connected",
                            "interval_seconds": 30,
                            "connection_attempt": attempts,
                            "last_successful_update_at": datetime.now(UTC).isoformat(),
                        },
                    )
                )
                next_event = asyncio.create_task(anext(iterator))
        except asyncio.CancelledError:
            if next_event is not None and not next_event.done():
                next_event.cancel()
                try:
                    await next_event
                except (asyncio.CancelledError, StopAsyncIteration):
                    pass
            raise
        except (OSError, RuntimeError, TimeoutError, WebSocketException) as exc:
            if next_event is not None and not next_event.done():
                next_event.cancel()
                try:
                    await next_event
                except (asyncio.CancelledError, StopAsyncIteration):
                    pass
            next_event = None
            bounded_retry = min(retry_seconds * (2 ** (attempts - 1)), 60.0)
            next_retry_at = datetime.now(UTC) + timedelta(seconds=bounded_retry)
            error_detail = f"{type(exc).__name__}: {exc}"
            journal.append(
                JournalEntry(
                    event="trade_update_monitor_error",
                    payload={
                        "status": "reconnecting",
                        "error_type": type(exc).__name__,
                        "last_error": error_detail,
                        "connection_attempt": attempts,
                        "retry_seconds": bounded_retry,
                        "next_retry_at": next_retry_at.isoformat(),
                    },
                )
            )
            journal.append(
                JournalEntry(
                    event="trade_update_monitor_heartbeat",
                    payload={
                        "status": "reconnecting",
                        "interval_seconds": 30,
                        "error_type": type(exc).__name__,
                        "last_error": error_detail,
                        "connection_attempt": attempts,
                        "retry_seconds": bounded_retry,
                        "next_retry_at": next_retry_at.isoformat(),
                    },
                )
            )
            if max_connection_attempts is not None and attempts >= max_connection_attempts:
                return
            await asyncio.sleep(bounded_retry)


async def _lifecycle_evidence() -> None:
    settings = get_settings()
    trades = DecisionJournal().complete_trade_evidence()
    print(
        json.dumps(
            {
                "mode": "read_only_lifecycle_evidence",
                "paper_only": settings.alpaca_paper_trade,
                "complete_trade_count": len(trades),
                "trades": trades,
            },
            indent=2,
        )
    )


async def _shadow_candidates(limit: int) -> None:
    settings = get_settings()
    print(
        json.dumps(
            {
                "mode": "read_only_shadow_candidates",
                "paper_only": settings.alpaca_paper_trade,
                "candidates": DecisionJournal().shadow_candidates(limit),
            },
            indent=2,
        )
    )


async def _shadow_session_report() -> None:
    settings = get_settings()
    print(
        json.dumps(
            {
                "paper_only": settings.alpaca_paper_trade,
                **DecisionJournal().shadow_session_report(),
            },
            indent=2,
        )
    )


async def _run_scheduler(interval_seconds: int, max_cycles: int | None) -> None:
    settings = get_settings()
    journal = DecisionJournal()
    executor = PaperExecutionAgent(settings, journal, AlpacaMCPClient(settings))
    scheduler = MarketHoursScheduler(
        AutonomousCycle(settings, executor), journal, interval_seconds=interval_seconds
    )
    print(json.dumps(await scheduler.run(max_cycles=max_cycles), indent=2))


async def _submit_approved(plan_id: str, *, session_armed: bool = False) -> None:
    settings = get_settings()
    if not settings.allow_order_execution or settings.dry_run:
        raise RuntimeError(
            "Submitting an approved plan requires ALLOW_ORDER_EXECUTION=true and DRY_RUN=false"
        )
    if not session_armed:
        raise RuntimeError(
            "Submitting an approved plan requires the explicit --arm-paper-execution session flag"
        )
    journal = DecisionJournal()
    cycle = AutonomousCycle(
        settings, PaperExecutionAgent(settings, journal, AlpacaMCPClient(settings))
    )
    print(json.dumps(await cycle.submit_approved_plan(plan_id), indent=2))


async def _preflight() -> None:
    report = await PaperPreflight(get_settings()).run()
    path = PaperPreflight.write_report(report)
    summary = {
        "status": report["status"],
        "checked_at": report["checked_at"],
        "paper_only": report["paper_only"],
        "rest": report["rest"],
        "market_data": report["market_data"],
        "mcp": {
            "available_tool_count": len(report["mcp"]["available_tools"]),
            "missing_required_tools": report["mcp"]["missing_required_tools"],
        },
        "report_path": str(path),
    }
    print(json.dumps(summary, indent=2))


def _symbols(value: str) -> list[str]:
    symbols = [symbol.strip().upper() for symbol in value.split(",") if symbol.strip()]
    if not symbols:
        raise ValueError("At least one symbol is required")
    return symbols


def main() -> None:
    parser = argparse.ArgumentParser(description="VegaGuard paper-options agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inspect-mcp")
    subparsers.add_parser(
        "preflight", help="Verify paper REST, option data, and MCP setup read-only"
    )
    demo_parser = subparsers.add_parser(
        "demo", help="Build a credential-free offline replay/research demonstration bundle"
    )
    demo_parser.add_argument("--fixture", default="tests/fixtures/strategy_replay_sanitized.json")
    demo_parser.add_argument("--output-dir", default="results/offline_demo")

    data_parser = subparsers.add_parser("data", help="Read-only historical data commands")
    data_subparsers = data_parser.add_subparsers(dest="data_command", required=True)
    fetch_parser = data_subparsers.add_parser("fetch-history")
    fetch_parser.add_argument(
        "--symbols", required=True, help="Comma-separated symbols, e.g. SPY,QQQ,IWM"
    )
    fetch_parser.add_argument("--start", required=True, help="Inclusive RFC-3339 date or timestamp")
    fetch_parser.add_argument("--end", required=True, help="Inclusive RFC-3339 date or timestamp")
    fetch_parser.add_argument("--data-dir", default="data")
    fetch_parser.add_argument("--feed", default="iex", choices=["iex", "sip"])

    live_parser = subparsers.add_parser("live", help="Paper-account commands")
    live_subparsers = live_parser.add_subparsers(dest="live_command", required=True)
    read_only_parser = live_subparsers.add_parser(
        "read-only-cycle", help="Query paper account and market data; never invokes execution"
    )
    read_only_parser.add_argument("--cycles", type=int, default=1)
    read_only_parser.add_argument("--interval-seconds", type=int, default=900)
    live_subparsers.add_parser(
        "monitor-trade-updates", help="Journal paper trade updates; never submits an order"
    )
    live_subparsers.add_parser(
        "lifecycle-evidence", help="Read journaled filled-and-exited paper trade evidence"
    )
    shadow_candidates_parser = live_subparsers.add_parser(
        "shadow-candidates", help="Read below-threshold and rejected candidate ledger"
    )
    shadow_candidates_parser.add_argument("--limit", type=int, default=20)
    live_subparsers.add_parser(
        "session-report", help="Read-only live shadow-evaluation evidence report"
    )
    scheduler_parser = live_subparsers.add_parser(
        "run-scheduler", help="Run the paper-only cycle every N seconds during market hours"
    )
    scheduler_parser.add_argument("--interval-seconds", type=int, default=900)
    scheduler_parser.add_argument("--max-cycles", type=int)
    submit_approved_parser = live_subparsers.add_parser(
        "submit-approved", help="Submit one exact, unexpired plan previously reviewed in dry run"
    )
    submit_approved_parser.add_argument("--plan-id", required=True)
    submit_approved_parser.add_argument(
        "--arm-paper-execution",
        action="store_true",
        help="Deliberately arm this one CLI session for the exact reviewed paper plan",
    )

    strategy_parser = subparsers.add_parser(
        "strategy", help="Deterministic local research commands"
    )
    strategy_subparsers = strategy_parser.add_subparsers(dest="strategy_command", required=True)
    backtest_parser = strategy_subparsers.add_parser("backtest")
    backtest_parser.add_argument("--data-dir", default="data/normalized")
    backtest_parser.add_argument("--symbols", required=True)
    backtest_parser.add_argument("--start", required=True)
    backtest_parser.add_argument("--end", required=True)
    backtest_parser.add_argument("--output", default="results/historical_strategy_backtest.json")
    backtest_parser.add_argument("--report", default="reports/historical_strategy_backtest.md")
    backtest_parser.add_argument("--initial-equity", type=float, default=100_000.0)
    backtest_parser.add_argument("--max-open-positions", type=int, default=3)
    backtest_parser.add_argument("--max-contracts-per-trade", type=int, default=1)
    backtest_parser.add_argument("--fee-per-contract-usd", type=float, default=0.0)
    backtest_parser.add_argument("--slippage-per-leg-usd", type=float, default=0.0)
    backtest_parser.add_argument("--quote-derived-risk-free-rate", type=float, default=0.04)
    backtest_parser.add_argument(
        "--exit-horizon-minutes",
        type=int,
        choices=[15, 30, 60],
        help="Optional fixed research exit horizon; never affects live execution",
    )
    walk_forward_parser = strategy_subparsers.add_parser(
        "walk-forward", help="Offline point-in-time threshold study; never contacts execution"
    )
    walk_forward_parser.add_argument("--data-dir", default="data/normalized")
    walk_forward_parser.add_argument("--symbols", required=True)
    walk_forward_parser.add_argument("--start", required=True)
    walk_forward_parser.add_argument("--end", required=True)
    walk_forward_parser.add_argument("--thresholds", default="40,50,60,70")
    walk_forward_parser.add_argument("--train-fraction", type=float, default=0.70)
    walk_forward_parser.add_argument("--minimum-in-sample-trades", type=int, default=30)
    walk_forward_parser.add_argument("--initial-equity", type=float, default=100_000.0)
    walk_forward_parser.add_argument("--max-open-positions", type=int, default=3)
    walk_forward_parser.add_argument("--max-contracts-per-trade", type=int, default=1)
    walk_forward_parser.add_argument("--fee-per-contract-usd", type=float, default=0.0)
    walk_forward_parser.add_argument("--slippage-per-leg-usd", type=float, default=0.0)
    walk_forward_parser.add_argument("--quote-derived-risk-free-rate", type=float, default=0.04)
    walk_forward_parser.add_argument(
        "--exit-horizon-minutes",
        type=int,
        choices=[15, 30, 60],
        help="Optional fixed research exit horizon; never affects live execution",
    )
    walk_forward_parser.add_argument(
        "--output", default="results/walk_forward_threshold_study.json"
    )
    calibration_parser = strategy_subparsers.add_parser(
        "calibrate-confidence",
        help="Offline empirical score/regime calibration; never changes live settings",
    )
    calibration_parser.add_argument("--data-dir", default="data/normalized")
    calibration_parser.add_argument("--symbols", required=True)
    calibration_parser.add_argument("--start", required=True)
    calibration_parser.add_argument("--end", required=True)
    calibration_parser.add_argument("--minimum-score", type=int, default=40)
    calibration_parser.add_argument("--minimum-observations-per-bucket", type=int, default=30)
    calibration_parser.add_argument("--initial-equity", type=float, default=100_000.0)
    calibration_parser.add_argument("--max-open-positions", type=int, default=3)
    calibration_parser.add_argument("--max-contracts-per-trade", type=int, default=1)
    calibration_parser.add_argument("--fee-per-contract-usd", type=float, default=0.0)
    calibration_parser.add_argument("--slippage-per-leg-usd", type=float, default=0.0)
    calibration_parser.add_argument("--quote-derived-risk-free-rate", type=float, default=0.04)
    calibration_parser.add_argument(
        "--exit-horizon-minutes",
        type=int,
        choices=[15, 30, 60],
        help="Optional fixed research exit horizon; never affects live execution",
    )
    calibration_parser.add_argument("--output", default="results/confidence_calibration_study.json")
    compare_parser = strategy_subparsers.add_parser(
        "compare-scorers", help="Offline A/B comparison; never calls live data or execution"
    )
    compare_parser.add_argument("--fixture", required=True, help="Sanitized replay input JSON")
    compare_parser.add_argument("--output", default="results/conflict_scorer_ab.json")
    replay_parser = subparsers.add_parser(
        "replay", help="Run the deterministic credential-free SIMULATION_REPLAY lifecycle"
    )
    replay_parser.add_argument("--fixture", default="tests/fixtures/strategy_replay_sanitized.json")
    replay_parser.add_argument("--output-dir", default="results/offline_demo")
    args = parser.parse_args()
    if args.command == "inspect-mcp":
        asyncio.run(_inspect_mcp())
    if args.command == "preflight":
        try:
            asyncio.run(_preflight())
        except RuntimeError as exc:
            parser.error(str(exc))
    if args.command == "demo":
        report = build_offline_demo(fixture=args.fixture, output_dir=args.output_dir)
        print(json.dumps(report, indent=2))
    if args.command == "data" and args.data_command == "fetch-history":
        try:
            asyncio.run(_fetch_history(args))
        except RuntimeError as exc:
            parser.error(str(exc))
    if args.command == "live" and args.live_command == "read-only-cycle":
        try:
            asyncio.run(_read_only_cycle(args.cycles, args.interval_seconds))
        except (RuntimeError, ValueError) as exc:
            parser.error(str(exc))
    if args.command == "live" and args.live_command == "monitor-trade-updates":
        try:
            asyncio.run(_monitor_trade_updates())
        except RuntimeError as exc:
            parser.error(str(exc))
    if args.command == "live" and args.live_command == "lifecycle-evidence":
        asyncio.run(_lifecycle_evidence())
    if args.command == "live" and args.live_command == "shadow-candidates":
        asyncio.run(_shadow_candidates(args.limit))
    if args.command == "live" and args.live_command == "session-report":
        asyncio.run(_shadow_session_report())
    if args.command == "live" and args.live_command == "run-scheduler":
        try:
            asyncio.run(_run_scheduler(args.interval_seconds, args.max_cycles))
        except (RuntimeError, ValueError) as exc:
            parser.error(str(exc))
    if args.command == "live" and args.live_command == "submit-approved":
        try:
            asyncio.run(_submit_approved(args.plan_id, session_armed=args.arm_paper_execution))
        except (RuntimeError, ValueError) as exc:
            parser.error(str(exc))
    if args.command == "strategy" and args.strategy_command == "backtest":
        start = datetime.fromisoformat(args.start)
        end = datetime.fromisoformat(args.end)
        result = HistoricalBacktester(
            args.data_dir,
            symbols=_symbols(args.symbols),
            start=start,
            end=end,
            initial_equity=args.initial_equity,
            max_open_positions=args.max_open_positions,
            max_contracts_per_trade=args.max_contracts_per_trade,
            fee_per_contract_usd=args.fee_per_contract_usd,
            slippage_per_leg_usd=args.slippage_per_leg_usd,
            quote_derived_risk_free_rate=args.quote_derived_risk_free_rate,
            exit_horizon_minutes=args.exit_horizon_minutes,
        ).run()
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result.as_dict(), indent=2) + "\n", encoding="utf-8")
        write_historical_report(
            result,
            path=args.report,
            symbols=_symbols(args.symbols),
            start=args.start,
            end=args.end,
        )
        print(json.dumps(result.as_dict(), indent=2))
    if args.command == "strategy" and args.strategy_command == "compare-scorers":
        report = compare_replay_scorers(load_observations(args.fixture))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    if args.command == "strategy" and args.strategy_command == "walk-forward":
        try:
            thresholds = [
                int(value.strip()) for value in args.thresholds.split(",") if value.strip()
            ]
            report = walk_forward_threshold_study(
                args.data_dir,
                symbols=_symbols(args.symbols),
                start=datetime.fromisoformat(args.start),
                end=datetime.fromisoformat(args.end),
                thresholds=thresholds,
                train_fraction=args.train_fraction,
                minimum_in_sample_trades=args.minimum_in_sample_trades,
                initial_equity=args.initial_equity,
                max_open_positions=args.max_open_positions,
                max_contracts_per_trade=args.max_contracts_per_trade,
                fee_per_contract_usd=args.fee_per_contract_usd,
                slippage_per_leg_usd=args.slippage_per_leg_usd,
                quote_derived_risk_free_rate=args.quote_derived_risk_free_rate,
                exit_horizon_minutes=args.exit_horizon_minutes,
            )
        except ValueError as exc:
            parser.error(str(exc))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    if args.command == "strategy" and args.strategy_command == "calibrate-confidence":
        try:
            backtest = HistoricalBacktester(
                args.data_dir,
                symbols=_symbols(args.symbols),
                start=datetime.fromisoformat(args.start),
                end=datetime.fromisoformat(args.end),
                initial_equity=args.initial_equity,
                max_open_positions=args.max_open_positions,
                max_contracts_per_trade=args.max_contracts_per_trade,
                score_threshold=args.minimum_score,
                fee_per_contract_usd=args.fee_per_contract_usd,
                slippage_per_leg_usd=args.slippage_per_leg_usd,
                quote_derived_risk_free_rate=args.quote_derived_risk_free_rate,
                exit_horizon_minutes=args.exit_horizon_minutes,
            ).run()
            report = confidence_calibration_study(
                backtest,
                minimum_observations_per_bucket=args.minimum_observations_per_bucket,
            )
        except ValueError as exc:
            parser.error(str(exc))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    if args.command == "replay":
        print(
            json.dumps(
                build_offline_demo(fixture=args.fixture, output_dir=args.output_dir), indent=2
            )
        )
