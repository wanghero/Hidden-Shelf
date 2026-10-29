"""社区来源解析器：javdb、JavBus、AVBase，以及 AVBase 200 验证页进整站冷却。

搬自 peach `tests/test_community_catalog.py`（解析部分）、`tests/test_metadata_sources.py` 的 `JavDBResourceTests`
（标题/身份/类别三条）与 `SiteCooldownTests`（AVBase 验证页）。夹具落在 `tests/fixtures/sources/`。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from hidden_shelf.scrape.access import FIRST_BLOCKED_PAUSE, Cooldown, SourcePaused, SourceTransport
from hidden_shelf.scrape.sources import (SITE_SOURCES, AVBaseSource, FailureReason, JavBusSource, JavDBSource, Page,
                                         Session, SourceFailure)
from hidden_shelf.scrape.sources.avbase import AVBASE, PRODUCT_ORDER, listing_date, own_products
from hidden_shelf.scrape.sources.javbus import JAVBUS
from hidden_shelf.scrape.sources.javdb import JAVDB, actresses, maker_writing
from hidden_shelf.scrape.sources.javdb_helpers import LOGIN, RECORD_KIND, clean
from hidden_shelf.scrape.transport import HostLimiter, HttpResponse

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def serve(pages):
    calls = []

    def call(request, timeout, limit):
        calls.append(request.url)
        found = request.url in pages
        return HttpResponse(200 if found else 404, {}, pages.get(request.url, b""), request.url)

    call.calls = calls
    return call


def work(site, pages, code):
    """走完取页与解析，交出快照那份 dict。"""
    return site.query(code, session=Session(serve(pages))).payload()


TITLE = "涼森れむ流 HOW TO SEX！！"
DMM_COVER = "https://pics.dmm.co.jp/mono/movie/adult/118abw358/118abw358pl.jpg"
MGS_COVER = "https://image.mgstage.com/images/prestige/abw/358/pb_e_abw-358.jpg"
JAVDB_COVER = "https://c0.jdbstatic.com/covers/zb/Zb7mX.jpg"
JAVBUS_COVER = "https://www.javbus.com/pics/cover/9x2a_b.jpg"
AVBASE_SEARCH = "https://www.avbase.net/works?q=ABW-358"
LUXU_SEARCH = "https://www.avbase.net/works?q=259LUXU-1514"
JAVBUS_WORK = "https://www.javbus.com/ABW-358"
JAVDB_SEARCH = "https://javdb.com/search?q=ABW-358&f=all"
JAVDB_DETAIL = "https://javdb.com/v/Zb7mX?locale=zh"

AVBASE_PAGE = fixture("avbase-works.html")
CHALLENGE_PAGE = fixture("avbase-challenge.html")
JAVBUS_PAGE = fixture("javbus-work.html")
JAVBUS_GATE = fixture("javbus-gate.html")
JAVDB_RESULTS = fixture("javdb-search.html")
JAVDB_PAGE = fixture("javdb-detail.html")
JAVDB_LOGIN = fixture("javdb-login.html")

#: 形状取自 259LUXU-1514 的实测页：名寄せ的作品标题是 FANZA 合集那一件的标题，单卖本作的只有 MGStage 那条。
LUXU_TITLE = "ラグジュTV 1485 綺麗で笑顔が素敵な看護師さんが「普通のセックスでは物足りない…」と刺激を求めて登場！"
LUXU_COVER = "https://image.mgstage.com/images/luxutv/sp/259luxu/1514/pake-03_sp-259luxu-1514.jpg"
LUXU_DATA = {"props": {"pageProps": {"works": [
    {"work_id": "259LUXU-1514", "title": "FIRST CLASS ファーストクラス File/006",
     "actors": [{"name": "東條なつ"}], "products": [
         {"source": "fanza", "title": "FIRST CLASS ファーストクラス File/006", "product_id": "118sng013",
          "image_url": "https://pics.dmm.co.jp/mono/movie/adult/118sng013/118sng013pl.jpg",
          "maker": {"name": "プレステージ"}, "label": {"name": "SINGLE"},
          "series": {"name": "FIRST CLASS ファーストクラス"},
          "date": "Fri Aug 16 2024 09:00:00 GMT+0900"},
         {"source": "mgstage", "title": LUXU_TITLE, "product_id": "259LUXU-1514", "image_url": LUXU_COVER,
          "maker": {"name": "ラグジュTV"}, "series": {"name": "ラグジュTV"},
          "date": "Fri Nov 19 2021 09:00:00 GMT+0900"},
     ]},
]}}}


def avbase_page(data) -> bytes:
    return ('<html><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data, ensure_ascii=False) + "</script></html>").encode()


# ---------- helpers ----------

def test_javdb_helpers():
    assert clean(" <b>高跟鞋</b>&nbsp;&amp; 絲襪\n") == "高跟鞋 & 絲襪"
    assert LOGIN.search("<title>登入 | JavDB</title>")
    assert not LOGIN.search("<title>ABW-358 | JavDB</title>")
    assert RECORD_KIND.sub("", "木下ひまり(無碼)") == "木下ひまり"
    assert RECORD_KIND.sub("", "木下ひまり") == "木下ひまり"


# ---------- javdb ----------

def test_javdb_config():
    assert (JAVDB.name, JAVDB.interval, JAVDB.cookie, JAVDB.stage) == ("javdb", 3.0, True, "community")
    assert {"javdb.com", "jdbstatic.com", "jdbimgs.com"} <= set(JAVDB.domains)
    assert JavDBSource().search_url("ABW-358") == JAVDB_SEARCH


def test_search_picks_the_card_matching_the_code():
    """两张卡 `ABW-358` 与 `ABW-3580` 只取前者；男优不进演员，女优带 javdb 演员 id。"""
    found = work(JavDBSource(), {JAVDB_SEARCH: JAVDB_RESULTS, JAVDB_DETAIL: JAVDB_PAGE}, "ABW-358")
    assert (found["id"], found["title"], found["maker"], found["release_date"], found["runtime"]) == (
        "ABW-358", TITLE, "プレステージ", "2023-05-23", 210)
    assert found["actresses"] == [{"japanese_name": "涼森れむ", "profile_source": "javdb", "external_id": "a"}]
    assert (found["source_url"], found["cover_urls"]) == ("https://javdb.com/v/Zb7mX", [JAVDB_COVER])


def test_javdb_payload_equals_the_snapshot_shape_field_for_field():
    expected = {
        "id": "ABW-358", "source_url": "https://javdb.com/v/Zb7mX", "title": TITLE,
        "origin_title": "", "display_title": TITLE, "source_id": "Zb7mX",
        "actresses": [{"japanese_name": "涼森れむ", "profile_source": "javdb", "external_id": "a"}],
        "maker": "プレステージ", "label": "", "series": "", "director": "", "release_date": "2023-05-23",
        "runtime": 210, "genres": [], "cover_urls": [JAVDB_COVER], "cover_url": JAVDB_COVER}
    assert work(JavDBSource(), {JAVDB_SEARCH: JAVDB_RESULTS, JAVDB_DETAIL: JAVDB_PAGE}, "ABW-358") == expected
    record = JavDBSource().parse(Page("https://javdb.com/v/Zb7mX", JAVDB_PAGE), "ABW-358")
    assert (record.source, record.provenance, record.code) == ("javdb", "javdb-page", "ABW-358")
    assert record.payload() == expected


def test_javdb_reads_the_cover_whichever_side_of_the_class_the_src_sits():
    later = f'<img class="video-cover" width="600" height="404" fetchpriority="high" src="{JAVDB_COVER}" />'.encode()
    earlier = f'<img src="{JAVDB_COVER}" class="video-cover" alt="">'.encode()
    assert later in JAVDB_PAGE
    for page in (JAVDB_PAGE, JAVDB_PAGE.replace(later, earlier)):
        assert JavDBSource().parse(Page("https://javdb.com/v/Zb7mX", page), "ABW-358").cover_url == JAVDB_COVER


def test_two_cards_same_code_is_ambiguous():
    source = JavDBSource()
    for identities in [("XeYkdb", "MO50k"), ("MO50k", "XeYkdb")]:
        html = "".join(f'<a href="/v/{identity}" class="box" title="film"><strong>MIKR-023</strong></a>'
                       for identity in identities)
        with patch.object(source, "_page", return_value=Page("https://javdb.com/search", html.encode())) as get:
            with pytest.raises(SourceFailure) as caught:
                source.fetch("MIKR-023", session=None)
            assert caught.value.detail == "identity_ambiguous"
            assert caught.value.reason == FailureReason.PARSE_ERROR
            assert get.call_count == 1
    # 同一个来源 id 的卡重复出现不算第二部片。
    card = '<a href="/v/XeYkdb" class="box" title="film"><strong>MIKR-023</strong></a>'
    detail = Page("https://javdb.com/v/XeYkdb", b"detail")
    with patch.object(source, "_page", side_effect=[Page("https://javdb.com/search", (card * 2).encode()), detail]):
        assert source.fetch("MIKR-023", session=None).url == detail.url


def test_login_page_is_auth_required():
    with pytest.raises(SourceFailure) as caught:
        work(JavDBSource(), {JAVDB_SEARCH: JAVDB_LOGIN}, "ABW-358")
    assert (caught.value.reason, str(caught.value)) == (FailureReason.AUTH_REQUIRED, "javdb 要求登录")
    with pytest.raises(SourceFailure) as caught:
        work(JavDBSource(), {JAVDB_SEARCH: JAVDB_RESULTS, JAVDB_DETAIL: JAVDB_LOGIN}, "ABW-358")
    assert caught.value.reason == FailureReason.AUTH_REQUIRED


def test_javdb_missing_code_and_404_detail_and_mismatch():
    with pytest.raises(SourceFailure) as caught:
        work(JavDBSource(), {JAVDB_SEARCH: JAVDB_RESULTS.replace(b"<strong>ABW-358</strong>", b"<strong>ABW-359</strong>")}, "ABW-358")
    assert (caught.value.reason, str(caught.value)) == (FailureReason.NOT_FOUND, "javdb 没有这个番号")
    with pytest.raises(SourceFailure) as caught:
        work(JavDBSource(), {JAVDB_SEARCH: JAVDB_RESULTS}, "ABW-358")
    assert (caught.value.reason, str(caught.value)) == (FailureReason.NOT_FOUND, "HTTP 404")
    mismatched = JAVDB_PAGE.replace(b'<a href="/video_codes/ABW">ABW</a>-358', b'<a href="/video_codes/ABW">ABW</a>-359')
    with pytest.raises(SourceFailure) as caught:
        JavDBSource().parse(Page("https://javdb.com/v/Zb7mX", mismatched), "ABW-358")
    assert (caught.value.reason, caught.value.kind, str(caught.value)) == (
        FailureReason.PARSE_ERROR, "unavailable", "javdb 详情页的番号与搜索结果不一致")


def test_parse_panel_fields_and_female_actors_with_ids():
    assert actresses('<a class="actor-female" href="/actors/z9">葵いぶき</a>') == [
        {"japanese_name": "葵いぶき", "profile_source": "javdb", "external_id": "z9"}]
    assert actresses('<a class="actor-female">名字没挂链接</a>') == [
        {"japanese_name": "名字没挂链接", "profile_source": "javdb", "external_id": ""}]
    assert actresses('<a href="/actors/b">男優</a>') == []
    categories = ('<div class="panel-block"><strong>類別:</strong><span class="value">'
                  '<a href="/tags/a"> 高跟鞋 </a><a href="/tags/b"><b>絲襪</b></a>'
                  '<a href="/tags/c">アナル</a><a href="/tags/d">未收录分類</a>'
                  '<a href="/tags/a">高跟鞋</a><a href="/tags/empty"> </a></span></div>')
    record = JavDBSource().parse(Page("https://javdb.com/v/Zb7mX", JAVDB_PAGE + categories.encode()), "ABW-358")
    assert record.tags == ("高跟鞋", "絲襪", "アナル", "未收录分類")
    assert record.payload()["genres"] == ["高跟鞋", "絲襪", "アナル", "未收录分類"]
    empty_panel = ('<div class="panel-block"><strong>類別:</strong>'
                   '<span class="value"><a href="/tags/empty"> </a></span></div>')
    for category_panel in (b"", empty_panel.encode()):
        record = JavDBSource().parse(Page("https://javdb.com/v/Zb7mX", JAVDB_PAGE + category_panel), "ABW-358")
        assert record.tags == () and record.payload()["genres"] == []


def test_origin_title_beats_display_title():
    panel = '<div class="panel-block"><strong>番號:</strong><span class="value">MIKR-023</span></div>'
    for html, expected in (('<span class="origin-title">日本語原題</span>', "日本語原題"),
                           ('<strong class="current-title">仅显示标题</strong>', "仅显示标题"),
                           ('<strong class="current-title">译文</strong><span class="origin-title">Original *Title*</span>',
                            "Original *Title*")):
        payload = JavDBSource().parse(Page("https://javdb.com/v/XeYkdb", (html + panel).encode()), "MIKR-023").payload()
        assert payload["title"] == expected, html
    html = '''<strong class="current-title">自动翻译标题</strong>
    <span class="origin-title" style="display:none">Original *A* **j*yqy*pq* 日本語</span>''' + panel
    payload = JavDBSource().parse(Page("https://javdb.com/v/XeYkdb", html.encode()), "MIKR-023").payload()
    assert payload["title"] == "Original *A* **j*yqy*pq* 日本語"
    assert payload["origin_title"] == payload["title"]
    assert payload["display_title"] == "自动翻译标题"
    assert payload["source_id"] == "XeYkdb"
    assert "javdb_rule" not in payload


def test_maker_writing_prefers_japanese():
    assert maker_writing("PRESTIGE,プレステージ") == "プレステージ"
    assert maker_writing("プレステージ,PRESTIGE") == "プレステージ"
    assert maker_writing("MOODYZ") == "MOODYZ"
    assert maker_writing("") == ""


# ---------- JavBus ----------

def test_javbus_config():
    assert (JAVBUS.name, JAVBUS.cookie, JAVBUS.interval) == ("javbus", True, 2.0)
    assert JavBusSource().work_url("ABW-358") == JAVBUS_WORK


def test_parse_fields_and_cover():
    expected = {
        "id": "ABW-358", "source_url": JAVBUS_WORK, "title": TITLE, "actresses": [{"japanese_name": "涼森れむ"}],
        "maker": "プレステージ", "label": "ABSOLUTELY WONDERFUL", "series": "", "director": "",
        "release_date": "2023-05-26", "runtime": 210, "cover_urls": [JAVBUS_COVER], "cover_url": JAVBUS_COVER}
    assert work(JavBusSource(), {JAVBUS_WORK: JAVBUS_PAGE}, "ABW-358") == expected
    record = JavBusSource().parse(Page(JAVBUS_WORK, JAVBUS_PAGE), "ABW-358")
    assert (record.source, record.provenance, record.code) == ("javbus", "javbus-page", "ABW-358")
    assert record.payload() == expected
    assert record.tags is None, "JavBus 的類別一栏不在字段行里，这一站不给标签"


def test_gate_page_is_auth_required():
    """年龄门回 200 却没有「識別碼」，要让人去贴 Cookie，而不是记成没有。"""
    with pytest.raises(SourceFailure, match="贴上浏览器里的 Cookie") as caught:
        work(JavBusSource(), {JAVBUS_WORK: JAVBUS_GATE}, "ABW-358")
    assert caught.value.reason == FailureReason.AUTH_REQUIRED


def test_near_miss_code_is_not_found():
    with pytest.raises(SourceFailure, match="JavBus 没有这个番号") as caught:
        work(JavBusSource(), {}, "ABW-358")
    assert (caught.value.reason, caught.value.status_code) == (FailureReason.NOT_FOUND, 404)
    with pytest.raises(SourceFailure, match="JavBus 没有这个番号") as caught:
        work(JavBusSource(), {JAVBUS_WORK: JAVBUS_PAGE.replace(b">ABW-358</span>", b">ABW-359</span>")}, "ABW-358")
    assert caught.value.reason == FailureReason.NOT_FOUND


# ---------- AVBase ----------

def test_avbase_config_and_dates():
    assert (AVBASE.name, AVBASE.cookie, AVBASE.stage) == ("avbase", False, "community")
    assert AVBaseSource().search_url("ABW-358") == AVBASE_SEARCH
    assert listing_date("Fri May 26 2023 09:00:00 GMT+0900") == "2023-05-26"
    assert listing_date("Tue May 23 2023 09:00:00 GMT+0900") == "2023-05-23"
    assert listing_date("2023-05-26") == ""
    assert listing_date(None) == ""
    assert PRODUCT_ORDER == ("fanza", "mgstage", "duga")


def test_parse_next_data_and_product_order():
    """`ABW-3580` 那张卡不算；合集（标题与商品号都对不上）被剔；FANZA 那条排前面。"""
    expected = {
        "id": "ABW-358", "source_url": "https://www.avbase.net/works/prestige:ABW-358", "title": TITLE,
        "actresses": [{"japanese_name": "涼森れむ"}], "maker": "プレステージ", "label": "ABSOLUTELY WONDERFUL",
        "series": "", "director": "監督A", "release_date": "2023-05-26", "runtime": None,
        "cover_urls": [DMM_COVER, MGS_COVER], "cover_url": DMM_COVER}
    assert work(AVBaseSource(), {AVBASE_SEARCH: AVBASE_PAGE}, "ABW-358") == expected
    record = AVBaseSource().parse(Page(AVBASE_SEARCH, AVBASE_PAGE), "ABW-358")
    assert (record.source, record.provenance, record.code) == ("avbase", "avbase-search", "ABW-358")
    assert record.payload() == expected
    assert record.tags is None


def test_collection_product_is_not_this_work():
    """合集顶着作品标题时也不算本作：商品号认得出番号的那条说了算。`259LUXU-1514` 的 `118sng013` 合集被剔。"""
    found = work(AVBaseSource(), {LUXU_SEARCH: avbase_page(LUXU_DATA)}, "259LUXU-1514")
    assert found == {
        "id": "259LUXU-1514", "source_url": "https://www.avbase.net/works/259LUXU-1514", "title": LUXU_TITLE,
        "actresses": [{"japanese_name": "東條なつ"}], "maker": "ラグジュTV", "label": "", "series": "ラグジュTV",
        "director": "", "release_date": "2021-11-19", "runtime": None,
        "cover_urls": [LUXU_COVER], "cover_url": LUXU_COVER}
    products = own_products("259LUXU-1514", LUXU_DATA["props"]["pageProps"]["works"][0])
    assert [product["source"] for product in products] == ["mgstage"]


def test_no_work_is_not_found():
    empty = {"props": {"pageProps": {"works": []}}}
    with pytest.raises(SourceFailure) as caught:
        work(AVBaseSource(), {AVBASE_SEARCH: avbase_page(empty)}, "ABW-358")
    assert (caught.value.reason, str(caught.value)) == (FailureReason.NOT_FOUND, "AVBase 没有这个番号")
    with pytest.raises(SourceFailure, match="AVBase 页面结构未识别") as caught:
        work(AVBaseSource(), {AVBASE_SEARCH: b"<html><body>redesigned</body></html>"}, "ABW-358")
    assert caught.value.reason == FailureReason.PARSE_ERROR


def test_challenge_page_is_cloudflare_reason():
    with pytest.raises(SourceFailure, match="AVBase 页面结构未识别") as caught:
        work(AVBaseSource(), {AVBASE_SEARCH: CHALLENGE_PAGE}, "ABW-358")
    assert caught.value.reason == FailureReason.CLOUDFLARE_CHALLENGE
    assert caught.value.cooldown_action == "blocked"


def test_an_avbase_challenge_served_with_200_pauses_the_whole_site(tmp_path: Path):
    """真的 `SourceTransport` 套假传输：验证页经 `holding()` 进冷却，冷却期内第二部片一次都不问。"""
    calls = []

    def fake(request, timeout, limit):
        calls.append(request.url)
        return HttpResponse(200, {}, CHALLENGE_PAGE, request.url)

    cooldown = Cooldown(tmp_path / "_cooldown.json")
    transport = SourceTransport(cooldown, factory=lambda source: fake, limiter=HostLimiter({}, default=0.0))
    session = Session(transport)
    with pytest.raises(SourceFailure) as caught:
        AVBaseSource().query("ABW-358", session=session)
    assert caught.value.reason == FailureReason.CLOUDFLARE_CHALLENGE
    assert (round(cooldown.paused_until("avbase") - cooldown.now()), cooldown.blocks("avbase")) == (FIRST_BLOCKED_PAUSE, 1)
    with pytest.raises(SourcePaused):
        AVBaseSource().query("MIDE-594", session=session)
    assert len(calls) == 1


def test_the_six_sites_are_registered():
    assert set(SITE_SOURCES) == {"r18dev", "dmm", "1pondo", "javdb", "javbus", "avbase"}
    for name, cls in SITE_SOURCES.items():
        assert cls.DEFAULT.name == name
