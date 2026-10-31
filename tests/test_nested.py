"""计划 10：母目录再跑时合并子目录里的旧库。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from hidden_shelf import db, pipeline
from hidden_shelf.config import ShelfConfig
from hidden_shelf.entities import names_for
from hidden_shelf.field_owners import owner_of, write_owned_fields, FieldWrite
from hidden_shelf.local_import import import_local
from hidden_shelf.nested import NESTED_LEGACY_DIR, find_nested_libraries, merge_nested_libraries
from hidden_shelf.paths import SHELF_DIR, ShelfPaths
from hidden_shelf.scan import scan
from hidden_shelf.scrape.apply import should_scrape


def _child_library(root: Path, fake_video) -> Path:
    """在 `root/child/` 造一块跑过（离线）的子盘：两部作品、封面来自本地图片、资料来自 overrides.json。"""
    child = root / "child"
    fake_video(child / "inbox" / "ABP-758.mp4")
    fake_video(child / "inbox" / "SSNI-100.mp4")
    Image.new("RGB", (800, 538), "blue").save(child / "inbox" / "ABP-758-cover.jpg")
    shelf = child / SHELF_DIR
    shelf.mkdir()
    (shelf / "overrides.json").write_text(json.dumps({
        "ABP-758": {"title": "子库标题", "studio": "Prestige", "series": "系列甲", "release_date": "2019-05-10",
                     "performers": ["甲", "乙"], "tags": ["巨乳"]},
        "SSNI-100": {"title": "第二部", "studio": "S1", "performers": ["丙"]},
    }, ensure_ascii=False), encoding="utf-8")
    result = pipeline.run(child, config=ShelfConfig(), steps=("scan", "import", "organize", "media", "build"))
    assert result.ok, result.error
    assert (child / "index.html").is_file()
    # 模拟联网刮削留下的痕迹：问过的时间、快照文件、艺人头像
    connection = db.connect(ShelfPaths(child))
    connection.execute("UPDATE asset SET scraped_at='2026-10-30T00:00:00+00:00' WHERE code='ABP-758'")
    row = connection.execute("SELECT id FROM entity WHERE kind='performer' AND canonical_name='甲'").fetchone()
    (shelf / "avatars").mkdir(exist_ok=True)
    Image.new("RGB", (100, 100), "green").save(shelf / "avatars" / f"{row['id']}.jpg")
    connection.execute("UPDATE entity SET avatar_file=? WHERE id=?", (f"avatars/{row['id']}.jpg", row["id"]))
    connection.commit()
    connection.close()
    (shelf / "sources" / "ABP-758-javdb.json").write_text("{}", encoding="utf-8")
    return child


@pytest.fixture
def parent(tmp_root: Path, fake_video):
    child = _child_library(tmp_root, fake_video)
    paths = ShelfPaths(tmp_root)
    paths.ensure()
    connection = db.connect(paths)
    scan(connection, paths, ShelfConfig())
    yield tmp_root, child, paths, connection
    connection.close()


def _asset(connection, code: str):
    return connection.execute("SELECT * FROM asset WHERE code=?", (code,)).fetchone()


def test_find_nested_libraries_skips_root_and_data_dirs(tmp_root: Path):
    (tmp_root / SHELF_DIR).mkdir()
    (tmp_root / SHELF_DIR / "shelf.db").write_bytes(b"")
    (tmp_root / "a" / SHELF_DIR).mkdir(parents=True)
    (tmp_root / "a" / SHELF_DIR / "shelf.db").write_bytes(b"")
    (tmp_root / "b" / SHELF_DIR).mkdir(parents=True)                      # 没有 shelf.db：不算库
    (tmp_root / "@eaDir" / "c" / SHELF_DIR).mkdir(parents=True)             # 系统目录：不进
    (tmp_root / "@eaDir" / "c" / SHELF_DIR / "shelf.db").write_bytes(b"")
    assert find_nested_libraries(tmp_root) == [tmp_root / "a"]


def test_merge_carries_fields_entities_cover_and_scraped_at(parent):
    root, child, paths, connection = parent
    result = merge_nested_libraries(connection, paths, progress=lambda m: None)
    assert result.libraries == 1 and result.assets == 2 and result.skipped == 0
    row = _asset(connection, "ABP-758")
    assert row["title"] == "子库标题" and row["studio"] == "Prestige" and row["release_date"] == "2019-05-10"
    assert owner_of(row["field_owners"], "title") == "user:manual", "归属原样带过来"
    assert names_for(connection, row["id"], "performer") == ["甲", "乙"]
    assert names_for(connection, row["id"], "tag") == ["巨乳"]
    assert row["series"] == "系列甲"
    assert row["cover_file"] == "covers/ABP-758.jpg" and paths.shelf_absolute(row["cover_file"]).is_file()
    assert owner_of(row["field_owners"], "cover_file") == "auto:local"
    assert row["scraped_at"] == "2026-10-30T00:00:00+00:00"
    assert row["probed_at"] is not None and row["duration"], "探测结果一并带过来，媒体步不用再 ffprobe"
    # 不再要求重刮：标题/厂牌/艺人/标签/封面都齐了
    full = dict(row)
    full["performer_count"], full["tag_count"] = 2, 1
    assert should_scrape(full) == (False, [])
    # 头像与快照
    performer = connection.execute("SELECT * FROM entity WHERE kind='performer' AND canonical_name='甲'").fetchone()
    assert performer["avatar_file"] == f"avatars/{performer['id']}.jpg"
    assert paths.shelf_absolute(performer["avatar_file"]).is_file()
    assert (paths.sources / "ABP-758-javdb.json").is_file()
    assert result.images == 6 and result.avatars == 1 and result.snapshots == 1


def test_merge_does_not_override_parent_values(parent):
    root, child, paths, connection = parent
    row = _asset(connection, "ABP-758")
    write_owned_fields(connection, "asset", row["id"], [FieldWrite("title", "母库标题", "auto:javdb")])
    merge_nested_libraries(connection, paths, progress=lambda m: None)
    row = _asset(connection, "ABP-758")
    assert row["title"] == "母库标题", "母库已有的值不动"
    assert owner_of(row["field_owners"], "title") == "auto:javdb"
    assert row["studio"] == "Prestige", "母库空着的字段照常补"


def test_merge_moves_child_library_and_is_idempotent(parent):
    root, child, paths, connection = parent
    first = merge_nested_libraries(connection, paths, progress=lambda m: None)
    assert first.moved == 1
    assert not (child / SHELF_DIR).exists() and not (child / "index.html").exists()
    kept = paths.legacy / NESTED_LEGACY_DIR / "child"
    assert (kept / SHELF_DIR / "shelf.db").is_file() and (kept / "index.html").is_file()
    second = merge_nested_libraries(connection, paths, progress=lambda m: None)
    assert second.libraries == 0


def test_merge_dry_run_keeps_child_in_place(parent):
    root, child, paths, connection = parent
    result = merge_nested_libraries(connection, paths, progress=lambda m: None, move=False)
    assert result.assets == 2 and result.moved == 0
    assert (child / SHELF_DIR / "shelf.db").is_file() and (child / "index.html").is_file()
    assert _asset(connection, "ABP-758")["title"] == "子库标题"


def test_merge_skips_broken_child_db(tmp_root: Path, fake_video):
    child = tmp_root / "child"
    fake_video(child / "ABP-758.mp4")
    (child / SHELF_DIR).mkdir()
    (child / SHELF_DIR / "shelf.db").write_bytes(b"not a database")
    paths = ShelfPaths(tmp_root)
    paths.ensure()
    connection = db.connect(paths)
    scan(connection, paths, ShelfConfig())
    messages: list[str] = []
    result = merge_nested_libraries(connection, paths, progress=messages.append)
    assert result.libraries == 1 and result.skipped == 1 and result.moved == 0
    assert (child / SHELF_DIR / "shelf.db").is_file()
    assert any("child" in m and "跳过" in m for m in messages)
    connection.close()


def test_import_local_merges_nested_and_pipeline_dry_run_keeps_it(parent):
    root, child, paths, connection = parent
    result = import_local(connection, paths, progress=lambda m: None, move_nested=False)
    assert result.nested["libraries"] == 1 and result.nested["moved"] == 0
    assert (child / SHELF_DIR).is_dir()
    result = import_local(connection, paths, progress=lambda m: None)
    assert result.nested["moved"] == 1
    assert not (child / SHELF_DIR).exists()
