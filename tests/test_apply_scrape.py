"""结算结果落库与「要不要问」。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hidden_shelf import db, entities
from hidden_shelf.field_owners import USER_MANUAL, FieldWrite, auto_owner, owner_of, write_owned_fields
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scrape.apply import ApplyReport, apply_settled, may_replace, should_scrape
from hidden_shelf.scrape.settle import Settled

NOW = "2026-10-29T12:00:00+00:00"


@pytest.fixture
def connection(tmp_root: Path):
    conn = db.connect(ShelfPaths(tmp_root))
    yield conn
    conn.close()


def _asset(connection, path: str, code: str = "ABW-358", **columns) -> int:
    keys = ["path", "name", "medium", "code", "code_key", "content_type", *columns]
    values = [path, path.rsplit("/", 1)[-1], "video", code, code, "censored", *columns.values()]
    cursor = connection.execute(
        f"INSERT INTO asset({','.join(keys)}) VALUES({','.join('?' * len(keys))})", values)
    return int(cursor.lastrowid)


def _row(connection, asset_id):
    return connection.execute("SELECT * FROM asset WHERE id=?", (asset_id,)).fetchone()


def _links(connection, asset_id, role):
    return [(row[0], row[1]) for row in connection.execute(
        "SELECT e.canonical_name, ae.source FROM asset_entity ae JOIN entity e ON e.id=ae.entity_id "
        "WHERE ae.asset_id=? AND ae.role=? ORDER BY ae.rowid", (asset_id, role))]


SETTLED = {
    "title": Settled("涼森れむ流", "r18dev"),
    "studio": Settled("Prestige", "r18dev"),
    "series": Settled("保健室の先生", "r18dev"),
    "release_date": Settled("2023-05-26", "r18dev"),
    "tags": Settled(("スレンダー", "企画"), "javdb"),
    "performers": Settled(({"name": "涼森れむ", "external_id": "1051912", "profile_source": "r18dev",
                            "thumb_url": "https://pics.dmm.co.jp/mono/actjpgs/suzumori_remu.jpg",
                            "aliases": ["すずもりれむ", "Remu Suzumori"]},), "r18dev"),
}


def test_may_replace():
    assert may_replace("", "", "javbus")
    assert may_replace("旧", "", "javbus"), "无主的现值谁都能换"
    assert may_replace("旧", "auto:javbus", "r18dev")
    assert may_replace("旧", "auto:frame", "javbus")
    assert not may_replace("旧", "auto:javdb", "javdb"), "同档不换"
    assert not may_replace("旧", "auto:r18dev", "avbase")
    assert not may_replace("旧", "auto:nfo", "r18dev"), "本地 NFO 是 0 档"
    assert not may_replace("旧", "auto:local", "dmm")
    assert not may_replace("", USER_MANUAL, "r18dev"), "用户的字段连空的也不碰"
    assert not may_replace("旧", "review:javdb", "r18dev")


def test_apply_writes_scalars_with_auto_owner(connection):
    asset_id = _asset(connection, "a/ABW-358.mp4")
    report = apply_settled(connection, [asset_id], "ABW-358", SETTLED, now=NOW)
    row = _row(connection, asset_id)
    assert (row["title"], row["studio"], row["series"], row["release_date"]) == ("涼森れむ流", "Prestige", "保健室の先生", "2023-05-26")
    owners = json.loads(row["field_owners"])
    assert owners == {"title": "auto:r18dev", "studio": "auto:r18dev", "series": "auto:r18dev", "release_date": "auto:r18dev"}
    assert row["scraped_at"] == NOW
    assert report.written == {"title": "r18dev", "studio": "r18dev", "series": "r18dev", "release_date": "r18dev"}
    assert report.kept == {} and (report.performers, report.tags) == (1, 2)
    assert _links(connection, asset_id, "studio") == [("Prestige", "auto:r18dev")]
    assert _links(connection, asset_id, "series") == [("保健室の先生", "auto:r18dev")]
    assert _links(connection, asset_id, "tag") == [("スレンダー", "auto:javdb"), ("企画", "auto:javdb")]
    assert _links(connection, asset_id, "performer") == [("涼森れむ", "auto:r18dev")]


def test_apply_does_not_overwrite_user_or_nfo(connection):
    asset_id = _asset(connection, "a/ABW-358.mp4")
    write_owned_fields(connection, "asset", asset_id, [FieldWrite("title", "用户标题", USER_MANUAL),
                                                       FieldWrite("studio", "NFO 厂牌", auto_owner("nfo"))])
    report = apply_settled(connection, [asset_id], "ABW-358", SETTLED, now=NOW)
    row = _row(connection, asset_id)
    assert (row["title"], row["studio"], row["series"]) == ("用户标题", "NFO 厂牌", "保健室の先生")
    assert (owner_of(row["field_owners"], "title"), owner_of(row["field_owners"], "studio")) == (USER_MANUAL, "auto:nfo")
    assert report.kept == {"title": USER_MANUAL, "studio": "auto:nfo"}
    assert set(report.written) == {"series", "release_date"}
    # 厂牌没写，实体关联也不换。
    assert _links(connection, asset_id, "studio") == []


def test_apply_higher_tier_replaces_lower(connection):
    asset_id = _asset(connection, "a/ABW-358.mp4")
    apply_settled(connection, [asset_id], "ABW-358", {"studio": Settled("兜底厂牌", "javbus")}, now=NOW)
    assert (_row(connection, asset_id)["studio"], _links(connection, asset_id, "studio")) == ("兜底厂牌", [("兜底厂牌", "auto:javbus")])
    # r18dev 来了：换，旧的自动关联换成新的。
    apply_settled(connection, [asset_id], "ABW-358", {"studio": Settled("Prestige", "r18dev")}, now=NOW)
    row = _row(connection, asset_id)
    assert (row["studio"], owner_of(row["field_owners"], "studio")) == ("Prestige", "auto:r18dev")
    assert _links(connection, asset_id, "studio") == [("Prestige", "auto:r18dev")]
    # avbase 再来：不换。
    report = apply_settled(connection, [asset_id], "ABW-358", {"studio": Settled("別メーカー", "avbase")}, now=NOW)
    assert _row(connection, asset_id)["studio"] == "Prestige" and report.kept == {"studio": "auto:r18dev"}
    # 同档也不换。
    apply_settled(connection, [asset_id], "ABW-358", {"studio": Settled("プレステージ", "dmm")}, now=NOW)
    assert _row(connection, asset_id)["studio"] == "Prestige"


def test_apply_performers_create_entities_with_refs_and_keep_user_links(connection):
    asset_id = _asset(connection, "a/ABW-358.mp4")
    user_pick = entities.ensure_entity(connection, "performer", "涼森れむ")
    entities.link(connection, asset_id, user_pick, "performer", "user")
    other = entities.ensure_entity(connection, "performer", "用户加的人")
    entities.link(connection, asset_id, other, "performer", "user")
    report = apply_settled(connection, [asset_id], "ABW-358", SETTLED, now=NOW)
    # 同一个人：用户的关联原样留着（source 不被改成 auto），外站 ID 与别名挂上她。
    assert _links(connection, asset_id, "performer") == [("涼森れむ", "user"), ("用户加的人", "user")]
    assert report.performers == 0
    assert entities.find_by_external_ref(connection, "performer", "r18dev", "1051912") == user_pick
    aliases = {row[0] for row in connection.execute("SELECT alias FROM entity_alias WHERE entity_id=?", (user_pick,))}
    assert aliases == {"すずもりれむ", "Remu Suzumori"}
    assert entities.metadata_of(connection, user_pick) == {
        "avatar_url": "https://pics.dmm.co.jp/mono/actjpgs/suzumori_remu.jpg", "avatar_source": "r18dev"}
    assert connection.execute("SELECT count(*) FROM entity WHERE kind='performer'").fetchone()[0] == 2
    # 再来一个 javdb 的同名不同 id：不新建，多挂一个 ref，头像地址不被覆盖。
    javdb = {"performers": Settled(({"name": "涼森れむ", "external_id": "a", "profile_source": "javdb", "thumb_url": "https://x/other.jpg"},
                                    {"name": "三宮つばき", "external_id": "b", "profile_source": "javdb"}), "javdb")}
    report = apply_settled(connection, [asset_id], "ABW-358", javdb, now=NOW)
    assert report.performers == 1
    assert entities.find_by_external_ref(connection, "performer", "javdb", "a") == user_pick
    assert entities.metadata_of(connection, user_pick)["avatar_url"].endswith("suzumori_remu.jpg")
    assert _links(connection, asset_id, "performer")[-1] == ("三宮つばき", "auto:javdb")


def test_apply_shares_across_parts(connection):
    first = _asset(connection, "a/ABW-358-cd1.mp4", part="1")
    second = _asset(connection, "a/ABW-358-cd2.mp4", part="2")
    report = apply_settled(connection, [first, second], "ABW-358", SETTLED, now=NOW)
    for asset_id in (first, second):
        row = _row(connection, asset_id)
        assert (row["title"], row["scraped_at"]) == ("涼森れむ流", NOW)
        assert _links(connection, asset_id, "performer") == [("涼森れむ", "auto:r18dev")]
        assert len(_links(connection, asset_id, "tag")) == 2
    assert connection.execute("SELECT count(*) FROM entity WHERE kind='performer'").fetchone()[0] == 1
    assert (report.performers, report.tags) == (2, 4)
    # 不存在的 id 跳过，不抛。
    assert isinstance(apply_settled(connection, [999], "ABW-358", SETTLED, now=NOW), ApplyReport)


def _candidate(**overrides):
    row = {"code": "ABW-358", "code_key": "ABW-358", "content_type": "censored", "path": "a/ABW-358.mp4",
           "name": "ABW-358.mp4", "title": "", "studio": "", "release_date": "", "field_owners": "{}",
           "scraped_at": None, "cover_file": None, "performer_count": 0, "tag_count": 0}
    row.update(overrides)
    return row


def test_should_scrape_rules():
    assert should_scrape(_candidate(), now=NOW) == (True, ["title", "performers", "studio", "release_date", "tags", "cover"])
    assert should_scrape(_candidate(code="", code_key=""), now=NOW) == (False, [])
    assert should_scrape(_candidate(content_type="unrecognized"), now=NOW) == (False, [])
    assert should_scrape(_candidate(code="YUJ-103", code_key="YUJ-103"), now=NOW) == (False, []), "韩国 MIB 不问"
    assert should_scrape(_candidate(code="TZ-105", code_key="TZ-105", path="B:/番号/TZ-105/兔子先生TZ-105.mp4",
                                    name="兔子先生TZ-105.mp4"), now=NOW) == (False, []), "其他体系不问"
    full = _candidate(title="t", studio="s", release_date="2023-05-26", performer_count=1, tag_count=1,
                      cover_file="covers/ABW-358.jpg",
                      field_owners=json.dumps({"title": "auto:r18dev", "studio": "auto:nfo", "release_date": "auto:dmm",
                                               "cover_file": "auto:local"}))
    assert should_scrape(full, now=NOW) == (False, []), "一项都不缺"
    assert should_scrape(full, force=True, now=NOW) == (True, ["title", "performers", "studio", "release_date", "tags", "cover"])
    # 社区来源写的标量算缺（还能升级），抽帧封面算缺。
    community = dict(full, field_owners=json.dumps({"title": "auto:javbus", "studio": "auto:r18dev",
                                                    "release_date": "auto:dmm", "cover_file": "auto:frame"}))
    assert should_scrape(community, now=NOW) == (True, ["title", "cover"])
    # 7 天内问过且不 force：不问，但照样报缺什么。
    recent = dict(community, scraped_at="2026-10-25T00:00:00+00:00")
    assert should_scrape(recent, now=NOW) == (False, ["title", "cover"])
    assert should_scrape(dict(recent, scraped_at="2026-10-01T00:00:00+00:00"), now=NOW) == (True, ["title", "cover"])
    assert should_scrape(recent, force=True, now=NOW)[0]
    # 只缺封面也问。
    assert should_scrape(dict(full, cover_file=None), now=NOW) == (True, ["cover"])
    # `datetime` 与时间戳都能当 now。
    import datetime as dt
    assert should_scrape(recent, now=dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc)) == (False, ["title", "cover"])
    assert should_scrape(recent, now=1_793_000_000.0)[0] is False
