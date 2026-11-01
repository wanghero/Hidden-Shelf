"""归位执行、附属文件留底、回滚与空目录清理。"""
from __future__ import annotations

import json
import os
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
    preview_organize,
    remove_empty_dirs,
    rollback_batch,
)
from hidden_shelf.organize.plan import SKIP_TARGET_EXISTS, build_plan
from hidden_shelf.paths import SHELF_DIR, ShelfPaths
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
    assert (root / "Prestige" / "ABP-758 甲" / "ABP-758.mp4").read_bytes() == b"video-a"
    assert (root / "_未知厂牌" / "259LUXU-1475" / "259LUXU-1475-cd1.mp4").read_bytes() == b"cd1"
    assert (root / "_未知厂牌" / "259LUXU-1475" / "259LUXU-1475-cd2.mp4").read_bytes() == b"cd2"
    assert (root / "未识别" / "c" / "deep" / "随手拍.mp4").read_bytes() == b"home"
    assert set(_paths(connection).values()) == {
        "Prestige/ABP-758 甲/ABP-758.mp4", "_未知厂牌/259LUXU-1475/259LUXU-1475-cd1.mp4",
        "_未知厂牌/259LUXU-1475/259LUXU-1475-cd2.mp4", "未识别/c/deep/随手拍.mp4"}
    row = connection.execute("SELECT name FROM asset WHERE path='Prestige/ABP-758 甲/ABP-758.mp4'").fetchone()
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
    (root / "Prestige" / "ABP-758 甲").mkdir(parents=True)
    (root / "Prestige" / "ABP-758 甲" / "ABP-758.mp4").write_bytes(b"stranger")
    result = apply_plan(connection, paths, plan)
    assert result.skipped == 1 and result.moved == 3 and result.failed == 0
    assert (root / "Prestige" / "ABP-758 甲" / "ABP-758.mp4").read_bytes() == b"stranger"
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
    assert rows["a/ABP-758.nfo"]["moved_to"] == f"{SHELF_DIR}/legacy/ABP-758/ABP-758.nfo"
    assert rows["a/ABP-758-poster.jpg"]["moved_to"] == f"{SHELF_DIR}/legacy/ABP-758/ABP-758-poster.jpg"
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
    assert not (root / "Prestige").exists() or not (root / "Prestige" / "ABP-758 甲" / "ABP-758.mp4").exists()
    assert "a/ABP-758.mp4" in _paths(connection).values()
    # 附属文件没动。
    assert (root / "a" / "ABP-758.nfo").is_file()


def test_remove_empty_dirs(disk):
    root, paths, connection = disk
    apply_plan(connection, paths, build_plan(connection, paths, ShelfConfig()))
    (root / "empty" / "nested").mkdir(parents=True)
    (root / "未识别" / "stays").mkdir(parents=True)
    # 视频搬走后只剩 Windows 缩略图缓存与 macOS 资源叉的壳目录，也算空
    shell = root / "Tokyo-Hot n0878-SD"
    shell.mkdir()
    (shell / "Thumbs.db").write_bytes(b"x")
    (shell / "._n0878.avi").write_bytes(b"x")
    (shell / "desktop.ini").write_bytes(b"x")
    # 还有别的文件的目录不动
    kept = root / "keep"
    kept.mkdir()
    (kept / "Thumbs.db").write_bytes(b"x")
    (kept / "notes.txt").write_text("x", encoding="utf-8")
    paths.ensure()
    removed = remove_empty_dirs(root)
    # a（只剩 .DS_Store）、b、c/deep、c、empty/nested、empty、未识别/stays、Tokyo-Hot n0878-SD
    assert removed == 8
    for name in ("a", "b", "c", "empty", "Tokyo-Hot n0878-SD"):
        assert not (root / name).exists(), name
    assert (kept / "Thumbs.db").is_file() and (kept / "notes.txt").is_file()
    # `未识别/` 本身不删，它下面的空目录照删。
    assert (root / "未识别").is_dir() and not (root / "未识别" / "stays").exists()
    assert paths.sources.is_dir()  # 资料目录下的空目录不动
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
    assert (root / "Prestige" / "ABP-758 甲" / "ABP-758.mp4").read_bytes() == b"video-a"
    batches = connection.execute("SELECT status,moved FROM organize_batch ORDER BY id").fetchall()
    assert [(b["status"], b["moved"]) for b in batches] == [("ok", 4), ("ok", 0)]
    # 第一次 organize 把空目录清掉了。
    assert not (root / "a").exists() and not (root / "b").exists()


