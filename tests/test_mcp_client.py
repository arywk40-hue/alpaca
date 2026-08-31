from pathlib import Path

from vegaguard.mcp_client import AlpacaMCPClient


def test_mcp_client_prefers_uvx_beside_the_active_python(monkeypatch, tmp_path):
    executable = tmp_path / "python"
    uvx = tmp_path / "uvx"
    executable.touch()
    uvx.touch()
    monkeypatch.setattr("vegaguard.mcp_client.sys.executable", str(executable))
    assert AlpacaMCPClient._uvx_command() == str(uvx)


def test_mcp_client_falls_back_to_path_when_virtualenv_has_no_uvx(monkeypatch, tmp_path):
    executable = Path(tmp_path / "python")
    executable.touch()
    monkeypatch.setattr("vegaguard.mcp_client.sys.executable", str(executable))
    assert AlpacaMCPClient._uvx_command() == "uvx"


def test_mcp_client_pins_compatible_server_runtime():
    assert AlpacaMCPClient._uvx_args() == [
        "--from",
        "alpaca-mcp-server==2.3.0",
        "--with",
        "fastmcp>=3.1,<4",
        "alpaca-mcp-server",
    ]


def test_mcp_allowlist_excludes_destructive_account_wide_tools():
    assert "place_option_order" in AlpacaMCPClient.approved_tools
    assert "close_position" not in AlpacaMCPClient.approved_tools
    assert "close_all_positions" not in AlpacaMCPClient.approved_tools
    assert "exercise_option" not in AlpacaMCPClient.approved_tools
