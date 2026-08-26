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
