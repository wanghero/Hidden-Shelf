"""`shelf serve`：端口选择与启动参数。uvicorn 与浏览器都用 monkeypatch 顶替，不真起服务。"""
from __future__ import annotations

import socket

import pytest

from hidden_shelf import cli
from hidden_shelf.serve import ports
from hidden_shelf.serve.ports import DEFAULT_PORT, PORT_RANGE, PortInUse, candidates, pick_port


def _hold(port: int) -> socket.socket:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", port))
    holder.listen(1)
    return holder


def test_candidates_order():
    found = candidates(8031, (8000, 8099))
    assert found[0] == 8031 and found[1] == 8032 and found[-1] == 8030
    assert sorted(found) == list(range(8000, 8100)) and len(found) == 100
    assert candidates(8000, (8000, 8002)) == [8000, 8001, 8002]


def test_pick_port_prefers_default_then_next_free(monkeypatch):
    busy = {8031}
    monkeypatch.setattr(ports, "is_free", lambda port, host=ports.HOST: port not in busy)
    assert pick_port() == 8032
    busy.clear()
    assert pick_port() == DEFAULT_PORT
    busy.update(range(8000, 8100))
    with pytest.raises(PortInUse, match="没有空闲端口"):
        pick_port()
    busy.clear()
    busy.add(8050)
    with pytest.raises(PortInUse, match="8050 已被占用"):
        pick_port(8050)
    assert pick_port(8051) == 8051
    with pytest.raises(PortInUse):
        pick_port(70000)


def test_is_free_sees_a_real_listener():
    holder = _hold(0)
    try:
        port = holder.getsockname()[1]
        assert not ports.is_free(port)
        with pytest.raises(PortInUse):
            pick_port(port)
    finally:
        holder.close()
    assert ports.is_free(port)


@pytest.fixture
def fake_uvicorn(monkeypatch):
    calls = {}

    def run(app, **kwargs):
        calls["app"] = app
        calls.update(kwargs)

    import uvicorn
    monkeypatch.setattr(uvicorn, "run", run)
    opened = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    calls["opened"] = opened
    return calls


def test_cli_serve_starts_uvicorn_on_loopback(fake_uvicorn, monkeypatch, capsys):
    monkeypatch.setattr(ports, "is_free", lambda port, host=ports.HOST: True)
    assert cli.main(["serve"]) == 0
    assert fake_uvicorn["host"] == "127.0.0.1" and fake_uvicorn["port"] == DEFAULT_PORT
    assert fake_uvicorn["log_level"] == "warning"
    assert fake_uvicorn["opened"] == [f"http://127.0.0.1:{DEFAULT_PORT}/"]
    out = capsys.readouterr().out
    assert f"进度网页：http://127.0.0.1:{DEFAULT_PORT}/" in out and "被占" not in out
    routes = {route.path for route in fake_uvicorn["app"].routes}
    assert {"/", "/api/state", "/api/run", "/api/cancel", "/api/open", "/api/events"} <= routes, "传给 uvicorn 的是真应用"


def test_cli_serve_no_browser_and_verbose(fake_uvicorn, monkeypatch):
    monkeypatch.setattr(ports, "is_free", lambda port, host=ports.HOST: True)
    assert cli.main(["serve", "--no-browser", "--verbose", "--port", "8040"]) == 0
    assert fake_uvicorn["opened"] == [] and fake_uvicorn["port"] == 8040 and fake_uvicorn["log_level"] == "info"


def test_cli_serve_moves_to_next_free_port_and_says_so(fake_uvicorn, monkeypatch, capsys):
    monkeypatch.setattr(ports, "is_free", lambda port, host=ports.HOST: port != DEFAULT_PORT)
    assert cli.main(["serve", "--no-browser"]) == 0
    assert fake_uvicorn["port"] == DEFAULT_PORT + 1
    assert f"默认端口 {DEFAULT_PORT} 被占，改用 {DEFAULT_PORT + 1}" in capsys.readouterr().out


def test_cli_serve_port_in_use_exit_2(fake_uvicorn, monkeypatch, capsys):
    monkeypatch.setattr(ports, "is_free", lambda port, host=ports.HOST: False)
    assert cli.main(["serve", "--port", "8031"]) == 2
    assert "已被占用" in capsys.readouterr().err
    assert "app" not in fake_uvicorn and fake_uvicorn["opened"] == []
    assert PORT_RANGE == (8000, 8099)
