import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from vegaguard.api import create_app
from vegaguard.config import Settings
from vegaguard.controller import DashboardAgentController
from vegaguard.journal import DecisionJournal
from vegaguard.models import JournalEntry


class BlockingScheduler:
    def __init__(self, *_args, **_kwargs):
        self.started = asyncio.Event()

    async def run(self):
        self.started.set()
        await asyncio.Event().wait()


class ClosedCycle:
    async def submit_approved_plan(self, plan_id: str):
        return {"status": "blocked", "reason": "market_closed", "plan_id": plan_id}


class BlockingTradeUpdateMonitor:
    async def events(self):
        yield {"event": "new"}
        await asyncio.Event().wait()


def _controller(tmp_path, *, settings: Settings | None = None, demo_builder=None):
    return DashboardAgentController(
        journal=DecisionJournal(tmp_path / "journal.jsonl"),
        settings_factory=lambda: settings or Settings(),
        cycle_factory=lambda *_args: ClosedCycle(),
        scheduler_factory=BlockingScheduler,
        demo_builder=demo_builder or (lambda **_kwargs: {"mode": "offline_reproducible_demo"}),
        enable_trade_update_monitor=False,
    )


@pytest.mark.asyncio
async def test_dashboard_controller_starts_stops_and_journals_heartbeat(tmp_path):
    controller = _controller(tmp_path)
    started = await controller.start_shadow(interval_seconds=60)
    assert started["status"] == "started"
    await asyncio.sleep(0)
    assert controller.status()["controller_running"] is True
    assert controller.status()["scheduler"]["status"] == "running"

    stopped = await controller.stop_shadow()
    assert stopped["status"] == "stopped"
    assert stopped["scheduler"]["status"] == "stopped"
    assert controller.status()["controller_running"] is False


@pytest.mark.asyncio
async def test_dashboard_controller_records_fixture_only_simulation(tmp_path):
    controller = _controller(
        tmp_path,
        demo_builder=lambda **_kwargs: {
            "mode": "offline_reproducible_demo",
            "simulated_lifecycle": {"paper_trade_counters": {"submitted": 0, "filled": 0}},
        },
    )
    assert (await controller.start_simulation())["status"] == "started"
    for _ in range(20):
        if controller.status()["simulation"]["status"] != "running":
            break
        await asyncio.sleep(0.01)
    status = controller.status()["simulation"]
    assert status["status"] == "completed"
    assert status["paper_trade_counters"] == {"submitted": 0, "filled": 0}
    assert controller.journal.latest()[0]["event"] == "simulation_replay_completed"


@pytest.mark.asyncio
async def test_dashboard_worker_owns_the_paper_trade_update_monitor(tmp_path):
    settings = Settings(alpaca_api_key="paper-key", alpaca_secret_key="paper-secret")
    controller = DashboardAgentController(
        journal=DecisionJournal(tmp_path / "journal.jsonl"),
        settings_factory=lambda: settings,
        cycle_factory=lambda *_args: ClosedCycle(),
        scheduler_factory=BlockingScheduler,
        monitor_factory=lambda *_args: BlockingTradeUpdateMonitor(),
    )
    await controller.start_shadow(interval_seconds=60)
    await asyncio.sleep(0)
    assert controller.status()["trade_update_monitor"]["status"] == "running"
    assert controller.status()["trade_update_monitor"]["last_event_at"]

    await controller.stop_shadow()
    assert controller.status()["trade_update_monitor"]["status"] == "stopped"


@pytest.mark.asyncio
async def test_dashboard_submission_is_locked_by_default_without_constructing_cycle(tmp_path):
    calls = 0

    def cycle_factory(*_args):
        nonlocal calls
        calls += 1
        return ClosedCycle()

    controller = DashboardAgentController(
        journal=DecisionJournal(tmp_path / "journal.jsonl"),
        settings_factory=Settings,
        cycle_factory=cycle_factory,
    )
    result = await controller.submit_approved_plan("vg-plan-locked")
    assert result == {
        "status": "blocked",
        "reasons": [
            "ALLOW_ORDER_EXECUTION=true",
            "DRY_RUN=false",
            "paper execution session must be armed",
        ],
    }
    assert calls == 0


