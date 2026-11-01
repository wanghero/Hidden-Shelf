"""Tokyo-Hot 官网来源（自写）与「简介」字段从来源到落库的流转。夹具是 2026-10-30 抓的作品页与搜索页裁剪版。"""
from __future__ import annotations

from pathlib import Path

import pytest

from hidden_shelf import db
from hidden_shelf.field_owners import owner_of
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scrape.apply import apply_settled
from hidden_shelf.scrape.policy import FIELD_SOURCE_ORDER, SOURCE_SPECS, source_tier
from hidden_shelf.scrape.routes import OFFICIAL_STAGE, route_for_code
from hidden_shelf.scrape.settle import SCALAR_FIELDS, Settled, extract, normalized_plot, settle
from hidden_shelf.scrape.sources import SITE_SOURCES, FailureReason, Page, Session, SourceFailure
from hidden_shelf.scrape.sources.tokyohot import STUDIO, TOKYOHOT, TokyoHotSource, plot_from_sentence, product_code
from hidden_shelf.scrape.transport import HttpResponse

FIXTURES = Path(__file__).parent / "fixtures" / "sources"
SEARCH_URL = "https://my.tokyo-hot.com/product/?q=n1161&lang=ja"
PRODUCT_URL = "https://my.tokyo-hot.com/product/6325/?lang=ja"
JACKET = "https://my.cdn.tokyo-hot.com/media/6325/jacket/n1161.jpg"
PRODUCT = (FIXTURES / "tokyohot-product.html").read_bytes()
SEARCH = (FIXTURES / "tokyohot-search.html").read_bytes()
EMPTY_SEARCH = b'<html><body><div id="main"><p>\xe3\x80\x8cn0610\xe3\x80\x8d\xe3\x81\xab\xe4\xb8\x80\xe8\x87\xb4\xe3\x81\x99\xe3\x82\x8b\xe4\xbd\x9c\xe5\x93\x81\xe3\x81\x8c\xe8\xa6\x8b\xe3\x81\xa4\xe3\x81\x8b\xe3\x82\x8a\xe3\x81\xbe\xe3\x81\x9b\xe3\x82\x93\xe3\x81\xa7\xe3\x81\x97\xe3\x81\x9f\xe3\x80\x82</p></div></body></html>'


def serve(pages):
    """假传输：按 URL 答页面，没登记的 URL 回 404。"""
    calls = []

    def call(request, timeout, limit):
        calls.append((request.url, request.headers.get("Referer"), limit))
        body = pages.get(request.url)
        return HttpResponse(200 if body is not None else 404, {}, body or b"", request.url)

    call.calls = calls
    return call


def test_config_registered_as_official_without_cookie():
    assert SITE_SOURCES["tokyohot"] is TokyoHotSource
    assert (TOKYOHOT.label, TOKYOHOT.provider, TOKYOHOT.stage, TOKYOHOT.cookie, TOKYOHOT.domains) == (
        "Tokyo-Hot", "tokyohot-html", "official", False, ("tokyo-hot.com",))
    assert SOURCE_SPECS["tokyohot"].official and source_tier("tokyohot") == source_tier("1pondo")
    assert "tokyohot" in OFFICIAL_STAGE
    for field in ("title", "performers", "release_date", "tags", "plot"):
        assert "tokyohot" in FIELD_SOURCE_ORDER[field]


def test_product_code_and_search_url():
    assert product_code("n1161") == "N1161" and product_code("red-200") == "RED-200" and product_code("k1300") == "K1300"
    assert product_code("ABW-358") == "" and product_code("040221-001") == ""
    assert TokyoHotSource().search_url("N1161") == SEARCH_URL, "搜索词按官网的小写写法"
    assert TokyoHotSource().search_url("ABW-358") == ""


def test_only_tokyo_hot_shaped_codes_ask_the_official_site():
    assert route_for_code("n1161", "Tokyo-Hot/n1161.mp4", "n1161.mp4", "Tokyo-Hot") == ("tokyohot", "avbase", "javbus", "javdb")
    assert route_for_code("red-200", "x.mp4", "x.mp4", None)[0] == "tokyohot"
    assert "tokyohot" not in route_for_code("040221-001", "x.mp4", "x.mp4", "Caribbeancom")
    assert "tokyohot" not in route_for_code("HEYZO-1380", "x.mp4", "x.mp4", "HEYZO")
    assert "tokyohot" not in route_for_code("ABW-358", "x.mp4", "x.mp4", "Prestige")


def test_fetch_searches_then_opens_the_numbered_product_page():
    transport = serve({SEARCH_URL: SEARCH, PRODUCT_URL: PRODUCT})
    record = TokyoHotSource().query("N1161", session=Session(transport))
    assert [url for url, _referer, _limit in transport.calls] == [SEARCH_URL, PRODUCT_URL]
    assert transport.calls[1][1] == SEARCH_URL, "作品页的 Referer 是搜索页"
    assert transport.calls[0][2] == 2 * 1024 * 1024
    assert record.code == "N1161" and record.source_url == PRODUCT_URL


def test_fetch_without_a_matching_result_is_a_miss():
    transport = serve({"https://my.tokyo-hot.com/product/?q=n0610&lang=ja": EMPTY_SEARCH})
    with pytest.raises(SourceFailure) as failed:
        TokyoHotSource().query("n0610", session=Session(transport))
    assert failed.value.reason is FailureReason.NOT_FOUND and failed.value.is_miss
    assert len(transport.calls) == 1, "没有结果就不再开作品页"


