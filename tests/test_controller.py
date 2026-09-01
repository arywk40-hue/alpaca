import asyncio
import json
from datetime import UTC, datetime, timedelta
from logging import INFO

import pytest
from fastapi.testclient import TestClient
from test_execution import plan as trade_plan

from vegaguard.api import create_app
from vegaguard.config import Settings
from vegaguard.controller import DashboardAgentController
from vegaguard.journal import DecisionJournal
from vegaguard.models import JournalEntry

TEST_DASHBOARD_TOKEN = "dashboard-test-token"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_DASHBOARD_TOKEN}"}


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
        settings_factory=lambda: settings or Settings(dashboard_bearer_token=TEST_DASHBOARD_TOKEN),
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
    for _ in range(20):
        if controller.status()["trade_update_monitor"]["last_event_at"]:
            break
        await asyncio.sleep(0)
    assert controller.status()["trade_update_monitor"]["status"] in {"running", "connected"}
    assert controller.status()["trade_update_monitor"]["last_event_at"]

    await controller.stop_shadow()
    assert controller.status()["trade_update_monitor"]["status"] == "connected"
    await controller.aclose()
    assert controller.status()["trade_update_monitor"]["status"] == "stopped"


@pytest.mark.asyncio
async def test_dashboard_guardian_resumes_existing_fill_without_starting_scheduler(tmp_path):
    journal = DecisionJournal(tmp_path / "journal.jsonl")
    journal.record_entry_fill(trade_plan(), filled_price=1.3, source="test")
    sleep_started = asyncio.Event()

    class ExistingPositionCycle(ClosedCycle):
        async def manage_open_spreads(self):
            return {"status": "market_closed", "managed": []}

    async def blocked_sleep(_seconds):
        sleep_started.set()
        await asyncio.Event().wait()

    controller = DashboardAgentController(
        journal=journal,
        settings_factory=Settings,
        cycle_factory=lambda *_args: ExistingPositionCycle(),
        enable_trade_update_monitor=False,
        worker_sleep=blocked_sleep,
    )
    await controller.start_lifecycle_workers()
    await sleep_started.wait()

    status = controller.status()
    assert status["controller_running"] is False
    assert status["position_guardian_process_running"] is True
    assert status["position_guardian"]["status"] == "waiting_market"
    await controller.aclose()


