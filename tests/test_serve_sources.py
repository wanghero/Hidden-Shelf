"""进度网页的「来源与登录」面板接口（计划 8 任务 2）。登录流程是假的，不开浏览器。"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hidden_shelf.netconfig import GlobalConfig, SourceSettings
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scrape.access import Cooldown
from hidden_shelf.scrape.login import LoginError
from hidden_shelf.serve.app import create_app
from hidden_shelf.serve.runner import RunManager
from hidden_shelf.serve.sources import SourcePanel
from serve_fakes import fake_pipeline

HEADERS = {"X-Shelf-Request": "1", "Origin": "http://127.0.0.1:8031"}


@pytest.fixture
def home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HIDDEN_SHELF_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def make(tmp_path: Path, **panel_options):
    panel_options.setdefault("fingerprint", lambda: False)
    panel = SourcePanel(**panel_options)
    app = create_app(RunManager(home=tmp_path / "serve-home", run_pipeline=fake_pipeline()), panel=panel, ping_seconds=0.05)
    client = TestClient(app)
    client.panel = panel
    return client


def _wait(client, name, status, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        row = {r["name"]: r for r in client.get("/api/sources", headers=HEADERS).json()["sources"]}[name]
        if row["login"]["status"] == status:
            return row
        time.sleep(0.02)
    raise AssertionError(f"{name} 没到 {status}")


def test_sources_list_hides_values_and_shows_cooldown(home: Path, tmp_path: Path, tmp_root: Path):
    GlobalConfig(sources={"javdb": SourceSettings(cookie="secret=1", user_agent="UA"), "avbase": SourceSettings(enabled=False)}).save()
    paths = ShelfPaths(tmp_root); paths.ensure()
    Cooldown(paths.sources / "_cooldown.json").pause("avbase", action="blocked")
    client = make(tmp_path, availability=lambda: "")
    assert client.get("/api/sources").status_code == 403, "GET /api/sources 也要同源头"
    body = client.get("/api/sources", params={"root": str(tmp_root)}, headers=HEADERS).json()
    assert "secret" not in json.dumps(body) and body["login_available"] is True and body["login_hint"] == ""
    assert body["fingerprint_available"] is False and "extra fingerprint" in body["fingerprint_hint"]
    rows = {r["name"]: r for r in body["sources"]}
    assert [r["name"] for r in body["sources"]][:3] == ["javdb", "javbus", "avbase"], "可登录的排前面"
    assert rows["javdb"] == {"name": "javdb", "label": "JavDB", "enabled": True, "needs_login": True, "needs_fingerprint": False,
                             "cookie": True, "user_agent": True, "cooldown_until": None, "login": {"status": "idle", "message": ""}}
    assert rows["avbase"]["enabled"] is False and rows["avbase"]["cooldown_until"] is not None
    assert rows["avbase"]["needs_login"] is False and rows["avbase"]["needs_fingerprint"] is True
    assert rows["r18dev"]["needs_login"] is False and rows["r18dev"]["cookie"] is False
    assert rows["javdb"]["cooldown_until"] is None


def test_sources_toggle_persists(home: Path, tmp_path: Path):
    client = make(tmp_path, availability=lambda: "")
    assert client.post("/api/sources", json={"name": "avbase", "enabled": False}, headers=HEADERS).json() == {"ok": True}
    assert GlobalConfig.load().enabled("avbase") is False
    assert client.post("/api/sources", json={"name": "nope", "enabled": True}, headers=HEADERS).status_code == 400
    assert client.post("/api/sources", json={"name": "avbase"}, headers=HEADERS).status_code == 400


def test_login_flow_runs_in_background_and_saves(home: Path, tmp_path: Path):
    seen = {}

    def capture(source, *, config, finish, notify, launch):
        seen["source"] = source
        notify("浏览器已打开")
        finish.wait(5)
        config.set_login(source, "sess=abc", "UA-x")
        from hidden_shelf.scrape.login import LoginResult
        return LoginResult(cookies=1, user_agent="UA-x")
    client = make(tmp_path, availability=lambda: "", capture=capture)
    assert client.post("/api/login", json={"name": "javdb"}, headers=HEADERS).status_code == 202
    row = _wait(client, "javdb", "running")
    assert "浏览器已打开" in row["login"]["message"]
    assert client.post("/api/login", json={"name": "javdb"}, headers=HEADERS).status_code == 409, "同一站不重复开"
    assert client.post("/api/login/finish", json={"name": "javdb"}, headers=HEADERS).status_code == 202
    row = _wait(client, "javdb", "done")
    assert "1 个 Cookie" in row["login"]["message"] and row["cookie"] is True and row["user_agent"] is True
    assert GlobalConfig.load().cookie("javdb") == "sess=abc" and seen["source"] == "javdb"
    assert client.post("/api/login/finish", json={"name": "javdb"}, headers=HEADERS).status_code == 409, "没在登录"


def test_login_failure_is_reported(home: Path, tmp_path: Path):
    def capture(source, **_):
        raise LoginError("没有拿到 JavDB 的 Cookie，原来的设置没动")
    client = make(tmp_path, availability=lambda: "", capture=capture)
    assert client.post("/api/login", json={"name": "javbus"}, headers=HEADERS).status_code == 202
    row = _wait(client, "javbus", "failed")
    assert "没有拿到" in row["login"]["message"]
    # 失败后可以再来一次。
    assert client.post("/api/login", json={"name": "javbus"}, headers=HEADERS).status_code == 202


def test_login_unavailable_and_unknown_source(home: Path, tmp_path: Path):
    client = make(tmp_path, availability=lambda: "没装 Playwright：uv sync --extra login")
    body = client.get("/api/sources", headers=HEADERS).json()
    assert body["login_available"] is False and "uv sync --extra login" in body["login_hint"]
    response = client.post("/api/login", json={"name": "javdb"}, headers=HEADERS)
    assert response.status_code == 400 and "uv sync --extra login" in response.json()["error"]
    client = make(tmp_path, availability=lambda: "")
    assert client.post("/api/login", json={"name": "avbase"}, headers=HEADERS).status_code == 400


def test_clear_cooldown(home: Path, tmp_path: Path, tmp_root: Path):
    paths = ShelfPaths(tmp_root); paths.ensure()
    cooldown = Cooldown(paths.sources / "_cooldown.json")
    cooldown.pause("avbase", action="blocked"); cooldown.pause("javdb", action="blocked")
    client = make(tmp_path, availability=lambda: "")
    assert client.post("/api/cooldown/clear", json={"root": str(tmp_root), "name": "avbase"}, headers=HEADERS).json() == {"cleared": ["avbase"]}
    assert client.post("/api/cooldown/clear", json={"root": str(tmp_root)}, headers=HEADERS).json() == {"cleared": ["javdb"]}
    assert Cooldown(paths.sources / "_cooldown.json").describe() == {}
    assert client.post("/api/cooldown/clear", json={"root": str(tmp_path / "nope")}, headers=HEADERS).status_code == 400
