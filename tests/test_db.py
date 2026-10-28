"""SQLite 工作库：连接、迁移、名字归一。"""
from __future__ import annotations

from pathlib import Path

from hidden_shelf import db
from hidden_shelf.paths import ShelfPaths


def _tables(connection):
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_connect_runs_migrations(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        assert db.schema_version(connection) == 1
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
        assert db.schema_version(second) == 1
        assert second.execute("SELECT count(*) FROM entity").fetchone()[0] == 1
        assert second.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 1
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
