"""字段归属与受保护写入。后半的断言搬自 peach `tests/test_field_owners.py`。"""
from __future__ import annotations

import json
import sqlite3

import pytest

from hidden_shelf.field_owners import (
    SCAN_FILENAME,
    USER_MANUAL,
    FieldWrite,
    auto_owner,
    is_protected,
    owner_of,
    parse_owners,
    review_owner,
    script_owner,
    write_owned_fields,
)


@pytest.fixture
def connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE asset(id INTEGER PRIMARY KEY, title TEXT, studio TEXT, series TEXT, "
                 "code TEXT, field_owners TEXT DEFAULT '{}', revision INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO asset(id) VALUES(1)")
    conn.execute("INSERT INTO asset(id) VALUES(2)")
    yield conn
    conn.close()


def row(connection, asset_id=1):
    return connection.execute("SELECT * FROM asset WHERE id=?", (asset_id,)).fetchone()


def test_auto_cannot_overwrite_user(connection):
    assert write_owned_fields(connection, "asset", 1, [FieldWrite("title", "用户写的", USER_MANUAL)]) == {"title": True}
    result = write_owned_fields(connection, "asset", 1, [FieldWrite("title", "NFO 给的", auto_owner("nfo"))])
    assert result == {"title": False}
    assert row(connection)["title"] == "用户写的"
    assert owner_of(row(connection)["field_owners"], "title") == USER_MANUAL


def test_auto_overwrites_auto(connection):
    write_owned_fields(connection, "asset", 1, [FieldWrite("title", "甲", auto_owner("frame"))])
    assert write_owned_fields(connection, "asset", 1, [FieldWrite("title", "乙", auto_owner("nfo"))]) == {"title": True}
    assert row(connection)["title"] == "乙"
    assert owner_of(row(connection)["field_owners"], "title") == "auto:nfo"
    assert row(connection)["revision"] == 2


def test_require_empty_only_fills_blank(connection):
    write_owned_fields(connection, "asset", 1, [FieldWrite("code", "ABC-001", auto_owner("nfo"))])
    result = write_owned_fields(connection, "asset", 1, [
        FieldWrite("code", "ZZZ-999", SCAN_FILENAME, require_empty=True),
        FieldWrite("studio", "厂牌", SCAN_FILENAME, require_empty=True),
    ])
    assert result == {"code": False, "studio": True}
    assert row(connection)["code"] == "ABC-001"
    assert row(connection)["studio"] == "厂牌"


def test_user_overrides_any_automatic_owner(connection):
    write_owned_fields(connection, "asset", 1, [FieldWrite("code", "ABC-001", script_owner("fix"))])
    assert write_owned_fields(connection, "asset", 1, [FieldWrite("code", "ABC-002", USER_MANUAL)]) == {"code": True}
    assert row(connection)["code"] == "ABC-002"


def test_a_blocked_field_does_not_take_the_rest_with_it(connection):
    write_owned_fields(connection, "asset", 1, [FieldWrite("studio", "用户写的", USER_MANUAL)])
    result = write_owned_fields(connection, "asset", 1, [
        FieldWrite("studio", "刮削给的", auto_owner("javbus")),
        FieldWrite("series", "某系列", auto_owner("javbus")),
    ])
    assert result == {"studio": False, "series": True}
    current = row(connection)
    assert (current["studio"], current["series"]) == ("用户写的", "某系列")
    assert parse_owners(current["field_owners"]) == {"studio": USER_MANUAL, "series": "auto:javbus"}


def test_revision_only_counts_value_changes(connection):
    write_owned_fields(connection, "asset", 1, [FieldWrite("studio", "同一个值", auto_owner("a"))])
    write_owned_fields(connection, "asset", 1, [FieldWrite("studio", "同一个值", auto_owner("b"))])
    assert row(connection)["revision"] == 1
    # 取值没变也要把归属换成最后一个写入者。
    assert owner_of(row(connection)["field_owners"], "studio") == "auto:b"


def test_null_owner_map_never_wipes_existing_owners(connection):
    connection.execute("UPDATE asset SET field_owners=NULL WHERE id=1")
    write_owned_fields(connection, "asset", 1, [FieldWrite("studio", "用户写的", USER_MANUAL)])
    write_owned_fields(connection, "asset", 1, [
        FieldWrite("studio", "刮削给的", auto_owner("javbus")),
        FieldWrite("series", "某系列", auto_owner("javbus")),
    ])
    stored = row(connection)["field_owners"]
    assert json.loads(stored) == {"studio": USER_MANUAL, "series": "auto:javbus"}


def test_custom_column_names(connection):
    connection.execute("CREATE TABLE other(id INTEGER PRIMARY KEY, name TEXT, owners TEXT, rev INTEGER DEFAULT 0)")
    connection.execute("INSERT INTO other(id) VALUES(7)")
    assert write_owned_fields(connection, "other", 7, [FieldWrite("name", "x", USER_MANUAL)],
                              owners_column="owners", revision_column="rev") == {"name": True}
    got = connection.execute("SELECT * FROM other WHERE id=7").fetchone()
    assert got["name"] == "x" and got["rev"] == 1
    assert parse_owners(got["owners"]) == {"name": USER_MANUAL}


def test_missing_row_writes_nothing(connection):
    assert write_owned_fields(connection, "asset", 999, [FieldWrite("title", "x", USER_MANUAL)]) == {"title": False}


def test_empty_writes(connection):
    assert write_owned_fields(connection, "asset", 1, []) == {}


def test_is_protected():
    assert is_protected(USER_MANUAL)
    assert is_protected("review:javbus")
    assert not is_protected("auto:nfo")
    assert not is_protected(SCAN_FILENAME)
    assert not is_protected("")
    assert not is_protected(None)


def test_parse_owners_tolerates_garbage():
    assert parse_owners("not json") == {}
    assert parse_owners(None) == {}
    assert parse_owners("[1,2]") == {}
    assert parse_owners('{"studio":"user:manual","bad":3}') == {"studio": "user:manual"}
    assert owner_of('{"studio":"user:manual"}', "studio") == USER_MANUAL
    assert owner_of('{"studio":"user:manual"}', None) == ""


def test_owner_identifiers_are_restricted_to_a_safe_shape():
    assert review_owner("r18dev") == "review:r18dev"
    assert auto_owner("aventertainment") == "auto:aventertainment"
    assert script_owner("apply_metadata_tags") == "script:apply_metadata_tags"
    for bad in ("", "R18Dev", "has space", 'quote"'):
        with pytest.raises(ValueError):
            review_owner(bad)


def test_an_unknown_owner_category_is_refused(connection):
    with pytest.raises(ValueError):
        write_owned_fields(connection, "asset", 1, [FieldWrite("studio", "甲", "plugin:whatever")])
    with pytest.raises(ValueError):
        write_owned_fields(connection, "asset", 1, [FieldWrite("studio", "甲", "user")])


def test_field_names_must_be_identifiers(connection):
    with pytest.raises(ValueError):
        write_owned_fields(connection, "asset", 1, [FieldWrite("title; DROP TABLE asset", "x", USER_MANUAL)])
