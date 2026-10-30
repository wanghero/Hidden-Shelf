"""媒体探测、九宫格、封面与海报。全部依赖 fake_video（ffmpeg 不在则 skip）。"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from hidden_shelf import db
from hidden_shelf.config import ShelfConfig
from hidden_shelf.field_owners import owner_of
from hidden_shelf.media import ffmpeg as ffmpeg_module
from hidden_shelf.media import fingerprint, process_assets
from hidden_shelf.media.covers import cover_from_frame, poster_box, poster_from_cover
from hidden_shelf.media.ffmpeg import FFmpegMissing, find_ffmpeg, probe
from hidden_shelf.media.sheets import build_sheet, sheet_timestamps
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scan import scan


def test_probe_reads_dimensions(fake_video, tmp_path: Path):
    info = probe(fake_video(tmp_path / "clip.mp4"))
    assert (info.width, info.height, info.vcodec, info.acodec, info.container) == (320, 240, "h264", "aac", "mp4")
    assert 1.5 <= info.duration <= 2.6


def test_probe_rejects_garbage(tmp_path: Path):
    if not shutil.which("ffprobe"):
        pytest.skip("没有 ffprobe")
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(ValueError):
        probe(bad)


def test_build_sheet_creates_3x3(fake_video, tmp_path: Path):
    video = fake_video(tmp_path / "clip.mp4", seconds=3)
    out = tmp_path / "sheet.jpg"
    assert build_sheet(find_ffmpeg(), video, out, duration=3.0, frame_width=120)
    with Image.open(out) as image:
        assert image.width == 3 * 120
        assert image.height == 3 * 90


def test_sheet_timestamps_skip_head_and_stay_in_range():
    stamps = sheet_timestamps(3600, 9)
    assert len(stamps) == 9 and stamps[0] >= 2.0 and stamps[-1] < 3600
    assert all(a < b for a, b in zip(stamps, stamps[1:]))
    short = sheet_timestamps(2.0, 9)
    assert all(0 <= s < 2.0 for s in short)


def test_build_sheet_fails_cleanly_on_garbage(tmp_path: Path):
    if not shutil.which("ffmpeg"):
        pytest.skip("没有 ffmpeg")
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"")
    out = tmp_path / "sheet.jpg"
    assert build_sheet(find_ffmpeg(), bad, out, duration=0, frame_width=64) is False
    assert not out.exists()


def test_fingerprint_skips_unchanged(tmp_path: Path):
    source = tmp_path / "src.bin"
    source.write_bytes(b"abc")
    artifact = tmp_path / "out.jpg"
    assert not fingerprint.current(artifact, source=source)
    artifact.write_bytes(b"img")
    assert not fingerprint.current(artifact, source=source)
    fingerprint.remember(artifact, source=source)
    assert fingerprint.current(artifact, source=source)
    source.write_bytes(b"abcd")
    assert not fingerprint.current(artifact, source=source)
    assert not fingerprint.current(artifact, source=source, rule="other/2")


def test_poster_crop_dvd_sleeve(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (800, 538), "red").save(cover)
    out = tmp_path / "poster.jpg"
    assert poster_from_cover(cover, out)
    with Image.open(out) as poster:
        assert poster.height == 538
        assert abs(poster.width / poster.height - 0.704) < 0.01
    assert poster_box(800, 538)[0] == 800 - round(538 * 0.704)


def test_poster_crop_non_sleeve(tmp_path: Path):
    cover = tmp_path / "square.jpg"
    Image.new("RGB", (400, 400), "blue").save(cover)
    out = tmp_path / "poster.jpg"
    assert poster_from_cover(cover, out)
    with Image.open(out) as poster:
        assert abs(poster.width / poster.height - 2 / 3) < 0.01
        assert poster.height == 400
    tall = tmp_path / "tall.jpg"
    Image.new("RGB", (200, 600), "blue").save(tall)
    assert poster_from_cover(tall, out)
    with Image.open(out) as poster:
        assert poster.width == 200 and abs(poster.width / poster.height - 2 / 3) < 0.01
    wide = tmp_path / "wide.jpg"
    Image.new("RGB", (1920, 1080), "blue").save(wide)
    assert poster_from_cover(wide, out)
    with Image.open(out) as poster:
        assert poster.height == 1080 and abs(poster.width / poster.height - 2 / 3) < 0.01


def test_poster_bad_image(tmp_path: Path):
    bad = tmp_path / "bad.jpg"
    bad.write_text("nope", encoding="utf-8")
    assert poster_from_cover(bad, tmp_path / "poster.jpg") is False
    assert not (tmp_path / "poster.jpg").exists()


def test_cover_from_frame(fake_video, tmp_path: Path):
    video = fake_video(tmp_path / "clip.mp4")
    out = tmp_path / "cover.jpg"
    assert cover_from_frame(find_ffmpeg(), video, out, duration=2.0)
    with Image.open(out) as image:
        assert image.size == (320, 240)


def test_missing_ffmpeg_message(monkeypatch):
    monkeypatch.setattr(ffmpeg_module.shutil, "which", lambda name: None)
    with pytest.raises(FFmpegMissing) as caught:
        find_ffmpeg()
    assert "brew install ffmpeg" in str(caught.value)


@pytest.fixture
def disk(tmp_root: Path, fake_video):
    (tmp_root / "a").mkdir()
    fake_video(tmp_root / "a" / "ABP-758.mp4")
    (tmp_root / "b").mkdir()
    fake_video(tmp_root / "b" / "259LUXU-1475-cd1.mp4")
    fake_video(tmp_root / "b" / "259LUXU-1475-cd2.mp4")
    (tmp_root / "c").mkdir()
    (tmp_root / "c" / "broken.mp4").write_bytes(b"")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    scan(connection, paths, ShelfConfig())
    yield tmp_root, paths, connection
    connection.close()


def test_process_assets_end_to_end(disk):
    root, paths, connection = disk
    messages: list[str] = []
    result = process_assets(connection, paths, progress=messages.append, frame_width=64)
    assert result.probed == 3
    assert result.frame_covers == 2  # ABP-758 一张，259LUXU 两碟共用一张
    assert result.sheets == 3
    assert result.posters == 2
    assert result.failed == 1  # broken.mp4 探测失败
    abp = connection.execute("SELECT * FROM asset WHERE path='a/ABP-758.mp4'").fetchone()
    assert (abp["width"], abp["height"], abp["vcodec"], abp["acodec"], abp["container"]) == (320, 240, "h264", "aac", "mp4")
    assert abp["duration"] > 1
    assert abp["probed_at"]
    assert abp["cover_file"] == "covers/ABP-758.jpg" and owner_of(abp["field_owners"], "cover_file") == "auto:frame"
    assert abp["sheet_file"] == "sheets/ABP-758.jpg"
    assert abp["poster_file"] == "posters/ABP-758.jpg"
    assert (paths.covers / "ABP-758.jpg").is_file() and (paths.sheets / "ABP-758.jpg").is_file()
    assert (paths.posters / "ABP-758.jpg").is_file()
    cd1 = connection.execute("SELECT * FROM asset WHERE path='b/259LUXU-1475-cd1.mp4'").fetchone()
    cd2 = connection.execute("SELECT * FROM asset WHERE path='b/259LUXU-1475-cd2.mp4'").fetchone()
    assert cd1["cover_file"] == cd2["cover_file"] == "covers/259LUXU-1475.jpg"
    assert cd1["sheet_file"] == "sheets/259LUXU-1475-cd1.jpg" and cd2["sheet_file"] == "sheets/259LUXU-1475-cd2.jpg"
    assert cd1["poster_file"] == cd2["poster_file"] == "posters/259LUXU-1475.jpg"
    broken = connection.execute("SELECT * FROM asset WHERE path='c/broken.mp4'").fetchone()
    assert broken["probed_at"] and broken["vcodec"] is None and broken["cover_file"] is None
    assert any("broken.mp4" in message for message in messages)


def test_corrupt_file_does_not_raise(tmp_root: Path):
    if not shutil.which("ffmpeg"):
        pytest.skip("没有 ffmpeg")
    (tmp_root / "x").mkdir()
    (tmp_root / "x" / "ABP-001.mp4").write_bytes(b"")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    scan(connection, paths, ShelfConfig())
    result = process_assets(connection, paths)
    assert result.failed == 1 and result.probed == 0
    connection.close()


def test_process_assets_is_idempotent(disk):
    root, paths, connection = disk
    process_assets(connection, paths, frame_width=64)
    second = process_assets(connection, paths, frame_width=64)
    assert (second.probed, second.sheets, second.posters, second.frame_covers) == (0, 0, 0, 0)


def test_local_cover_beats_frame_cover(disk):
    root, paths, connection = disk
    from hidden_shelf.local_import import import_local
    process_assets(connection, paths, frame_width=64)
    Image.new("RGB", (300, 200), "green").save(root / "a" / "ABP-758-poster.jpg")
    scan(connection, paths, ShelfConfig())
    import_local(connection, paths)
    abp = connection.execute("SELECT * FROM asset WHERE path='a/ABP-758.mp4'").fetchone()
    assert owner_of(abp["field_owners"], "cover_file") == "auto:local"
    with Image.open(paths.covers / "ABP-758.jpg") as image:
        assert image.size == (300, 200)
    # 封面换了，海报跟着重做。
    result = process_assets(connection, paths, frame_width=64)
    assert result.posters == 1


def test_missing_ffmpeg_in_process(disk, monkeypatch):
    root, paths, connection = disk
    monkeypatch.setattr(ffmpeg_module.shutil, "which", lambda name: None)
    with pytest.raises(FFmpegMissing):
        process_assets(connection, paths)
