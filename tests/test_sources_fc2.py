"""FC2 两站：发行方商品页与 JavArchive 转载页的取页与解析。

搬自 peach `tests/test_metadata_fc2.py`（去掉 fc2cmadb、FC2PPV-DB、JAVten 三站）。夹具落在 `tests/fixtures/sources/`。
"""
from __future__ import annotations

import urllib.parse
from pathlib import Path

import pytest

from hidden_shelf.scrape.access import SOURCES
from hidden_shelf.scrape.policy import SOURCE_SPECS
from hidden_shelf.scrape.sources import SITE_SOURCES, FailureReason, Page, Session, SourceFailure
from hidden_shelf.scrape.sources.fc2 import (FC2, STUDIO, UNRECOGNISED, Fc2Source, canonical_code, runtime_minutes,
                                             storage_original, strip_code, video_id)
from hidden_shelf.scrape.sources.javarchive import JAVARCHIVE, JavArchiveSource, links
from hidden_shelf.scrape.transport import HttpResponse

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


COVER = "https://storage92000.contents.fc2.com/file/261/26076760/1711813737.76.jpg"
TITLE = "みお(19)可愛い巨乳JDの初アナル貫通動画"
ARTICLE = fixture("fc2-article.html")
GONE = fixture("fc2-gone.html")
ARTICLE_URL = "https://adult.contents.fc2.com/article/4364209/"

ARCHIVE_LINK = "/926949-FC2-PPV-4137487-Gカップ・脅威-マジ凄いです！脅威のパイパーGカップグラマラス!-pn.html"
ARCHIVE_TITLE = "Gカップ・脅威 マジ凄いです！脅威のパイパーGカップグラマラス!"
PICS = "https://img.javstore.net/images/2023/12/26/"
SEARCH_PAGE = fixture("javarchive-search.html")
WORK_PAGE = fixture("javarchive-work.html")
SEARCH_URL = "https://javarchive.com/search?q=FC2-PPV-4137487"
REPOST = "https://javarchive.com/800025-fc2ppv-4137487-離婚の後遺症で性欲が止まらない変態女-pn.html"


def page(body, url="https://example.test/") -> Page:
    return Page(url, body.encode() if isinstance(body, str) else body)


def article(body, code):
    return Fc2Source().parse(page(body), code).payload()


def archive(body, code):
    return JavArchiveSource().parse(page(body), code).payload()


def serve(pages):
    """按解码后的地址回页面的假传输；缺的回 404。"""
    calls = []

    def call(request, timeout, limit):
        url = urllib.parse.unquote(request.url)
        calls.append((url, request.headers.get("Referer"), limit))
        body = pages.get(url)
        if isinstance(body, str):
            body = body.encode()
        return HttpResponse(200 if body is not None else 404, {}, body or b"", request.url)

    call.calls = calls
    return call


def replaced(body: bytes, *pairs: tuple[str, str]) -> bytes:
    for old, new in pairs:
        assert old.encode() in body, old
        body = body.replace(old.encode(), new.encode())
    return body


# ---------- 番号与共用函数 ----------

def test_video_id_shapes():
    for code in ("FC2-PPV-4364209", "FC2PPV-4364209", "fc2_ppv_4364209", "FC2 PPV 4364209", "FC2-4364209", "fc2ppv 4364209"):
        assert video_id(code) == "4364209", code
    assert canonical_code("4364209") == "FC2-PPV-4364209"
    assert canonical_code("x") == ""
    assert Fc2Source().article_url("FC2PPV-4364209") == ARTICLE_URL
    # `FC2-PPV-3312576-1` 是 21 段合集里的一段：认出商品号就意味着把合集封面套给每一段。
    for code in ("FC2-PPV-3312576-1", "FC2-PPV-3312576_4", "", "ABW-358"):
        assert video_id(code) == "", code
        assert Fc2Source().article_url(code) == "", code
        assert JavArchiveSource().search_url(code) == "", code
    for site in (Fc2Source(), JavArchiveSource()):
        transport = serve({})
        with pytest.raises(SourceFailure) as caught:
            site.records("FC2-PPV-3312576-1", session=Session(transport))
        assert (caught.value.reason, str(caught.value)) == (FailureReason.NOT_FOUND, UNRECOGNISED)
        assert transport.calls == []


