"""运行管理器：后台线程与生命周期事件、单运行、取消、状态归约、异常不吞、选项校验、最近目录。"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from hidden_shelf import pipeline
from hidden_shelf.serve.runner import RunBusy, RunManager, RunOptions, reduce_state
from serve_fakes import fake_pipeline


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def _options(tmp_root: Path, **kw) -> RunOptions:
    return RunOptions.from_payload({"root": str(tmp_root), **kw})


def test_start_runs_in_background_and_emits_lifecycle(tmp_root: Path, home: Path):
    runner = fake_pipeline()
    manager = RunManager(home=home, run_pipeline=runner)
    run_id = manager.start(_options(tmp_root, offline=True))
    assert isinstance(run_id, str) and run_id
    assert manager.wait(timeout=10)
    events = manager.log_for(run_id).events
    assert events[0].kind == "run.start" and events[0].seq == 1
    assert events[0].stats["root"] == str(tmp_root.resolve()) and events[0].stats["options"]["offline"] is True
    assert events[-1].kind == "run.done" and events[-1].stats["ok"] is True
    assert events[-1].stats["index_html"].endswith("index.html") and events[-1].stats["cancelled"] is False
    assert [e.kind for e in events if e.kind.startswith("step.") and e.step == "scan"] == ["step.start", "step.progress", "step.progress", "step.done"]
    assert manager.log_for(run_id).closed
    assert runner.calls[0]["offline"] is True and runner.calls[0]["move"] is True
    state = manager.state()
    assert state["running"] is False and state["run"] == run_id
    assert all(row["status"] == "done" for row in state["steps"].values())
    assert state["result"]["ok"] is True
    assert manager.recent_roots() == [str(tmp_root.resolve())]
    assert manager.log_for("bogus") is None and manager.log_for() is manager.log_for(run_id)


def test_second_start_while_running_is_busy(tmp_root: Path, home: Path):
    gate = threading.Event()
    manager = RunManager(home=home, run_pipeline=fake_pipeline(gate=gate))
    first = manager.start(_options(tmp_root))
    assert manager.running and manager.state()["running"]
    with pytest.raises(RunBusy, match="已有一个运行"):
        manager.start(_options(tmp_root))
    gate.set()
    assert manager.wait(timeout=10)
    assert not manager.running
    second = manager.start(_options(tmp_root))
    assert second != first
    assert manager.wait(timeout=10)
    assert manager.log_for(second).events[0].seq == 1, "新运行序号从 1 起"
    assert manager.log_for(first) is None, "只保留最近一次"


def test_cancel_flag_reaches_pipeline(tmp_root: Path, home: Path):
    gate = threading.Event()
    manager = RunManager(home=home, run_pipeline=fake_pipeline(gate=gate, check_cancel=True))
    assert manager.cancel() is False, "没在跑"
    run_id = manager.start(_options(tmp_root))
    # 等第一步真的跑完（假流水线卡在 gate 上），再说停：这样「当前步完成后不再开下一步」才测得到。
    import time
    for _ in range(200):
        if manager.state()["steps"]["scan"]["status"] == "done":
            break
        time.sleep(0.01)
    assert manager.cancel() is True
    assert manager.state()["cancel_requested"] is True
    gate.set()
    assert manager.wait(timeout=10)
    events = manager.log_for(run_id).events
    assert events[-1].kind == "run.cancelled" and events[-1].stats["cancelled"] is True
    assert any(e.level == "warning" and "收到停止请求" in (e.message or "") for e in events)
    assert [e.step for e in events if e.kind == "step.start"] == ["scan"], "当前步完成后不再开下一步"
    assert manager.cancel() is False
    state = manager.state()
    assert state["running"] is False and state["result"]["cancelled"] is True
    assert state["steps"]["import"]["status"] == "waiting"


def test_state_reduces_events(tmp_root: Path, home: Path):
    manager = RunManager(home=home, run_pipeline=fake_pipeline(fail=("scrape",), skip=("organize",)))
    manager.start(_options(tmp_root))
    assert manager.wait(timeout=10)
    steps = manager.state()["steps"]
    assert steps["scan"]["status"] == "done" and steps["scan"]["stats"] == {"added": 0}
    assert steps["scrape"]["status"] == "failed" and steps["scrape"]["error"] == "RuntimeError: 炸了"
    assert steps["organize"]["status"] == "skipped" and steps["organize"]["message"] == "--offline"
    assert steps["build"]["status"] == "done" and steps["build"]["message"] == "[2/2] build 第二行"
    # 硬失败：后续步保持 waiting，结果 ok=false。
    manager = RunManager(home=home, run_pipeline=fake_pipeline(fail=("media",)))
    manager.start(_options(tmp_root))
    assert manager.wait(timeout=10)
    state = manager.state()
    assert state["steps"]["media"]["status"] == "failed" and state["steps"]["build"]["status"] == "waiting"
    assert state["result"]["ok"] is False and state["result"]["failed_step"] == "media"
    assert reduce_state([])["steps"]["scan"]["status"] == "waiting" and reduce_state([])["run"] is None


def test_pipeline_exception_is_reported_not_swallowed(tmp_root: Path, home: Path):
    manager = RunManager(home=home, run_pipeline=fake_pipeline(raise_error=RuntimeError("线程里炸了")))
    run_id = manager.start(_options(tmp_root))
    assert manager.wait(timeout=10)
    last = manager.log_for(run_id).events[-1]
    assert last.kind == "run.done" and last.stats["ok"] is False and "线程里炸了" in last.stats["error"]
    assert not manager.running, "锁已释放"
    assert manager.start(_options(tmp_root))


def test_options_from_payload_validation(tmp_root: Path):
    options = RunOptions.from_payload({"root": str(tmp_root), "steps": ["build", "scan"], "offline": True})
    assert options.steps == ("scan", "build") and options.offline and options.move_unrecognized
    assert options.to_dict()["steps"] == ["scan", "build"]
    with pytest.raises(ValueError, match="不存在"):
        RunOptions.from_payload({"root": str(tmp_root / "nope")})
    with pytest.raises(ValueError, match="请填写"):
        RunOptions.from_payload({"root": ""})
    with pytest.raises(ValueError, match="步骤"):
        RunOptions.from_payload({"root": str(tmp_root), "steps": ["scan", "hentai"]})
    with pytest.raises(ValueError, match="步骤"):
        RunOptions.from_payload({"root": str(tmp_root), "steps": []})
    with pytest.raises(ValueError, match="offline"):
        RunOptions.from_payload({"root": str(tmp_root), "offline": "false"})
    with pytest.raises(ValueError, match="JSON 对象"):
        RunOptions.from_payload(["x"])
    assert RunOptions.from_payload({"root": str(tmp_root)}).dry_run is False
    dry = RunOptions.from_payload({"root": str(tmp_root), "dry_run": True})
    assert dry.dry_run is True and dry.to_dict()["dry_run"] is True
    with pytest.raises(ValueError, match="dry_run"):
        RunOptions.from_payload({"root": str(tmp_root), "dry_run": "yes"})


def test_recent_roots_roundtrip(home: Path, tmp_path: Path):
    manager = RunManager(home=home, run_pipeline=fake_pipeline())
    assert manager.recent_roots() == []
    for index in range(12):
        manager.remember_root(tmp_path / f"disk{index}")
    roots = manager.recent_roots()
    assert len(roots) == 10 and roots[0].endswith("disk11") and roots[-1].endswith("disk2")
    manager.remember_root(tmp_path / "disk5")
    roots = manager.recent_roots()
    assert roots[0].endswith("disk5") and roots.count(str(tmp_path / "disk5")) == 1 and len(roots) == 10
    manager.recent_path.write_text("not json", encoding="utf-8")
    assert manager.recent_roots() == []
    assert manager.recent_path.parent == home


def test_options_reject_readonly_root_with_hint(tmp_root: Path, monkeypatch):
    import os
    monkeypatch.setattr(os, "access", lambda path, mode, **kw: not (mode & os.W_OK))
    with pytest.raises(ValueError, match="不可写") as caught:
        RunOptions.from_payload({"root": str(tmp_root)})
    assert "NTFS" in str(caught.value)
