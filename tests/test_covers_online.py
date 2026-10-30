"""联网封面：候选拼法、量尺寸择优、落盘归属。断言搬自 peach `tests/test_jav_covers.py` 的 `CodeShapeTests`、
`ContentIdTests`、`BestCoverTests`。"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from PIL import Image

from hidden_shelf import db
from hidden_shelf.field_owners import USER_MANUAL, FieldWrite, auto_owner, owner_of, write_owned_fields
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scrape import covers
from hidden_shelf.scrape.covers import (COVER_IMAGE, PRODUCT_IMAGE, Candidate, best_cover, candidate_for,
                                        candidates_from_records, cid_variants, code_variants, content_id_images,
                                        dmm_cdn_images, install_online_cover, is_javdb_image, official_image_candidates,
                                        referer_for)
from hidden_shelf.scrape.transport import HttpResponse, NotFound, Unavailable


def jpeg(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (128, 90, 70)).save(buffer, format="JPEG")
    return buffer.getvalue()


def gif(width, height, frames=2):
    images = [Image.new("RGB", (width, height), (i * 40, 90, 70)) for i in range(frames)]
    buffer = io.BytesIO()
    images[0].save(buffer, format="GIF", save_all=True, append_images=images[1:])
    return buffer.getvalue()


def transport_for(pages: dict, *, final_url: dict | None = None):
    """假传输：`url -> (status, body)` 或异常；记录每次请求的 Range 头与是不是整张下载。"""
    calls = []

    def call(request, timeout, limit):
        calls.append((request.url, request.headers.get("Range"), request.headers.get("Referer")))
        body = pages.get(request.url)
        if isinstance(body, Exception):
            raise body
        if body is None:
            return HttpResponse(404, {}, b"", request.url)
        status, data = body
        return HttpResponse(status, {}, data, (final_url or {}).get(request.url, request.url))

    call.calls = calls
    return call


def test_code_variants_and_cid_variants():
    assert code_variants("278GYAN-017") == ["278GYAN-017", "GYAN-017"]
    assert code_variants("ABW-232") == ["ABW-232"]
    assert code_variants("278gyan17") == ["278GYAN-017", "GYAN-017"]
    assert "waaa00415" in cid_variants("waaa415")
    assert cid_variants("bazx00302")[0] == "bazx00302"
    assert "abw00232" in cid_variants("118abw232")
    assert cid_variants("") == []


def test_dmm_urls_expand_to_modern_and_legacy_cdn_routes():
    original = "https://pics.dmm.co.jp/mono/movie/adult/118abw232/118abw232pl.jpg"
    urls = {candidate.url for candidate in dmm_cdn_images(original)}
    assert "https://awsimgsrc.dmm.com/dig/mono/movie/118abw232/118abw232pl.jpg" in urls
    assert "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/118abw232/118abw232pl.jpg" in urls
    assert original in urls and len(urls) == 3
    dmm = "https://pics.dmm.co.jp/digital/video/dazd00308/dazd00308pl.jpg"
    assert {c.url for c in official_image_candidates(dmm)} == {c.url for c in dmm_cdn_images(dmm)}
    mgs = "https://image.mgstage.com/images/prestige/sp/pasn/031/pake-03_sp-pasn-031.jpg"
    assert [c.url for c in official_image_candidates(mgs)] == [mgs]
    assert official_image_candidates("https://c0.jdbstatic.com/covers/xe/XeVp0e.jpg") == []
    assert official_image_candidates("") == []
    assert [c.url for c in content_id_images("waaa415")] == [
        "https://awsimgsrc.dmm.com/dig/digital/video/waaa415/waaa415pl.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/waaa415/waaa415pl.jpg",
        "https://awsimgsrc.dmm.com/dig/digital/video/waaa00415/waaa00415pl.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/waaa00415/waaa00415pl.jpg"]


def test_candidate_for_and_referers():
    assert candidate_for(mgs := "https://image.mgstage.com/images/prestige/abw/358/pb_e_abw-358.jpg") == Candidate(
        "image.mgstage.com", mgs, "https://www.mgstage.com/", PRODUCT_IMAGE)
    assert candidate_for("https://image.mgstage.com/images/x/popsample_1.jpg").kind == "preview"
    assert candidate_for("https://pics.dmm.co.jp/digital/video/a/apl.jpg").referer == "https://www.dmm.co.jp/"
    assert referer_for("https://img.javstore.net/images/x.jpg") == "https://javarchive.com/"
    assert referer_for("https://storage92000.contents.fc2.com/file/x.jpg") == "https://adult.contents.fc2.com/"
    assert referer_for("https://www.1pondo.tv/moviepages/x/images/str.jpg") == "https://www.1pondo.tv/"
    assert referer_for("https://pic.duga.jp/a.jpg") == "https://duga.jp/"
    assert candidate_for("https://unknown.example/x.jpg").kind == COVER_IMAGE
    assert is_javdb_image("https://c0.jdbstatic.com/covers/zb/Zb7mX.jpg")
    assert is_javdb_image("", "javdb") and not is_javdb_image("https://pics.dmm.co.jp/x.jpg", "r18dev")


def test_candidates_from_records_expands_dmm_cdn_and_drops_javdb():
    records = [
        ("r18dev", {"content_id": "118abw358", "cover_urls": ["https://pics.dmm.co.jp/digital/video/118abw00358/118abw00358pl.jpg"]}),
        ("javdb", {"cover_urls": ["https://c0.jdbstatic.com/covers/zb/Zb7mX.jpg"]}),
        ("avbase", {"cover_urls": ["https://image.mgstage.com/images/prestige/abw/358/pb_e_abw-358.jpg",
                                   "https://pics.dmm.co.jp/mono/movie/adult/118sng021/118sng021pl.jpg",
                                   "https://pic.duga.jp/a/jacket_thumb.jpg", "http://insecure.example/x.jpg"]}),
        ("javbus", "not a dict"),
    ]
    found = candidates_from_records("ABW-358", records)
    urls = [candidate.url for candidate in found]
    assert "https://pics.dmm.co.jp/digital/video/118abw00358/118abw00358pl.jpg" in urls
    assert "https://awsimgsrc.dmm.com/dig/digital/video/118abw00358/118abw00358pl.jpg" in urls
    assert "https://awsimgsrc.dmm.com/dig/digital/video/118abw358/118abw358pl.jpg" in urls, "content_id 展开"
    assert "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/abw00358/abw00358pl.jpg" in urls, "去厂牌前缀补零"
    assert "https://image.mgstage.com/images/prestige/abw/358/pb_e_abw-358.jpg" in urls
    assert not any("jdbstatic" in url for url in urls), "javdb 的图不进"
    assert not any("118sng021" in url for url in urls), "别的作品的封套不进"
    assert not any("thumb" in url or url.startswith("http://") for url in urls)
    assert len(urls) == len(set(urls))
    assert candidates_from_records("ABW-358", []) == []


def test_best_cover_picks_largest_by_range_probe():
    small = "https://pics.dmm.co.jp/mono/movie/adult/118abw232/118abw232pl.jpg"
    large = "https://awsimgsrc.dmm.com/dig/mono/movie/118abw232/118abw232pl.jpg"
    tiny = "https://pic.duga.jp/a/jacket.jpg"
    transport = transport_for({small: (200, jpeg(800, 539)), large: (200, jpeg(2184, 1464)), tiny: (200, jpeg(147, 200))})
    winner, size, data = best_cover(transport, "ABW-232", [candidate_for(u) for u in (small, large, tiny)])
    assert (winner.url, size) == (large, (2184, 1464))
    assert Image.open(io.BytesIO(data)).size == (2184, 1464)
    probes = [(url, rng) for url, rng, _ in transport.calls if rng]
    assert probes == [(small, "bytes=0-65535"), (large, "bytes=0-65535"), (tiny, "bytes=0-65535")]
    downloads = [url for url, rng, _ in transport.calls if not rng]
    assert downloads == [large], "只整张下载最大那张"
    assert transport.calls[0][2] == "https://www.dmm.co.jp/"


def test_best_cover_prefers_product_image_at_equal_size_and_never_thumbnails():
    dmm = "https://pics.dmm.co.jp/mono/movie/adult/118abw232/118abw232pl.jpg"
    mgs = "https://image.mgstage.com/images/prestige/abw/232/pb_e_abw-232.jpg"
    thumb = "https://pic.duga.jp/a/jacket_thumb.jpg"
    transport = transport_for({dmm: (200, jpeg(800, 539)), mgs: (200, jpeg(800, 539)), thumb: (200, jpeg(3000, 2000))})
    winner, size, _ = best_cover(transport, "ABW-232", [candidate_for(u) for u in (dmm, mgs, thumb)])
    assert (winner.url, size) == (mgs, (800, 539))
    assert not any("thumb" in url for url, _, _ in transport.calls), "缩略图连尺寸都不量"


def test_best_cover_falls_back_to_small_width():
    url = "https://image.mgstage.com/images/luxutv/259luxu/1475/pb_e_259luxu-1475.jpg"
    tiny = "https://pic.duga.jp/a/jacket.jpg"
    transport = transport_for({url: (200, jpeg(300, 300)), tiny: (200, jpeg(147, 200))})
    winner, size, _ = best_cover(transport, "259LUXU-1475", [candidate_for(url), candidate_for(tiny)])
    assert (winner.url, size) == (url, (300, 300))
    with pytest.raises(NotFound):
        best_cover(transport_for({tiny: (200, jpeg(147, 200))}), "ABW-232", [candidate_for(tiny)])


def test_best_cover_rejects_placeholder_and_animated():
    placeholder = "https://pics.dmm.co.jp/mono/movie/adult/118abw232/118abw232pl.jpg"
    moving = "https://img.javstore.net/images/2022/01/03/FC2PPV-2543627.gif"
    still = "https://img.javstore.net/images/2022/01/03/fc2ppv-2543627.jpg"
    # DMM 没图时 302 到 590×800 的「准备中」，尺寸够门槛，只能按最终地址认。
    transport = transport_for({placeholder: (200, jpeg(590, 800))},
                              final_url={placeholder: "https://pics.dmm.co.jp/mono/movie/adult/now_printing/now_printing.jpg"})
    with pytest.raises(NotFound):
        best_cover(transport, "ABW-232", [candidate_for(placeholder)])
    # 动图只有下完整张才认得出；候选全是动图算没有。
    transport = transport_for({moving: (200, gif(800, 450))})
    with pytest.raises(NotFound, match="动图"):
        best_cover(transport, "FC2-PPV-2543627", [candidate_for(moving)])
    transport = transport_for({moving: (200, gif(800, 450)), still: (200, jpeg(700, 394))})
    winner, size, _ = best_cover(transport, "FC2-PPV-2543627", [candidate_for(moving), candidate_for(still)])
    assert (winner.url, size) == (still, (700, 394))


def test_best_cover_tells_a_definitive_miss_from_source_trouble():
    url = "https://pics.dmm.co.jp/mono/movie/adult/118abw232/118abw232pl.jpg"
    other = "https://pic.duga.jp/a/jacket.jpg"
    with pytest.raises(NotFound):
        best_cover(transport_for({}), "ABW-232", [candidate_for(url)]), "全部 404 是确定答复"
    with pytest.raises(NotFound):
        best_cover(transport_for({}), "ABW-232", [])
    with pytest.raises(Unavailable):
        best_cover(transport_for({url: (503, b"")}), "ABW-232", [candidate_for(url)])
    with patch("hidden_shelf.scrape.transport.NETWORK_RETRY_DELAYS", ()), pytest.raises(Unavailable):
        best_cover(transport_for({url: httpx.ConnectError("reset"), other: (200, jpeg(147, 200))}), "ABW-232",
                   [candidate_for(url), candidate_for(other)])
    # 整张下载失败退到下一张量过的。
    high = "https://one.example/high.jpg"
    low = "https://two.example/low.jpg"

    def transport(request, timeout, limit):
        if request.headers.get("Range"):
            return HttpResponse(200, {}, jpeg(1200, 800) if request.url == high else jpeg(1000, 674), request.url)
        if request.url == high:
            return HttpResponse(503, {}, b"", request.url)
        return HttpResponse(200, {}, jpeg(1000, 674), request.url)

    winner, size, _ = best_cover(transport, "ABW-232", [candidate_for(high), candidate_for(low)])
    assert (winner.url, size) == (low, (1000, 674))
    # 下载后尺寸与量到的对不上就不要。
    liar = transport_for({url: (200, jpeg(800, 539))})
    original = liar

    def mismatch(request, timeout, limit):
        if request.headers.get("Range"):
            return HttpResponse(200, {}, jpeg(1200, 800), request.url)
        return original(request, timeout, limit)

    with pytest.raises(NotFound):
        best_cover(mismatch, "ABW-232", [candidate_for(url)])


@pytest.fixture
def connection(tmp_root: Path):
    conn = db.connect(ShelfPaths(tmp_root))
    yield conn
    conn.close()


def _asset(connection, path, code="ABW-232"):
    return int(connection.execute(
        "INSERT INTO asset(path,name,medium,code,code_key,content_type) VALUES(?,?,?,?,?,?)",
        (path, path.rsplit("/", 1)[-1], "video", code, code, "censored")).lastrowid)


def test_install_online_cover_respects_owner(connection, tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    paths.ensure()
    data = jpeg(800, 539)
    empty = _asset(connection, "a/ABW-232-cd1.mp4")
    frame = _asset(connection, "a/ABW-232-cd2.mp4")
    write_owned_fields(connection, "asset", frame, [FieldWrite("cover_file", "covers/ABW-232.jpg", auto_owner("frame"))])
    (paths.posters / "ABW-232.jpg.rule").parent.mkdir(parents=True, exist_ok=True)
    (paths.posters / "ABW-232.jpg.rule").write_text("{}")
    rel = install_online_cover(connection, paths, [empty, frame], "ABW-232", data, "r18dev")
    assert rel == "covers/ABW-232.jpg"
    assert Image.open(paths.covers / "ABW-232.jpg").size == (800, 539)
    for asset_id in (empty, frame):
        row = connection.execute("SELECT cover_file, field_owners FROM asset WHERE id=?", (asset_id,)).fetchone()
        assert (row["cover_file"], owner_of(row["field_owners"], "cover_file")) == ("covers/ABW-232.jpg", "auto:r18dev")
    assert not (paths.posters / "ABW-232.jpg.rule").exists(), "旧海报指纹删掉，media 步重做海报"
    # 本地旧封面（auto:local）与用户的不动：连文件也不写。
    local = _asset(connection, "b/ABW-233.mp4", "ABW-233")
    write_owned_fields(connection, "asset", local, [FieldWrite("cover_file", "covers/ABW-233.jpg", auto_owner("local"))])
    (paths.covers / "ABW-233.jpg").write_bytes(b"old")
    assert install_online_cover(connection, paths, [local], "ABW-233", data, "r18dev") == ""
    assert (paths.covers / "ABW-233.jpg").read_bytes() == b"old"
    user = _asset(connection, "c/ABW-234.mp4", "ABW-234")
    write_owned_fields(connection, "asset", user, [FieldWrite("cover_file", "covers/mine.jpg", USER_MANUAL)])
    assert install_online_cover(connection, paths, [user], "ABW-234", data, "r18dev") == ""
    # 一碟能写一碟不能：只写能写的那碟，文件照写。
    mixed_local = _asset(connection, "d/ABW-235-cd1.mp4", "ABW-235")
    write_owned_fields(connection, "asset", mixed_local, [FieldWrite("cover_file", "covers/ABW-235.jpg", auto_owner("local"))])
    mixed_empty = _asset(connection, "d/ABW-235-cd2.mp4", "ABW-235")
    assert install_online_cover(connection, paths, [mixed_local, mixed_empty], "ABW-235", data, "dmm") == "covers/ABW-235.jpg"
    assert owner_of(connection.execute("SELECT field_owners FROM asset WHERE id=?", (mixed_local,)).fetchone()[0], "cover_file") == "auto:local"
    assert owner_of(connection.execute("SELECT field_owners FROM asset WHERE id=?", (mixed_empty,)).fetchone()[0], "cover_file") == "auto:dmm"
    # 联网封面可以被更高档的联网封面换掉吗？不：`auto:dmm` 不在可换名单里，再来一张不写。
    assert install_online_cover(connection, paths, [mixed_empty], "ABW-235", jpeg(900, 600), "r18dev") == ""
    assert install_online_cover(connection, paths, [999], "ABW-999", data, "r18dev") == ""
