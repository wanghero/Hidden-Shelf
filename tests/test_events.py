"""运行事件：SSE 形状、序号与补发、淘汰规则、订阅与关闭、`Progress` 回调映射。"""
from __future__ import annotations

import json
import queue
import threading

import pytest

from hidden_shelf.serve.events import KEEP_ALWAYS, KINDS, Event, EventProgress, RunLog, event_from_dict


def test_event_to_sse_shape():
    event = Event(7, "2026-10-29T00:00:00.000+00:00", "run-1", "step.progress", "scan", "info", "扫描 3 个文件", None)
    text = event.to_sse()
    lines = text.split("\n")
    assert lines[0] == "id: 7" and lines[1] == "event: step.progress" and lines[2].startswith("data: ")
    assert text.endswith("\n\n") and lines[3] == "" and lines[4] == ""
    data = json.loads(lines[2][len("data: "):])
    assert data == {"seq": 7, "ts": "2026-10-29T00:00:00.000+00:00", "run": "run-1", "kind": "step.progress",
                    "step": "scan", "level": "info", "message": "扫描 3 个文件", "stats": None}
    assert "扫描 3 个文件" in text, "中文不转义"
    assert event_from_dict(data) == event
    assert set(KINDS) - KEEP_ALWAYS == {"step.progress"}


def test_runlog_sequence_and_since():
    from datetime import datetime, timezone
    log = RunLog("run-1", clock=lambda: 1_793_236_000.0)
    first = log.append("run.start", stats={"root": "/x"})
    expected = datetime.fromtimestamp(1_793_236_000.0, timezone.utc).isoformat(timespec="milliseconds")
    assert (first.seq, first.run, first.ts) == (1, "run-1", expected)
    assert first.ts.endswith("+00:00") and first.ts.startswith("2026-10-")
    for index in range(40):
        log.append("step.progress", step="scan", message=f"第 {index} 行")
    assert log.last_seq == 41
    tail = log.since(37)
    assert [event.seq for event in tail] == [38, 39, 40, 41]
    assert log.since(41) == [] and len(log.since(0)) == 41
    with pytest.raises(ValueError):
        log.append("bogus")


def test_runlog_eviction_keeps_milestones():
    log = RunLog("run-1", limit=10)
    log.append("run.start")
    log.append("step.start", step="scan")
    for index in range(50):
        log.append("step.progress", step="scan", message=str(index))
    log.append("step.done", step="scan", stats={"added": 50})
    kinds = [event.kind for event in log.events]
    assert kinds.count("run.start") == 1 and kinds.count("step.start") == 1 and kinds.count("step.done") == 1
    assert len(log.events) == 10
    progress = [event for event in log.events if event.kind == "step.progress"]
    assert [event.message for event in progress] == [str(index) for index in range(43, 50)], "只剩最新的 progress"
    # 只有里程碑时超限也不丢。
    tiny = RunLog("run-2", limit=2)
    for _ in range(5):
        tiny.append("step.start", step="scan")
    assert len(tiny.events) == 5


def test_runlog_subscribe_and_close():
    log = RunLog("run-1")
    log.append("run.start")
    first, second = log.subscribe(), log.subscribe()
    assert first.empty(), "订阅只收之后的事件"
    log.append("step.start", step="scan")
    log.append("step.done", step="scan", stats={})
    assert [first.get_nowait().kind, first.get_nowait().kind] == ["step.start", "step.done"]
    assert second.get_nowait().kind == "step.start"
    log.unsubscribe(second)
    log.append("run.done", stats={"ok": True})
    assert first.get_nowait().kind == "run.done" and second.get_nowait().kind == "step.done" and second.empty()
    log.close()
    assert first.get_nowait() is None
    assert log.closed
    with pytest.raises(RuntimeError):
        log.append("step.progress", message="晚了")
    late = log.subscribe()
    assert late.get_nowait() is None, "已结束的运行新订阅者立刻收到结束标记"
    log.close()  # 幂等


def test_runlog_is_thread_safe():
    log = RunLog("run-1", limit=100_000)

    def worker(prefix):
        for index in range(500):
            log.append("step.progress", message=f"{prefix}-{index}")

    threads = [threading.Thread(target=worker, args=(name,)) for name in "abcd"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    seqs = [event.seq for event in log.events]
    assert seqs == list(range(1, 2001))


def test_event_progress_maps_callbacks():
    log = RunLog("run-1")
    progress = EventProgress(log)
    progress.step("scan")
    progress.advance(1, "扫描 a/b.mp4")
    progress.advance(1, "")
    progress.log("warning", "有一条警告")
    progress.done({"added": 1})
    progress.step("scrape", total=3)
    progress.failed("scrape", "RuntimeError: 炸了")
    progress.step("organize")
    progress.skipped("organize", "config.scrape=false")
    rows = [(event.kind, event.step, event.level, event.message, event.stats) for event in log.events]
    assert rows == [
        ("step.start", "scan", None, None, None),
        ("step.progress", "scan", "info", "扫描 a/b.mp4", None),
        ("step.progress", "scan", "warning", "有一条警告", None),
        ("step.done", "scan", None, None, {"added": 1}),
        ("step.start", "scrape", None, None, {"total": 3}),
        ("step.failed", "scrape", "error", "RuntimeError: 炸了", None),
        ("step.start", "organize", None, None, None),
        ("step.skipped", "organize", "info", "config.scrape=false", None),
    ]
    assert isinstance(log.subscribe(), queue.Queue)
