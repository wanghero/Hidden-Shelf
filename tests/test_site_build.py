"""静态站数据文件与页面骨架。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hidden_shelf import db
from hidden_shelf.config import ShelfConfig
from hidden_shelf.local_import import import_local
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scan import scan
from hidden_shelf.site import build as build_module
from hidden_shelf.site.build import build_site, read_data_js, to_js
from hidden_shelf.site.playability import play_hint


@pytest.mark.parametrize("container,vcodec,acodec,expected", [
    ("mp4", "h264", "aac", "native"),
    ("mov", "h264", "mp3", "native"),
    ("m4v", "h264", "", "native"),
    ("webm", "vp9", "opus", "native"),
    ("webm", "av1", "", "native"),
    ("mp4", "hevc", "aac", "check"),
    ("mp4", "av1", "aac", "check"),
    ("mp4", "h264", "ac3", "check"),
    ("mp4", "h264", "flac", "check"),
    ("mp4", "h264", "opus", "check"),
    ("mp4", "mpeg4", "aac", "unsupported"),
    ("mkv", "h264", "aac", "unsupported"),
    ("avi", "mpeg4", "mp3", "unsupported"),
    ("wmv", "wmv3", "wmav2", "unsupported"),
    ("rmvb", "rv40", "cook", "unsupported"),
    ("flv", "h264", "aac", "unsupported"),
    ("ts", "h264", "aac", "unsupported"),
    ("iso", "", "", "unsupported"),
    ("", "", "", "unsupported"),
    ("MP4", "H264", "AAC", "native"),
])
def test_play_hint_table(container, vcodec, acodec, expected):
    assert play_hint(container, vcodec, acodec) == expected


@pytest.fixture
def disk(tmp_root: Path):
    (tmp_root / "a").mkdir()
    (tmp_root / "a" / "ABP-758.mp4").write_bytes(b"0" * 10)
    (tmp_root / "a" / "ABP-758.nfo").write_text(
        "<movie><title>标题</title><studio>Prestige</studio><set><name>系列一</name></set>"
        "<premiered>2019-05-10</premiered><actor><name>甲</name></actor><actor><name>乙</name></actor>"
        "<genre>巨乳</genre></movie>", encoding="utf-8")
    (tmp_root / "b").mkdir()
    (tmp_root / "b" / "259LUXU-1475-cd2.mp4").write_bytes(b"0" * 30)
    (tmp_root / "b" / "259LUXU-1475-cd1.mp4").write_bytes(b"0" * 20)
    (tmp_root / "c").mkdir()
    (tmp_root / "c" / "随手拍 #1 50%.mp4").write_bytes(b"0" * 5)
    (tmp_root / "d").mkdir()
    (tmp_root / "d" / "ABW-358.mp4").write_bytes(b"0" * 7)
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    scan(connection, paths, ShelfConfig())
    import_local(connection, paths)
    connection.execute("UPDATE asset SET title='x</script><script>alert(1)</script>' WHERE path='d/ABW-358.mp4'")
    connection.execute("UPDATE asset SET duration=100, width=1920, height=1080, vcodec='h264', acodec='aac', "
                       "container='mp4', play_hint='native' WHERE code_key='259LUXU-1475'")
    connection.execute("UPDATE asset SET cover_file='covers/ABP-758.jpg', poster_file='posters/ABP-758.jpg', "
                       "sheet_file='sheets/ABP-758.jpg' WHERE path='a/ABP-758.mp4'")
    connection.commit()
    yield tmp_root, paths, connection
    connection.close()


def test_build_writes_files(disk):
    root, paths, connection = disk
    result = build_site(connection, paths, ShelfConfig())
    assert result.works == 3 and result.unrecognized == 1 and result.performers == 2
    assert result.studios == 1 and result.series == 1 and result.tags == 1
    for name in ("index.html",):
        assert (root / name).is_file()
    for name in ("works.js", "entities.js", "unrecognized.js", "meta.js"):
        assert (paths.site_data / name).is_file(), name
    for name in ("tokens.css", "app.css", "i18n.js", "shelf-core.js", "ripple.js", "app.js"):
        assert (paths.site / name).is_file(), name
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "<title>藏片阁</title>" in html
    assert "<noscript>" in html
    assert 'href=".shelf/site/tokens.css"' in html
    assert "http://" not in html and "https://" not in html
    assert 'lang="zh-CN"' in html


def test_works_group_parts(disk):
    root, paths, connection = disk
    build_site(connection, paths, ShelfConfig())
    works = {work["id"]: work for work in read_data_js(paths.site_data / "works.js")}
    luxu = works["259LUXU-1475"]
    assert [part["part"] for part in luxu["parts"]] == ["1", "2"]
    assert [part["path"] for part in luxu["parts"]] == ["b/259LUXU-1475-cd1.mp4", "b/259LUXU-1475-cd2.mp4"]
    assert luxu["kind"] == "amateur" and luxu["definition"] == "1080p" and luxu["duration"] == 200
    assert luxu["parts"][0]["play_hint"] == "native"
    assert luxu["size"] == 50
    abp = works["ABP-758"]
    assert abp["title"] == "标题" and abp["studio"] == "Prestige" and abp["series"] == "系列一"
    assert abp["date"] == "2019-05-10" and abp["year"] == 2019 and abp["kind"] == "censored"
    assert abp["cover"] == ".shelf/covers/ABP-758.jpg" and abp["poster"] == ".shelf/posters/ABP-758.jpg"
    assert abp["sheet"] == ".shelf/sheets/ABP-758.jpg"
    assert len(abp["performers"]) == 2 and len(abp["tags"]) == 1
    entities = read_data_js(paths.site_data / "entities.js")
    names = {p["id"]: p["name"] for p in entities["performers"]}
    assert [names[i] for i in abp["performers"]] == ["甲", "乙"]
    assert entities["studios"] == [{"id": "Prestige", "name": "Prestige", "count": 1}]
    assert entities["performers"][0]["count"] == 1 and entities["performers"][0]["avatar"] is None
    unrecognized = read_data_js(paths.site_data / "unrecognized.js")
    assert unrecognized[0]["path"] == "c/随手拍 #1 50%.mp4"
    assert unrecognized[0]["name"] == "随手拍 #1 50%.mp4"


def test_vanished_excluded(disk):
    root, paths, connection = disk
    (root / "d" / "ABW-358.mp4").unlink()
    (root / "c" / "随手拍 #1 50%.mp4").unlink()
    scan(connection, paths, ShelfConfig())
    result = build_site(connection, paths, ShelfConfig())
    assert result.works == 2 and result.unrecognized == 0
    ids = {work["id"] for work in read_data_js(paths.site_data / "works.js")}
    assert "ABW-358" not in ids
    assert connection.execute("SELECT count(*) FROM asset WHERE vanished=1").fetchone()[0] == 2


def test_data_js_is_valid(disk):
    root, paths, connection = disk
    build_site(connection, paths, ShelfConfig())
    for name in ("works.js", "entities.js", "unrecognized.js", "meta.js"):
        text = (paths.site_data / name).read_text(encoding="utf-8")
        assert text.startswith("window.__shelf=window.__shelf||{};window.__shelf.")
        assert "</script" not in text
        match = re.search(r"=(\[.*\]|\{.*\});\s*$", text, re.S)
        assert match, name
        json.loads(match.group(1).replace("<\\/", "</"))
    works = {work["id"]: work for work in read_data_js(paths.site_data / "works.js")}
    assert works["ABW-358"]["title"] == "x</script><script>alert(1)</script>"
    meta = read_data_js(paths.site_data / "meta.js")
    assert meta["counts"] == {"works": 3, "performers": 2, "studios": 1, "series": 1, "tags": 1, "unrecognized": 1}
    assert meta["dataFiles"] == ["meta.js", "works.js", "entities.js", "unrecognized.js"]
    assert meta["language"] == "zh" and meta["version"] and meta["builtAt"]
    assert meta["totalBytes"] == 72 and meta["totalDuration"] == 200


def test_to_js_escapes():
    assert to_js({"a": "</script>"}) == '{"a":"<\\/script>"}'
    assert to_js(" ") == '"\\u2028"'
    assert to_js("中文") == '"中文"'


def test_split_when_large(disk, monkeypatch):
    root, paths, connection = disk
    result = build_site(connection, paths, ShelfConfig(), split_bytes=600)
    assert len([name for name in result.data_files if name.startswith("works")]) >= 2
    assert not (paths.site_data / "works.js").exists()
    meta = read_data_js(paths.site_data / "meta.js")
    assert meta["dataFiles"] == result.data_files
    collected = []
    for name in result.data_files:
        if name.startswith("works"):
            text = (paths.site_data / name).read_text(encoding="utf-8")
            assert ".concat(" in text
            collected.extend(read_data_js(paths.site_data / name))
    assert {work["id"] for work in collected} == {"ABP-758", "259LUXU-1475", "ABW-358"}
    # 再 build 一次回到单文件时，旧分片被清掉。
    build_site(connection, paths, ShelfConfig())
    assert not list(paths.site_data.glob("works-*.js"))
    assert (paths.site_data / "works.js").is_file()


def test_index_references_all_data_files(disk):
    root, paths, connection = disk
    result = build_site(connection, paths, ShelfConfig(), split_bytes=600)
    html = (root / "index.html").read_text(encoding="utf-8")
    for name in result.data_files:
        assert f'src=".shelf/site/data/{name}"' in html, name
    order = [m.group(1) for m in re.finditer(r'src="\.shelf/site/(?:data/)?([\w.-]+)"', html)]
    assert order[0] == "i18n.js"
    assert order[1:1 + len(result.data_files)] == result.data_files
    assert order[-3:] == ["shelf-core.js", "ripple.js", "app.js"]


def test_english_language_sets_lang(disk):
    root, paths, connection = disk
    build_site(connection, paths, ShelfConfig(language="en"))
    assert 'lang="en"' in (root / "index.html").read_text(encoding="utf-8")


def test_i18n_dictionaries_have_same_keys():
    text = (build_module.STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    zh = set(re.findall(r"^\s+'([\w.]+)':", text.split("var en = {")[0], re.M))
    en = set(re.findall(r"^\s+'([\w.]+)':", text.split("var en = {")[1], re.M))
    assert zh == en and zh
