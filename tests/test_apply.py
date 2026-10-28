"""归位执行、附属文件留底、回滚与空目录清理。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from hidden_shelf import db
from hidden_shelf.config import ShelfConfig
from hidden_shelf.local_import import import_local
from hidden_shelf.organize import apply as apply_module
from hidden_shelf.organize.apply import (
    apply_plan,
    backup_database,
    organize,
    remove_empty_dirs,
    rollback_batch,
)
from hidden_shelf.organize.plan import SKIP_TARGET_EXISTS, build_plan
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scan import scan


@pytest.fixture
def disk(tmp_root: Path):
    (tmp_root / "a").mkdir()
    (tmp_root / "a" / "ABP-758.mp4").write_bytes(b"video-a")
    (tmp_root / "a" / "ABP-758.nfo").write_text("<movie><title>甲</title><studio>Prestige</studio></movie>", encoding="utf-8")
    Image.new("RGB", (30, 20), "red").save(tmp_root / "a" / "ABP-758-poster.jpg")
    (tmp_root / "a" / ".DS_Store").write_bytes(b"ds")
    (tmp_root / "b").mkdir()
    (tmp_root / "b" / "259LUXU-1475-cd1.mp4").write_bytes(b"cd1")
    (tmp_root / "b" / "259LUXU-1475-cd2.mp4").write_bytes(b"cd2")
    (tmp_root / "c" / "deep").mkdir(parents=True)
    (tmp_root / "c" / "deep" / "随手拍.mp4").write_bytes(b"home")
    (tmp_root / "c" / "deep" / "随手拍.jpg").write_bytes(b"cover")
    (tmp_root / "c" / "deep" / "随手拍.srt").write_bytes(b"sub")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    scan(connection, paths, ShelfConfig())
    import_local(connection, paths)
    yield tmp_root, paths, connection
    connection.close()


def _paths(connection):
    return {row["id"]: row["path"] for row in connection.execute("SELECT id,path FROM asset ORDER BY id")}


def test_apply_moves_and_updates_db(disk):
    root, paths, connection = disk
    plan = build_plan(connection, paths, ShelfConfig())
    result = apply_plan(connection, paths, plan)
    assert result.moved == 4 and result.failed == 0 and result.skipped == 0
    assert (root / "Prestige" / "ABP-758" / "ABP-758.mp4").read_bytes() == b"video-a"
    assert (root / "_未知厂牌" / "259LUXU-1475" / "259LUXU-1475-cd1.mp4").read_bytes() == b"cd1"
    assert (root / "_未知厂牌" / "259LUXU-1475" / "259LUXU-1475-cd2.mp4").read_bytes() == b"cd2"
    assert (root / "未识别" / "c" / "deep" / "随手拍.mp4").read_bytes() == b"home"
    assert set(_paths(connection).values()) == {
        "Prestige/ABP-758/ABP-758.mp4", "_未知厂牌/259LUXU-1475/259LUXU-1475-cd1.mp4",
        "_未知厂牌/259LUXU-1475/259LUXU-1475-cd2.mp4", "未识别/c/deep/随手拍.mp4"}
    row = connection.execute("SELECT name FROM asset WHERE path='Prestige/ABP-758/ABP-758.mp4'").fetchone()
    assert row["name"] == "ABP-758.mp4"
    assert result.batch_log and result.batch_log.is_file()
    entries = [json.loads(line) for line in result.batch_log.read_text(encoding="utf-8").splitlines()]
    assert {e["kind"] for e in entries} == {"asset", "sidecar"}
    assert all(e["ok"] for e in entries)


def test_apply_backup_created(disk):
    root, paths, connection = disk
    apply_plan(connection, paths, build_plan(connection, paths, ShelfConfig()))
    backups = list(paths.backups.glob("shelf-*.db"))
    assert len(backups) == 1
    import sqlite3
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("SELECT count(*) FROM asset").fetchone()[0] == 4


def test_backup_keeps_last_five(disk):
    root, paths, connection = disk
    paths.ensure()
    for index in range(7):
        (paths.backups / f"shelf-2000010{index}-000000.db").write_bytes(b"old")
    backup_database(paths, connection)
    remaining = sorted(path.name for path in paths.backups.glob("shelf-*.db"))
    assert len(remaining) == 5
    assert "shelf-20000100-000000.db" not in remaining and "shelf-20000101-000000.db" not in remaining


def test_apply_target_exists_not_overwritten(disk):
    root, paths, connection = disk
    plan = build_plan(connection, paths, ShelfConfig())
    # 计划算好之后、执行之前，有人在目标位置放了另一个文件。
    (root / "Prestige" / "ABP-758").mkdir(parents=True)
    (root / "Prestige" / "ABP-758" / "ABP-758.mp4").write_bytes(b"stranger")
    result = apply_plan(connection, paths, plan)
    assert result.skipped == 1 and result.moved == 3 and result.failed == 0
    assert (root / "Prestige" / "ABP-758" / "ABP-758.mp4").read_bytes() == b"stranger"
    assert (root / "a" / "ABP-758.mp4").read_bytes() == b"video-a"
    assert "a/ABP-758.mp4" in _paths(connection).values()
    entries = [json.loads(line) for line in result.batch_log.read_text(encoding="utf-8").splitlines()]
    assert any(e.get("error") == SKIP_TARGET_EXISTS for e in entries)


def test_apply_sidecars_go_to_legacy(disk):
    root, paths, connection = disk
    apply_plan(connection, paths, build_plan(connection, paths, ShelfConfig()))
    legacy = paths.legacy / "ABP-758"
    assert (legacy / "ABP-758.nfo").is_file()
    assert (legacy / "ABP-758-poster.jpg").is_file()
    assert not any(path.suffix in (".jpg", ".nfo") for path in (root / "Prestige").rglob("*"))
    rows = {r["path"]: r for r in connection.execute("SELECT path,status,moved_to FROM sidecar")}
    assert rows["a/ABP-758.nfo"]["status"] == "moved"
    assert rows["a/ABP-758.nfo"]["moved_to"] == ".shelf/legacy/ABP-758/ABP-758.nfo"
    assert rows["a/ABP-758-poster.jpg"]["moved_to"] == ".shelf/legacy/ABP-758/ABP-758-poster.jpg"
    # 导入的封面还在。
    assert (paths.covers / "ABP-758.jpg").is_file()


def test_apply_unrecognized_moves_with_sidecars(disk):
    root, paths, connection = disk
    apply_plan(connection, paths, build_plan(connection, paths, ShelfConfig()))
    target_dir = root / "未识别" / "c" / "deep"
    assert (target_dir / "随手拍.mp4").is_file()
    assert (target_dir / "随手拍.jpg").read_bytes() == b"cover"
    assert (target_dir / "随手拍.srt").read_bytes() == b"sub"
    # 原目录里不再有文件（空目录由 organize 的清理步骤删）。
    assert not any(path.is_file() for path in (root / "c").rglob("*"))


def test_apply_db_failure_renames_back(disk, monkeypatch):
    root, paths, connection = disk

    def boom(*args, **kwargs):
        raise RuntimeError("库挂了")

    monkeypatch.setattr(apply_module, "_update_row", boom)
    result = apply_plan(connection, paths, build_plan(connection, paths, ShelfConfig()))
    assert result.failed == 4 and result.moved == 0
    assert (root / "a" / "ABP-758.mp4").read_bytes() == b"video-a"
    assert not (root / "Prestige").exists() or not (root / "Prestige" / "ABP-758" / "ABP-758.mp4").exists()
    assert "a/ABP-758.mp4" in _paths(connection).values()
    # 附属文件没动。
    assert (root / "a" / "ABP-758.nfo").is_file()


def test_remove_empty_dirs(disk):
    root, paths, connection = disk
    apply_plan(connection, paths, build_plan(connection, paths, ShelfConfig()))
    (root / "empty" / "nested").mkdir(parents=True)
    (root / "未识别" / "stays").mkdir(parents=True)
    paths.ensure()
    removed = remove_empty_dirs(root)
    # a（只剩 .DS_Store）、b、c/deep、c、empty/nested、empty、未识别/stays
    assert removed == 7
    for name in ("a", "b", "c", "empty"):
        assert not (root / name).exists(), name
    # `未识别/` 本身不删，它下面的空目录照删。
    assert (root / "未识别").is_dir() and not (root / "未识别" / "stays").exists()
    assert paths.sources.is_dir()  # .shelf 下的空目录不动
    assert root.is_dir()


def test_rollback_restores(disk):
    root, paths, connection = disk
    result = apply_plan(connection, paths, build_plan(connection, paths, ShelfConfig()))
    restored = rollback_batch(connection, paths, result.batch_log)
    assert restored == len(result.batch_log.read_text(encoding="utf-8").splitlines())
    assert (root / "a" / "ABP-758.mp4").read_bytes() == b"video-a"
    assert (root / "a" / "ABP-758.nfo").is_file()
    assert (root / "a" / "ABP-758-poster.jpg").is_file()
    assert (root / "c" / "deep" / "随手拍.mp4").is_file()
    assert set(_paths(connection).values()) == {
        "a/ABP-758.mp4", "b/259LUXU-1475-cd1.mp4", "b/259LUXU-1475-cd2.mp4", "c/deep/随手拍.mp4"}
    assert connection.execute("SELECT count(*) FROM sidecar WHERE status='moved'").fetchone()[0] == 0
    assert not (paths.legacy / "ABP-758" / "ABP-758.nfo").exists()


def test_second_run_no_moves(disk):
    root, paths, connection = disk
    first = organize(connection, paths, ShelfConfig())
    assert first.moved == 4
    scan(connection, paths, ShelfConfig())
    second = organize(connection, paths, ShelfConfig())
    assert second.moved == 0 and second.failed == 0
    assert (root / "Prestige" / "ABP-758" / "ABP-758.mp4").read_bytes() == b"video-a"
    batches = connection.execute("SELECT status,moved FROM organize_batch ORDER BY id").fetchall()
    assert [(b["status"], b["moved"]) for b in batches] == [("ok", 4), ("ok", 0)]
    # 第一次 organize 把空目录清掉了。
    assert not (root / "a").exists() and not (root / "b").exists()


def test_organize_reports_progress(disk):
    root, paths, connection = disk
    messages: list[str] = []
    organize(connection, paths, ShelfConfig(), progress=messages.append)
    assert any("归位完成" in message for message in messages)
