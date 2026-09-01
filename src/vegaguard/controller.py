"""Backend-managed, safety-preserving dashboard controller."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from httpx import HTTPError
from websockets.exceptions import WebSocketException

from .config import Settings, get_settings
from .demo import build_offline_demo
from .execution import PaperExecutionAgent
from .journal import DecisionJournal
from .mcp_client import AlpacaMCPClient
from .models import JournalEntry
from .monitoring import OrderLifecycle, PaperTradeUpdateMonitor
from .scheduler import MarketHoursScheduler
from .service import AutonomousCycle


class DashboardAgentController:
    """Own one shadow scheduler and fixture replay task for a FastAPI process.

    The worker can produce scan, candidate, risk, and preview events, but never
    invokes the MCP order tool directly. Even when a server is configured with
    execution flags, ``PaperExecutionAgent.submit`` leaves a plan awaiting an
    exact unexpired-plan approval.
    """

    def __init__(
        self,
        *,
        journal: DecisionJournal | None = None,
        settings_factory: Callable[[], Settings] = get_settings,
        cycle_factory: Callable[[Settings, PaperExecutionAgent], AutonomousCycle] = AutonomousCycle,
        scheduler_factory: Callable[..., MarketHoursScheduler] = MarketHoursScheduler,
        demo_builder: Callable[..., dict[str, Any]] = build_offline_demo,
        monitor_factory: Callable[[Settings, DecisionJournal], PaperTradeUpdateMonitor]
        | None = None,
        enable_trade_update_monitor: bool = True,
        worker_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.journal = journal or DecisionJournal()
        self.settings_factory = settings_factory
        self.cycle_factory = cycle_factory
        self.scheduler_factory = scheduler_factory
        self.demo_builder = demo_builder
        self.monitor_factory = monitor_factory or PaperTradeUpdateMonitor
        self.enable_trade_update_monitor = enable_trade_update_monitor
        self.worker_sleep = worker_sleep
        self._scheduler_task: asyncio.Task[None] | None = None
        self._simulation_task: asyncio.Task[None] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._guardian_task: asyncio.Task[None] | None = None
        self._interval_seconds: int | None = None
        self._simulation: dict[str, Any] = {"status": "idle", "last_error": None}
        self._monitor: dict[str, Any] = {
            "status": "stopped",
            "last_error": None,
            "last_event_at": None,
        }
        self._session_id = f"vg-session-{uuid4().hex[:20]}"
        self._process_id = os.getpid()
        self._paper_armed = False
        self._armed_at: datetime | None = None
        self._emergency_stop_active = False

    def _cycle(self, settings: Settings) -> AutonomousCycle:
        return self.cycle_factory(
            settings,
            PaperExecutionAgent(settings, self.journal, AlpacaMCPClient(settings)),
        )

    def status(self) -> dict[str, Any]:
        scheduler = self.journal.scheduler_status()
        guardian = self.journal.guardian_status()
        durable_monitor = self.journal.monitor_status()
        settings = self.settings_factory()
        configuration_ready = (
            settings.alpaca_paper_trade and settings.allow_order_execution and not settings.dry_run
        )
        monitor_running = self._is_running(self._monitor_task)
        monitor = {
            **durable_monitor,
            "status": self._monitor["status"]
            if monitor_running or self._monitor["status"] in {"disabled", "not_configured"}
            else durable_monitor["status"]
            if durable_monitor["status"] != "never_started"
            else "stopped",
            "controller_status": self._monitor["status"],
            "process_running": monitor_running,
            "last_event_at": self._monitor.get("last_event_at"),
        }
        scheduler_running = self._is_running(self._scheduler_task)
        heartbeat_active = scheduler["status"] in {"running", "waiting"}
        if scheduler_running:
            scheduler_source = "in_process_controller"
            scheduler_explanation = "scheduler task is owned by this dashboard process"
        elif heartbeat_active and scheduler.get("worker_kind") in {None, "external_cli"}:
            scheduler_source = "external_cli"
            scheduler_explanation = (
                "durable heartbeat is active, but the scheduler runs in a separate CLI process"
            )
        elif heartbeat_active:
            scheduler_source = "external_process"
            scheduler_explanation = (
                "durable heartbeat is active, but it is owned by another backend process"
            )
        else:
            scheduler_source = "durable_history"
            scheduler_explanation = "no scheduler task is running in this dashboard process"
        scheduler = {
            **scheduler,
            "source": scheduler_source,
            "process_running": scheduler_running,
            "ownership_explanation": scheduler_explanation,
        }
        return {
            "scheduler": scheduler,
            "position_guardian": guardian,
            "controller_running": scheduler_running,
            "scheduler_process_running": scheduler_running,
            "position_guardian_process_running": self._is_running(self._guardian_task),
            "lifecycle_running": self._is_running(self._guardian_task)
            or self._is_running(self._monitor_task),
            "session_id": self._session_id,
            "process_id": self._process_id,
            "simulation": self._simulation,
            "trade_update_monitor": monitor,
            "paper_execution": {
                "locked": not configuration_ready
                or not self._paper_armed
                or self._emergency_stop_active,
                "configuration_ready": configuration_ready,
                "armed": self._paper_armed,
                "armed_at": self._armed_at.isoformat() if self._armed_at else None,
                "emergency_stop_active": self._emergency_stop_active,
                "paper_account": settings.alpaca_paper_trade,
                "allow_order_execution": settings.allow_order_execution,
                "dry_run": settings.dry_run,
                "requirement": (
                    "session arm plus exact unexpired plan_id approval remain mandatory"
                ),
            },
        }

    async def start_shadow(self, *, interval_seconds: int = 900) -> dict[str, Any]:
        if interval_seconds < 60:
            raise ValueError("scheduler interval must be at least 60 seconds")
        if self._is_running(self._scheduler_task):
            return {"status": "already_running", **self.status()}
        settings = self.settings_factory()
        self._interval_seconds = interval_seconds
        scheduler = self.scheduler_factory(
            self._cycle(settings),
            self.journal,
            interval_seconds=interval_seconds,
            session_id=self._session_id,
            process_id=self._process_id,
            worker_kind="dashboard_controller",
        )
        started_at = datetime.now(UTC)
        self.journal.append(
            JournalEntry(
                timestamp=started_at,
                event="scheduler_heartbeat",
                payload={
                    "status": "running",
                    "cycle_number": None,
                    "interval_seconds": interval_seconds,
                    "last_cycle_status": None,
                    "last_error": None,
                    "next_run_at": (started_at + timedelta(seconds=interval_seconds)).isoformat(),
                    "session_id": self._session_id,
                    "process_id": self._process_id,
                    "worker_kind": "dashboard_controller",
                    "last_cycle_started_at": None,
                    "last_cycle_completed_at": None,
                    "last_successful_cycle_at": None,
                    "market_open": None,
                },
            )
        )
        self._scheduler_task = asyncio.create_task(self._run_scheduler(scheduler))
        await self.start_lifecycle_workers(settings=settings)
        return {"status": "started", **self.status()}

    async def start_lifecycle_workers(self, *, settings: Settings | None = None) -> None:
        """Resume read-only lifecycle discovery independently of entry scanning."""
        settings = settings or self.settings_factory()
        await self._start_trade_update_monitor(settings)
        if self.journal.open_entry_plans() and not self._is_running(self._guardian_task):
            self._guardian_task = asyncio.create_task(self._run_position_guardian(settings))

    async def _run_scheduler(self, scheduler: MarketHoursScheduler) -> None:
        try:
            await scheduler.run()
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError) as exc:  # Defensive worker boundary.
            self._record_heartbeat("error", last_error=f"{type(exc).__name__}: {exc}")
        finally:
            if self._scheduler_task is asyncio.current_task():
                self._scheduler_task = None

    async def stop_shadow(self) -> dict[str, Any]:
        task = self._scheduler_task
        if task is None or task.done():
            self._scheduler_task = None
            return {"status": "already_stopped", **self.status()}
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._scheduler_task = None
        self._record_heartbeat("stopped")
        await self.start_lifecycle_workers()
        return {"status": "stopped", **self.status()}

    async def arm_paper_execution(self, confirmation: str) -> dict[str, Any]:
        """Arm this backend session only after deliberate operator confirmation."""
        if confirmation != "ARM PAPER EXECUTION":
            return {
                "status": "blocked",
                "reasons": ["confirmation must equal ARM PAPER EXECUTION"],
            }
        settings = self.settings_factory()
        required = {
            "ALPACA_PAPER_TRADE=true": settings.alpaca_paper_trade,
            "ALLOW_ORDER_EXECUTION=true": settings.allow_order_execution,
            "DRY_RUN=false": not settings.dry_run,
        }
        missing = [name for name, satisfied in required.items() if not satisfied]
        if missing:
            return {"status": "blocked", "reasons": missing, **self.status()}
        now = datetime.now(UTC)
        if self._emergency_stop_active:
            self.journal.append(
                JournalEntry(
                    timestamp=now,
                    event="emergency_stop_cleared",
                    payload={"session_id": self._session_id, "process_id": self._process_id},
                )
            )
        self._emergency_stop_active = False
        self._paper_armed = True
        self._armed_at = now
        self.journal.append(
            JournalEntry(
                timestamp=now,
                event="paper_execution_armed",
                payload={"session_id": self._session_id, "process_id": self._process_id},
            )
        )
        return {"status": "armed", **self.status()}

    async def disarm_paper_execution(self, *, reason: str = "operator") -> dict[str, Any]:
        self._paper_armed = False
        self._armed_at = None
        self.journal.append(
            JournalEntry(
                event="paper_execution_disarmed",
                payload={
                    "session_id": self._session_id,
                    "process_id": self._process_id,
                    "reason": reason,
                },
            )
        )
        return {"status": "disarmed", **self.status()}

    async def emergency_stop(self) -> dict[str, Any]:
        """Latch entry execution off and halt backend automation without external calls."""
        self._emergency_stop_active = True
        self._paper_armed = False
        self._armed_at = None
        self.journal.append(
            JournalEntry(
                event="emergency_stop_activated",
                payload={
                    "session_id": self._session_id,
                    "process_id": self._process_id,
                    "effect": "new entries disarmed; backend workers stopped",
                },
            )
        )
        await self.stop_shadow()
        await self._stop_position_guardian()
        await self._stop_trade_update_monitor()
        await self._stop_simulation()
        return {"status": "emergency_stopped", **self.status()}

    async def start_simulation(
        self,
        *,
        fixture: str | Path = "tests/fixtures/strategy_replay_sanitized.json",
        output_dir: str | Path = "results/dashboard_simulation",
    ) -> dict[str, Any]:
        if self._is_running(self._simulation_task):
            return {"status": "already_running", "simulation": self._simulation}
        self._simulation = {"status": "running", "last_error": None, "output_dir": str(output_dir)}
        self.journal.append(
            JournalEntry(event="simulation_replay_started", payload={"fixture": str(fixture)})
        )
        self._simulation_task = asyncio.create_task(
            self._run_simulation(Path(fixture), Path(output_dir))
        )
        return {"status": "started", "simulation": self._simulation}

    async def _run_simulation(self, fixture: Path, output_dir: Path) -> None:
        try:
            report = await asyncio.to_thread(
                self.demo_builder, fixture=fixture, output_dir=output_dir
            )
            self._simulation = {
                "status": "completed",
                "last_error": None,
                "output_dir": str(output_dir),
                "mode": report.get("mode"),
                "paper_trade_counters": report.get("simulated_lifecycle", {}).get(
                    "paper_trade_counters", {}
                ),
            }
            self.journal.append(
                JournalEntry(event="simulation_replay_completed", payload=self._simulation)
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._simulation = {"status": "error", "last_error": f"{type(exc).__name__}: {exc}"}
            self.journal.append(
                JournalEntry(event="simulation_replay_error", payload=self._simulation)
            )
        finally:
            self._simulation_task = None

    async def submit_approved_plan(self, plan_id: str) -> dict[str, Any]:
        """Reach MCP only through the existing exact-plan gate sequence."""
        settings = self.settings_factory()
        required = {
            "ALPACA_PAPER_TRADE=true": settings.alpaca_paper_trade,
            "ALLOW_ORDER_EXECUTION=true": settings.allow_order_execution,
            "DRY_RUN=false": not settings.dry_run,
        }
        missing = [name for name, satisfied in required.items() if not satisfied]
        if self._emergency_stop_active:
            missing.append("emergency stop must be deliberately cleared by re-arming")
        if not self._paper_armed:
            missing.append("paper execution session must be armed")
        if missing:
            return {"status": "blocked", "reasons": missing}
        try:
            return await self._cycle(settings).submit_approved_plan(plan_id)
        finally:
            # One deliberate arm authorizes at most one exact-plan attempt.
            await self.disarm_paper_execution(reason="exact_plan_attempt_completed")

    async def aclose(self) -> None:
        await self.stop_shadow()
        await self._stop_position_guardian()
        await self._stop_trade_update_monitor()
        await self._stop_simulation()
        self._paper_armed = False
        self._armed_at = None

    async def _start_trade_update_monitor(self, settings: Settings) -> None:
        if not self.enable_trade_update_monitor:
            self._monitor = {
                "status": "disabled",
                "last_error": None,
                "last_event_at": None,
            }
            return
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            self._monitor = {
                "status": "not_configured",
                "last_error": "paper credentials are not configured",
                "last_event_at": None,
            }
            return
        if self._is_running(self._monitor_task):
            return
        self._monitor = {"status": "running", "last_error": None, "last_event_at": None}
        self._monitor_task = asyncio.create_task(self._run_trade_update_monitor(settings))

    async def _run_trade_update_monitor(self, settings: Settings) -> None:
        attempts = 0
        last_successful_update_at: str | None = None
        next_event: asyncio.Task[Any] | None = None
        try:
            while True:
                attempts += 1
                try:
                    await self._reconcile_orders_read_only(settings)
                    self._record_monitor_heartbeat(
                        status="reconciling",
                        attempt=attempts,
                        last_successful_update_at=last_successful_update_at,
                    )
                    monitor = self.monitor_factory(settings, self.journal)
                    iterator = monitor.events().__aiter__()
                    next_event = asyncio.create_task(anext(iterator))
                    self._record_monitor_heartbeat(
                        status="connected",
                        attempt=attempts,
                        last_successful_update_at=last_successful_update_at,
                    )
                    while True:
                        done, _ = await asyncio.wait({next_event}, timeout=30)
                        if not done:
                            self._record_monitor_heartbeat(
                                status="connected_idle",
                                attempt=attempts,
                                last_successful_update_at=last_successful_update_at,
                            )
                            continue
                        try:
                            _event = next_event.result()
                        except StopAsyncIteration as exc:
                            raise RuntimeError("paper trade-update stream ended") from exc
                        last_successful_update_at = datetime.now(UTC).isoformat()
                        self._monitor = {
                            "status": "connected",
                            "last_error": None,
                            "last_event_at": last_successful_update_at,
                        }
                        self._record_monitor_heartbeat(
                            status="connected",
                            attempt=attempts,
                            last_successful_update_at=last_successful_update_at,
                        )
                        next_event = asyncio.create_task(anext(iterator))
                except (
                    OSError,
                    HTTPError,
                    RuntimeError,
                    TimeoutError,
                    WebSocketException,
                ) as exc:
                    retry_seconds = min(5 * (2 ** (attempts - 1)), 60)
                    next_retry_at = datetime.now(UTC) + timedelta(seconds=retry_seconds)
                    self._monitor = {
                        "status": "reconnecting",
                        "last_error": f"{type(exc).__name__}: {exc}",
                        "last_event_at": self._monitor.get("last_event_at"),
                    }
                    self.journal.append(
                        JournalEntry(event="trade_update_monitor_error", payload=self._monitor)
                    )
                    self._record_monitor_heartbeat(
                        status="reconnecting",
                        attempt=attempts,
                        last_successful_update_at=last_successful_update_at,
                        error=exc,
                        retry_seconds=retry_seconds,
                        next_retry_at=next_retry_at,
                    )
                    await self.worker_sleep(retry_seconds)
        finally:
            if next_event is not None and not next_event.done():
                next_event.cancel()
                try:
                    await next_event
                except (asyncio.CancelledError, StopAsyncIteration):
                    pass
            if self._monitor_task is asyncio.current_task():
                self._monitor_task = None

    async def _reconcile_orders_read_only(self, settings: Settings) -> None:
        cycle = self._cycle(settings)
        reconcile = getattr(cycle, "reconcile_orders", None)
        if callable(reconcile):
            await reconcile(OrderLifecycle(self.journal))

    def _record_monitor_heartbeat(
        self,
        *,
        status: str,
        attempt: int,
        last_successful_update_at: str | None,
        error: Exception | None = None,
        retry_seconds: float | None = None,
        next_retry_at: datetime | None = None,
    ) -> None:
        self.journal.append(
            JournalEntry(
                event="trade_update_monitor_heartbeat",
                payload={
                    "status": status,
                    "interval_seconds": 30,
                    "connection_attempt": attempt,
                    "last_successful_update_at": last_successful_update_at,
                    "last_error": f"{type(error).__name__}: {error}" if error else None,
                    "error_type": type(error).__name__ if error else None,
                    "retry_seconds": retry_seconds,
                    "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
                    "session_id": self._session_id,
                    "process_id": self._process_id,
                },
            )
        )

    async def _run_position_guardian(self, settings: Settings) -> None:
        cycle = self._cycle(settings)
        try:
            while True:
                if self._is_running(self._scheduler_task):
                    self._record_guardian_heartbeat(
                        {"status": "delegated_to_scheduler", "managed": []}
                    )
                else:
                    try:
                        outcome = await cycle.manage_open_spreads()
                    except (HTTPError, OSError, RuntimeError, TimeoutError) as exc:
                        outcome = {
                            "status": "management_error",
                            "error_type": type(exc).__name__,
                            "reason": str(exc) or type(exc).__name__,
                            "managed": [],
                        }
                    self.journal.append(
                        JournalEntry(event="position_management_cycle", payload=outcome)
                    )
                    self._record_guardian_heartbeat(outcome)
                await self.worker_sleep(60)
        finally:
            if self._guardian_task is asyncio.current_task():
                self._guardian_task = None

    def _record_guardian_heartbeat(self, outcome: dict[str, Any]) -> None:
        now = datetime.now(UTC)
        outcome_status = str(outcome.get("status") or "unknown")
        is_error = outcome_status == "management_error"
        self.journal.append(
            JournalEntry(
                timestamp=now,
                event="position_guardian_heartbeat",
                payload={
                    "status": outcome_status
                    if outcome_status == "delegated_to_scheduler"
                    else "error"
                    if is_error
                    else "waiting_market"
                    if outcome_status == "market_closed"
                    else "running",
                    "interval_seconds": 60,
                    "last_successful_update_at": None if is_error else now.isoformat(),
                    "last_error": outcome.get("reason") if is_error else None,
                    "error_type": outcome.get("error_type") if is_error else None,
                    "managed_position_count": outcome.get(
                        "managed_position_count", len(outcome.get("managed") or [])
                    ),
                    "recovered_spread_count": outcome.get("recovered_spread_count"),
                    "matched_leg_count": outcome.get("matched_leg_count"),
                    "matched_legs": outcome.get("matched_legs") or [],
                    "unmatched_spread_count": outcome.get("unmatched_spread_count"),
                    "last_reconciliation_at": outcome.get("last_reconciliation_at"),
                    "reconciliation_status": outcome.get("reconciliation_status"),
                    "market_open": False
                    if outcome_status == "market_closed"
                    else None
                    if is_error or outcome_status == "delegated_to_scheduler"
                    else True,
                    "session_id": self._session_id,
                    "process_id": self._process_id,
                    "worker_kind": "dashboard_controller",
                },
            )
        )

    async def _stop_position_guardian(self) -> None:
        task = self._guardian_task
        if task is None:
            return
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._guardian_task = None
        self.journal.append(
            JournalEntry(
                event="position_guardian_heartbeat",
                payload={
                    "status": "stopped",
                    "interval_seconds": 60,
                    "session_id": self._session_id,
                    "process_id": self._process_id,
                },
            )
        )

    async def _stop_trade_update_monitor(self) -> None:
        task = self._monitor_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._monitor_task = None
        if self._monitor.get("status") not in {"disabled", "not_configured"}:
            self._monitor = {
                "status": "stopped",
                "last_error": self._monitor.get("last_error"),
                "last_event_at": self._monitor.get("last_event_at"),
            }
            self._record_monitor_heartbeat(
                status="stopped",
                attempt=0,
                last_successful_update_at=self._monitor.get("last_event_at"),
            )

    async def _stop_simulation(self) -> None:
        if self._simulation_task is None or self._simulation_task.done():
            self._simulation_task = None
            return
        self._simulation_task.cancel()
        try:
            await self._simulation_task
        except asyncio.CancelledError:
            pass
        self._simulation_task = None
        self._simulation = {"status": "stopped", "last_error": None}

    def _record_heartbeat(self, status: str, *, last_error: str | None = None) -> None:
        now = datetime.now(UTC)
        self.journal.append(
            JournalEntry(
                timestamp=now,
                event="scheduler_heartbeat",
                payload={
                    "status": status,
                    "cycle_number": None,
                    "interval_seconds": self._interval_seconds or 900,
                    "last_cycle_status": None,
                    "last_error": last_error,
                    "next_run_at": None,
                    "session_id": self._session_id,
                    "process_id": self._process_id,
                },
            )
        )

    @staticmethod
    def _is_running(task: asyncio.Task[None] | None) -> bool:
        return task is not None and not task.done()
