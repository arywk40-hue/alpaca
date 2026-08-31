import json

import pytest

from vegaguard.config import Settings
from vegaguard.preflight import PaperPreflight


class _Alpaca:
    async def account(self):
        return {"id": "paper-account", "status": "ACTIVE"}

    async def clock(self):
        return {"is_open": True}

    async def option_snapshots(self, _underlying):
        return {"SPY260918C00650000": {}}


class _MCP:
    async def tool_schemas(self):
        return [{"name": name} for name in PaperPreflight.required_mcp_tools]


@pytest.mark.asyncio
async def test_preflight_is_read_only_and_saves_no_secrets(tmp_path):
    report = await PaperPreflight(Settings(_env_file=None), alpaca=_Alpaca(), mcp=_MCP()).run()
    assert report["status"] == "ready"
    assert report["paper_only"] is True
    assert report["market_data"]["option_snapshot_count"] == 1
    assert "configured_account_id" not in report["rest"]
    assert "paper-account" not in json.dumps(report)
    path = PaperPreflight.write_report(report, tmp_path / "preflight.json")
    assert json.loads(path.read_text()) == report


@pytest.mark.asyncio
async def test_preflight_reports_missing_mcp_capability_without_executing():
    class IncompleteMCP:
        async def tool_schemas(self):
            return [{"name": "get_clock"}]

    report = await PaperPreflight(
        Settings(_env_file=None), alpaca=_Alpaca(), mcp=IncompleteMCP()
    ).run()
    assert report["status"] == "incomplete"
    assert "place_option_order" in report["mcp"]["missing_required_tools"]


@pytest.mark.asyncio
async def test_preflight_validates_optional_submission_account_id():
    matching = await PaperPreflight(
        Settings(_env_file=None, alpaca_account_id="paper-account"),
        alpaca=_Alpaca(),
        mcp=_MCP(),
    ).run()
    assert matching["status"] == "ready"
    assert matching["rest"]["account_id_matches_configuration"] is True

    mismatched = await PaperPreflight(
        Settings(_env_file=None, alpaca_account_id="different-paper-account"),
        alpaca=_Alpaca(),
        mcp=_MCP(),
    ).run()
    assert mismatched["status"] == "incomplete"
    assert mismatched["rest"]["account_id_matches_configuration"] is False
