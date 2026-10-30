"""扫描：登记视频、附属文件与番号；重扫标记消失；不覆盖用户改过的番号。"""
from __future__ import annotations

from pathlib import Path

import pytest

from hidden_shelf import db
from hidden_shelf.config import ShelfConfig
from hidden_shelf.field_owners import USER_MANUAL, FieldWrite, owner_of, write_owned_fields
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scan import scan

TREE = (
    "a/ABP-758.mp4", "a/ABP-758-poster.jpg", "a/ABP-758.nfo",
    "b/259LUXU-1475-cd1.mp4", "b/259LUXU-1475-cd2.mp4",
    "c/随手拍.mp4",
    ".shelf/x.mp4", ".shelf/covers/ABP-758.jpg",
    "a/.DS_Store", "a/._ABP-758.mp4", "@eaDir/ABP-758.mp4", "$RECYCLE.BIN/x.mp4",
    "System Volume Information/y.mp4",
)


@pytest.fixture
def disk(tmp_root: Path):
    for rel in TREE:
        target = tmp_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"0" * 16 if target.suffix == ".mp4" else b"x")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    yield tmp_root, paths, connection
    connection.close()


def _assets(connection):
    return {row["path"]: row for row in connection.execute("SELECT * FROM asset ORDER BY path")}


def test_scan_registers_videos_and_codes(disk):
    root, paths, connection = disk
    result = scan(connection, paths, ShelfConfig())
    assets = _assets(connection)
    assert set(assets) == {"a/ABP-758.mp4", "b/259LUXU-1475-cd1.mp4", "b/259LUXU-1475-cd2.mp4", "c/随手拍.mp4"}
    assert result.seen == 4 and result.added == 4 and result.vanished == 0 and result.unrecognized == 1
    abp = assets["a/ABP-758.mp4"]
    assert (abp["code"], abp["code_key"], abp["part"], abp["content_type"]) == ("ABP-758", "ABP-758", "", "censored")
    assert abp["name"] == "ABP-758.mp4" and abp["medium"] == "video" and abp["size"] == 16
    assert abp["first_seen"] and abp["last_seen"] and abp["vanished"] == 0
    assert owner_of(abp["field_owners"], "code") == "scan:filename"
    cd1 = assets["b/259LUXU-1475-cd1.mp4"]
    cd2 = assets["b/259LUXU-1475-cd2.mp4"]
    assert (cd1["code"], cd1["part"], cd1["content_type"]) == ("259LUXU-1475", "1", "amateur")
    assert (cd2["code"], cd2["part"]) == ("259LUXU-1475", "2")
    assert cd1["code_key"] == cd2["code_key"] == "259LUXU-1475"
    other = assets["c/随手拍.mp4"]
    assert other["code"] is None and other["code_key"] is None and other["content_type"] == "unrecognized"


def test_scan_registers_sidecars(disk):
    root, paths, connection = disk
    result = scan(connection, paths, ShelfConfig())
    assert result.sidecars == 2
    rows = connection.execute("SELECT s.path,s.kind,s.status,a.path AS video FROM sidecar s "
                              "LEFT JOIN asset a ON a.id=s.asset_id ORDER BY s.path").fetchall()
    assert [(r["path"], r["kind"], r["status"], r["video"]) for r in rows] == [
        ("a/ABP-758-poster.jpg", "poster", "pending", "a/ABP-758.mp4"),
        ("a/ABP-758.nfo", "nfo", "pending", "a/ABP-758.mp4"),
    ]


def test_scan_skips_shelf_and_system_dirs(disk):
    root, paths, connection = disk
    scan(connection, paths, ShelfConfig())
    for path in _assets(connection):
        assert not path.startswith((".shelf/", "@eaDir/", "$RECYCLE.BIN/", "System Volume Information/"))
        assert "/._" not in path
    assert connection.execute("SELECT count(*) FROM sidecar WHERE path LIKE '.shelf/%'").fetchone()[0] == 0


def test_rescan_marks_vanished(disk):
    root, paths, connection = disk
    scan(connection, paths, ShelfConfig())
    (root / "c" / "随手拍.mp4").unlink()
    result = scan(connection, paths, ShelfConfig())
    assets = _assets(connection)
    assert result.vanished == 1 and result.added == 0 and result.seen == 3
    assert assets["c/随手拍.mp4"]["vanished"] == 1
    assert all(row["vanished"] == 0 for path, row in assets.items() if path != "c/随手拍.mp4")
    # 放回去再扫，恢复 0，且不新增行。
    (root / "c" / "随手拍.mp4").write_bytes(b"0" * 16)
    result = scan(connection, paths, ShelfConfig())
    assert result.vanished == 0 and result.added == 0
    assert _assets(connection)["c/随手拍.mp4"]["vanished"] == 0
    assert connection.execute("SELECT count(*) FROM asset").fetchone()[0] == 4


