import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from .config import get_settings
from .data.alpaca import AlpacaHistoricalDataProvider
from .data.fetch import fetch_history
from .execution import PaperExecutionAgent
from .journal import DecisionJournal
from .mcp_client import AlpacaMCPClient
from .monitoring import PaperTradeUpdateMonitor
from .preflight import PaperPreflight
from .scheduler import MarketHoursScheduler
from .service import AutonomousCycle
from .strategy.backtest import HistoricalBacktester, write_historical_report
from .strategy.replay import load_observations, run_replay, write_report
from .strategy.research import compare_replay_scorers


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


async def _monitor_trade_updates() -> None:
    settings = get_settings()
    monitor = PaperTradeUpdateMonitor(settings, DecisionJournal())
    async for event in monitor.events():
        print(json.dumps(event, indent=2))


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


async def _run_scheduler(interval_seconds: int, max_cycles: int | None) -> None:
    settings = get_settings()
    journal = DecisionJournal()
    executor = PaperExecutionAgent(settings, journal, AlpacaMCPClient(settings))
    scheduler = MarketHoursScheduler(
        AutonomousCycle(settings, executor), journal, interval_seconds=interval_seconds
    )
    print(json.dumps(await scheduler.run(max_cycles=max_cycles), indent=2))


async def _preflight() -> None:
    report = await PaperPreflight(get_settings()).run()
    path = PaperPreflight.write_report(report)
    print(json.dumps({**report, "report_path": str(path)}, indent=2))


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
    scheduler_parser = live_subparsers.add_parser(
        "run-scheduler", help="Run the paper-only cycle every N seconds during market hours"
    )
    scheduler_parser.add_argument("--interval-seconds", type=int, default=900)
    scheduler_parser.add_argument("--max-cycles", type=int)

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
    compare_parser = strategy_subparsers.add_parser(
        "compare-scorers", help="Offline A/B comparison; never calls live data or execution"
    )
    compare_parser.add_argument("--fixture", required=True, help="Sanitized replay input JSON")
    compare_parser.add_argument("--output", default="results/conflict_scorer_ab.json")
    replay_parser = subparsers.add_parser("replay")
    replay_parser.add_argument("--fixture", required=True, help="Sanitized replay input JSON")
    replay_parser.add_argument("--output", default="results/strategy_replay.json")
    replay_parser.add_argument("--data-source", default="sanitized fixture")
    args = parser.parse_args()
    if args.command == "inspect-mcp":
        asyncio.run(_inspect_mcp())
    if args.command == "preflight":
        try:
            asyncio.run(_preflight())
        except RuntimeError as exc:
            parser.error(str(exc))
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
    if args.command == "live" and args.live_command == "run-scheduler":
        try:
            asyncio.run(_run_scheduler(args.interval_seconds, args.max_cycles))
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
    if args.command == "replay":
        result = run_replay(load_observations(args.fixture))
        write_report(
            result,
            Path(args.output),
            data_source=args.data_source,
            limitations=[
                "This fixture validates deterministic accounting only.",
                "It is not a claim of historical or live strategy performance.",
            ],
        )
        print(json.dumps(result.summary.as_dict(), indent=2))