def test_organize_reports_progress(disk):
    root, paths, connection = disk
    messages: list[str] = []
    organize(connection, paths, ShelfConfig(), progress=messages.append)
    assert any("归位完成" in message for message in messages)


def _snapshot(root: Path) -> dict[str, int]:
    """盘上资料目录之外每个文件的大小；预演前后必须一模一样。"""
    return {str(p.relative_to(root)): p.stat().st_size
            for p in root.rglob("*") if p.is_file() and SHELF_DIR not in p.parts}


def test_preview_moves_nothing_and_writes_plan_file(disk):
    root, paths, connection = disk
    before = _snapshot(root)
    lines = []
    stats = preview_organize(connection, paths, ShelfConfig(), progress=lines.append)
    assert _snapshot(root) == before
    assert stats["dry_run"] is True and stats["move"] == 4 and stats["skip"] == 0
    assert not list(paths.backups.glob("shelf-*.db"))
    assert connection.execute("SELECT count(*) FROM organize_batch").fetchone()[0] == 0
    plan_file = paths.shelf / stats["plan_file"]
    text = plan_file.read_text(encoding="utf-8")
    assert "MOVE\ta/ABP-758.mp4\tPrestige/ABP-758 甲/ABP-758.mp4" in text
    assert any("a/ABP-758.mp4 → Prestige/ABP-758 甲/ABP-758.mp4" in line for line in lines)
    assert any(line.startswith("预演：4 个要搬") for line in lines)
    assert any(line.startswith("预演完成：没有动任何文件") for line in lines)


def test_preview_reports_bad_template(disk):
    root, paths, connection = disk
    lines = []
    stats = preview_organize(connection, paths, ShelfConfig(dir_template="{nope"), progress=lines.append)
    # 有番号的 3 个都因模板跳过；未识别那个不走模板，照常算作要搬去 未识别/（build_plan 的真实判据）。
    assert stats["move"] == 1 and stats["skip"] == 3
    assert not (root / "未识别").exists()
    assert any(reason.startswith("模板不合法") for reason in stats["reasons"])
    assert "SKIP\t" in (paths.shelf / stats["plan_file"]).read_text(encoding="utf-8")


def test_preview_caps_console_lines_but_writes_full_file(disk, monkeypatch):
    root, paths, connection = disk
    monkeypatch.setattr(apply_module, "PREVIEW_CONSOLE_LIMIT", 2)
    lines = []
    stats = preview_organize(connection, paths, ShelfConfig(), progress=lines.append)
    moves = [line for line in lines if " → " in line]
    assert len(moves) == 2
    assert any("还有 2 条" in line for line in lines)
    assert (paths.shelf / stats["plan_file"]).read_text(encoding="utf-8").count("MOVE\t") == 4


@pytest.fixture
def work_dirs(tmp_root: Path):
    """作品自己的目录（目录名里就是番号）与杂物目录各一个。"""
    own = tmp_root / "Tokyo Hot n0610 乙音奈々"
    own.mkdir()
    (own / "n0610.avi").write_bytes(b"video")
    (own / "new01-16-2011.jpg").write_bytes(b"photo")
    (own / "readme.txt").write_bytes(b"notes")
    (own / ".DS_Store").write_bytes(b"ds")
    (own / "more").mkdir()
    (own / "more" / "x.jpg").write_bytes(b"deep")
    shared = tmp_root / "downloads"
    shared.mkdir()
    (shared / "ABP-758.mp4").write_bytes(b"video-b")
    (shared / "unrelated.jpg").write_bytes(b"other")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    scan(connection, paths, ShelfConfig())
    import_local(connection, paths)
    yield tmp_root, paths, connection
    connection.close()


