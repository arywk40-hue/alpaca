import json

from vegaguard.demo import build_offline_demo


def test_offline_demo_writes_reproducible_non_live_artifacts(tmp_path):
    summary = build_offline_demo(
        fixture="tests/fixtures/strategy_replay_sanitized.json", output_dir=tmp_path
    )
    assert summary["mode"] == "offline_reproducible_demo"
    assert summary["live_execution"] == "disabled_by_design"
    assert summary["observation_count"] == 3
    assert {path.name for path in tmp_path.iterdir()} == {
        "README.md",
        "demo_summary.json",
        "scorer_comparison.json",
        "simulated_lifecycle.json",
        "strategy_replay.json",
    }
    replay = json.loads((tmp_path / "strategy_replay.json").read_text())
    assert replay["limitations"][0].startswith("Sanitized deterministic fixture")
    lifecycle = json.loads((tmp_path / "simulated_lifecycle.json").read_text())
    assert lifecycle["mode"] == "SIMULATION_REPLAY"
    assert lifecycle["simulated_plan_count"] == 2
    assert lifecycle["simulated_exit_count"] == 2
    assert lifecycle["paper_trade_counters"] == {
        "submitted": 0,
        "acknowledged": 0,
        "filled": 0,
        "realized": 0,
    }
    assert [event["stage"] for event in lifecycle["events"]].count("simulated_exit") == 2
    assert [event["stage"] for event in lifecycle["events"]].count("simulated_order") == 2
    assert [event["stage"] for event in lifecycle["events"]].count("simulated_fill") == 2
    assert all(event["mode"] == "SIMULATION_REPLAY" for event in lifecycle["events"])


def test_offline_replay_is_byte_for_byte_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_offline_demo(fixture="tests/fixtures/strategy_replay_sanitized.json", output_dir=first)
    build_offline_demo(fixture="tests/fixtures/strategy_replay_sanitized.json", output_dir=second)
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }
