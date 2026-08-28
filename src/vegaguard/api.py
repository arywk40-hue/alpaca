"""FastAPI surface for the backend-managed paper-only dashboard."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .controller import DashboardAgentController
from .dashboard import dashboard_html, dashboard_state
from .execution import PaperExecutionAgent
from .journal import DecisionJournal
from .mcp_client import AlpacaMCPClient
from .monitoring import OrderLifecycle
from .preflight import PaperPreflight
from .service import AutonomousCycle


class StartShadowRequest(BaseModel):
    interval_seconds: int = Field(default=900, ge=60)


class SubmitPlanRequest(BaseModel):
    plan_id: str = Field(min_length=1)


class ArmPaperRequest(BaseModel):
    confirmation: Literal["ARM PAPER EXECUTION"]


def create_app(*, controller: DashboardAgentController | None = None) -> FastAPI:
    """Create an app with one controller whose workers stop with the server."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.controller = controller or DashboardAgentController()
        try:
            yield
        finally:
            await application.state.controller.aclose()

    api = FastAPI(title="VegaGuard", version="0.1.0", lifespan=lifespan)

    def agent(request: Request) -> DashboardAgentController:
        return request.app.state.controller

    @api.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        return dashboard_html()

    @api.get("/health")
    async def health() -> dict:
        settings = get_settings()
        return {
            "status": "ok",
            "paper_only": settings.alpaca_paper_trade,
            "execution_enabled": settings.allow_order_execution,
            "mcp_required": True,
        }

    @api.get("/mcp/tools")
    async def mcp_tools() -> dict:
        settings = get_settings()
        tools = await AlpacaMCPClient(settings).tool_schemas()
        return {"tools": tools}

    @api.get("/preflight")
    async def preflight() -> dict:
        return await PaperPreflight(get_settings()).run()

    @api.get("/journal")
    async def journal(limit: int = 20) -> dict:
        return {"entries": DecisionJournal().latest(limit=min(max(limit, 1), 100))}

    @api.get("/dashboard/state")
    async def read_dashboard_state(request: Request, limit: int = 20) -> dict:
        controller_instance = agent(request)
        return {
            **dashboard_state(controller_instance.journal, limit=min(max(limit, 1), 100)),
            "agent": controller_instance.status(),
        }

    @api.post("/agent/shadow/start")
    async def start_shadow(request: Request, body: StartShadowRequest) -> dict:
        return await agent(request).start_shadow(interval_seconds=body.interval_seconds)

    @api.post("/agent/shadow/stop")
    async def stop_shadow(request: Request) -> dict:
        return await agent(request).stop_shadow()

    @api.post("/agent/simulation/start")
    async def start_simulation(request: Request) -> dict:
        return await agent(request).start_simulation()

    @api.get("/agent/status")
    async def agent_status(request: Request) -> dict:
        return agent(request).status()

    @api.post("/agent/paper/submit-approved")
    async def submit_approved(request: Request, body: SubmitPlanRequest) -> dict:
        result = await agent(request).submit_approved_plan(body.plan_id)
        if result.get("status") == "blocked":
            raise HTTPException(status_code=409, detail=result)
        return result

    @api.post("/agent/paper/arm")
    async def arm_paper(request: Request, body: ArmPaperRequest) -> dict:
        result = await agent(request).arm_paper_execution(body.confirmation)
        if result.get("status") == "blocked":
            raise HTTPException(status_code=409, detail=result)
        return result

    @api.post("/agent/paper/disarm")
    async def disarm_paper(request: Request) -> dict:
        return await agent(request).disarm_paper_execution()

    @api.post("/agent/emergency-stop")
    async def emergency_stop(request: Request) -> dict:
        return await agent(request).emergency_stop()

    @api.get("/events")
    async def events(request: Request) -> StreamingResponse:
        journal = agent(request).journal

        async def stream() -> AsyncIterator[str]:
            last_payload: str | None = None
            while not await request.is_disconnected():
                latest = journal.latest(1)
                payload = json.dumps(
                    {
                        "event": latest[0] if latest else None,
                        "scheduler": journal.scheduler_status(),
                    },
                    separators=(",", ":"),
                )
                if payload != last_payload:
                    last_payload = payload
                    yield f"data: {payload}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    # Legacy diagnostic routes retain their previous behavior. The execution
    # agent now returns an approval-required preview instead of direct submit.
    @api.post("/cycle/run")
    async def run_cycle() -> dict:
        settings = get_settings()
        journal = DecisionJournal()
        executor = PaperExecutionAgent(settings, journal, AlpacaMCPClient(settings))
        return await AutonomousCycle(settings, executor).run_once()

    @api.post("/cycle/read-only")
    async def run_read_only_cycle() -> dict:
        settings = get_settings()
        journal = DecisionJournal()
        executor = PaperExecutionAgent(settings, journal, AlpacaMCPClient(settings))
        return await AutonomousCycle(settings, executor).run_read_only()

    @api.post("/lifecycle/reconcile")
    async def reconcile_lifecycle() -> dict:
        settings = get_settings()
        journal = DecisionJournal()
        executor = PaperExecutionAgent(settings, journal, AlpacaMCPClient(settings))
        return await AutonomousCycle(settings, executor).reconcile_orders(OrderLifecycle(journal))

    @api.post("/lifecycle/manage")
    async def manage_lifecycle() -> dict:
        settings = get_settings()
        journal = DecisionJournal()
        executor = PaperExecutionAgent(settings, journal, AlpacaMCPClient(settings))
        return await AutonomousCycle(settings, executor).manage_open_spreads()

    return api


app = create_app()
