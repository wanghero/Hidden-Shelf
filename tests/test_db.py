"""SQLite 工作库：连接、迁移、名字归一。"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from hidden_shelf import db, entities
from hidden_shelf.paths import ShelfPaths


def _tables(connection):
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_connect_runs_migrations(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        assert db.schema_version(connection) == 2
        assert {"asset", "sidecar", "entity", "entity_alias", "asset_entity", "run",
                "organize_batch", "schema_version"} <= _tables(connection)
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        columns = {row[1] for row in connection.execute("PRAGMA table_info(asset)")}
        assert {"path", "code", "code_key", "part", "vanished", "field_owners", "revision",
                "cover_file", "poster_file", "sheet_file", "play_hint", "content_type"} <= columns
        connection.execute("INSERT INTO asset(path,name,medium) VALUES('a/b.mp4','b.mp4','video')")
        row = connection.execute("SELECT * FROM asset").fetchone()
        assert row["path"] == "a/b.mp4"
        assert row["vanished"] == 0 and row["part"] == "" and row["field_owners"] == "{}"
    finally:
        connection.close()
    assert paths.db.is_file()


def test_connect_is_idempotent(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    first = db.connect(paths)
    first.execute("INSERT INTO entity(kind,canonical_name,normalized_name) VALUES('performer','甲','甲')")
    first.commit()
    first.close()
    second = db.connect(paths)
    try:
        assert db.schema_version(second) == 2
        assert second.execute("SELECT count(*) FROM entity").fetchone()[0] == 1
        assert second.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 2
    finally:
        second.close()


def test_entity_uniqueness(tmp_root: Path):
    connection = db.connect(ShelfPaths(tmp_root))
    try:
        connection.execute("INSERT INTO entity(kind,canonical_name,normalized_name) VALUES('performer','甲','甲')")
        import sqlite3
        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO entity(kind,canonical_name,normalized_name) VALUES('performer','甲 ','甲')")
        connection.execute("INSERT INTO entity(kind,canonical_name,normalized_name) VALUES('tag','甲','甲')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO entity(kind,canonical_name,normalized_name) VALUES('bogus','x','x')")
    finally:
        connection.close()


def test_normalize_name():
    assert db.normalize_name("Ａｂｃ 甲") == db.normalize_name("abc甲")
    assert db.normalize_name("三上　悠亜") == db.normalize_name("三上悠亜")
    assert db.normalize_name("Prestige（プレステージ）") == db.normalize_name("prestige プレステージ".replace(" ", ""))
    assert db.normalize_name("  ") == ""
    assert db.normalize_name("A-B_C") == db.normalize_name("abc")


def _nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


#: 带浊音假名的真实目录名：`が` 在 NFC 下是一个码位，NFD 下是 `か` + 浊音符两个。
NFC_PATH = "Tokyo-Hot/N0017 こんな娘が生カン・中出し!-滝沢美鈴/N0017.avi"


def test_stored_paths_are_normalised_to_nfc(tmp_root: Path):
    """macOS 交回来的分解写法进了库，下一次连库就被改成 NFC（`paths.nfc` 说了为什么）。"""
    connection = db.connect(ShelfPaths(tmp_root))
    try:
        connection.execute("INSERT INTO asset(path,name,medium) VALUES(?,?,'video')",
                           (_nfd(NFC_PATH), _nfd("N0017.avi")))
        connection.execute("INSERT INTO sidecar(path,kind) VALUES(?,'cover')",
                           (_nfd("Tokyo-Hot/N0017 こんな娘が生カン・中出し!-滝沢美鈴/folder.jpg"),))
        assert db.normalize_stored_paths(connection) == 2
        assert connection.execute("SELECT path FROM asset").fetchone()[0] == NFC_PATH
        assert connection.execute("SELECT name FROM asset").fetchone()[0] == "N0017.avi"
        assert "こんな娘が生カン" in connection.execute("SELECT path FROM sidecar").fetchone()[0]
        # 幂等：第二遍一个字节都不用改。
        assert db.normalize_stored_paths(connection) == 0
    finally:
        connection.close()


def test_two_spellings_of_one_file_merge_into_the_row_with_the_data(tmp_root: Path):
    """同一个文件被当成两部片登记过：留下带资料的那条，文件事实、关联、附属文件都并过来。"""
    connection = db.connect(ShelfPaths(tmp_root))
    try:
        # 旧记录：NFC 写法，刮好了资料，上一趟重扫时因为对不上被判「消失」。
        old = connection.execute(
            "INSERT INTO asset(path,name,medium,code,code_key,title,scraped_at,cover_file,vanished,first_seen,"
            "field_owners) VALUES(?,?,'video','N0017','N0017','こんな娘が生カン・中出し!','2026-11-01T00:00:00+00:00',"
            "'covers/N0017.jpg',1,'2026-10-30T00:00:00',?)",
            (NFC_PATH, "N0017.avi", json.dumps({"title": "auto:tokyohot"}))).lastrowid
        performer = entities.ensure_entity(connection, "performer", "滝沢美鈴")
        entities.link(connection, old, performer, "performer", "auto:tokyohot")
        # 新记录：同一个文件的分解写法，没有任何资料，只有今天刚做的探测与九宫格。
        new = connection.execute(
            "INSERT INTO asset(path,name,medium,code,code_key,probed_at,duration,sheet_file,vanished,first_seen) "
            "VALUES(?,?,'video','N0017','N0017','2026-11-02T00:00:00',1800.0,'sheets/N0017.jpg',0,"
            "'2026-11-02T00:00:00')", (_nfd(NFC_PATH), _nfd("N0017.avi"))).lastrowid
        sidecar = connection.execute(
            "INSERT INTO sidecar(asset_id,path,kind,status) VALUES(?,?,'cover','placed')",
            (new, "Tokyo-Hot/N0017 nfd/N0017-cover.jpg")).lastrowid

        assert db.normalize_stored_paths(connection) == 1

        rows = connection.execute("SELECT * FROM asset").fetchall()
        assert len(rows) == 1, "两条记录应该并成一条"
        row = rows[0]
        assert int(row["id"]) == old and row["path"] == NFC_PATH
        # 资料跟着留下的那条，一个字都没丢。
        assert row["title"] == "こんな娘が生カン・中出し!" and row["scraped_at"] == "2026-11-01T00:00:00+00:00"
        assert json.loads(row["field_owners"])["title"] == "auto:tokyohot"
        assert row["cover_file"] == "covers/N0017.jpg"
        # 文件事实从新记录补上：文件还在盘上，探测结果与九宫格不用重做。
        assert row["vanished"] == 0
        assert row["probed_at"] == "2026-11-02T00:00:00" and row["duration"] == 1800.0
        assert row["sheet_file"] == "sheets/N0017.jpg"
        assert row["first_seen"] == "2026-10-30T00:00:00"
        # 关联与附属文件改指到留下的那条。
        assert connection.execute("SELECT count(*) FROM asset_entity WHERE asset_id=?", (old,)).fetchone()[0] == 1
        assert connection.execute("SELECT asset_id FROM sidecar WHERE id=?", (sidecar,)).fetchone()[0] == old
        assert db.normalize_stored_paths(connection) == 0
    finally:
        connection.close()


def test_merging_keeps_the_scraped_row_even_when_it_came_second(tmp_root: Path):
    """留哪条按「刮过没有」判，不按先后：先建的那条没资料时让位给后建的。"""
    connection = db.connect(ShelfPaths(tmp_root))
    try:
        bare = connection.execute("INSERT INTO asset(path,name,medium) VALUES(?,?,'video')",
                                  (NFC_PATH, "N0017.avi")).lastrowid
        scraped = connection.execute(
            "INSERT INTO asset(path,name,medium,title,scraped_at) VALUES(?,?,'video','有资料',"
            "'2026-11-02T00:00:00+00:00')", (_nfd(NFC_PATH), _nfd("N0017.avi"))).lastrowid
        assert db.normalize_stored_paths(connection) == 1
        rows = connection.execute("SELECT id,path,title FROM asset").fetchall()
        assert [int(row["id"]) for row in rows] == [scraped] and bare not in [int(row["id"]) for row in rows]
        assert rows[0]["path"] == NFC_PATH and rows[0]["title"] == "有资料"
    finally:
        connection.close()
