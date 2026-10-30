"""厂牌名规范写法：カリビアンコム → Caribbeancom（用户 2026-10-30 定），新写入与老库都要归一。"""
from __future__ import annotations

from pathlib import Path

import pytest

from hidden_shelf import db, entities
from hidden_shelf.config import ShelfConfig
from hidden_shelf.field_owners import USER_MANUAL, FieldWrite, owner_of, write_owned_fields
from hidden_shelf.local_import import import_local
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scan import scan
from hidden_shelf.scrape.settle import extract
from hidden_shelf.studios import canonical_studio, canonicalize_existing


@pytest.mark.parametrize("raw,expected", [
    ("カリビアンコム", "Caribbeancom"),
    ("  カリビアンコム ", "Caribbeancom"),
    ("ｶﾘﾋﾞｱﾝｺﾑ", "Caribbeancom"),           # 半角片假名，NFKC 后同一个键
    ("carib", "Caribbeancom"),
    ("CARIBBEANCOM", "Caribbeancom"),
    ("カリビアンコムプレミアム", "Caribbeancompr"),
    ("Caribbeancom Premium", "Caribbeancompr"),
    ("一本道", "1pondo"),
    ("1pon", "1pondo"),
    ("天然むすめ", "10musume"),
    ("10mu", "10musume"),
    ("パコパコママ", "Pacopacomama"),
    ("ムラムラってくる素人", "Muramura"),
    ("東京熱", "Tokyo-Hot"),
    ("heyzo", "HEYZO"),
    ("Prestige", "Prestige"),                 # 没登记的原样
    ("MGS", "MGS"),
    ("", ""),
    (None, ""),
])
def test_canonical_studio(raw, expected):
    assert canonical_studio(raw) == expected


def test_settle_extract_canonicalizes_studio():
    found = {row.field: row.value for row in extract({"title": "x", "maker": "カリビアンコム"}, source="javdb")}
    assert found["studio"] == "Caribbeancom"