def test_runtime_and_strip_code():
    assert runtime_minutes("41:50") == 41.83
    assert runtime_minutes("1:23:45") == 83.75
    assert runtime_minutes("") is None
    assert runtime_minutes("収録時間 41:50") is None
    assert strip_code("FC2-PPV-4137487 素顔", "4137487") == "素顔"
    assert strip_code("FC2PPV 4137487 - 素顔", "4137487") == "素顔"
    assert strip_code("[FC2-PPV-4137487] 素顔", "4137487") == "素顔"
    assert strip_code("素顔 FC2-PPV-4137487", "4137487") == "素顔 FC2-PPV-4137487"


def test_storage_original_unwraps_thumbnail_and_drops_no_image():
    wrapped = "https://contents-thumbnail2.fc2.com/w276/" + COVER.removeprefix("https://")
    assert storage_original(wrapped) == COVER
    assert storage_original(COVER) == COVER
    assert storage_original("/storage/images/article/no-image.jpg") == ""
    assert storage_original("https://fc2cmadb.com/storage/images/article/no-image.png") == ""
    assert storage_original("") == ""


# ---------- FC2 商品页 ----------

def test_fc2_parse_product_ld_json():
    assert article(ARTICLE, "FC2-PPV-4364209") == {
        "id": "FC2-PPV-4364209", "content_id": "4364209", "source_url": ARTICLE_URL, "title": TITLE,
        "description": "本編と別アングルの2本立て。", "actresses": [], "maker": STUDIO,
        "label": "大人仮面Z", "seller_url": "https://adult.contents.fc2.com/users/otonakamenz/",
        "series": "", "director": "", "release_date": "2024-03-31", "runtime": 41.83,
        "genres": ["おっぱい", "お尻", "素人"], "cover_urls": [COVER], "cover_url": COVER}
    assert (FC2.name, FC2.stage, FC2.cookie, FC2.page_limit) == ("fc2", "official", False, 2 * 1024 * 1024)
    # 卖家名空着时退回主页地址，别把这一栏丢掉。
    nameless = replaced(ARTICLE, ('<a href="https://adult.contents.fc2.com/users/otonakamenz/">大人仮面Z</a>', ""))
    assert article(nameless, "FC2-PPV-4364209")["label"] == "https://adult.contents.fc2.com/users/otonakamenz/"
    # Product 里的图是缩放服务地址时取原件。
    wrapped = replaced(ARTICLE, (COVER, "https://contents-thumbnail2.fc2.com/w276/" + COVER.removeprefix("https://")))
    assert article(wrapped, "FC2-PPV-4364209")["cover_urls"] == [COVER]


def test_fc2_query_asks_once_with_its_page_limit():
    transport = serve({ARTICLE_URL: ARTICLE})
    found = Fc2Source().records("FC2-PPV-4364209", session=Session(transport))
    assert [record.title for record in found] == [TITLE]
    assert transport.calls == [(ARTICLE_URL, "https://adult.contents.fc2.com/", 2 * 1024 * 1024)]


def test_fc2_gone_page_is_not_found():
    with pytest.raises(SourceFailure) as caught:
        article(GONE, "FC2-PPV-4364209")
    assert (caught.value.kind, str(caught.value)) == ("not_found", "FC2 上没有这个商品")
    assert caught.value.is_miss


def test_fc2_sku_mismatch_is_not_found():
    """站上的商品号会被复用给别的投稿，不核 sku 就把另一部片的资料写到这个番号头上。"""
    other = replaced(ARTICLE, ('"sku": "4364209"', '"sku": "4470851"'))
    with pytest.raises(SourceFailure) as caught:
        article(other, "FC2-PPV-4364209")
    assert (caught.value.reason, str(caught.value)) == (FailureReason.NOT_FOUND, "FC2 上没有这个商品")
    with pytest.raises(SourceFailure) as caught:
        article(ARTICLE, "ABW-358")
    assert str(caught.value) == UNRECOGNISED


# ---------- JavArchive ----------

def test_javarchive_links_by_number_boundary():
    assert links(SEARCH_PAGE, "FC2-PPV-4137487") == [ARCHIVE_LINK, "/800025-fc2ppv-4137487-離婚の後遺症で性欲が止まらない変態女-pn.html"]
    assert links(SEARCH_PAGE.decode(), "fc2ppv4137487")[0] == ARCHIVE_LINK
    # 站上 `4137487` 与 `41374870` 都有；按子串比会把后者安到前者头上。
    longer = SEARCH_PAGE.replace(b"4137487", b"41374870")
    assert links(longer, "FC2-PPV-4137487") == []
    assert links(SEARCH_PAGE, "FC2-PPV-9999999") == []
    assert links(SEARCH_PAGE, "ORETD-615") == []
    # 一页里既有别的作品，也有侧栏的热门与归档，挑的必须是这个商品号那一条。
    assert links(SEARCH_PAGE, "FC2-PPV-1863914")[0].startswith("/735702-")
    assert JavArchiveSource().search_url("FC2-PPV-4137487") == SEARCH_URL
    assert JAVARCHIVE.name == "javarchive" and JAVARCHIVE.stage == "community"