def test_search_result_must_carry_the_exact_code():
    listing = Page(SEARCH_URL, SEARCH)
    assert TokyoHotSource().product_url(listing, "N1161") == PRODUCT_URL
    assert TokyoHotSource().product_url(listing, "n1162") == ""
    with pytest.raises(SourceFailure) as failed:
        TokyoHotSource().query("ABW-358", session=Session(serve({})))
    assert failed.value.reason is FailureReason.NOT_FOUND


def test_parse_reads_every_field_from_the_product_page():
    payload = TokyoHotSource().parse(Page(PRODUCT_URL, PRODUCT), "n1161").payload()
    assert payload["id"] == "N1161" and payload["title"] == "清楚令嬢鬼畜肉棒注入孕カン"
    assert payload["maker"] == STUDIO == "Tokyo-Hot" and payload["label"] == "東熱"
    assert payload["series"] == "撮りおろし徹底陵辱ビデオ", "系列栏的几个 AI 重制标记不算系列"
    assert payload["release_date"] == "2016-06-24" and payload["runtime"] == 103.22
    assert payload["actresses"] == [{"japanese_name": "加藤萌衣", "profile_source": "tokyohot", "external_id": "6993"}]
    assert payload["genres"][:4] == ["ブッカケ", "3P～複数プレイ", "オモチャ・異物挿入", "フェラ"] and len(payload["genres"]) == 11
    assert payload["cover_urls"] == [JACKET] and payload["cover_url"] == JACKET
    plot = payload["plot"]
    assert plot.startswith("チャームポイントはスレンダーボディと美脚。"), "开头重复的标题去掉"
    assert plot.count("\n\n") == 1, "两段正文之间空一行"
    assert plot.endswith("膣口をテープで塞がれる。")
    assert "餌食情報" not in plot and "kato moe" not in plot and "身長" not in plot


def test_parse_rejects_a_page_for_another_code_or_a_changed_layout():
    with pytest.raises(SourceFailure) as failed:
        TokyoHotSource().parse(Page(PRODUCT_URL, PRODUCT), "n1162")
    assert failed.value.reason is FailureReason.NOT_FOUND
    with pytest.raises(SourceFailure) as failed:
        TokyoHotSource().parse(Page(PRODUCT_URL, b"<html><body>Maintenance</body></html>"), "n1161")
    assert failed.value.reason is FailureReason.PARSE_ERROR
    with pytest.raises(SourceFailure):
        TokyoHotSource().parse(Page(PRODUCT_URL, PRODUCT), "ABW-358")


def test_plot_from_sentence_handles_pages_without_a_profile():
    fragment = ("タイトル<br />第一段。<br /><br />　第二段。<br /><br />"
                "＝シーンはこちら＝<br /><a href=\"../21084/\">『作品A』</a><br /><a href=\"../21058/\">『作品B』</a>")
    assert plot_from_sentence(fragment, "タイトル") == "第一段。\n\n第二段。\n\n＝シーンはこちら＝\n『作品A』\n『作品B』"
    assert plot_from_sentence("", "x") == ""
    assert plot_from_sentence("餌食情報<br />名前：甲", "x") == ""


def test_plot_is_a_scalar_field_that_keeps_paragraphs():
    assert "plot" in SCALAR_FIELDS
    assert normalized_plot("  一段  文字\r\n\r\n\r\n\r\n二段 \n") == "一段 文字\n\n二段"
    record = TokyoHotSource().parse(Page(PRODUCT_URL, PRODUCT), "n1161")
    settled = settle("n1161", extract(record))
    assert settled["plot"].source == "tokyohot" and settled["plot"].value.count("\n\n") == 1
    # 老快照：dmm / fc2 / 1pondo 把简介放在 `description` 里，也算简介候选
    old = {"id": "112312_478", "title": "x", "description": "官网的说明。"}
    plots = [candidate for candidate in extract(old, source="1pondo") if candidate.field == "plot"]
    assert [candidate.value for candidate in plots] == ["官网的说明。"]
    assert "plot" not in {c.field for c in extract({"id": "x", "title": "y"}, source="javdb")}


def test_apply_writes_plot_with_source_owner_and_keeps_user_text(tmp_root: Path):
    connection = db.connect(ShelfPaths(tmp_root))
    try:
        asset_id = int(connection.execute(
            "INSERT INTO asset(path,name,medium,code,code_key,content_type) VALUES('n1161.mp4','n1161.mp4','video',"
            "'n1161','n1161','uncensored')").lastrowid)
        apply_settled(connection, [asset_id], "n1161", {"plot": Settled("第一段。\n\n第二段。", "tokyohot")},
                      now="2026-10-30T12:00:00+00:00")
        row = connection.execute("SELECT plot, field_owners FROM asset WHERE id=?", (asset_id,)).fetchone()
        assert row["plot"] == "第一段。\n\n第二段。" and owner_of(row["field_owners"], "plot") == "auto:tokyohot"
        connection.execute("UPDATE asset SET plot='用户写的', field_owners=json_set(field_owners,'$.plot','user:manual') "
                           "WHERE id=?", (asset_id,))
        apply_settled(connection, [asset_id], "n1161", {"plot": Settled("别的", "tokyohot")},
                      now="2026-10-30T12:00:00+00:00")
        assert connection.execute("SELECT plot FROM asset WHERE id=?", (asset_id,)).fetchone()[0] == "用户写的"
    finally:
        connection.close()