def test_ensure_entity_canonicalizes_studio_only(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        studio_id = entities.ensure_entity(connection, "studio", "カリビアンコム")
        assert entities.ensure_entity(connection, "studio", "Caribbeancom") == studio_id
        assert connection.execute("SELECT canonical_name FROM entity WHERE id=?", (studio_id,)).fetchone()[0] == "Caribbeancom"
        # 其它类型不走这张表：叫 カリビアンコム 的标签就是标签。
        tag_id = entities.ensure_entity(connection, "tag", "カリビアンコム")
        assert connection.execute("SELECT canonical_name FROM entity WHERE id=?", (tag_id,)).fetchone()[0] == "カリビアンコム"
    finally:
        connection.close()


def test_import_nfo_canonicalizes_studio(tmp_root: Path):
    (tmp_root / "030315-819.mp4").write_bytes(b"0" * 16)
    (tmp_root / "030315-819.nfo").write_text("<movie><title>甲</title><studio>カリビアンコム</studio></movie>", encoding="utf-8")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        import_local(connection, paths)
        row = connection.execute("SELECT studio, field_owners FROM asset").fetchone()
        assert row["studio"] == "Caribbeancom" and owner_of(row["field_owners"], "studio") == "auto:nfo"
        assert [r[0] for r in connection.execute("SELECT canonical_name FROM entity WHERE kind='studio'")] == ["Caribbeancom"]
    finally:
        connection.close()


def test_canonicalize_existing_rewrites_old_library(tmp_root: Path):
    """已经刮过的老库：资产的 studio 改成规范写法、归属不动；别名实体并进规范实体；用户手写的不碰。"""
    for name in ("030315-819.mp4", "120614-753.mp4", "121914-760.mp4", "ABP-758.mp4"):
        (tmp_root / name).write_bytes(b"0" * 16)
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        ids = {row["name"]: int(row["id"]) for row in connection.execute("SELECT id,name FROM asset")}
        alias_id = connection.execute(
            "INSERT INTO entity(kind,canonical_name,normalized_name) VALUES('studio','カリビアンコム',?)",
            (db.normalize_name("カリビアンコム"),)).lastrowid
        canon_id = connection.execute(
            "INSERT INTO entity(kind,canonical_name,normalized_name) VALUES('studio','Caribbeancom',?)",
            (db.normalize_name("Caribbeancom"),)).lastrowid
        write_owned_fields(connection, "asset", ids["030315-819.mp4"], [FieldWrite("studio", "カリビアンコム", "auto:javdb")])
        entities.link(connection, ids["030315-819.mp4"], alias_id, "studio", "scrape")
        write_owned_fields(connection, "asset", ids["120614-753.mp4"], [FieldWrite("studio", "カリビアンコム", "auto:avbase")])
        entities.link(connection, ids["120614-753.mp4"], alias_id, "studio", "scrape")
        entities.link(connection, ids["120614-753.mp4"], canon_id, "studio", "scrape")   # 两个实体都挂着
        write_owned_fields(connection, "asset", ids["121914-760.mp4"], [FieldWrite("studio", "カリビアンコム", USER_MANUAL)])
        write_owned_fields(connection, "asset", ids["ABP-758.mp4"], [FieldWrite("studio", "Prestige", "auto:nfo")])
        connection.commit()

        assert canonicalize_existing(connection) == 2
        studios = {row["name"]: (row["studio"], owner_of(row["field_owners"], "studio"))
                   for row in connection.execute("SELECT name, studio, field_owners FROM asset")}
        assert studios["030315-819.mp4"] == ("Caribbeancom", "auto:javdb")
        assert studios["120614-753.mp4"] == ("Caribbeancom", "auto:avbase")
        assert studios["121914-760.mp4"] == ("カリビアンコム", USER_MANUAL)
        assert studios["ABP-758.mp4"] == ("Prestige", "auto:nfo")
        assert [r[0] for r in connection.execute("SELECT canonical_name FROM entity WHERE kind='studio' ORDER BY id")] == ["Caribbeancom"]
        linked = {int(r[0]) for r in connection.execute("SELECT asset_id FROM asset_entity WHERE entity_id=? AND role='studio'", (canon_id,))}
        assert linked == {ids["030315-819.mp4"], ids["120614-753.mp4"]}
        # 幂等：再跑一遍什么都不改。
        assert canonicalize_existing(connection) == 0
        # import 步开头会自动跑这一遍（老库再跑一次 shelf run 就修好）。
        write_owned_fields(connection, "asset", ids["ABP-758.mp4"], [FieldWrite("studio", "carib", "auto:javbus")])
        connection.commit()
        import_local(connection, paths)
        assert connection.execute("SELECT studio FROM asset WHERE name='ABP-758.mp4'").fetchone()[0] == "Caribbeancom"
    finally:
        connection.close()


def test_pipeline_organizes_into_english_folder(tmp_root: Path, fake_video):
    """用户看到的最终效果：目录叫 Caribbeancom/，站点厂牌列表里也是 Caribbeancom。"""
    from hidden_shelf import pipeline
    from hidden_shelf.site.build import read_data_js

    fake_video(tmp_root / "030315-819.mp4")
    (tmp_root / "030315-819.nfo").write_text("<movie><title>甲</title><studio>カリビアンコム</studio></movie>", encoding="utf-8")
    result = pipeline.run(tmp_root, scrape_options=pipeline.ScrapeOptions(offline=True))
    assert result.ok, result.error
    assert (tmp_root / "Caribbeancom" / "030315-819" / "030315-819.mp4").is_file()
    assert not (tmp_root / "カリビアンコム").exists()
    studios = read_data_js(ShelfPaths(tmp_root).site_data / "entities.js")["studios"]
    assert [s["name"] for s in studios] == ["Caribbeancom"]