def test_rescan_updates_observations_only(disk):
    root, paths, connection = disk
    scan(connection, paths, ShelfConfig())
    before = _assets(connection)["a/ABP-758.mp4"]
    (root / "a" / "ABP-758.mp4").write_bytes(b"0" * 64)
    result = scan(connection, paths, ShelfConfig())
    after = _assets(connection)["a/ABP-758.mp4"]
    assert result.updated == 1
    assert after["size"] == 64 and after["id"] == before["id"] and after["first_seen"] == before["first_seen"]


def test_scan_keeps_user_code(disk):
    root, paths, connection = disk
    scan(connection, paths, ShelfConfig())
    asset_id = connection.execute("SELECT id FROM asset WHERE path='c/随手拍.mp4'").fetchone()[0]
    write_owned_fields(connection, "asset", asset_id, [FieldWrite("code", "XYZ-001", USER_MANUAL)])
    connection.commit()
    scan(connection, paths, ShelfConfig())
    row = _assets(connection)["c/随手拍.mp4"]
    assert row["code"] == "XYZ-001"
    assert row["code_key"] == "XYZ-001"
    assert row["content_type"] == "censored"
    # 自动识别出的番号同样不被重扫改掉。
    abp_id = connection.execute("SELECT id FROM asset WHERE path='a/ABP-758.mp4'").fetchone()[0]
    write_owned_fields(connection, "asset", abp_id, [FieldWrite("code", "ABP-999", USER_MANUAL)])
    connection.commit()
    scan(connection, paths, ShelfConfig())
    assert _assets(connection)["a/ABP-758.mp4"]["code"] == "ABP-999"


def test_scan_uses_custom_patterns(disk):
    root, paths, connection = disk
    (root / "d").mkdir()
    (root / "d" / "MYLABEL001 whatever.mp4").write_bytes(b"0")
    config = ShelfConfig(code_patterns=[r"^(?P<code>MYLABEL\d{3})"])
    scan(connection, paths, config)
    assert _assets(connection)["d/MYLABEL001 whatever.mp4"]["code"] == "MYLABEL-001"


def test_unrecognized_dir_is_registered(disk):
    root, paths, connection = disk
    (root / "未识别" / "c").mkdir(parents=True)
    (root / "未识别" / "c" / "录像.mp4").write_bytes(b"0")
    scan(connection, paths, ShelfConfig())
    row = _assets(connection)["未识别/c/录像.mp4"]
    assert row["content_type"] == "unrecognized"


def test_sidecar_pairs_in_single_video_dir_and_artwork_dir(disk):
    root, paths, connection = disk
    (root / "a" / "movie.nfo").write_text("<movie/>", encoding="utf-8")
    (root / "a" / "poster.jpg").write_bytes(b"x")
    (root / "a" / "extrafanart").mkdir()
    (root / "a" / "extrafanart" / "fanart1.jpg").write_bytes(b"x")
    (root / "b" / "259LUXU-1475.nfo").write_text("<movie/>", encoding="utf-8")
    (root / "b" / "stray.nfo").write_text("<movie/>", encoding="utf-8")
    scan(connection, paths, ShelfConfig())
    rows = {r["path"]: r for r in connection.execute(
        "SELECT s.path,s.kind,a.path AS video FROM sidecar s LEFT JOIN asset a ON a.id=s.asset_id")}
    assert rows["a/movie.nfo"]["video"] == "a/ABP-758.mp4"
    assert rows["a/poster.jpg"]["video"] == "a/ABP-758.mp4"
    assert rows["a/extrafanart/fanart1.jpg"]["kind"] == "fanart"
    assert rows["a/extrafanart/fanart1.jpg"]["video"] == "a/ABP-758.mp4"
    # 多碟目录里按番号配对，配到第一碟；配不上的留空。
    assert rows["b/259LUXU-1475.nfo"]["video"] == "b/259LUXU-1475-cd1.mp4"
    assert rows["b/stray.nfo"]["video"] is None


def test_progress_is_called(disk):
    root, paths, connection = disk
    messages: list[str] = []
    scan(connection, paths, ShelfConfig(), progress=messages.append)
    assert messages
