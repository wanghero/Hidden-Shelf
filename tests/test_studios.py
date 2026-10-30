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
from hidden_shelf.studios import canonical_studio, canonicalize_existing, fill_studios_from_code, studio_from_code


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
    ("キャットウォーク", "Catwalk"),
    ("Catwalk Poison", "Catwalk"),
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


@pytest.mark.parametrize("code,expected", [
    ("n0610", "Tokyo-Hot"),
    ("N0610", "Tokyo-Hot"),
    ("k1234", "Tokyo-Hot"),
    ("red-123", "Tokyo-Hot"),
    ("TOKYO-HOT-N0762", "Tokyo-Hot"),
    ("HEYZO-1031", "HEYZO"),
    ("heyzo-1031", "HEYZO"),
    ("ABP-758", ""),            # 有码：字母段不指向任何一家
    ("032715_001", ""),         # 日期式：カリビアンコム、一本道、天然むすめ 同形，猜不得
    ("FC2-PPV-1234567", ""),
    ("", ""),
    (None, ""),
])
def test_studio_from_code(code, expected):
    assert studio_from_code(code) == expected


def test_import_fills_studio_from_code_shape(tmp_root: Path):
    """番号形状本身说明片商的（Tokyo-Hot 的 `n####`、HEYZO），导入步直接补厂牌，不等联网；
    已有厂牌的、用户手写的、形状不说明片商的都不碰；再跑一遍什么都不改。"""
    (tmp_root / "Tokyo Hot n0610 乙音奈々").mkdir()
    (tmp_root / "Tokyo Hot n0610 乙音奈々" / "n0610.H264.avi").write_bytes(b"0" * 16)
    for name in ("n0611.avi", "k1234.mp4", "HEYZO-1031.mp4", "ABP-758.mp4", "032715_001.mp4"):
        (tmp_root / name).write_bytes(b"0" * 16)
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        ids = {row["code"]: int(row["id"]) for row in connection.execute("SELECT id,code FROM asset")}
        write_owned_fields(connection, "asset", ids["n0611"], [FieldWrite("studio", "我的东热", USER_MANUAL)])
        write_owned_fields(connection, "asset", ids["k1234"], [FieldWrite("studio", "東京熱", "auto:javbus")])
        connection.commit()
        messages: list[str] = []
        import_local(connection, paths, progress=messages.append)
        studios = {row["code"]: (row["studio"], owner_of(row["field_owners"], "studio"))
                   for row in connection.execute("SELECT code, studio, field_owners FROM asset")}
        assert studios["n0610"] == ("Tokyo-Hot", "auto:local")
        assert studios["HEYZO-1031"] == ("HEYZO", "auto:local")
        assert studios["n0611"] == ("我的东热", USER_MANUAL)
        assert studios["k1234"] == ("Tokyo-Hot", "auto:javbus")     # 规范写法由 canonicalize_existing 改，归属不动
        assert studios["ABP-758"] == (None, "") and studios["032715_001"] == (None, "")
        assert any("按番号形状补上厂牌：2 条" in line for line in messages)
        linked = {row[0]: row[1] for row in connection.execute(
            "SELECT ae.asset_id, e.canonical_name FROM asset_entity ae JOIN entity e ON e.id=ae.entity_id WHERE ae.role='studio'")}
        assert linked[ids["n0610"]] == "Tokyo-Hot" and linked[ids["HEYZO-1031"]] == "HEYZO"
        assert [r[0] for r in connection.execute("SELECT canonical_name FROM entity WHERE kind='studio' ORDER BY canonical_name")] == ["HEYZO", "Tokyo-Hot"]
        assert fill_studios_from_code(connection) == 0
    finally:
        connection.close()


def test_studio_keeps_uncensored_type_after_rename(tmp_root: Path):
    """归位改名后文件名里没了发行站名，厂牌是登记过的无码片商就仍算无码。"""
    from hidden_shelf.scan import content_type_of
    assert content_type_of("Catwalk CWPBD-120 Miku Ohashi.mp4", "CWPBD-120") == "uncensored"
    assert content_type_of("CWPBD-120.mp4", "CWPBD-120") == "censored"
    assert content_type_of("CWPBD-120.mp4", "CWPBD-120", "キャットウォーク") == "uncensored"
    assert content_type_of("CWPBD-120.mp4", "CWPBD-120", "Catwalk") == "uncensored"
    assert content_type_of("ABP-758.mp4", "ABP-758", "Prestige") == "censored"
    (tmp_root / "CWPBD-120.mp4").write_bytes(b"0" * 16)
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        asset_id = connection.execute("SELECT id FROM asset").fetchone()[0]
        write_owned_fields(connection, "asset", asset_id, [FieldWrite("studio", "キャットウォーク", "auto:javbus")])
        connection.commit()
        scan(connection, paths, ShelfConfig())
        assert connection.execute("SELECT content_type FROM asset").fetchone()[0] == "uncensored"
    finally:
        connection.close()