def test_javarchive_parse_rows_and_covers():
    assert archive(WORK_PAGE, "FC2-PPV-4137487") == {
        "id": "FC2-PPV-4137487", "content_id": "4137487", "source_url": "https://javarchive.com" + ARCHIVE_LINK,
        "title": ARCHIVE_TITLE, "description": "", "actresses": [], "maker": STUDIO, "label": "",
        "seller_url": "", "series": "", "director": "", "release_date": "2023-11-21", "runtime": 50.05,
        "genres": ["ハメ撮り", "素人", "爆乳"],
        "cover_urls": [PICS + "4137487pl.jpg", PICS + "4137487ps.jpg"], "cover_url": PICS + "4137487pl.jpg"}
    assert archive(replaced(WORK_PAGE, (f"<h1><a href=\"{ARCHIVE_LINK}\" title=\"FC2-PPV-4137487 {ARCHIVE_TITLE}\">FC2-PPV-4137487 {ARCHIVE_TITLE}</a></h1>",
                                        "<h1>FC2PPV 4137487 素顔</h1>")), "FC2-PPV-4137487")["title"] == "素顔"
    # 转存者自己起的名字也认得：封面认位置不认文件名。
    named = replaced(WORK_PAGE, (f"{PICS}4137487pl.jpg", f"{PICS}FC2PPV-4137487.jpg"),
                     (f"{PICS}4137487ps.jpg", f"{PICS}FC2PPV4137487-2.jpg"))
    assert archive(named, "FC2-PPV-4137487")["cover_urls"] == [PICS + "FC2PPV-4137487.jpg", PICS + "FC2PPV4137487-2.jpg"]
    # 只有 schema.org 那个图位时它就是封面；两个图位都没有时留空，`_s.jpg` 预览永远不算。
    no_first = replaced(WORK_PAGE, (f'<div class="fisrst_sc"><img src="{PICS}4137487pl.jpg" alt="FC2-PPV-4137487 {ARCHIVE_TITLE}" /></div>', ""))
    assert archive(no_first, "FC2-PPV-4137487")["cover_url"] == PICS + "4137487ps.jpg"
    none = replaced(no_first, (f'<img itemprop="image" src="{PICS}4137487ps.jpg" alt="FC2-PPV-4137487 {ARCHIVE_TITLE}">', ""))
    assert archive(none, "FC2-PPV-4137487")["cover_urls"] == []
    # 正文那块留空时不去拿 head 里被截断的 description；`--` 标签丢掉。
    bare = replaced(WORK_PAGE, ("标签：ハメ撮り｜素人｜爆乳 <br class='a5555' />", ""),
                    ("日期：2023/11/21 <br class='a5555' />", ""), ("时长：50:03 <br class='a5555' />", ""))
    found = archive(bare, "FC2-PPV-4137487")
    assert (found["genres"], found["release_date"], found["runtime"]) == ([], "", None)
    assert archive(replaced(WORK_PAGE, ("标签：ハメ撮り｜素人｜爆乳", "标签：--")), "FC2-PPV-4137487")["genres"] == []


def test_javarchive_title_unescapes_backslashes():
    """本机真实冒烟（2026-10-29）：站上 `<h1>` 把括号写成 `\\(19\\)`，标题里不能留反斜杠。"""
    escaped = r"みお\(19\)可愛い巨乳JDの初アナル貫通動画 \[完全版\] 50\%OFF"
    body = replaced(WORK_PAGE, (f"<h1><a href=\"{ARCHIVE_LINK}\" title=\"FC2-PPV-4137487 {ARCHIVE_TITLE}\">FC2-PPV-4137487 {ARCHIVE_TITLE}</a></h1>",
                                f"<h1>FC2-PPV-4137487 {escaped}</h1>"))
    title = archive(body, "FC2-PPV-4137487")["title"]
    assert "\\" not in title
    assert title == "みお(19)可愛い巨乳JDの初アナル貫通動画 [完全版] 50%OFF"
    # 日文的全角反斜杠与字母前的反斜杠不是转义，原样保留。
    kept = replaced(WORK_PAGE, (f"<h1><a href=\"{ARCHIVE_LINK}\" title=\"FC2-PPV-4137487 {ARCHIVE_TITLE}\">FC2-PPV-4137487 {ARCHIVE_TITLE}</a></h1>",
                                r"<h1>FC2-PPV-4137487 路径＼風 C:\new</h1>"))
    assert archive(kept, "FC2-PPV-4137487")["title"] == r"路径＼風 C:\new"


