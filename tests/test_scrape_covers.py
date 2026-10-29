"""封面地址判据。搬自 peach `tests/test_jav_covers.py` 的 `CrossProductCoverTests`。"""
from __future__ import annotations

import pytest

from hidden_shelf.scrape.covers import THUMBNAIL, is_cross_product_cover


def test_thumbnail_pattern():
    for url in ("https://x/thumb/a.jpg", "https://x/a_s.jpg", "https://x/ts/a.jpg", "https://x/a-s1.jpg", "https://x/icon.png"):
        assert THUMBNAIL.search(url), url
    for url in ("https://pics.dmm.co.jp/mono/movie/adult/118abw358/118abw358pl.jpg",
                "https://image.mgstage.com/images/prestige/abw/358/pb_e_abw-358.jpg"):
        assert not THUMBNAIL.search(url), url


def test_dmm_content_id_must_carry_the_code_letters():
    assert is_cross_product_cover("259LUXU-1475", "https://pics.dmm.co.jp/mono/movie/adult/118sng021/118sng021pl.jpg")
    assert is_cross_product_cover("428SUKE-080",
                                  "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/h_1711mgt00164/h_1711mgt00164pl.jpg")


def test_matching_content_ids_and_non_dmm_hosts_pass():
    assert not is_cross_product_cover("ABW-232", "https://pics.dmm.co.jp/mono/movie/adult/118abw232/118abw232pl.jpg")
    # `MGT-164` -> `h_1711mgt00164`：厂牌数字与补零都不影响字母段。
    assert not is_cross_product_cover("MGT-164",
                                      "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/h_1711mgt00164/h_1711mgt00164pl.jpg")
    # MGS、FC2 的路径里没有 content_id，判据不适用，不能顺手拦掉。
    assert not is_cross_product_cover("259LUXU-1475", "https://image.mgstage.com/images/luxutv/259luxu/1475/pb_e_259luxu-1475.jpg")
    assert not is_cross_product_cover("FC2-PPV-3071875", "https://contents-thumbnail2.fc2.com/w1200/storage/x.jpg")


@pytest.mark.parametrize("code,cid,expected", [
    ("YUJ-101", "yuj00011", True), ("CHU-201", "chu00021", True), ("435MFC-135", "h_1711mfcc00027", True),
    ("278GYAN-017", "gyan00017", False), ("428SUKE-073", "h_1711suke00073", False),
    ("476MLA-234", "mla234", False), ("HA-102", "49ha102r", False),
])
def test_dmm_content_id_must_carry_the_code_number(code, cid, expected):
    assert is_cross_product_cover(code, f"https://pics.dmm.co.jp/mono/movie/{cid}/{cid}pl.jpg") is expected


def test_an_fc2_image_named_after_another_work_is_cross_product():
    for url in ("https://img.javstore.net/images/2024/01/15/2184960PL.gif",
                "http://img2.javstore.net/images/2026/04/27/4536228pl.jpg"):
        assert is_cross_product_cover("FC2-PPV-1512205", url), url
    for code, url in (("FC2-PPV-2653914", "https://img.javstore.net/images/2022/02/14/FC2PPV-2653914-1-1.gif"),
                      ("FC2-PPV-1083921", "https://img.javstore.net/images/2023/12/24/1083921pl.jpg"),
                      ("FC2-PPV-2935152", "https://img.javstore.net/images/2022/07/31/pl1654160016.07k.gif"),
                      ("FC2-PPV-3264420", "https://img.javstore.net/images/2025/10/07/5dd29b14380eaPS.jpg")):
        assert not is_cross_product_cover(code, url), url
