"""在浏览器里登录来源站：抓该站 Cookie 与 UA 存进全局配置（计划 8）。浏览器句柄是假的，测试不开浏览器。"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from hidden_shelf.netconfig import GlobalConfig, SourceSettings
from hidden_shelf.scrape import login
from hidden_shelf.scrape.login import LOGIN_SOURCES, LoginError, capture_login


class FakeBrowser:
    """每次 `cookies()` 回下一轮快照；`close_after` 轮之后窗口「已关」。"""

    def __init__(self, rounds, *, ua="Mozilla/5.0 Fake", close_after=None):
        self.rounds = list(rounds)
        self.index = 0
        self.ua = ua
        self.close_after = close_after
        self.closed_calls = 0
        self.url = None

    def cookies(self):
        snapshot = self.rounds[min(self.index, len(self.rounds) - 1)]
        self.index += 1
        return snapshot

    def user_agent(self):
        return self.ua

    def closed(self):
        return self.close_after is not None and self.index >= self.close_after

    def close(self):
        self.closed_calls += 1


def _launcher(browser):
    def launch(url):
        browser.url = url
        return browser
    return launch


JAVDB = [{"name": "_jdb_session", "value": "abc", "domain": "javdb.com"},
         {"name": "over18", "value": "1", "domain": ".javdb.com"},
         {"name": "cf_clearance", "value": "zzz", "domain": "www.javdb.com"},
         {"name": "other", "value": "x", "domain": "example.com"}]


def test_login_sources_are_the_ones_that_gate():
    assert LOGIN_SOURCES == ("javdb", "javbus"), "avbase 靠指纹传输，不靠登录"
    with pytest.raises(LoginError, match="不在可登录的来源里"):
        capture_login("avbase", config=GlobalConfig(), finish=threading.Event(), launch=_launcher(FakeBrowser([[]])))


def test_capture_uses_last_snapshot_when_window_closes():
    """用户登录完直接关窗口：窗口没了就拿不到 Cookie，所以每轮都留一份快照，用最后一份。"""
    browser = FakeBrowser([[], JAVDB[:1], JAVDB], close_after=3)
    config = GlobalConfig(sources={"javdb": SourceSettings(cookie="old=1")})
    notes: list[str] = []
    result = capture_login("javdb", config=config, finish=threading.Event(), notify=notes.append,
                           launch=_launcher(browser), poll_seconds=0)
    assert browser.url == "https://javdb.com/login"
    assert result.cookies == 3 and result.user_agent == "Mozilla/5.0 Fake"
    assert config.cookie("javdb") == "_jdb_session=abc; over18=1; cf_clearance=zzz", "只收该站域名下的，example.com 的不要"
    assert config.sources["javdb"].user_agent == "Mozilla/5.0 Fake"
    assert config.sources["javdb"].enabled is True
    assert browser.closed_calls == 1
    assert any("浏览器已打开" in note for note in notes)


def test_capture_finish_event_ends_the_wait():
    browser = FakeBrowser([JAVDB])
    finish = threading.Event()
    finish.set()
    config = GlobalConfig()
    result = capture_login("javdb", config=config, finish=finish, launch=_launcher(browser), poll_seconds=0)
    assert result.cookies == 3 and browser.closed_calls == 1


def test_capture_without_cookies_keeps_old_value():
    browser = FakeBrowser([[]], close_after=1)
    config = GlobalConfig(sources={"javdb": SourceSettings(cookie="old=1", user_agent="UA-old")})
    with pytest.raises(LoginError, match="没有拿到"):
        capture_login("javdb", config=config, finish=threading.Event(), launch=_launcher(browser), poll_seconds=0)
    assert config.cookie("javdb") == "old=1" and config.sources["javdb"].user_agent == "UA-old"


def test_capture_times_out():
    browser = FakeBrowser([[]])
    with pytest.raises(LoginError, match="超时"):
        capture_login("javdb", config=GlobalConfig(), finish=threading.Event(), launch=_launcher(browser),
                      poll_seconds=0, timeout=0)
    assert browser.closed_calls == 1


def test_login_unavailable_message(monkeypatch):
    monkeypatch.setattr(login, "_import_playwright", lambda: (_ for _ in ()).throw(ImportError("no")))
    text = login.availability()
    assert "uv sync --extra login" in text and "playwright install chromium" in text


def test_cli_login_without_playwright_exits_2(monkeypatch, capsys):
    from hidden_shelf import cli
    monkeypatch.setattr(login, "availability", lambda: "缺 Playwright：请先 uv sync --extra login")
    assert cli.main(["login", "javdb"]) == 2
    assert "uv sync --extra login" in capsys.readouterr().err


def test_cli_login_saves_config(monkeypatch, capsys, tmp_path: Path):
    from hidden_shelf import cli
    monkeypatch.setenv("HIDDEN_SHELF_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(login, "availability", lambda: "")
    monkeypatch.setattr(login, "launch_browser", _launcher(FakeBrowser([JAVDB], close_after=1)))
    monkeypatch.setattr(cli, "_wait_for_enter", lambda finish: None)
    assert cli.main(["login", "javdb"]) == 0
    out = capsys.readouterr().out
    assert "已保存 3 个 Cookie" in out and "abc" not in out, "不打印 Cookie 值"
    assert GlobalConfig.load().cookie("javdb").startswith("_jdb_session=abc")
