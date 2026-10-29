"""原始快照与「没有」记忆。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from hidden_shelf.scrape.snapshots import TTL_SECONDS, Snapshots


class Clock:
    def __init__(self, start=1_700_000_000.0):
        self.now = start

    def __call__(self):
        return self.now


def test_snapshot_roundtrip_and_ttl(tmp_path: Path):
    clock = Clock()
    snapshots = Snapshots(tmp_path / "sources", now=clock)
    assert snapshots.load("ABW-358", "r18dev") is None
    snapshots.save_result("ABW-358", "r18dev", {"id": "ABW-358", "title": "x"})
    path = snapshots.path("ABW-358", "r18dev")
    assert path.name == "ABW-358-r18dev.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["source"] == "r18dev" and stored["code"] == "ABW-358" and stored["result"]["title"] == "x"
    assert stored["fetched_at"]
    assert snapshots.load("ABW-358", "r18dev") == {"id": "ABW-358", "title": "x"}
    assert snapshots.sources_for("ABW-358") == ["r18dev"]
    # 第 8 天过期：按文件 mtime 算。
    old = clock.now - TTL_SECONDS - 10
    os.utime(path, (old, old))
    assert snapshots.load("ABW-358", "r18dev") is None
    assert not snapshots.fresh_miss("ABW-358", "r18dev")


def test_snapshot_miss_memory(tmp_path: Path):
    clock = Clock()
    snapshots = Snapshots(tmp_path / "sources", now=clock)
    snapshots.save_miss("ABW-358", "javdb", "not_found", "javdb 没有这个番号")
    assert snapshots.fresh_miss("ABW-358", "javdb")
    assert snapshots.load("ABW-358", "javdb") is None
    stored = json.loads(snapshots.path("ABW-358", "javdb").read_text(encoding="utf-8"))
    assert stored["error"] == {"reason": "not_found", "message": "javdb 没有这个番号"}
    path = snapshots.path("ABW-358", "javdb")
    old = clock.now - TTL_SECONDS - 10
    os.utime(path, (old, old))
    assert not snapshots.fresh_miss("ABW-358", "javdb")
    # 后来有了结果，覆盖「没有」。
    snapshots.save_result("ABW-358", "javdb", {"id": "ABW-358"})
    assert not snapshots.fresh_miss("ABW-358", "javdb") and snapshots.load("ABW-358", "javdb")


def test_snapshot_forget_and_bad_file(tmp_path: Path):
    snapshots = Snapshots(tmp_path / "sources")
    snapshots.save_result("ABW-358", "r18dev", {})
    snapshots.save_miss("ABW-358", "javdb", "not_found")
    snapshots.save_result("ABW-359", "r18dev", {})
    assert snapshots.forget("ABW-358") == 2
    assert snapshots.sources_for("ABW-358") == [] and snapshots.sources_for("ABW-359") == ["r18dev"]
    snapshots.path("ABW-359", "r18dev").write_text("{broken", encoding="utf-8")
    assert snapshots.load("ABW-359", "r18dev") is None and not snapshots.fresh_miss("ABW-359", "r18dev")