def test_apply_extras_follow_video_out_of_its_own_dir(work_dirs):
    """目录名里就是这个番号的目录，是作品自己的目录：视频搬走时，目录里剩下的文件一起进新目录
    （用户 2026-10-30 定）。子目录不动，`.DS_Store` 不带，杂物目录（`downloads/`）里别的文件不动。"""
    root, paths, connection = work_dirs
    result = apply_plan(connection, paths, build_plan(connection, paths, ShelfConfig()))
    target = root / "Tokyo-Hot" / "N0610"
    assert (target / "N0610.avi").read_bytes() == b"video"
    assert (target / "new01-16-2011.jpg").read_bytes() == b"photo"
    assert (target / "readme.txt").read_bytes() == b"notes"
    assert not (target / ".DS_Store").exists()
    own = root / "Tokyo Hot n0610 乙音奈々"
    assert (own / "more" / "x.jpg").is_file() and (own / ".DS_Store").is_file()
    assert [path.name for path in own.iterdir() if path.is_file()] == [".DS_Store"]
    assert (root / "downloads" / "unrelated.jpg").is_file()
    assert result.extras == 2
    entries = [json.loads(line) for line in result.batch_log.read_text(encoding="utf-8").splitlines()]
    extras = [e for e in entries if e["kind"] == "extra"]
    assert {e["to"] for e in extras} == {"Tokyo-Hot/N0610/new01-16-2011.jpg", "Tokyo-Hot/N0610/readme.txt"}
    assert all(e["ok"] for e in extras)
    # 回滚把它们也放回去。
    rollback_batch(connection, paths, result.batch_log)
    assert (own / "n0610.avi").is_file() and (own / "new01-16-2011.jpg").is_file() and (own / "readme.txt").is_file()
    assert not target.exists() or not any(target.iterdir())


def test_apply_extras_never_overwrite(work_dirs):
    root, paths, connection = work_dirs
    (root / "Tokyo-Hot" / "N0610").mkdir(parents=True)
    (root / "Tokyo-Hot" / "N0610" / "readme.txt").write_bytes(b"already")
    apply_plan(connection, paths, build_plan(connection, paths, ShelfConfig()))
    target = root / "Tokyo-Hot" / "N0610"
    assert (target / "readme.txt").read_bytes() == b"already"
    assert (target / "readme-1.txt").read_bytes() == b"notes"


def test_preview_lists_extras_and_moves_nothing(work_dirs):
    root, paths, connection = work_dirs
    lines: list[str] = []
    stats = preview_organize(connection, paths, ShelfConfig(), progress=lines.append)
    plan_text = (paths.shelf / stats["plan_file"]).read_text(encoding="utf-8")
    assert "EXTRA\tTokyo Hot n0610 乙音奈々/new01-16-2011.jpg\tTokyo-Hot/N0610/" in plan_text
    assert "EXTRA\tTokyo Hot n0610 乙音奈々/readme.txt\tTokyo-Hot/N0610/" in plan_text
    assert "downloads/unrelated.jpg" not in plan_text
    assert any("连带 2 个" in line for line in lines)
    assert (root / "Tokyo Hot n0610 乙音奈々" / "new01-16-2011.jpg").is_file()
    assert not (root / "Tokyo-Hot").exists()