@pytest.mark.asyncio
async def test_dashboard_submission_still_returns_market_closed_after_execution_flags_pass(
    tmp_path,
):
    controller = _controller(tmp_path, settings=Settings(allow_order_execution=True, dry_run=False))
    armed = await controller.arm_paper_execution("ARM PAPER EXECUTION")
    assert armed["status"] == "armed"
    result = await controller.submit_approved_plan("vg-plan-exact")
    assert result == {"status": "blocked", "reason": "market_closed", "plan_id": "vg-plan-exact"}
    assert controller.status()["paper_execution"]["armed"] is False


@pytest.mark.asyncio
async def test_dashboard_arm_requires_configuration_and_exact_confirmation(tmp_path):
    controller = _controller(tmp_path)
    assert (await controller.arm_paper_execution("yes"))["status"] == "blocked"
    blocked = await controller.arm_paper_execution("ARM PAPER EXECUTION")
    assert blocked["status"] == "blocked"
    assert blocked["paper_execution"]["configuration_ready"] is False

    ready = _controller(
        tmp_path / "ready", settings=Settings(allow_order_execution=True, dry_run=False)
    )
    armed = await ready.arm_paper_execution("ARM PAPER EXECUTION")
    assert armed["status"] == "armed"
    assert armed["paper_execution"]["locked"] is False
    assert armed["session_id"].startswith("vg-session-")
    assert isinstance(armed["process_id"], int)


@pytest.mark.asyncio
async def test_emergency_stop_disarms_and_stops_all_backend_automation(tmp_path):
    controller = _controller(tmp_path, settings=Settings(allow_order_execution=True, dry_run=False))
    await controller.start_shadow(interval_seconds=60)
    await controller.arm_paper_execution("ARM PAPER EXECUTION")

    stopped = await controller.emergency_stop()

    assert stopped["status"] == "emergency_stopped"
    assert stopped["controller_running"] is False
    assert stopped["paper_execution"]["armed"] is False
    assert stopped["paper_execution"]["emergency_stop_active"] is True
    blocked = await controller.submit_approved_plan("vg-plan-exact")
    assert blocked["status"] == "blocked"
    assert any("emergency stop" in reason for reason in blocked["reasons"])
    assert controller.journal.latest()[0]["event"] == "scheduler_heartbeat"


def test_dashboard_controller_exposes_stale_heartbeat(tmp_path):
    controller = _controller(tmp_path)
    timestamp = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)
    controller.journal.append(
        JournalEntry(
            timestamp=timestamp,
            event="scheduler_heartbeat",
            payload={"status": "waiting", "interval_seconds": 60},
        )
    )
    assert (
        controller.journal.scheduler_status(now=timestamp + timedelta(seconds=181))["status"]
        == "stale"
    )


def test_dashboard_routes_manage_the_backend_controller_lifecycle(tmp_path):
    controller = _controller(tmp_path)
    with TestClient(create_app(controller=controller)) as client:
        state = client.get("/dashboard/state")
        assert state.status_code == 200
        assert state.json()["agent"]["paper_execution"]["locked"] is True
        started = client.post("/agent/shadow/start", json={"interval_seconds": 60})
        assert started.status_code == 200
        assert started.json()["status"] == "started"
        stopped = client.post("/agent/shadow/stop")
        assert stopped.status_code == 200
        assert stopped.json()["scheduler"]["status"] == "stopped"
        blocked = client.post("/agent/paper/submit-approved", json={"plan_id": "vg-plan-locked"})
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["status"] == "blocked"
        arm = client.post("/agent/paper/arm", json={"confirmation": "ARM PAPER EXECUTION"})
        assert arm.status_code == 409
        assert client.post("/agent/paper/disarm").status_code == 200
        emergency = client.post("/agent/emergency-stop")
        assert emergency.status_code == 200
        assert emergency.json()["paper_execution"]["emergency_stop_active"] is True


def test_server_lifespan_stops_a_running_dashboard_worker(tmp_path):
    controller = _controller(tmp_path)
    with TestClient(create_app(controller=controller)) as client:
        assert client.post("/agent/shadow/start", json={"interval_seconds": 60}).status_code == 200
    assert controller.status()["controller_running"] is False
    assert controller.status()["scheduler"]["status"] == "stopped"
