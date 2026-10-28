"""附属文件判定规则。后半的断言搬自 peach `tests/test_scan.py`。"""
from __future__ import annotations

import pytest

from hidden_shelf.rules.sidecars import (
    ARTWORK,
    ARTWORK_DIRS,
    IMAGE_EXTENSIONS,
    is_sidecar,
    medium_of,
    sidecar_kind,
    video_stems,
)


@pytest.mark.parametrize("name,expected", [
    ("a.mp4", "video"), ("A.MP4", "video"), ("x.iso", "video"),
    ("b.jpg", "image"), ("b.webp", "image"),
    ("c.flac", "audio"),
    ("d.7z", "archive"),
    ("e.nfo", "nfo"), ("E.NFO", "nfo"),
    ("f.srt", "subtitle"), ("f.ass", "subtitle"), ("f.vtt", "subtitle"),
    ("notes.txt", "other"), ("noext", "other"),
])
def test_medium_of(name, expected):
    assert medium_of(name) == expected


def test_video_stems_are_casefolded_and_skip_trailers():
    assert video_stems(["ABP-758.mp4", "ABP-758-trailer.mp4", "x.jpg"]) == frozenset({"abp-758"})


def test_is_sidecar_matches_video_stem():
    videos = frozenset({"abp-758"})
    for name in ("ABP-758-poster.jpg", "ABP-758.nfo", "ABP-758.mp4_thumbs.jpg", "poster.jpg",
                 "ABP-758-fanart.JPG"):
        assert is_sidecar(name, videos), name
    assert not is_sidecar("unrelated.jpg", videos)
    assert not is_sidecar("ABP-758.mp4", videos)
    # 没有正片的目录里，图片是图集自己的内容。
    assert not is_sidecar("poster.jpg", frozenset())
    # `extrafanart/` 这类目录里任何图都算附属。
    assert is_sidecar("whatever.jpg", frozenset(), artwork_dir=True)
    assert not is_sidecar("whatever.mp4", frozenset(), artwork_dir=True)


def test_sidecar_kind():
    videos = frozenset({"abp-758"})
    assert sidecar_kind("ABP-758-poster.jpg", videos) == "poster"
    assert sidecar_kind("ABP-758-fanart.jpg", videos) == "fanart"
    assert sidecar_kind("ABP-758.nfo", videos) == "nfo"
    assert sidecar_kind("movie.nfo", videos) == "nfo"
    assert sidecar_kind("ABP-758.jpg", videos) == "cover"
    assert sidecar_kind("cover.jpg", videos) == "cover"
    assert sidecar_kind("folder.jpg", videos) == "cover"
    assert sidecar_kind("ABP-758_4x4_thumb.jpg", videos) == "thumb"
    assert sidecar_kind("ABP-758-thumb.jpg", videos) == "thumb"
    assert sidecar_kind("ABP-758.srt", videos) == "subtitle"
    assert sidecar_kind("ABP-758.chs.ass", videos) == "subtitle"
    assert sidecar_kind("ABP-758-landscape.jpg", videos) == "other"
    assert sidecar_kind("ABP-758-trailer.mp4", videos) == "other"
    assert sidecar_kind("unrelated.jpg", videos) is None
    assert sidecar_kind("ABP-758.mp4", videos) is None
    assert sidecar_kind("notes.txt", videos) is None
    assert sidecar_kind("whatever.png", frozenset(), artwork_dir=True) == "fanart"


def test_same_name_image_only_counts_when_video_present():
    assert sidecar_kind("ABP-758.jpg", frozenset()) is None
    assert sidecar_kind("ABP-758.srt", frozenset()) is None


def test_constants():
    assert {"poster", "fanart", "cover", "thumb", "landscape", "banner", "clearlogo"} <= ARTWORK
    assert ARTWORK_DIRS == frozenset({"extrafanart", "extrathumbs"})
    assert ".jpg" in IMAGE_EXTENSIONS


# ---- 搬自 peach tests/test_scan.py ----


def test_trailer_names_use_an_explicit_terminal_marker():
    assert video_stems(['ABC-123.mp4', 'ABC-123-trailer.mp4']) == frozenset({'abc-123'})
    for name in ('ABC-123-trailer.mp4', 'ABC-123.TRAILER.MKV', 'ABC-123_trailer.mov',
                 'ABC-123 trailer.m4v', 'trailer.mp4'):
        assert is_sidecar(name, frozenset()), name
    for name in ('ABC-123.mp4', 'Trailer Park.mp4', 'ABC-123-trailer-park.mp4',
                 'ABC-123trailer.mp4', 'ABC-123-trailer.mp4.bak', 'trailer.jpg'):
        assert not is_sidecar(name, frozenset()), name


def test_the_rule_reads_names_only():
    videos = video_stems(["ABC-1.mp4", "notes.txt"])
    assert videos == frozenset({"abc-1"})
    sidecar = {name: is_sidecar(name, videos) for name in (
        "x.NFO", "Poster.JPG", "ABC-1-fanart.jpg", "ABC-1.jpg", "OTHER-fanart.jpg",
        "a.png.thumb.png", "ABC-1_3x3_thumbs.jpg", "ABC-1.srt", "001.jpg")}
    # 与 peach 的差别：同名图片 `ABC-1.jpg` 与字幕 `ABC-1.srt` 这里也算附属——
    # 本项目要把它们导入或留底，而不是像 peach 那样只决定「登不登记」。
    assert {name for name, hit in sidecar.items() if hit} == {
        "x.NFO", "Poster.JPG", "ABC-1-fanart.jpg", "a.png.thumb.png",
        "ABC-1_3x3_thumbs.jpg", "ABC-1.jpg", "ABC-1.srt"}


def test_medium_is_decided_by_extension():
    assert [medium_of(name) for name in ("a.MP4", "b.webp", "c.flac", "d.7z", "e.nfo")] == [
        "video", "image", "audio", "archive", "nfo"]