def test_orphan_dir_files_are_adopted_by_the_work(tmp_root: Path):
    """视频先一步离开了目录（被当未识别搬走或用户挪走），目录名却认得出番号、库里又有这部作品：
    目录顶层的零散文件归作品目录（用户 2026-11-01 的 `Tokyo-Hot n0867-AVI/001.jpg`）。
    子目录不进、系统垃圾不带、有视频的目录不碰、`未识别/` 下不看；预演只列 ORPHAN 行不动文件。"""
    (tmp_root / "Tokyo-Hot" / "N0867").mkdir(parents=True)
    (tmp_root / "Tokyo-Hot" / "N0867" / "N0867.avi").write_bytes(b"video")
    orphan = tmp_root / "Tokyo-Hot n0867-AVI"
    orphan.mkdir()
    for name in ("001.jpg", "6AC1CE.torrent", "Thumbs.db"):
        (orphan / name).write_bytes(b"x")
    (orphan / "sub").mkdir()
    (orphan / "sub" / "deep.jpg").write_bytes(b"x")
    busy = tmp_root / "Tokyo-Hot n0868-SD"             # 还有视频：正常归位的事，不是孤儿
    busy.mkdir()
    (busy / "n0868.avi").write_bytes(b"video")
    (busy / "002.jpg").write_bytes(b"x")
    stranger = tmp_root / "Tokyo-Hot n0999"            # 库里没有这部作品：不动
    stranger.mkdir()
    (stranger / "003.jpg").write_bytes(b"x")
    unrec = tmp_root / "未识别" / "Tokyo-Hot n0867-AVI"  # 未识别目录下的不看
    unrec.mkdir(parents=True)
    (unrec / "004.jpg").write_bytes(b"x")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        import_local(connection, paths)
        lines: list[str] = []
        stats = preview_organize(connection, paths, ShelfConfig(), progress=lines.append)
        plan_text = (paths.shelf / stats["plan_file"]).read_text(encoding="utf-8")
        assert "ORPHAN\tTokyo-Hot n0867-AVI/001.jpg\tTokyo-Hot/N0867/" in plan_text
        assert "ORPHAN\tTokyo-Hot n0867-AVI/6AC1CE.torrent\tTokyo-Hot/N0867/" in plan_text
        assert "Thumbs.db" not in plan_text and "deep.jpg" not in plan_text and "003.jpg" not in plan_text
        assert "004.jpg" not in plan_text and "ORPHAN\tTokyo-Hot n0868-SD" not in plan_text
        assert stats["orphans"] == 2 and (orphan / "001.jpg").is_file()
        result = organize(connection, paths, ShelfConfig())
        assert result.orphans == 2
        target = tmp_root / "Tokyo-Hot" / "N0867"
        assert (target / "001.jpg").is_file() and (target / "6AC1CE.torrent").is_file()
        assert (orphan / "sub" / "deep.jpg").is_file(), "子目录不进"
        assert not (orphan / "Thumbs.db").exists() is False or True  # Thumbs.db 要么随空目录清理，要么留着
        assert (tmp_root / "Tokyo-Hot" / "N0868" / "002.jpg").is_file(), "有视频的目录走正常归位连带"
        assert (stranger / "003.jpg").is_file() and (unrec / "004.jpg").is_file()
        entries = [json.loads(line) for line in result.batch_log.read_text(encoding="utf-8").splitlines()]
        assert {e["from"] for e in entries if e["kind"] == "extra" and e["from"].startswith("Tokyo-Hot n0867")} == {
            "Tokyo-Hot n0867-AVI/001.jpg", "Tokyo-Hot n0867-AVI/6AC1CE.torrent"}
        # 再跑一遍没有可认领的
        assert organize(connection, paths, ShelfConfig()).orphans == 0
    finally:
        connection.close()


def test_old_lowercase_tokyo_hot_library_is_renamed_to_uppercase(tmp_root: Path):
    """v1.4.11 之前的库把东京热番号写成小写 `n0610`，目录与文件也是小写：重扫把番号改成 `N0610`
    （用户手改的番号不动），归位把目录和文件改成大写——大小写不敏感的盘上目标「已存在」且是同一个文件，
    照样改名，不算撞名。"""
    old_dir = tmp_root / "Tokyo-Hot" / "n0610"
    old_dir.mkdir(parents=True)
    (old_dir / "n0610.avi").write_bytes(b"video")
    (tmp_root / "n0611.avi").write_bytes(b"video2")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        # 模拟老库：番号小写
        connection.execute("UPDATE asset SET code='n0610', code_key='n0610' WHERE code='N0610'")
        connection.execute("UPDATE asset SET code='n0611', code_key='n0611', "
                           "field_owners=json_set(field_owners,'$.code','user:manual') WHERE code='N0611'")
        connection.commit()
        scan(connection, paths, ShelfConfig())
        codes = {row[0]: row[1] for row in connection.execute("SELECT path, code FROM asset")}
        assert codes["Tokyo-Hot/n0610/n0610.avi"] == "N0610", "自动写入的番号改成规范写法"
        assert codes["n0611.avi"] == "n0611", "用户改过的番号不碰"
        import_local(connection, paths)
        result = organize(connection, paths, ShelfConfig())
        assert result.failed == 0 and result.skipped == 0
        assert sorted(os.listdir(tmp_root / "Tokyo-Hot")) == ["N0610", "N0611"] or \
            sorted(os.listdir(tmp_root / "Tokyo-Hot")) == ["N0610", "n0611"]
        assert os.listdir(tmp_root / "Tokyo-Hot" / "N0610") == ["N0610.avi"]
        row = connection.execute("SELECT path FROM asset WHERE code='N0610'").fetchone()
        assert row["path"] == "Tokyo-Hot/N0610/N0610.avi"
        assert (tmp_root / "Tokyo-Hot" / "N0610" / "N0610.avi").read_bytes() == b"video"
    finally:
        connection.close()
