import json
import sys

import pytest

from vegaguard import cli
from vegaguard.config import Settings


@pytest.mark.asyncio
async def test_multi_cycle_read_only_command_reuses_one_scanner_and_never_executes(
    monkeypatch, capsys
):
    instances = []

    class FakeCycle:
        def __init__(self, *_args):
            self.calls = 0
            instances.append(self)

        async def run_read_only(self):
            self.calls += 1
            return {"mode": "read_only", "observation": self.calls}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli, "PaperExecutionAgent", lambda *_args: object())
    monkeypatch.setattr(cli, "AlpacaMCPClient", lambda *_args: object())
    monkeypatch.setattr(cli, "AutonomousCycle", FakeCycle)
    monkeypatch.setattr(cli.asyncio, "sleep", no_sleep)
    await cli._read_only_cycle(cycles=2, interval_seconds=60)
    assert len(instances) == 1 and instances[0].calls == 2
    assert json.loads(capsys.readouterr().out) == {
        "cycles": [
            {"mode": "read_only", "observation": 1},
            {"mode": "read_only", "observation": 2},
        ]
    }


@pytest.mark.asyncio
async def test_multi_cycle_read_only_validates_the_interval_before_creating_clients():
    with pytest.raises(ValueError, match="at least 60"):
        await cli._read_only_cycle(cycles=2, interval_seconds=59)


@pytest.mark.asyncio
async def test_lifecycle_evidence_command_is_read_only(monkeypatch, capsys):
    class FakeJournal:
        def complete_trade_evidence(self):
            return [{"client_order_id": "vg-paper-1", "realized_pnl": 12.5}]

    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli, "DecisionJournal", FakeJournal)
    await cli._lifecycle_evidence()
    assert json.loads(capsys.readouterr().out) == {
        "mode": "read_only_lifecycle_evidence",
        "paper_only": True,
        "complete_trade_count": 1,
        "trades": [{"client_order_id": "vg-paper-1", "realized_pnl": 12.5}],
    }


@pytest.mark.asyncio
async def test_shadow_candidates_command_is_read_only(monkeypatch, capsys):
    class FakeJournal:
        def shadow_candidates(self, limit):
            assert limit == 3
            return [{"underlying": "IWM", "classification": "below_threshold"}]

    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli, "DecisionJournal", FakeJournal)
    await cli._shadow_candidates(3)
    assert json.loads(capsys.readouterr().out) == {
        "mode": "read_only_shadow_candidates",
        "paper_only": True,
        "candidates": [{"underlying": "IWM", "classification": "below_threshold"}],
    }


@pytest.mark.asyncio
async def test_submit_approved_refuses_when_dry_run_is_still_enabled(monkeypatch):
    monkeypatch.setattr(
        cli, "get_settings", lambda: Settings(allow_order_execution=True, dry_run=True)
    )
    with pytest.raises(RuntimeError, match="DRY_RUN=false"):
        await cli._submit_approved("vg-plan-test")


@pytest.mark.asyncio
async def test_submit_approved_requires_an_explicit_cli_session_arm(monkeypatch):
    monkeypatch.setattr(
        cli, "get_settings", lambda: Settings(allow_order_execution=True, dry_run=False)
    )
    with pytest.raises(RuntimeError, match="--arm-paper-execution"):
        await cli._submit_approved("vg-plan-test")


@pytest.mark.asyncio
async def test_session_report_command_is_read_only(monkeypatch, capsys):
    class FakeJournal:
        def shadow_session_report(self):
            return {"mode": "read_only_live_shadow_evaluation", "candidate_count": 2}

    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli, "DecisionJournal", FakeJournal)
    await cli._shadow_session_report()
    assert json.loads(capsys.readouterr().out) == {
        "paper_only": True,
        "mode": "read_only_live_shadow_evaluation",
        "candidate_count": 2,
    }


def test_replay_command_runs_the_full_credential_free_simulation(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "vegaguard",
            "replay",
            "--fixture",
            "tests/fixtures/strategy_replay_sanitized.json",
            "--output-dir",
            str(tmp_path),
        ],
    )
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "offline_reproducible_demo"
    assert result["live_execution"] == "disabled_by_design"
    assert result["simulated_lifecycle"]["paper_trade_counters"]["submitted"] == 0
