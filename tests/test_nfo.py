"""NFO 读取与附属文件配对。后半的断言搬自 peach `tests/test_metadata_library.py`。"""
from __future__ import annotations

from pathlib import Path

import pytest

from hidden_shelf.rules.nfo import SidecarIndex, directory_files, local_art, read_nfo

KODI_NFO = """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>标题甲</title>
  <originaltitle>原題</originaltitle>
  <num>ABP-758</num>
  <studio>Prestige</studio>
  <set><name>系列一</name></set>
  <premiered>2019-05-10</premiered>
  <plot>剧情简介</plot>
  <actor><name>甲</name></actor>
  <actor><name>乙</name></actor>
  <genre>巨乳</genre>
  <tag>中文字幕</tag>
  <tag>巨乳</tag>
  <thumb>https://x/cover.jpg</thumb>
</movie>
"""


def test_read_nfo_basic(tmp_path: Path):
    path = tmp_path / "ABP-758.nfo"
    path.write_text(KODI_NFO, encoding="utf-8")
    payload = read_nfo(path)
    assert payload["title"] == "标题甲"
    assert payload["original_title"] == "原題"
    assert payload["code"] == "ABP-758"
    assert payload["studio"] == "Prestige"
    assert payload["series"] == "系列一"
    assert payload["release_date"] == "2019-05-10"
    assert payload["year"] == "2019"
    assert payload["actors"] == ["甲", "乙"]
    assert payload["tags"] == ["巨乳", "中文字幕"]
    assert payload["cover_url"] == "https://x/cover.jpg"
    assert payload["plot"] == "剧情简介"
    assert "local_art" not in payload


def test_read_nfo_omits_missing_keys(tmp_path: Path):
    path = tmp_path / "x.nfo"
    path.write_text("<movie><title>只有标题</title></movie>", encoding="utf-8")
    assert read_nfo(path) == {"title": "只有标题"}


def test_read_nfo_rejects_dtd(tmp_path: Path):
    path = tmp_path / "bad.nfo"
    path.write_text('<!DOCTYPE movie [<!ENTITY x "t">]><movie><title>&x;</title></movie>',
                    encoding="utf-8")
    with pytest.raises(ValueError):
        read_nfo(path)


def test_read_nfo_rejects_oversized(tmp_path: Path):
    path = tmp_path / "big.nfo"
    path.write_bytes(b"<movie><plot>" + b"x" * (1024 * 1024 + 10) + b"</plot></movie>")
    with pytest.raises(ValueError):
        read_nfo(path)


def test_read_nfo_rejects_non_movie_root(tmp_path: Path):
    path = tmp_path / "tv.nfo"
    path.write_text("<tvshow><title>剧</title></tvshow>", encoding="utf-8")
    with pytest.raises(ValueError):
        read_nfo(path)


def test_read_nfo_local_art(tmp_path: Path):
    path = tmp_path / "x.nfo"
    path.write_text("<movie><art><poster>ABP-758-poster.jpg</poster></art></movie>", encoding="utf-8")
    assert read_nfo(path)["local_art"] == "ABP-758-poster.jpg"


def test_sidecar_index_pairs_by_stem_then_code(tmp_path: Path):
    for name in ("ABP-758.mp4", "ABP-758.nfo", "movie.nfo", "ABP-758-poster.jpg", "ABP-758.jpg"):
        (tmp_path / name).touch()
    files = directory_files(tmp_path)
    assert set(files) == {"abp-758.mp4", "abp-758.nfo", "movie.nfo", "abp-758-poster.jpg", "abp-758.jpg"}
    index = SidecarIndex(files)
    assert index.videos == [tmp_path / "ABP-758.mp4"]
    assert set(index.nfos) == {tmp_path / "ABP-758.nfo", tmp_path / "movie.nfo"}
    video = tmp_path / "ABP-758.mp4"
    assert index.nfo_for(video) == tmp_path / "ABP-758.nfo"
    images = index.images_for(video)
    assert tmp_path / "ABP-758-poster.jpg" in images
    assert tmp_path / "ABP-758.jpg" in images
    assert images[0] == tmp_path / "ABP-758-poster.jpg"


def test_sidecar_index_code_match_when_stem_differs(tmp_path: Path):
    for name in ("ABP-758-CD1.mp4", "abp758.nfo"):
        (tmp_path / name).touch()
    index = SidecarIndex(directory_files(tmp_path))
    assert index.nfo_for(tmp_path / "ABP-758-CD1.mp4") == tmp_path / "abp758.nfo"


def test_local_art_stays_inside_directory(tmp_path: Path):
    folder = tmp_path / "film"
    folder.mkdir()
    (tmp_path / "outside.jpg").touch()
    (folder / "inside.jpg").touch()
    video = folder / "film.mp4"
    assert local_art(video, {"local_art": "../outside.jpg"}) is None
    assert local_art(video, {"local_art": "https://example.com/poster.jpg"}) is None
    assert local_art(video, {}) is None
    assert local_art(video, {"local_art": "inside.jpg"}) == (folder / "inside.jpg").resolve()
    assert local_art(video, {"local_art": "missing.jpg"}) is None


