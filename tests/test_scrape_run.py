"""刮削编排端到端（假传输回放 Task 4–6 的夹具）。"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from PIL import Image

from hidden_shelf import db, entities
from hidden_shelf.config import ShelfConfig
from hidden_shelf.field_owners import USER_MANUAL, FieldWrite, auto_owner, owner_of, write_owned_fields
from hidden_shelf.netconfig import GlobalConfig, SourceSettings
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scrape.run import ScrapeResult, scrape_assets
from hidden_shelf.scrape.transport import HttpResponse

FIXTURES = Path(__file__).parent / "fixtures" / "sources"
from datetime import datetime, timezone

T = 1_793_236_000.0  # 2026-10-29 附近的一个时刻
STAMP = datetime.fromtimestamp(T, timezone.utc).isoformat(timespec="seconds")

DETAIL_URL = "https://r18.dev/videos/vod/movies/detail/-/dvd_id=ABW-358/json"
COMBINED_URL = "https://r18.dev/videos/vod/movies/detail/-/combined=118abw358/json"
JACKET = "https://pics.dmm.co.jp/digital/video/118abw00358/118abw00358pl.jpg"
HD = "https://awsimgsrc.dmm.com/dig/digital/video/118abw00358/118abw00358pl.jpg"
AVATAR = "https://pics.dmm.co.jp/mono/actjpgs/suzumori_remu.jpg"
DMM_ENDPOINT = "https://api.video.dmm.co.jp/graphql"
AVBASE_SEARCH = "https://www.avbase.net/works?q=ABW-358"
JAVBUS_WORK = "https://www.javbus.com/ABW-358"
JAVDB_SEARCH = "https://javdb.com/search?q=ABW-358&f=all"
JAVDB_DETAIL = "https://javdb.com/v/Zb7mX?locale=zh"
AVBASE_TITLE = "涼森れむ流 HOW TO SEX！！"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def jpeg(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (128, 90, 70)).save(buffer, format="JPEG")
    return buffer.getvalue()


def png(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 200, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


DMM_EMPTY = b'{"data":{"ppvContent":null,"legacySearchPPV":{"result":{"contents":[]}}}}'


def replay(pages: dict):
    """按地址回放：值是 bytes、`(status, bytes)`、异常或 `callable(request)`；没登记的回 404。"""
    calls = []

    def call(request, timeout, limit):
        calls.append((request.method, request.url))
        body = pages.get(request.url)
        if callable(body):
            return body(request)
        if isinstance(body, Exception):
            raise body
        if body is None:
            return HttpResponse(404, {}, b"", request.url)
        if isinstance(body, tuple):
            return HttpResponse(body[0], {}, body[1], request.url)
        return HttpResponse(200, {}, body, request.url)

    call.calls = calls
    call.hosts = lambda: {httpx.URL(url).host for _, url in calls}
    call.count = lambda host: sum(1 for _, url in calls if httpx.URL(url).host.endswith(host))
    return call


def r18_pages() -> dict:
    return {DETAIL_URL: fixture("r18dev-detail.json"), COMBINED_URL: fixture("r18dev-combined.json"),
            JACKET: jpeg(800, 539), HD: jpeg(2184, 1464), AVATAR: png(400, 600)}


@pytest.fixture
def disk(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    paths.ensure()
    connection = db.connect(paths)
    connection.execute("INSERT INTO asset(path,name,medium,code,code_key,content_type) VALUES(?,?,?,?,?,?)",
                       ("a/ABW-358.mp4", "ABW-358.mp4", "video", "ABW-358", "ABW-358", "censored"))
    connection.commit()
    yield tmp_root, paths, connection
    connection.close()


def _asset(connection, code="ABW-358"):
    return connection.execute("SELECT * FROM asset WHERE code=?", (code,)).fetchone()


def _links(connection, asset_id, role):
    return [(row[0], row[1]) for row in connection.execute(
        "SELECT e.canonical_name, ae.source FROM asset_entity ae JOIN entity e ON e.id=ae.entity_id "
        "WHERE ae.asset_id=? AND ae.role=? ORDER BY ae.rowid", (asset_id, role))]


def run(disk, pages, **options):
    _root, paths, connection = disk
    lines = []
    transport = replay(pages)
    options.setdefault("global_config", GlobalConfig())
    result = scrape_assets(connection, paths, ShelfConfig(), transport=transport, progress=lines.append,
                           now=lambda: T, **options)
    return result, transport, lines


def test_scrape_end_to_end_censored_short_circuits_after_r18dev(disk):
    root, paths, connection = disk
    result, transport, lines = run(disk, r18_pages())
    row = _asset(connection)
    assert (row["title"], row["studio"], row["series"], row["release_date"]) == ("涼森れむ流", "Prestige", "保健室の先生", "2023-05-26")
    owners = json.loads(row["field_owners"])
    assert {owners[name] for name in ("title", "studio", "series", "release_date")} == {"auto:r18dev"}
    assert owners["cover_file"] == "auto:dmm" and row["cover_file"] == "covers/ABW-358.jpg"
    assert Image.open(paths.covers / "ABW-358.jpg").size == (2184, 1464)
    assert row["scraped_at"] == STAMP
    assert _links(connection, row["id"], "performer") == [("涼森れむ", "auto:r18dev")]
    assert _links(connection, row["id"], "tag") == [("スレンダー", "auto:r18dev"), ("企画", "auto:r18dev")]
    remu = entities.find_by_external_ref(connection, "performer", "r18dev", "1051912")
    assert remu is not None
    assert connection.execute("SELECT avatar_file FROM entity WHERE id=?", (remu,)).fetchone()[0] == f"avatars/{remu}.jpg"
    # 快照一份（r18dev 一家答了就停）；dmm、avbase、javbus、javdb 零请求。
    snapshot = json.loads((paths.sources / "ABW-358-r18dev.json").read_text(encoding="utf-8"))
    assert snapshot["source"] == "r18dev" and snapshot["result"]["records"][0]["title"] == "涼森れむ流"
    assert not any((paths.sources / f"ABW-358-{name}.json").exists() for name in ("dmm", "avbase", "javbus", "javdb"))
    assert transport.hosts() <= {"r18.dev", "pics.dmm.co.jp", "awsimgsrc.dmm.com", "awsimgsrc.dmm.co.jp"}
    assert transport.count("r18.dev") == 2
    assert (result.asked, result.settled, result.covers, result.avatars, result.skipped, result.failed) == (1, 1, 1, 1, 0, 0)
    assert result.paused == [] and not result.network_down
    assert any(line.startswith("ABW-358 ← r18dev · 标题/厂牌/系列/发行日/演员/标签 · 封面 2184×1464") for line in lines), lines
    assert any(line.startswith("刮削完成") for line in lines)


def test_community_sources_stop_at_the_first_answer(disk):
    root, paths, connection = disk
    pages = {DMM_ENDPOINT: DMM_EMPTY, AVBASE_SEARCH: fixture("avbase-works.html"), JAVBUS_WORK: fixture("javbus-work.html"),
             JAVDB_SEARCH: fixture("javdb-search.html"), JAVDB_DETAIL: fixture("javdb-detail.html")}
    result, transport, _ = run(disk, pages)
    row = _asset(connection)
    assert (row["title"], row["studio"], row["release_date"]) == (AVBASE_TITLE, "プレステージ", "2023-05-26")
    assert owner_of(row["field_owners"], "title") == "auto:avbase"
    assert _links(connection, row["id"], "performer") == [("涼森れむ", "auto:avbase")]
    assert transport.count("javbus.com") == 0 and transport.count("javdb.com") == 0, "avbase 答了就停"
    assert (paths.sources / "ABW-358-r18dev.json").exists() and (paths.sources / "ABW-358-dmm.json").exists()
    assert "error" in json.loads((paths.sources / "ABW-358-r18dev.json").read_text(encoding="utf-8"))
    assert result.missing == 2 and result.asked == 3


def test_a_partial_community_answer_asks_the_next_one_only(disk):
    root, paths, connection = disk
    page = fixture("avbase-works.html").replace('"actors": [{"name": "涼森れむ"}], '.encode(), b"")
    assert b'"actors"' not in page, "avbase 这次没给演员"
    pages = {DMM_ENDPOINT: DMM_EMPTY, AVBASE_SEARCH: page, JAVBUS_WORK: fixture("javbus-work.html"),
             JAVDB_SEARCH: fixture("javdb-search.html"), JAVDB_DETAIL: fixture("javdb-detail.html")}
    _, transport, _ = run(disk, pages)
    row = _asset(connection)
    assert owner_of(row["field_owners"], "title") == "auto:avbase", "标题仍听 avbase"
    assert _links(connection, row["id"], "performer") == [("涼森れむ", "auto:javbus")], "演员由 javbus 补"
    assert sum(1 for _, url in transport.calls if url == JAVBUS_WORK) == 1 and transport.count("javdb.com") == 0
    assert any(url.startswith("https://www.javbus.com/pics/cover/") for _, url in transport.calls), "javbus 的封面也量尺寸"


def test_snapshot_is_reused_within_7_days(disk):
    root, paths, connection = disk
    run(disk, r18_pages())
    # 第二次（强制）：r18dev 两页零请求，资料从快照来；图只量不装（封面归属已是 auto:dmm）。
    pages = {url: body for url, body in r18_pages().items() if not url.startswith("https://r18.dev/")}
    pages[DETAIL_URL] = AssertionError("快照还新鲜，不该再问 r18.dev")
    result, transport, lines = run(disk, pages, force=True)
    assert transport.count("r18.dev") == 0 and result.asked == 0 and result.settled == 1
    assert any("封面保留本地那张" in line for line in lines)
    # 不强制：7 天内问过且资料齐 → 跳过，一个请求都没有。
    result, transport, _ = run(disk, pages)
    assert result.skipped == 1 and transport.calls == []


def test_not_found_is_remembered_and_transient_is_not(disk):
    root, paths, connection = disk
    pages = {DMM_ENDPOINT: (503, b""), AVBASE_SEARCH: httpx.ConnectError("reset"),
             JAVDB_SEARCH: fixture("javdb-login.html")}
    with patch("hidden_shelf.scrape.transport.NETWORK_RETRY_DELAYS", ()):
        result, transport, _ = run(disk, pages)
    assert sorted(paths.sources.glob("ABW-358-*.json")) == [paths.sources / "ABW-358-javbus.json", paths.sources / "ABW-358-r18dev.json"]
    for name in ("r18dev", "javbus"):
        record = json.loads((paths.sources / f"ABW-358-{name}.json").read_text(encoding="utf-8"))
        assert record["error"]["reason"] == "not_found"
    assert result.missing == 2 and result.asked == 5 and result.settled == 0
    assert _asset(connection)["title"] is None
    assert _asset(connection)["scraped_at"] == STAMP, "问过了就记时刻，7 天内不再问"


def test_403_pauses_site_for_the_run(disk):
    root, paths, connection = disk
    connection.execute("INSERT INTO asset(path,name,medium,code,code_key,content_type) VALUES(?,?,?,?,?,?)",
                       ("b/SSIS-057.mp4", "SSIS-057.mp4", "video", "SSIS-057", "SSIS-057", "censored"))
    connection.commit()
    pages = {DMM_ENDPOINT: DMM_EMPTY, JAVDB_SEARCH: (403, b""), "https://javdb.com/search?q=SSIS-057&f=all": (403, b"")}
    result, transport, lines = run(disk, pages)
    assert result.paused == ["javdb"]
    assert transport.count("javdb.com") == 1, "冷却期内第二个番号对 javdb 零请求"
    cooldown = json.loads((paths.sources / "_cooldown.json").read_text(encoding="utf-8"))
    assert cooldown["javdb"]["blocks"] == 1 and cooldown["javdb"]["until"] > T
    assert any("javdb 暂停" in line for line in lines)
    assert transport.count("r18.dev") == 2 and transport.count("avbase.net") == 2


def test_identity_mismatch_rejected(disk):
    root, paths, connection = disk
    other = json.loads(fixture("r18dev-detail.json"))
    other["content_id"] = "118abw359"
    pages = {DETAIL_URL: json.dumps(other).encode(), DMM_ENDPOINT: DMM_EMPTY}
    result, transport, lines = run(disk, pages)
    assert _asset(connection)["title"] is None
    record = json.loads((paths.sources / "ABW-358-r18dev.json").read_text(encoding="utf-8"))
    assert record["error"] == {"reason": "parse_error", "message": "来源返回的番号不匹配"}
    assert transport.count("r18.dev") == 1, "身份对不上就不去取日文页"
    assert any("番号不匹配" in line for line in lines)


def test_user_and_nfo_fields_survive(disk):
    root, paths, connection = disk
    asset_id = _asset(connection)["id"]
    write_owned_fields(connection, "asset", asset_id, [FieldWrite("title", "用户标题", USER_MANUAL),
                                                       FieldWrite("studio", "NFO 厂牌", auto_owner("nfo")),
                                                       FieldWrite("cover_file", "covers/ABW-358.jpg", auto_owner("local"))])
    (paths.covers / "ABW-358.jpg").write_bytes(b"local cover")
    connection.commit()
    result, _, lines = run(disk, r18_pages())
    row = _asset(connection)
    assert (row["title"], row["studio"], row["release_date"]) == ("用户标题", "NFO 厂牌", "2023-05-26")
    assert (owner_of(row["field_owners"], "title"), owner_of(row["field_owners"], "studio"),
            owner_of(row["field_owners"], "cover_file")) == (USER_MANUAL, "auto:nfo", "auto:local")
    assert (paths.covers / "ABW-358.jpg").read_bytes() == b"local cover"
    assert result.covers == 0
    assert any("保留 标题/厂牌" in line for line in lines)


def test_offline_network_down_does_not_raise(disk):
    root, paths, connection = disk
    for code in ("SSIS-057", "MIDV-012"):
        connection.execute("INSERT INTO asset(path,name,medium,code,code_key,content_type) VALUES(?,?,?,?,?,?)",
                           (f"x/{code}.mp4", f"{code}.mp4", "video", code, code, "censored"))
    connection.commit()
    down = lambda request: (_ for _ in ()).throw(httpx.ConnectError("no route"))
    transport = replay({})
    transport_down = lambda request, timeout, limit: (_ for _ in ()).throw(httpx.ConnectError("no route"))
    lines = []
    with patch("hidden_shelf.scrape.transport.NETWORK_RETRY_DELAYS", ()):
        result = scrape_assets(connection, paths, ShelfConfig(), global_config=GlobalConfig(), transport=transport_down,
                               progress=lines.append, now=lambda: T)
    assert isinstance(result, ScrapeResult) and result.network_down
    assert result.settled == 0 and result.failed == 0
    assert any("网络不可用" in line for line in lines)
    assert not list(paths.sources.glob("*-*.json")), "连接失败不记快照"
    assert all(row[0] is None for row in connection.execute("SELECT scraped_at FROM asset")), "没问成不算问过"


def test_disabled_source_and_only_sources_option(disk):
    root, paths, connection = disk
    pages = {**r18_pages(), DMM_ENDPOINT: DMM_EMPTY, AVBASE_SEARCH: fixture("avbase-works.html"), JAVBUS_WORK: fixture("javbus-work.html")}
    config = GlobalConfig(sources={"r18dev": SourceSettings(enabled=False)})
    _, transport, _ = run(disk, pages, global_config=config)
    assert transport.count("r18.dev") == 0 and transport.count("avbase.net") == 1
    assert owner_of(_asset(connection)["field_owners"], "title") == "auto:avbase"
    # 只问 javbus。
    connection.execute("UPDATE asset SET title=NULL, field_owners='{}', scraped_at=NULL")
    connection.commit()
    (paths.sources / "ABW-358-avbase.json").unlink()
    _, transport, _ = run(disk, pages, only_sources=("javbus",), force=True)
    assert transport.hosts() <= {"www.javbus.com", "pics.dmm.co.jp", "awsimgsrc.dmm.com", "awsimgsrc.dmm.co.jp"}
    assert owner_of(_asset(connection)["field_owners"], "title") == "auto:javbus"


def test_route_override_and_unasked_codes(disk):
    root, paths, connection = disk
    connection.execute("INSERT INTO asset(path,name,medium,code,code_key,content_type) VALUES(?,?,?,?,?,?)",
                       ("k/YUJ-103.mp4", "YUJ-103.mp4", "video", "YUJ-103", "YUJ-103", "other"))
    connection.commit()
    config = GlobalConfig(routes={"censored": ["javbus"]})
    pages = {JAVBUS_WORK: fixture("javbus-work.html")}
    result, transport, _ = run(disk, pages, global_config=config)
    assert transport.hosts() == {"www.javbus.com"}
    assert result.skipped == 1, "韩国 MIB 不问"
    assert _asset(connection)["studio"] == "プレステージ"


def test_one_failing_code_does_not_stop_the_run(disk, monkeypatch):
    root, paths, connection = disk
    connection.execute("INSERT INTO asset(path,name,medium,code,code_key,content_type) VALUES(?,?,?,?,?,?)",
                       ("b/SSIS-057.mp4", "SSIS-057.mp4", "video", "SSIS-057", "SSIS-057", "censored"))
    connection.commit()
    from hidden_shelf.scrape import run as run_module
    original = run_module.apply_settled

    def boom(connection_, ids, code, settled, *, now):
        if code == "ABW-358":
            raise RuntimeError("炸了")
        return original(connection_, ids, code, settled, now=now)

    monkeypatch.setattr(run_module, "apply_settled", boom)
    pages = {**r18_pages(), "https://r18.dev/videos/vod/movies/detail/-/dvd_id=SSIS-057/json": fixture("dmm-content.json")}
    result, _, lines = run(disk, pages)
    assert result.failed == 1
    assert "RuntimeError: 炸了" in (_asset(connection)["scrape_note"] or "")
    assert any("ABW-358 出错" in line for line in lines)