@pytest.mark.asyncio
async def test_trade_monitor_reconnects_with_bounded_backoff_and_persists_health(tmp_path):
    settings = Settings(alpaca_api_key="paper-key", alpaca_secret_key="paper-secret")
    attempts = 0
    sleeps: list[float] = []
    second_connected = asyncio.Event()

    class ReconnectingMonitor:
        async def events(self):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("temporary disconnect detail")
            yield {"event": "new"}
            second_connected.set()
            await asyncio.Event().wait()

    async def retry_sleep(seconds):
        sleeps.append(seconds)

    controller = DashboardAgentController(
        journal=DecisionJournal(tmp_path / "journal.jsonl"),
        settings_factory=lambda: settings,
        cycle_factory=lambda *_args: ClosedCycle(),
        monitor_factory=lambda *_args: ReconnectingMonitor(),
        worker_sleep=retry_sleep,
    )
    await controller.start_lifecycle_workers()
    await second_connected.wait()
    await asyncio.sleep(0)

    status = controller.status()["trade_update_monitor"]
    assert attempts == 2
    assert sleeps == [5]
    assert status["status"] == "connected"
    assert status["last_successful_update_at"]
    error_events = [
        event
        for event in controller.journal.latest()
        if event["event"] == "trade_update_monitor_error"
    ]
    assert "temporary disconnect detail" in error_events[0]["payload"]["last_error"]
    await controller.aclose()


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
        social = client.get("/social")
        assert social.status_code == 200
        assert "paper session monitor" in social.text
        assert "operator-token" not in social.text
        state = client.get("/dashboard/state")
        assert state.status_code == 200
        assert state.json()["agent"]["paper_execution"]["locked"] is True
        started = client.post(
            "/agent/shadow/start", json={"interval_seconds": 60}, headers=AUTH_HEADERS
        )
        assert started.status_code == 200
        assert started.json()["status"] == "started"
        stopped = client.post("/agent/shadow/stop", headers=AUTH_HEADERS)
        assert stopped.status_code == 200
        assert stopped.json()["scheduler"]["status"] == "stopped"
        blocked = client.post(
            "/agent/paper/submit-approved",
            json={"plan_id": "vg-plan-locked"},
            headers=AUTH_HEADERS,
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["status"] == "blocked"
        arm = client.post(
            "/agent/paper/arm",
            json={"confirmation": "ARM PAPER EXECUTION"},
            headers=AUTH_HEADERS,
        )
        assert arm.status_code == 409
        assert client.post("/agent/paper/disarm", headers=AUTH_HEADERS).status_code == 200
        emergency = client.post("/agent/emergency-stop", headers=AUTH_HEADERS)
        assert emergency.status_code == 200
        assert emergency.json()["paper_execution"]["emergency_stop_active"] is True


def test_server_lifespan_stops_a_running_dashboard_worker(tmp_path):
    controller = _controller(tmp_path)
    with TestClient(create_app(controller=controller)) as client:
        assert (
            client.post(
                "/agent/shadow/start", json={"interval_seconds": 60}, headers=AUTH_HEADERS
            ).status_code
            == 200
        )
    assert controller.status()["controller_running"] is False
    assert controller.status()["scheduler"]["status"] == "stopped"


@pytest.mark.parametrize(
    ("path", "json"),
    [
        ("/agent/shadow/start", {"interval_seconds": 60}),
        ("/agent/shadow/stop", None),
        ("/agent/simulation/start", None),
        ("/agent/paper/arm", {"confirmation": "ARM PAPER EXECUTION"}),
        ("/agent/paper/disarm", None),
        ("/agent/paper/submit-approved", {"plan_id": "vg-plan-test"}),
        ("/agent/emergency-stop", None),
        ("/cycle/run", None),
        ("/lifecycle/manage", None),
    ],
)
def test_mutating_routes_reject_missing_and_incorrect_dashboard_tokens(tmp_path, path, json):
    controller = _controller(tmp_path)
    with TestClient(create_app(controller=controller)) as client:
        missing = client.post(path, json=json)
        incorrect = client.post(
            path,
            json=json,
            headers={"Authorization": "Bearer wrong-dashboard-token"},
        )

    assert missing.status_code == 401
    assert incorrect.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert missing.json()["detail"] == "dashboard bearer token required"
    assert "wrong-dashboard-token" not in missing.text
    assert "wrong-dashboard-token" not in incorrect.text


def test_mutating_route_accepts_the_configured_dashboard_token(tmp_path):
    controller = _controller(tmp_path)
    with TestClient(create_app(controller=controller)) as client:
        response = client.post("/agent/paper/disarm", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "disarmed"
    assert TEST_DASHBOARD_TOKEN not in response.text


def test_dashboard_token_never_leaks_to_html_responses_journal_or_logs(tmp_path, caplog):
    controller = _controller(tmp_path)
    with caplog.at_level(INFO), TestClient(create_app(controller=controller)) as client:
        response = client.post("/agent/paper/disarm", headers=AUTH_HEADERS)
        html = client.get("/").text

    assert response.status_code == 200
    assert TEST_DASHBOARD_TOKEN not in response.text
    assert TEST_DASHBOARD_TOKEN not in html
    assert TEST_DASHBOARD_TOKEN not in caplog.text
    assert TEST_DASHBOARD_TOKEN not in json.dumps(controller.journal.latest())


def test_mutating_route_stays_locked_when_server_token_is_unset(tmp_path):
    controller = _controller(tmp_path, settings=Settings())
    with TestClient(create_app(controller=controller)) as client:
        response = client.post("/agent/paper/disarm", headers=AUTH_HEADERS)

    assert response.status_code == 401
    assert response.json()["detail"] == "dashboard bearer token required"


def test_read_only_dashboard_routes_remain_public(tmp_path):
    controller = _controller(tmp_path)
    with TestClient(create_app(controller=controller)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/dashboard/state").status_code == 200
        assert client.get("/agent/status").status_code == 200