def test_javarchive_another_work_is_not_this_one():
    for body, code, wording in ((WORK_PAGE.replace(b"4137487", b"4364209"), "FC2-PPV-4137487", "JavArchive 上没有这个商品"),
                                (b"<div class='news'></div>", "FC2-PPV-4137487", "JavArchive 上没有这个商品"),
                                (WORK_PAGE, "ORETD-615", UNRECOGNISED)):
        with pytest.raises(SourceFailure) as caught:
            archive(body, code)
        assert (caught.value.reason, str(caught.value)) == (FailureReason.NOT_FOUND, wording)


def test_javarchive_records_skip_404_entries():
    repost_page = replaced(WORK_PAGE, (f"{PICS}4137487pl.jpg", f"{PICS}FC2PPV-4137487.jpg"),
                           (f'<img itemprop="image" src="{PICS}4137487ps.jpg" alt="FC2-PPV-4137487 {ARCHIVE_TITLE}">', ""))
    both = serve({SEARCH_URL: SEARCH_PAGE, "https://javarchive.com" + ARCHIVE_LINK: WORK_PAGE, REPOST: repost_page})
    found = JavArchiveSource().records("FC2-PPV-4137487", session=Session(both))
    assert [record.cover_urls for record in found] == [(PICS + "4137487pl.jpg", PICS + "4137487ps.jpg"),
                                                       (PICS + "FC2PPV-4137487.jpg",)]
    assert both.calls == [(SEARCH_URL, "https://javarchive.com/", 2 * 1024 * 1024),
                          ("https://javarchive.com" + ARCHIVE_LINK, "https://javarchive.com/", 2 * 1024 * 1024),
                          (REPOST, "https://javarchive.com/", 2 * 1024 * 1024)]
    # 第一条 404 时只剩还在的那一条；全对不上归 not_found。
    one = serve({SEARCH_URL: SEARCH_PAGE, REPOST: WORK_PAGE})
    assert len(JavArchiveSource().records("FC2-PPV-4137487", session=Session(one))) == 1
    stray = serve({SEARCH_URL: SEARCH_PAGE, REPOST: WORK_PAGE.replace(b"4137487", b"4364209")})
    with pytest.raises(SourceFailure) as caught:
        JavArchiveSource().records("FC2-PPV-4137487", session=Session(stray))
    assert (caught.value.reason, str(caught.value)) == (FailureReason.NOT_FOUND, "JavArchive 上没有这个商品")
    # 搜索无命中是没有；403 保持它的档。
    with pytest.raises(SourceFailure) as caught:
        JavArchiveSource().records("FC2-PPV-4137487", session=Session(serve({SEARCH_URL: SEARCH_PAGE.replace(b"4137487", b"41374870")})))
    assert str(caught.value) == "JavArchive 上没有这个商品"
    refused = lambda request, timeout, limit: HttpResponse(403, {}, b"", request.url)
    with pytest.raises(SourceFailure) as caught:
        JavArchiveSource().records("FC2-PPV-4137487", session=Session(refused))
    assert (caught.value.reason, str(caught.value)) == (FailureReason.AUTH_REQUIRED, "HTTP 403")
    # `fetch` 只取第一条。
    first = JavArchiveSource().query("FC2-PPV-4137487", session=Session(both))
    assert first.cover_urls == (PICS + "4137487pl.jpg", PICS + "4137487ps.jpg")


def test_all_nine_sites_are_registered_and_tables_agree():
    assert set(SITE_SOURCES) == set(SOURCE_SPECS) == set(SOURCES) == {
        "r18dev", "dmm", "1pondo", "tokyohot", "fc2", "javarchive", "javdb", "javbus", "avbase"}
    for name, cls in SITE_SOURCES.items():
        config = cls.DEFAULT
        assert config.name == name
        assert config.cookie == bool(SOURCES[name].get("cookie")), name
        assert set(config.domains) <= set(SOURCES[name]["domains"]), name
        assert (config.stage in {"official", "official_mirror"}) == SOURCE_SPECS[name].official, name
