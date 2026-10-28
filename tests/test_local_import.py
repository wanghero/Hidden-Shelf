"""本地 NFO、封面与用户覆盖的导入。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from hidden_shelf import db
from hidden_shelf.config import ShelfConfig
from hidden_shelf.entities import names_for
from hidden_shelf.field_owners import owner_of
from hidden_shelf.local_import import apply_overrides, import_local
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scan import scan

NFO = """<movie>
  <title>标题甲</title>
  <num>ABP-758</num>
  <studio>Prestige</studio>
  <set><name>系列一</name></set>
  <premiered>2019-05-10</premiered>
  <plot>简介</plot>
  <actor><name>甲</name></actor>
  <actor><name>乙</name></actor>
  <genre>巨乳</genre>
  <tag>中文字幕</tag>
</movie>
"""


def _write_nfo(path: Path, title: str = "标题甲") -> None:
    path.write_text(NFO.replace("标题甲", title), encoding="utf-8")


@pytest.fixture
def disk(tmp_root: Path):
    (tmp_root / "a").mkdir()
    (tmp_root / "a" / "ABP-758.mp4").write_bytes(b"0" * 16)
    _write_nfo(tmp_root / "a" / "ABP-758.nfo")
    Image.new("RGB", (300, 200), "red").save(tmp_root / "a" / "ABP-758-poster.jpg")
    (tmp_root / "b").mkdir()
    (tmp_root / "b" / "259LUXU-1475-cd1.mp4").write_bytes(b"0")
    (tmp_root / "b" / "259LUXU-1475-cd2.mp4").write_bytes(b"0")
    (tmp_root / "b" / "259LUXU-1475.nfo").write_text(
        "<movie><title>多碟</title><studio>MGS</studio><actor><name>丙</name></actor></movie>", encoding="utf-8")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    scan(connection, paths, ShelfConfig())
    yield tmp_root, paths, connection
    connection.close()


def _asset(connection, path):
    return connection.execute("SELECT * FROM asset WHERE path=?", (path,)).fetchone()


def test_import_nfo_fields_and_performers(disk):
    root, paths, connection = disk
    result = import_local(connection, paths)
    assert result.nfo == 2
    row = _asset(connection, "a/ABP-758.mp4")
    assert (row["title"], row["studio"], row["series"], row["release_date"], row["plot"]) == (
        "标题甲", "Prestige", "系列一", "2019-05-10", "简介")
    assert owner_of(row["field_owners"], "title") == "auto:nfo"
    performers = connection.execute(
        "SELECT e.canonical_name, ae.source FROM asset_entity ae JOIN entity e ON e.id=ae.entity_id "
        "WHERE ae.asset_id=? AND ae.role='performer' ORDER BY ae.rowid", (row["id"],)).fetchall()
    assert [(p[0], p[1]) for p in performers] == [("甲", "nfo"), ("乙", "nfo")]
    assert connection.execute("SELECT count(*) FROM entity WHERE kind='performer'").fetchone()[0] == 3
    assert names_for(connection, row["id"], "tag") == ["巨乳", "中文字幕"]
    assert connection.execute("SELECT count(*) FROM entity WHERE kind='studio' AND canonical_name='Prestige'").fetchone()[0] == 1
    assert connection.execute("SELECT status FROM sidecar WHERE path='a/ABP-758.nfo'").fetchone()[0] == "imported"


def test_shared_nfo_fills_all_parts(disk):
    root, paths, connection = disk
    import_local(connection, paths)
    for part in ("cd1", "cd2"):
        row = _asset(connection, f"b/259LUXU-1475-{part}.mp4")
        assert (row["title"], row["studio"]) == ("多碟", "MGS")
        assert names_for(connection, row["id"], "performer") == ["丙"]


def test_import_cover_copies_to_shelf(disk):
    root, paths, connection = disk
    result = import_local(connection, paths)
    assert result.covers == 1
    cover = paths.covers / "ABP-758.jpg"
    assert cover.is_file()
    with Image.open(cover) as image:
        assert image.size == (300, 200) and image.mode == "RGB"
    row = _asset(connection, "a/ABP-758.mp4")
    assert row["cover_file"] == "covers/ABP-758.jpg"
    assert owner_of(row["field_owners"], "cover_file") == "auto:local"
    assert connection.execute("SELECT status FROM sidecar WHERE path='a/ABP-758-poster.jpg'").fetchone()[0] == "imported"
    # 原图原地不动。
    assert (root / "a" / "ABP-758-poster.jpg").is_file()


def test_cover_priority_poster_over_cover_over_fanart(disk):
    root, paths, connection = disk
    Image.new("RGB", (10, 10), "blue").save(root / "a" / "ABP-758.jpg")
    Image.new("RGB", (20, 20), "green").save(root / "a" / "ABP-758-fanart.jpg")
    scan(connection, paths, ShelfConfig())
    import_local(connection, paths)
    with Image.open(paths.covers / "ABP-758.jpg") as image:
        assert image.size == (300, 200)  # poster 胜出
    statuses = {r[0]: r[1] for r in connection.execute("SELECT path,status FROM sidecar WHERE kind IN ('cover','poster','fanart')")}
    assert set(statuses.values()) == {"imported"}


def test_import_is_idempotent(disk):
    root, paths, connection = disk
    import_local(connection, paths)
    second = import_local(connection, paths)
    assert second.nfo == 0 and second.covers == 0
    assert connection.execute("SELECT count(*) FROM entity WHERE kind='performer'").fetchone()[0] == 3
    assert connection.execute("SELECT count(*) FROM asset_entity").fetchone()[0] == connection.execute(
        "SELECT count(*) FROM (SELECT DISTINCT asset_id,entity_id,role FROM asset_entity)").fetchone()[0]


def test_override_beats_nfo(disk):
    root, paths, connection = disk
    paths.ensure()
    paths.overrides.write_text(json.dumps({
        "abp758": {"title": "我的标题", "performers": ["丁"], "tags": ["收藏"]},
        "ZZZ-999": {"title": "找不到"},
    }, ensure_ascii=False), encoding="utf-8")
    result = import_local(connection, paths)
    assert result.overrides == 1
    row = _asset(connection, "a/ABP-758.mp4")
    assert row["title"] == "我的标题"
    assert row["studio"] == "Prestige"
    assert owner_of(row["field_owners"], "title") == "user:manual"
    assert names_for(connection, row["id"], "performer") == ["丁", "甲", "乙"]
    assert "收藏" in names_for(connection, row["id"], "tag")
    # 改 NFO 标题再导入：NFO 重新进入 pending 后也写不进。
    _write_nfo(root / "a" / "ABP-758.nfo", title="NFO 新标题")
    connection.execute("UPDATE sidecar SET status='pending' WHERE path='a/ABP-758.nfo'")
    import_local(connection, paths)
    assert _asset(connection, "a/ABP-758.mp4")["title"] == "我的标题"
    # 换一个用户演员：旧的 user 关联被替换，NFO 的保留。
    paths.overrides.write_text(json.dumps({"ABP-758": {"performers": ["戊"]}}, ensure_ascii=False), encoding="utf-8")
    assert apply_overrides(connection, paths) == 1
    assert names_for(connection, row["id"], "performer") == ["戊", "甲", "乙"]


def test_override_bad_json_is_skipped(disk):
    root, paths, connection = disk
    paths.ensure()
    paths.overrides.write_text("{broken", encoding="utf-8")
    assert apply_overrides(connection, paths) == 0


def test_bad_image_skipped(disk):
    root, paths, connection = disk
    (root / "a" / "ABP-758-poster.jpg").write_text("not an image", encoding="utf-8")
    messages: list[str] = []
    result = import_local(connection, paths, progress=messages.append)
    assert result.covers == 0
    assert not (paths.covers / "ABP-758.jpg").exists()
    assert _asset(connection, "a/ABP-758.mp4")["cover_file"] is None
    assert any("ABP-758-poster.jpg" in message for message in messages)


def test_bad_nfo_skipped(disk):
    root, paths, connection = disk
    (root / "a" / "ABP-758.nfo").write_text("<!DOCTYPE x><movie/>", encoding="utf-8")
    messages: list[str] = []
    result = import_local(connection, paths, progress=messages.append)
    assert result.nfo == 1  # b 目录那个仍然导入
    assert connection.execute("SELECT status FROM sidecar WHERE path='a/ABP-758.nfo'").fetchone()[0] == "failed"
    assert any("ABP-758.nfo" in message for message in messages)


def test_nfo_code_fills_blank_asset_code(tmp_root: Path):
    (tmp_root / "x").mkdir()
    (tmp_root / "x" / "movie.mp4").write_bytes(b"0")
    (tmp_root / "x" / "movie.nfo").write_text("<movie><num>ABW-358</num><title>t</title></movie>", encoding="utf-8")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    scan(connection, paths, ShelfConfig())
    import_local(connection, paths)
    row = _asset(connection, "x/movie.mp4")
    assert (row["code"], row["code_key"], row["content_type"]) == ("ABW-358", "ABW-358", "censored")
    connection.close()
