from fastapi import FastAPI

from .config import get_settings
from .execution import PaperExecutionAgent
from .journal import DecisionJournal
from .mcp_client import AlpacaMCPClient
from .monitoring import OrderLifecycle
from .service import AutonomousCycle

app = FastAPI(title="VegaGuard", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "paper_only": settings.alpaca_paper_trade,
        "execution_enabled": settings.allow_order_execution,
        "mcp_required": True,
    }


@app.get("/mcp/tools")
async def mcp_tools() -> dict:
    settings = get_settings()
    tools = await AlpacaMCPClient(settings).tool_schemas()
    return {"tools": tools}


@app.get("/journal")
async def journal(limit: int = 20) -> dict:
    return {"entries": DecisionJournal().latest(limit=min(max(limit, 1), 100))}


@app.post("/cycle/run")
async def run_cycle() -> dict:
    settings = get_settings()
    journal = DecisionJournal()
    executor = PaperExecutionAgent(settings, journal, AlpacaMCPClient(settings))
    return await AutonomousCycle(settings, executor).run_once()


@app.post("/cycle/read-only")
async def run_read_only_cycle() -> dict:
    settings = get_settings()
    journal = DecisionJournal()
    executor = PaperExecutionAgent(settings, journal, AlpacaMCPClient(settings))
    return await AutonomousCycle(settings, executor).run_read_only()


@app.post("/lifecycle/reconcile")
async def reconcile_lifecycle() -> dict:
    settings = get_settings()
    journal = DecisionJournal()
    executor = PaperExecutionAgent(settings, journal, AlpacaMCPClient(settings))
    return await AutonomousCycle(settings, executor).reconcile_orders(OrderLifecycle(journal))
