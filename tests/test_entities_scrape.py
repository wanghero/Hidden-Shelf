"""实体层的计划 2 扩展：迁移 0002、外站 ID、别名、按名字与字形解析艺人。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hidden_shelf import db, entities
from hidden_shelf.paths import ShelfPaths


@pytest.fixture
def connection(tmp_root: Path):
    conn = db.connect(ShelfPaths(tmp_root))
    yield conn
    conn.close()


def _columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_migration_0002(tmp_root: Path):
    # 先只建 0001 的库，塞一条别名，再跑迁移：别名保留且 source='scrape'，新列新表都在。
    path = tmp_root / "old.db"
    old = sqlite3.connect(path)
    old.execute("PRAGMA foreign_keys=ON")
    old.executescript((db.MIGRATIONS_DIR / "0001_init.sql").read_text(encoding="utf-8"))
    old.execute("INSERT INTO schema_version(version) VALUES(1)")
    old.execute("INSERT INTO entity(id,kind,canonical_name,normalized_name) VALUES(7,'performer','涼森れむ','涼森れむ')")
    old.execute("INSERT INTO entity_alias(entity_id,alias,normalized) VALUES(7,'Remu Suzumori','remusuzumori')")
    old.commit()
    assert db.schema_version(old) == 1
    db.migrate(old)
    assert db.schema_version(old) == 2
    row = old.execute("SELECT entity_id, alias, normalized, source, confidence FROM entity_alias").fetchone()
    assert tuple(row) == (7, "Remu Suzumori", "remusuzumori", "scrape", 1.0)
    assert {"avatar_file", "metadata"} <= _columns(old, "entity")
    assert {"scraped_at", "scrape_note"} <= _columns(old, "asset")
    assert {"entity_id", "provider", "external_kind", "external_id", "metadata", "synced_at"} <= _columns(old, "entity_external_ref")
    assert old.execute("SELECT metadata FROM entity WHERE id=7").fetchone()[0] == "{}"
    # 同实体同写法不同来源可以各一条；同来源重复不行。
    old.execute("INSERT INTO entity_alias(entity_id,alias,normalized,source) VALUES(7,'Remu Suzumori','remusuzumori','javdb')")
    with pytest.raises(sqlite3.IntegrityError):
        old.execute("INSERT INTO entity_alias(entity_id,alias,normalized,source) VALUES(7,'Remu Suzumori','remusuzumori','javdb')")
    # 级联：删实体连带别名与外站 ID。
    old.execute("INSERT INTO entity_external_ref(entity_id,provider,external_kind,external_id) VALUES(7,'r18dev','performer','1051912')")
    old.execute("DELETE FROM entity WHERE id=7")
    assert old.execute("SELECT count(*) FROM entity_alias").fetchone()[0] == 0
    assert old.execute("SELECT count(*) FROM entity_external_ref").fetchone()[0] == 0
    old.close()


def test_fresh_db_is_version_2(connection):
    assert db.schema_version(connection) == 2
    assert connection.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 2


def test_normalize_name_strips_zero_width():
    assert db.normalize_name("‌斋藤亚美里") == db.normalize_name("斋藤亚美里")
    assert db.normalize_name("Remu Suzumori") == "remusuzumori"
    assert db.normalize_name("涼森れむ") == "涼森れむ"


def test_external_ref_and_alias_basics(connection):
    remu = entities.ensure_entity(connection, "performer", "涼森れむ")
    assert entities.find_by_external_ref(connection, "performer", "r18dev", "1051912") is None
    assert entities.add_external_ref(connection, remu, "r18dev", "performer", "1051912", now="t")
    assert entities.find_by_external_ref(connection, "performer", "r18dev", "1051912") == remu
    assert entities.find_by_external_ref(connection, "studio", "r18dev", "1051912") is None, "按实体类型分开"
    assert not entities.add_external_ref(connection, remu, "r18dev", "performer", "")
    assert entities.add_alias(connection, remu, "すずもりれむ", "r18dev")
    assert entities.add_alias(connection, remu, "Remu Suzumori", "r18dev")
    assert not entities.add_alias(connection, remu, "Remu Suzumori", "r18dev"), "同来源同写法只登记一次"
    assert entities.add_alias(connection, remu, "Remu Suzumori", "javdb"), "另一来源可以再记一条"
    assert not entities.add_alias(connection, remu, "涼森れむ"), "与规范名相同的不算别名"
    assert not entities.add_alias(connection, remu, "  ")
    rows = connection.execute("SELECT alias, source FROM entity_alias WHERE entity_id=? ORDER BY rowid", (remu,)).fetchall()
    assert [tuple(row) for row in rows] == [("すずもりれむ", "r18dev"), ("Remu Suzumori", "r18dev"), ("Remu Suzumori", "javdb")]


def test_resolve_performer_by_external_ref_then_name_then_glyph(connection):
    remu = entities.resolve_performer(connection, "涼森れむ", provider="r18dev", external_id="1051912",
                                      aliases=["すずもりれむ", "Remu Suzumori"], now="t")
    # 同一个外站 ID 再来，名字写法不同也是她；不新建。
    assert entities.resolve_performer(connection, "凉森玲梦", provider="r18dev", external_id="1051912") == remu
    # javdb 给同名不同 id → 同实体并多挂一个 ref。
    assert entities.resolve_performer(connection, "涼森れむ", provider="javdb", external_id="a") == remu
    refs = connection.execute("SELECT provider, external_id FROM entity_external_ref WHERE entity_id=? ORDER BY provider",
                              (remu,)).fetchall()
    assert [tuple(row) for row in refs] == [("javdb", "a"), ("r18dev", "1051912")]
    # 只给别名（罗马字）也解得到她。
    assert entities.resolve_performer(connection, "Remu Suzumori") == remu
    # `永瀬みなも` 与 `永濑みなも` 合一：字形折叠唯一命中，现写法登记成别名。
    minamo = entities.resolve_performer(connection, "永瀬みなも", provider="javdb", external_id="m1")
    assert entities.resolve_performer(connection, "永濑みなも") == minamo
    aliases = {row[0] for row in connection.execute("SELECT alias FROM entity_alias WHERE entity_id=?", (minamo,))}
    assert "永濑みなも" in aliases
    # `釈愛麗絲` 两个 javdb id 都能挂上。
    alice = entities.resolve_performer(connection, "釈愛麗絲", provider="javdb", external_id="x1")
    assert entities.resolve_performer(connection, "釈愛麗絲", provider="javdb", external_id="x2") == alice
    assert connection.execute("SELECT count(*) FROM entity_external_ref WHERE entity_id=?", (alice,)).fetchone()[0] == 2
    assert connection.execute("SELECT count(*) FROM entity WHERE kind='performer'").fetchone()[0] == 3
    with pytest.raises(ValueError):
        entities.resolve_performer(connection, "  ")


def test_former_name_lands_on_the_entity_already_there(connection):
    akari = entities.ensure_entity(connection, "performer", "美谷朱里")
    # 现名没登记、旧名已在库里：挂到旧名那一位身上，现名成为别名。
    assert entities.resolve_performer(connection, "美谷朱音", former_names=["美谷朱里"], provider="r18dev", external_id="1039982") == akari
    aliases = {row[0] for row in connection.execute("SELECT alias FROM entity_alias WHERE entity_id=?", (akari,))}
    assert aliases == {"美谷朱音"}
    assert connection.execute("SELECT count(*) FROM entity WHERE kind='performer'").fetchone()[0] == 1
    # 现名已登记时旧名成为她的别名。
    new = entities.resolve_performer(connection, "七海ひな", former_names=["七瀬ひな"])
    assert {row[0] for row in connection.execute("SELECT alias FROM entity_alias WHERE entity_id=?", (new,))} == {"七瀬ひな"}


def test_ambiguous_alias_or_glyph_match_creates_a_new_entity(connection):
    first = entities.ensure_entity(connection, "performer", "甲")
    second = entities.ensure_entity(connection, "performer", "乙")
    entities.add_alias(connection, first, "みほちゃん")
    entities.add_alias(connection, second, "みほちゃん")
    third = entities.resolve_performer(connection, "みほちゃん")
    assert third not in (first, second), "别名撞名时不任意指向一位"


def test_external_id_owned_by_another_entity_is_not_stolen(connection):
    remu = entities.ensure_entity(connection, "performer", "涼森れむ")
    other = entities.ensure_entity(connection, "performer", "三宮つばき")
    assert entities.add_external_ref(connection, remu, "r18dev", "performer", "1051912")
    assert not entities.add_external_ref(connection, other, "r18dev", "performer", "1051912")
    assert entities.find_by_external_ref(connection, "performer", "r18dev", "1051912") == remu
    # 外站 ID 优先：名字说是三宮つばき，ID 说是涼森れむ，按 ID；ID 既已属她，不再改。
    assert entities.resolve_performer(connection, "三宮つばき", provider="r18dev", external_id="1051912") == remu
    # 反过来：三宮つばき 带着一个已属涼森れむ 的 ID 过来解析——按 ID 命中涼森れむ，三宮つばき 自己的实体不受影响。
    assert connection.execute("SELECT count(*) FROM entity_external_ref").fetchone()[0] == 1


def test_resolve_named_and_metadata(connection):
    prestige = entities.resolve_named(connection, "studio", "Prestige")
    entities.add_alias(connection, prestige, "プレステージ", "javdb")
    assert entities.resolve_named(connection, "studio", "プレステージ") == prestige
    assert entities.resolve_named(connection, "studio", "prestige") == prestige
    assert entities.resolve_named(connection, "studio", "MOODYZ") != prestige
    assert entities.resolve_named(connection, "tag", "巨乳") == entities.ensure_entity(connection, "tag", "巨乳")
    with pytest.raises(ValueError):
        entities.resolve_named(connection, "bogus", "x")
    with pytest.raises(ValueError):
        entities.resolve_named(connection, "series", "")
    assert entities.metadata_of(connection, prestige) == {}
    assert entities.merge_metadata(connection, prestige, {"avatar_url": "https://x/a.jpg", "note": 1}) == {
        "avatar_url": "https://x/a.jpg", "note": 1}
    assert entities.merge_metadata(connection, prestige, {"note": None}) == {"avatar_url": "https://x/a.jpg"}
    assert entities.metadata_of(connection, prestige) == {"avatar_url": "https://x/a.jpg"}
    connection.execute("UPDATE entity SET metadata='not json' WHERE id=?", (prestige,))
    assert entities.metadata_of(connection, prestige) == {}
