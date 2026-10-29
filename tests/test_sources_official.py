"""官方来源解析器：r18.dev、DMM、一本道。

搬自 peach `tests/test_metadata_r18dev.py`、`test_metadata_dmm.py`、`test_metadata_1pondo.py`，去掉
`LibraryMetadataProvider` 那一层；夹具落在 `tests/fixtures/sources/`。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from hidden_shelf.scrape.access import SourcePaused
from hidden_shelf.scrape.sources import SITE_SOURCES, FailureReason, Page, Session, SourceFailure
from hidden_shelf.scrape.sources.dmm import (DETAIL_ATTEMPTS, DETAIL_QUERY, DMM, SEARCH_LIMIT, SEARCH_QUERY,
                                             DmmSource, code_from_cid, code_parts, guessed_cid, matching_cids,
                                             release_date)
from hidden_shelf.scrape.sources.onepondo import ONEPONDO, STUDIO, OnePondoSource, movie_id, names_this_studio
from hidden_shelf.scrape.sources.r18dev import ACTRESS_IMAGE, R18DEV, R18DevSource, actresses, with_japanese
from hidden_shelf.scrape.transport import HttpResponse, NotFound, Unavailable

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def fixture(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def encoded(data) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode()


def serve(pages):
    """假传输：按 URL 答页面；值是异常就抛；没登记的 URL 回 404。"""
    calls = []

    def call(request, timeout, limit):
        calls.append((request.url, request.headers.get("Referer"), limit))
        body = pages.get(request.url)
        if isinstance(body, Exception):
            raise body
        return HttpResponse(200 if body is not None else 404, {}, body or b"", request.url)

    call.calls = calls
    return call


# ---------- r18.dev ----------

DETAIL_URL = "https://r18.dev/videos/vod/movies/detail/-/dvd_id=ABW-358/json"
COMBINED_URL = "https://r18.dev/videos/vod/movies/detail/-/combined=118abw358/json"
JACKET = "https://pics.dmm.co.jp/digital/video/118abw00358/118abw00358pl.jpg"
DETAIL = fixture("r18dev-detail")
COMBINED = fixture("r18dev-combined")
JAPANESE_ACTRESS = {"japanese_name": "涼森れむ", "name_kana": "すずもりれむ", "name_romaji": "Remu Suzumori",
                    "dmm_id": 1051912, "thumb_url": "https://pics.dmm.co.jp/mono/actjpgs/suzumori_remu.jpg",
                    "profile_source": "r18dev"}
#: `R18DevSource().query('ABW-358')` 对这份夹具交出的 payload，逐键钉住（与 peach `EXPECTED` 相同）。
R18_EXPECTED = {
    "id": "ABW-358", "content_id": "118abw358", "source_url": DETAIL_URL, "title": "涼森れむ流", "maker": "Prestige",
    "series": "保健室の先生", "release_date": "2023-05-26", "director": "Charlie Nakata", "label": "ABSOLUTELY WONDERFUL",
    "runtime": 210, "cover_urls": [JACKET], "cover_url": JACKET, "actresses": [JAPANESE_ACTRESS],
    "genres": ["スレンダー", "企画"], "raw": DETAIL,
    "translations": [{"language": "ja", "title": "涼森れむ流", "series": "保健室の先生",
                      "label": "ABSOLUTELY WONDERFUL", "director": "チャーリー中田"}],
    "combined": COMBINED}


def test_r18dev_config_and_urls():
    site = R18DevSource()
    assert site.config is R18DEV
    assert (R18DEV.name, R18DEV.label, R18DEV.provider, R18DEV.stage, R18DEV.interval, R18DEV.cookie,
            R18DEV.page_limit) == ("r18dev", "r18.dev", "r18-json", "official_mirror", 2.0, False, 2 * 1024 * 1024)
    assert site.detail_url("ABW-358") == DETAIL_URL
    assert site.combined_url("118abw358") == COMBINED_URL
    assert site.detail_url("ABW 358") == DETAIL_URL.replace("ABW-358", "ABW%20358")


def test_parse_english_page():
    record = R18DevSource().parse(Page(DETAIL_URL, encoded(DETAIL)), "ABW-358")
    assert (record.source, record.provenance, record.code, record.source_url) == ("r18dev", "r18-json", "ABW-358", DETAIL_URL)
    assert (record.title, record.studio, record.label, record.series, record.director, record.release_date,
            record.runtime, record.cover_urls) == ("Remu Style", "Prestige", "ABSOLUTELY WONDERFUL", "HOW TO SEX",
                                                   "Charlie Nakata", "2023-05-26", 210, (JACKET,))
    assert record.performers == ({"japanese_name": "Remu Suzumori"},)
    assert record.tags == ("Slender", "Variety")
    assert (record.extra["content_id"], record.extra["raw"]) == ("118abw358", DETAIL)


def test_parse_tolerates_str_body_and_missing_fields():
    record = R18DevSource().parse(Page(DETAIL_URL, json.dumps({"content_id": "118abw358", "title": "Remu Style"})), "ABW-358")
    assert (record.release_date, record.director, record.cover_urls, record.runtime, record.tags) == ("", "", (), None, ())
    payload = record.payload()
    assert (payload["release_date"], payload["director"], payload["cover_url"], payload["cover_urls"],
            payload["genres"], payload["actresses"]) == ("", "", "", [], [], [])


def test_with_japanese_replaces_names_and_genres_and_keeps_brand_maker():
    record = R18DevSource().parse(Page(DETAIL_URL, encoded(DETAIL)), "ABW-358")
    japanese = with_japanese(record, COMBINED)
    assert japanese.performers == (JAPANESE_ACTRESS,)
    assert japanese.tags == ("スレンダー", "企画")
    assert japanese.studio == "Prestige", "厂牌实体用品牌名，日文写法会另起一个实体"
    assert japanese.extra["translations"] == R18_EXPECTED["translations"]
    assert japanese.extra["combined"] is COMBINED
    assert (japanese.title, japanese.series) == ("涼森れむ流", "保健室の先生")


@pytest.mark.parametrize("combined", [{"content_id": "118xyz001", "title_ja": "别的片"}, ["not", "a", "dict"]])
def test_combined_for_another_work_counts_as_missing(combined):
    """英文页的标题、系列与罗马字演员不交出去：落了库，系列与演员就成了英文的实体规范名。"""
    record = R18DevSource().parse(Page(DETAIL_URL, encoded(DETAIL)), "ABW-358")
    bare = with_japanese(record, combined)
    assert (bare.title, bare.series, bare.performers) == ("", "", ())
    assert (bare.studio, bare.release_date, bare.cover_urls, bare.tags) == (record.studio, record.release_date,
                                                                          record.cover_urls, record.tags)


def test_an_empty_japanese_side_leaves_title_series_and_cast_empty():
    record = R18DevSource().parse(Page(DETAIL_URL, encoded(DETAIL)), "ABW-358")
    bare = with_japanese(record, {"content_id": "118abw358", "actresses": [{"name_kanji": ""}], "categories": []})
    assert (bare.title, bare.series, bare.performers, bare.tags) == ("", "", (), record.tags)
    assert bare.extra["translations"] == [{"language": "ja", "title": "", "series": "", "label": "", "director": ""}]


def test_actresses_build_the_official_avatar_only_from_a_bare_filename():
    rows = [{"id": 7, "image_url": "a.jpg", "name_kanji": "甲"}, {"id": 8, "image_url": "x/y.jpg", "name_romaji": "Otsu"},
            {"image_url": "", "name_kanji": "丙"}]
    found = actresses(rows)
    assert [row["thumb_url"] for row in found] == [ACTRESS_IMAGE.format(filename="a.jpg"), "", ""]
    assert [row["japanese_name"] for row in found] == ["甲", "", "丙"]
    assert found[1]["name_romaji"] == "Otsu"
    assert [row["dmm_id"] for row in found] == [7, 8, ""]
    assert actresses(None) == []


def test_query_merges_japanese_page():
    transport = serve({DETAIL_URL: encoded(DETAIL), COMBINED_URL: encoded(COMBINED)})
    record = R18DevSource().query("ABW-358", session=Session(transport))
    assert transport.calls == [(DETAIL_URL, "https://r18.dev/", 2 * 1024 * 1024),
                               (COMBINED_URL, "https://r18.dev/", 2 * 1024 * 1024)]
    assert record.payload() == R18_EXPECTED


def test_without_the_japanese_page_only_language_neutral_fields_stand():
    english = dict(R18_EXPECTED, title="", series="", actresses=[], genres=["Slender", "Variety"])
    english.pop("translations")
    english.pop("combined")
    for body in (Unavailable("HTTP 503"), NotFound("HTTP 404"), b"<html>maintenance</html>"):
        transport = serve({DETAIL_URL: encoded(DETAIL), COMBINED_URL: body})
        assert R18DevSource().query("ABW-358", session=Session(transport)).payload() == english, body
    with patch("hidden_shelf.scrape.transport.NETWORK_RETRY_DELAYS", ()):
        transport = serve({DETAIL_URL: encoded(DETAIL), COMBINED_URL: httpx.ConnectError("reset")})
        assert R18DevSource().query("ABW-358", session=Session(transport)).payload() == english


def test_404_is_not_found():
    with pytest.raises(SourceFailure) as caught:
        R18DevSource().query("ABW-358", session=Session(serve({})))
    assert (caught.value.reason, caught.value.kind, str(caught.value)) == (FailureReason.NOT_FOUND, "not_found", "HTTP 404")


def test_identity_mismatch_is_parse_error():
    with pytest.raises(SourceFailure) as caught:
        R18DevSource().parse(Page(DETAIL_URL, encoded(dict(DETAIL, content_id="118abw359"))), "ABW-358")
    assert (caught.value.reason, caught.value.kind, str(caught.value)) == (FailureReason.PARSE_ERROR, "unavailable", "来源返回的番号不匹配")
    for body in (b"<html>cloudflare</html>", b"[1, 2]"):
        with pytest.raises(SourceFailure) as caught:
            R18DevSource().parse(Page(DETAIL_URL, body), "ABW-358")
        assert (caught.value.reason, str(caught.value)) == (FailureReason.PARSE_ERROR, "r18.dev 返回的不是作品 JSON")


def test_r18dev_transport_tiers_keep_their_semantics():
    with pytest.raises(SourceFailure) as caught:
        R18DevSource().query("ABW-358", session=Session(serve({DETAIL_URL: Unavailable("HTTP 503")})))
    assert (caught.value.reason, caught.value.status_code) == (FailureReason.SERVER_ERROR, 503)
    with pytest.raises(SourcePaused):
        R18DevSource().query("ABW-358", session=Session(serve({DETAIL_URL: SourcePaused("来源正在冷却")})))
    with pytest.raises(SourceFailure) as caught:
        R18DevSource().query("ABW-358", session=Session(serve({DETAIL_URL: Unavailable("本趟对外请求配额已用完")})))
    assert (caught.value.reason, str(caught.value)) == (FailureReason.NETWORK, "本趟对外请求配额已用完")


# ---------- DMM ----------

ENDPOINT = "https://api.video.dmm.co.jp/graphql"
PAGE_URL = "https://video.dmm.co.jp/av/content/?id=ssis00057"
COVER = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00057/ssis00057pl.jpg"
SAMPLE = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00057/ssis00057-1.jpg"
ITEM = fixture("dmm-content")
SEARCH_FIXTURE = fixture("dmm-search")
FKOS = {"id": "h_1721fkos00006", "title": "個人撮影6", "makerContentId": "FKOS-006", "makerReleasedAt": "2023-01-19T15:00:00Z",
        "duration": 3600, "maker": {"id": "1", "name": "FKOS"}, "actresses": [], "genres": [], "packageImage": None}
DMM_EXPECTED = {
    "id": "SSIS-057", "content_id": "ssis00057", "source_url": PAGE_URL, "title": "パンティーストッキングマニア 三宮つばき",
    "maker": "エスワン ナンバーワンスタイル", "label": "S1 NO.1 STYLE", "series": "", "director": "肉尊",
    "release_date": "2021-05-07", "runtime": 151.15, "cover_urls": [COVER], "cover_url": COVER,
    "actresses": [{"japanese_name": "三宮つばき", "dmm_id": "1062909"}], "genres": ["ギリモザ", "単体作品"],
    "description": "新人OLの‘つばき’は才色兼備で", "sample_images": [SAMPLE], "raw": ITEM}


def graphql(contents=None, items=None):
    """假接口：按请求体里的查询与变量答复。`contents` 是搜索结果的 cid 列，`items` 是 cid → 商品或异常。"""
    calls = []
    items = items or {}

    def call(request, timeout, limit):
        payload = json.loads(request.body)
        variables = payload["variables"]
        calls.append((request.method, request.url, request.headers.get("Referer"), request.headers.get("Content-Type"),
                      limit, payload["query"], variables))
        if payload["query"] == SEARCH_QUERY:
            body = {"data": {"legacySearchPPV": {"result": {"contents": [{"id": cid} for cid in contents or []]}}}}
        else:
            item = items.get(variables["id"])
            if isinstance(item, Exception):
                raise item
            body = {"data": {"ppvContent": item}}
        return HttpResponse(200, {}, encoded(body), request.url)

    call.calls = calls
    return call


def asked(transport):
    """这趟发了哪几条查询：`('detail', cid)` 或 `('search', 关键词)`。"""
    return [("search", variables["queryWord"]) if query == SEARCH_QUERY else ("detail", variables["id"])
            for _, _, _, _, _, query, variables in transport.calls]


def test_code_from_cid_keeps_the_release_suffix():
    for product, expected in {"1dandy00899": "DANDY-899", "118abw00220": "ABW-220", "h_086iqqq00026": "IQQQ-026",
                              "1dandy00851c": "DANDY-851C", "48midv00012ai": "MIDV-012AI"}.items():
        assert code_from_cid(product) == expected
    assert code_from_cid("opaque_cid") == ""


def test_code_parts_keep_the_numeric_prefix_and_the_digits_as_written():
    assert code_parts("SSIS-057") == ("", "SSIS", "057")
    assert code_parts("ssis057") == ("", "SSIS", "057")
    assert code_parts("300MIUM-1239") == ("300", "MIUM", "1239")
    assert code_parts("MIDV-012ai") == ("", "MIDV", "012AI")
    for code in ("", None, "FC2-PPV-1812235", "092415_001", "n0780"):
        assert code_parts(code) is None, code


def test_guessed_cid_and_matching_cids():
    assert guessed_cid("SSIS-057") == "ssis00057"
    assert guessed_cid("START-640") == "start00640"
    assert guessed_cid("300MIUM-1239") == "300mium01239"
    assert guessed_cid("DANDY-851C") == "dandy00851c"
    assert guessed_cid("092415_001") == ""
    # 搜 `SSIS 057` 前几条是 `ssis00570`；搜 `ERK 116` 会带出 `gerk116`。厂牌数字前缀与 `h_` 前缀都容得下。
    search_ids = [row["id"] for row in SEARCH_FIXTURE["data"]["legacySearchPPV"]["result"]["contents"]]
    assert matching_cids("SSIS-057", search_ids) == ["ssis00057", "1ssis00057"]
    assert matching_cids("ERK-116", ["h_1838erkr01116", "gerk116", "erk116"]) == ["erk116"]
    assert matching_cids("FKOS-006", ["h_1721fkos00006"]) == ["h_1721fkos00006"]
    assert matching_cids("FNS-061", ["1fns00061"]) == ["1fns00061"]
    # `MIDV 012` 同时命中原版与 AI 重制版，原版先核。
    assert matching_cids("MIDV-012", ["48midv00012ai", "midv00127", "midv00012", "48midv00012"]) == ["midv00012", "48midv00012", "48midv00012ai"]
    assert matching_cids("DANDY-851C", ["1dandy00851", "1dandy00851c", "1dandy00851ai"]) == ["1dandy00851c"]
    assert matching_cids("300MIUM-1239", ["300mium01239", "mium01239", "259mium01239"]) == ["300mium01239"]
    assert matching_cids("092415_001", ["anything"]) == []


def test_release_date_to_jst():
    assert release_date("2021-05-06T15:00:00Z") == "2021-05-07"
    assert release_date("2026-10-21T15:00:00+00:00") == "2026-10-22"
    assert release_date("2021-05-07") == "2021-05-07"
    assert release_date("2021-05-07T00:00:00") == "2021-05-07"
    assert release_date("not a date at all") == "not a date"
    assert release_date(None) == ""


def test_dmm_config_and_endpoint():
    site = DmmSource()
    assert site.config is DMM
    assert (DMM.name, DMM.label, DMM.provider, DMM.stage, DMM.interval, DMM.cookie, DMM.page_limit) == (
        "dmm", "DMM / FANZA", "dmm-graphql", "official", 2.0, False, 1024 * 1024)
    assert site.endpoint() == ENDPOINT
    assert site.content_url("ssis00057") == PAGE_URL
    assert site.content_url("h_1721fkos00006") == PAGE_URL.replace("ssis00057", "h_1721fkos00006")


def test_dmm_parse_record():
    record = DmmSource().parse(Page(PAGE_URL, encoded(ITEM)), "SSIS-057")
    assert (record.source, record.provenance, record.code, record.source_url) == ("dmm", "dmm-graphql", "SSIS-057", PAGE_URL)
    assert (record.title, record.studio, record.label, record.series, record.director, record.release_date,
            record.runtime, record.cover_urls) == (ITEM["title"], "エスワン ナンバーワンスタイル", "S1 NO.1 STYLE", "",
                                                   "肉尊", "2021-05-07", 151.15, (COVER,))
    assert record.performers == ({"japanese_name": "三宮つばき", "dmm_id": "1062909"},)
    assert record.tags == ("ギリモザ", "単体作品")
    assert (record.extra["content_id"], record.extra["sample_images"], record.extra["raw"]) == ("ssis00057", [SAMPLE], ITEM)
    assert record.payload() == DMM_EXPECTED


def test_dmm_parse_tolerates_missing_fields_and_null_objects():
    record = DmmSource().parse(Page(PAGE_URL, json.dumps({"id": "ssis00057", "title": "x", "series": None,
                                                          "packageImage": None, "duration": 0})), "SSIS-057")
    assert (record.series, record.director, record.release_date, record.runtime, record.cover_urls,
            record.tags, record.performers) == ("", "", "", None, (), (), ())
    assert record.payload()["cover_url"] == ""


def test_query_hits_the_guessed_cid_in_one_post():
    transport = graphql(items={"ssis00057": ITEM})
    record = DmmSource().query("SSIS-057", session=Session(transport))
    assert record.payload() == DMM_EXPECTED
    assert asked(transport) == [("detail", "ssis00057")]
    assert transport.calls[0] == ("POST", ENDPOINT, "https://api.video.dmm.co.jp/", "application/json", 1024 * 1024,
                                  DETAIL_QUERY, {"id": "ssis00057"})


def test_fetch_tries_guess_then_search():
    """`FKOS-006` 的 cid 带厂牌数字前缀 `h_1721`，猜不出来，只有搜索答得出。"""
    transport = graphql(contents=["h_1721fkos00006"], items={"h_1721fkos00006": FKOS})
    record = DmmSource().query("FKOS-006", session=Session(transport))
    assert (record.code, record.extra["content_id"], record.release_date, record.cover_urls) == (
        "FKOS-006", "h_1721fkos00006", "2023-01-20", ())
    assert asked(transport) == [("detail", "fkos00006"), ("search", "FKOS 006"), ("detail", "h_1721fkos00006")]
    assert transport.calls[1][6] == {"limit": SEARCH_LIMIT, "sort": "RELEASE_DATE", "queryWord": "FKOS 006"}


def test_a_detail_that_is_another_film_is_not_trusted():
    other = dict(ITEM, id="ssis00570", makerContentId="SSIS-570")
    transport = graphql(contents=["1ssis00057", "2ssis00057"],
                        items={"1ssis00057": other, "2ssis00057": dict(ITEM, id="2ssis00057")})
    record = DmmSource().query("SSIS-057", session=Session(transport))
    assert record.extra["content_id"] == "2ssis00057"
    assert asked(transport) == [("detail", "ssis00057"), ("search", "SSIS 057"), ("detail", "1ssis00057"), ("detail", "2ssis00057")]


def test_search_hits_are_capped_and_the_guess_is_not_asked_twice():
    transport = graphql(contents=["midv00012", "48midv00012", "48midv00012ai"], items={})
    with pytest.raises(SourceFailure) as caught:
        DmmSource().query("MIDV-012", session=Session(transport))
    assert (caught.value.reason, str(caught.value)) == (FailureReason.NOT_FOUND, "DMM 没有这个番号")
    assert asked(transport) == [("detail", "midv00012"), ("search", "MIDV 012"), ("detail", "48midv00012"), ("detail", "48midv00012ai")]
    assert len(asked(transport)) - 2 == DETAIL_ATTEMPTS


def test_dmm_failures_come_through_the_shared_reason_table():
    with pytest.raises(SourceFailure) as caught:
        DmmSource().query("FC2-PPV-1812235", session=Session(graphql()))
    assert (caught.value.reason, str(caught.value)) == (FailureReason.NOT_FOUND, "认不出可以问 DMM 的番号")
    with pytest.raises(SourceFailure) as caught:
        DmmSource().parse(Page(PAGE_URL, encoded(dict(ITEM, makerContentId="SSIS-570", id="ssis00570"))), "SSIS-057")
    assert (caught.value.reason, caught.value.kind, str(caught.value)) == (FailureReason.PARSE_ERROR, "unavailable", "来源返回的番号不匹配")
    for body in (b"<html>maintenance</html>", b"[1, 2]", b'{"title": "no id"}'):
        with pytest.raises(SourceFailure) as caught:
            DmmSource().parse(Page(PAGE_URL, body), "SSIS-057")
        assert (caught.value.reason, str(caught.value)) == (FailureReason.PARSE_ERROR, "DMM 返回的不是作品 JSON")


def test_a_refused_query_and_a_non_json_reply_are_parse_errors():
    refused = lambda request, timeout, limit: HttpResponse(
        200, {}, b'{"errors": [{"message": "Cannot query field \\"largeUrl\\""}]}', request.url)
    with pytest.raises(SourceFailure) as caught:
        DmmSource().query("SSIS-057", session=Session(refused))
    assert (caught.value.reason, str(caught.value)) == (FailureReason.PARSE_ERROR, 'DMM 拒绝了这条查询：Cannot query field "largeUrl"')
    cloudflare = lambda request, timeout, limit: HttpResponse(200, {}, b"<html>Just a moment</html>", request.url)
    with pytest.raises(SourceFailure) as caught:
        DmmSource().query("SSIS-057", session=Session(cloudflare))
    assert (caught.value.reason, str(caught.value)) == (FailureReason.PARSE_ERROR, "DMM 返回的不是作品 JSON")


def test_dmm_transport_tiers_keep_their_semantics():
    with pytest.raises(SourceFailure) as caught:
        DmmSource().query("SSIS-057", session=Session(graphql(items={"ssis00057": Unavailable("HTTP 503")})))
    assert (caught.value.reason, caught.value.status_code) == (FailureReason.SERVER_ERROR, 503)
    with pytest.raises(SourceFailure) as caught:
        DmmSource().query("SSIS-057", session=Session(graphql(items={"ssis00057": Unavailable("HTTP 422")})))
    assert (caught.value.reason, caught.value.status_code) == (FailureReason.NETWORK, 422)
    with pytest.raises(SourcePaused):
        DmmSource().query("SSIS-057", session=Session(graphql(items={"ssis00057": SourcePaused("来源正在冷却")})))


# ---------- 一本道 ----------

PONDO_COVER = "https://www.1pondo.tv/moviepages/112312_478/images/str.jpg"
PONDO_DETAIL = "https://www.1pondo.tv/dyn/phpauto/movie_details/movie_id/112312_478.json"
PONDO = fixture("1pondo-detail")


def details(**changes) -> bytes:
    raw = {**PONDO, **changes}
    return encoded(raw)


def parse_details(body, code):
    return OnePondoSource().parse(Page(PONDO_DETAIL, body if isinstance(body, bytes) else body.encode()), code).payload()


def test_movie_id_and_studio_evidence():
    assert movie_id("112312_478") == "112312_478"
    assert movie_id("092415-001") == "092415_001"
    assert OnePondoSource().detail_url("092415-001") == "https://www.1pondo.tv/dyn/phpauto/movie_details/movie_id/092415_001.json"
    # `125735_816` 是手机录像 `VID_20220818_125735_816.mp4` 剪出来的，12 月 57 日不存在。
    for code in ("ABW-358", "FC2-PPV-4364209", "n1234", "125735-816", "", None):
        assert movie_id(code) == "", repr(code)
        assert OnePondoSource().detail_url(code) == "", repr(code)
    transport = serve({})
    with pytest.raises(SourceFailure) as caught:
        OnePondoSource().query("ABW-358", session=Session(transport))
    assert (caught.value.reason, str(caught.value)) == (FailureReason.NOT_FOUND, "这个番号不是一本道的写法")
    assert transport.calls == []
    # 一本道与カリビアンコム 的番号同形，问不问它看本机手上的路径、文件名与库里厂牌。
    assert names_this_studio("B:/云下载/[JAV] [Uncensored] 1pon 112312_478/x.mp4", "", "")
    assert names_this_studio("B:/MVP/1pondo-092415_159-001-FHD/x.mp4", "x.mp4", None)
    assert names_this_studio("", "", "一本道")
    assert not names_this_studio("B:/云下载/Carib-040221-001-FHD/x.mp4", "x.mp4", "カリビアンコム")
    assert not names_this_studio()


def test_1pondo_parse_record():
    assert parse_details(details(), "112312_478") == {
        "id": "112312_478", "content_id": "112312_478", "source_url": "https://www.1pondo.tv/movies/112312_478/",
        "title": "裸演奏 〜第5回演奏会・ホルン〜", "description": "楽器とエロスのハーモニー。",
        "actresses": [{"japanese_name": "飯岡かなこ", "name_romaji": "Kanako Iioka"}],
        "maker": STUDIO, "label": "", "series": "裸演奏", "director": "", "release_date": "2012-11-23",
        "runtime": 64.57, "genres": ["AV女優", "スレンダー", "中出し", "720p"],
        "cover_urls": [PONDO_COVER], "cover_url": PONDO_COVER}
    # 官网按秒记时长，库里按分钟。
    assert parse_details(details(Duration=0), "112312_478")["runtime"] is None
    assert parse_details(details(Duration=None), "112312_478")["runtime"] is None
    # 日文名是身份，罗马字作别名跟着走；只有 `Actor` 一栏时也认得她。
    found = parse_details(details(ActressesJa=["白咲碧", "陽菜"], ActressesEn=["Aoi Shirosaki", "Hina"]), "112312_478")
    assert found["actresses"] == [{"japanese_name": "白咲碧", "name_romaji": "Aoi Shirosaki"},
                                  {"japanese_name": "陽菜", "name_romaji": "Hina"}]
    found = parse_details(details(ActressesJa=[], ActressesEn=[]), "112312_478")
    assert found["actresses"] == [{"japanese_name": "飯岡かなこ", "name_romaji": ""}]
    # 剧照缺了退回列表缩略图。
    without = {key: value for key, value in PONDO.items() if not key.startswith("Thumb")}
    assert OnePondoSource().parse(Page(PONDO_DETAIL, encoded(without)), "112312_478").cover_url == \
        "https://www.1pondo.tv/moviepages/112312_478/images/thum_b.jpg"
    assert ONEPONDO.name == "1pondo"


def test_parse_rejects_other_movie_id():
    for body, code, wording in ((details(MovieID="092415_001"), "112312_478", "一本道回的作品号对不上这个番号"),
                                (b"null", "112312_478", "一本道回的作品号对不上这个番号"),
                                (details(), "ABW-358", "这个番号不是一本道的写法")):
        with pytest.raises(SourceFailure) as caught:
            parse_details(body, code)
        assert (caught.value.reason, str(caught.value)) == (FailureReason.NOT_FOUND, wording)
    with pytest.raises(SourceFailure) as caught:
        parse_details("<html>维护中</html>", "112312_478")
    assert (caught.value.reason, str(caught.value)) == (FailureReason.PARSE_ERROR, "一本道返回的不是作品 JSON")


def test_1pondo_query_and_404():
    transport = serve({PONDO_DETAIL: details()})
    found = OnePondoSource().query("112312-478", session=Session(transport))
    assert found.title == "裸演奏 〜第5回演奏会・ホルン〜"
    assert transport.calls == [(PONDO_DETAIL, "https://www.1pondo.tv/", 1024 * 1024)]
    with pytest.raises(SourceFailure) as caught:
        OnePondoSource().query("112312_478", session=Session(serve({})))
    assert (caught.value.kind, str(caught.value)) == ("not_found", "一本道站上没有这部片")


def test_the_three_official_sites_are_registered():
    assert {"r18dev", "dmm", "1pondo"} <= set(SITE_SOURCES)
    assert SITE_SOURCES["r18dev"] is R18DevSource
    assert SITE_SOURCES["dmm"] is DmmSource
    assert SITE_SOURCES["1pondo"] is OnePondoSource
    for name, cls in SITE_SOURCES.items():
        assert cls.DEFAULT.name == name
