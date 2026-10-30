"""流水线的步间取消与 `failed`/`skipped` 回调；`ConsoleProgress` 的文字与计划 1、2 一致。"""
from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest

from hidden_shelf import pipeline
from hidden_shelf.config import ShelfConfig


class Recorder(pipeline.Progress):
    def __init__(self):
        self.calls = []

    def step(self, name, total=None):
        self.calls.append(("step", name))

    def done(self, stats):
        self.calls.append(("done", dict(stats)))

    def failed(self, name, error):
        self.calls.append(("failed", name, error))

    def skipped(self, name, reason):
        self.calls.append(("skipped", name, reason))

    def log(self, level, message):
        self.calls.append(("log", level, message))


@pytest.fixture
def fake_steps(monkeypatch):
    """把六步全换成记录调用的假函数，不碰 ffmpeg 也不碰网络。"""
    ran = []

    def make(name, stats):
        def fake(*args, **kwargs):
            ran.append(name)
            return stats
        return fake

    monkeypatch.setattr(pipeline, "scan", make("scan", {"added": 1}))
    monkeypatch.setattr(pipeline, "import_local", make("import", {"nfo": 0}))
    monkeypatch.setattr(pipeline, "organize", make("organize", {"moved": 0}))
    monkeypatch.setattr(pipeline, "process_assets", make("media", {"probed": 0}))
    monkeypatch.setattr(pipeline, "build_site", make("build", {"works": 0}))
    return ran


def _runs(root):
    with sqlite3.connect(root / "HiddenShelf" / "shelf.db") as connection:
        return connection.execute("SELECT step,status FROM run ORDER BY id").fetchall()


def test_pipeline_cancel_between_steps(tmp_root: Path, fake_steps):
    recorder = Recorder()
    seen = []

    def cancel():
        # import 完成后才说停：scan、import 都该跑完，scrape 不该开。
        seen.append(tuple(fake_steps))
        return "import" in fake_steps

    result = pipeline.run(tmp_root, progress=recorder, cancel=cancel,
                          scrape_options=pipeline.ScrapeOptions(offline=True))
    assert result.cancelled and result.ok and result.failed_step == ""
    assert fake_steps == ["scan", "import"], "取消只在步与步之间生效"
    assert result.index_html is None
    assert _runs(tmp_root) == [("scan", "ok"), ("import", "ok")]
    assert ("log", "warning", "已取消：在刮削之前停下") in recorder.calls
    assert [call for call in recorder.calls if call[0] == "step"] == [("step", "scan"), ("step", "import")]
    assert "已取消：在 刮削 之前停下" in result.log_path.read_text(encoding="utf-8")
    # 没有取消回调时照旧跑完。
    fake_steps.clear()
    result = pipeline.run(tmp_root, scrape_options=pipeline.ScrapeOptions(offline=True))
    assert not result.cancelled and fake_steps == ["scan", "import", "organize", "scan", "media", "build"]


def test_pipeline_calls_failed_and_skipped(tmp_root: Path, fake_steps, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("炸了")

    monkeypatch.setattr(pipeline, "build_site", boom)
    recorder = Recorder()
    result = pipeline.run(tmp_root, progress=recorder, scrape_options=pipeline.ScrapeOptions(offline=True))
    assert not result.ok and result.failed_step == "build"
    assert ("skipped", "scrape", "--offline") in recorder.calls
    assert ("failed", "build", "RuntimeError: 炸了") in recorder.calls
    assert not any(call[0] == "log" and call[1] == "error" for call in recorder.calls), "失败走 failed() 不再走 log()"
    # scrape 软失败：failed() 被调但流水线继续。
    import hidden_shelf.scrape.run as run_module
    monkeypatch.setattr(run_module, "scrape_assets", boom)
    monkeypatch.setattr(pipeline, "build_site", lambda *a, **k: {"works": 0})
    recorder = Recorder()
    result = pipeline.run(tmp_root, config=ShelfConfig(scrape=True), progress=recorder)
    assert result.ok and ("failed", "scrape", "RuntimeError: 炸了") in recorder.calls
    assert ("step", "build") in recorder.calls


def test_console_progress_wording_is_unchanged():
    stream = io.StringIO()
    console = pipeline.ConsoleProgress(stream=stream)
    console.step("scrape")
    console.skipped("scrape", "--offline")
    console.step("build")
    console.failed("build", "RuntimeError: 炸了")
    assert stream.getvalue().splitlines() == ["== 刮削 ==", "[刮削] 跳过刮削（--offline）", "== 出站 ==",
                                               "[出站] ✗ 出站失败：RuntimeError: 炸了"]
    # 默认实现什么都不做，不抛。
    base = pipeline.Progress()
    base.failed("x", "y")
    base.skipped("x", "y")