# ---- 搬自 peach tests/test_metadata_library.py（`sidecars(video)` 改为 SidecarIndex 调用） ----


def _pair(video: Path):
    index = SidecarIndex(directory_files(video.parent))
    return index.nfo_for(video), index.images_for(video)


def test_movie_sidecar_only_when_unambiguous_and_named_file_preferred(tmp_path: Path):
    video = tmp_path / "one.mp4"
    video.touch()
    common = tmp_path / "movie.nfo"
    common.touch()
    assert _pair(video)[0] == common
    (tmp_path / "two.mkv").touch()
    assert _pair(video)[0] is None
    named = tmp_path / "one.NFO"
    named.touch()
    assert _pair(video)[0] == named


def test_numbered_image_set_beside_the_video_is_not_its_poster(tmp_path: Path):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    video = gallery / "TG@BOT- (1).mp4"
    for name in ("TG@BOT- (1).mp4", "TG@BOT- (1).jpg", "TG@BOT- (2).jpg", "TG@BOT- (10).jpg"):
        (gallery / name).touch()
    assert _pair(video)[1] == []
    (gallery / "cover.jpg").touch()
    assert _pair(video)[1] == [gallery / "cover.jpg"]


def test_release_sidecar_is_shared_by_parts_and_versions(tmp_path: Path):
    video = tmp_path / "ABC-123-CD1.mp4"
    for name in (video.name, "ABC-123-CD2.mp4", "ABC-123-4K.mkv", "ABC-124.mp4"):
        (tmp_path / name).touch()
    shared = tmp_path / "ABC-123.nfo"
    shared.write_text("<movie><id>ABC-123</id><title>本地标题</title></movie>", encoding="utf-8")
    for name in (video.name, "ABC-123-CD2.mp4", "ABC-123-4K.mkv"):
        assert _pair(tmp_path / name)[0] == shared
    assert _pair(tmp_path / "ABC-124.mp4")[0] is None
    named = video.with_suffix(".nfo")
    named.touch()
    assert _pair(video)[0] == named
    (tmp_path / "ABC-123-4K.nfo").touch()
    assert _pair(tmp_path / "ABC-123-CD2.mp4")[0] is None


def test_movie_sidecar_is_shared_only_by_one_release(tmp_path: Path):
    video = tmp_path / "ABC-123-CD1.mp4"
    for name in (video.name, "ABC-123-CD2.mp4"):
        (tmp_path / name).touch()
    common = tmp_path / "movie.nfo"
    common.touch()
    assert _pair(video)[0] == common
    (tmp_path / "ABC-124.mp4").touch()
    assert _pair(video)[0] is None


def test_releases_sharing_a_folder_keep_their_same_name_posters(tmp_path: Path):
    for code in ("ABC-123", "ABC-124"):
        (tmp_path / f"{code}.mp4").touch()
        (tmp_path / f"{code}.jpg").touch()
    (tmp_path / "ABC-123-fanart.jpg").touch()
    assert _pair(tmp_path / "ABC-123.mp4")[1] == [tmp_path / "ABC-123.jpg"]


def test_episode_and_plain_set_without_jav_identity(tmp_path: Path):
    path = tmp_path / "episode.nfo"
    path.write_text('<episodedetails><title>Episode</title><uniqueid type="tmdb">123</uniqueid>'
                    '<set>Collection</set><aired>2024-01-02</aired></episodedetails>', encoding="utf-8")
    payload = read_nfo(path)
    assert "code" not in payload
    assert payload["series"] == "Collection"
    assert payload["release_date"] == "2024-01-02"


def test_jav_id_and_imdb_id_have_distinct_meanings(tmp_path: Path):
    path = tmp_path / "movie.nfo"
    path.write_text("<movie><id>ABW-358</id></movie>", encoding="utf-8")
    assert read_nfo(path)["code"] == "ABW-358"
    path.write_text("<movie><id>tt1234567</id></movie>", encoding="utf-8")
    assert "code" not in read_nfo(path)


def test_two_different_codes_are_refused(tmp_path: Path):
    path = tmp_path / "movie.nfo"
    path.write_text("<movie><id>ABW-358</id><num>ABW-359</num></movie>", encoding="utf-8")
    with pytest.raises(ValueError):
        read_nfo(path)


def test_entity_declarations_rejected_in_utf16(tmp_path: Path):
    path = tmp_path / "unsafe.nfo"
    path.write_bytes('<!DOCTYPE movie [<!ENTITY x "test">]><movie><title>&x;</title></movie>'.encode("utf-16"))
    with pytest.raises(ValueError):
        read_nfo(path)
