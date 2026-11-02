"""扫描：登记视频、附属文件与番号；重扫标记消失；不覆盖用户改过的番号。"""
from __future__ import annotations

from pathlib import Path

import pytest

from hidden_shelf import db
from hidden_shelf.config import ShelfConfig
from hidden_shelf.field_owners import USER_MANUAL, FieldWrite, owner_of, write_owned_fields
from hidden_shelf.paths import SHELF_DIR, ShelfPaths
from hidden_shelf.scan import scan

TREE = (
    "a/ABP-758.mp4", "a/ABP-758-poster.jpg", "a/ABP-758.nfo",
    "b/259LUXU-1475-cd1.mp4", "b/259LUXU-1475-cd2.mp4",
    "c/随手拍.mp4",
    f"{SHELF_DIR}/x.mp4", f"{SHELF_DIR}/covers/ABP-758.jpg",
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
        assert not path.startswith((f"{SHELF_DIR}/", "@eaDir/", "$RECYCLE.BIN/", "System Volume Information/"))
        assert "/._" not in path
    assert connection.execute("SELECT count(*) FROM sidecar WHERE path LIKE ?", (f"{SHELF_DIR}/%",)).fetchone()[0] == 0


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


def test_scan_skips_visible_shelf_dir(tmp_root: Path):
    """`HiddenShelf/` 整目录跳过：legacy 里的 NFO 与 jpg、sheets 里故意放的 .mp4 都不能登记。"""
    for rel in (f"{SHELF_DIR}/legacy/X/X.nfo", f"{SHELF_DIR}/covers/X.jpg", f"{SHELF_DIR}/sheets/ABP-758.mp4",
                "a/ABP-758.mp4"):
        target = tmp_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"0" * 16)
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        result = scan(connection, paths, ShelfConfig())
        assert result.seen == 1
        for table in ("asset", "sidecar"):
            rows = connection.execute(f"SELECT path FROM {table}").fetchall()
            assert not any(row["path"].startswith(f"{SHELF_DIR}/") for row in rows), table
    finally:
        connection.close()


def _make(root: Path, *rels: str) -> None:
    for rel in rels:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"0" * 16)


def test_dir_name_is_the_fallback_when_the_file_name_hides_the_code(tmp_root: Path):
    """用户 2026-11-01 的 `Tokyo-Hot n0926 …/_n0926.avi`：番号只写在目录上，文件名前黏了字头。"""
    _make(tmp_root,
          "Tokyo-Hot n0926 東熱強制プレイに半泣き/_n0926.avi",
          "Tokyo-Hot n0972-SD/net_n0972.avi",
          # 同目录另一部认得出，番号与目录名一致：不算打架，认不出的那个照样补上
          "Tokyo-Hot n0867-AVI/n0867.avi", "Tokyo-Hot n0867-AVI/com_n0867.avi",
          # 分卷：两个都认不出，目录名给同一个番号
          "Tokyo-Hot n0500/_n0500-cd1.avi", "Tokyo-Hot n0500/_n0500-cd2.avi")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        assets = _assets(connection)
        codes = {path: row["code"] for path, row in assets.items()}
        assert codes["Tokyo-Hot n0926 東熱強制プレイに半泣き/_n0926.avi"] == "N0926"
        assert codes["Tokyo-Hot n0972-SD/net_n0972.avi"] == "N0972"
        assert codes["Tokyo-Hot n0867-AVI/com_n0867.avi"] == "N0867"
        assert codes["Tokyo-Hot n0500/_n0500-cd1.avi"] == codes["Tokyo-Hot n0500/_n0500-cd2.avi"] == "N0500"
        # 归属分得清是从哪儿来的
        assert owner_of(assets["Tokyo-Hot n0867-AVI/n0867.avi"]["field_owners"], "code") == "scan:filename"
        assert owner_of(assets["Tokyo-Hot n0926 東熱強制プレイに半泣き/_n0926.avi"]["field_owners"], "code") == "scan:dirname"
        # 分卷号仍按文件名算
        assert assets["Tokyo-Hot n0500/_n0500-cd2.avi"]["part"] == "2"
    finally:
        connection.close()


def test_dir_fallback_is_dropped_when_the_directory_holds_another_code(tmp_root: Path):
    """目录里另有视频认出了别的番号，说明这目录装的不止一部片，目录名代表不了谁。"""
    _make(tmp_root, "N0600 乱放的目录/N0601.mp4", "N0600 乱放的目录/随手拍.avi",
          "没有番号的目录/随手拍2.avi")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        result = scan(connection, paths, ShelfConfig())
        codes = {path: row["code"] for path, row in _assets(connection).items()}
        assert codes["N0600 乱放的目录/N0601.mp4"] == "N0601", "文件名认出来的不受影响"
        assert not codes["N0600 乱放的目录/随手拍.avi"], "退路作废，宁可当未识别"
        assert not codes["没有番号的目录/随手拍2.avi"]
        assert result.unrecognized == 2
    finally:
        connection.close()


def test_dir_fallback_never_uses_the_disk_root_name(tmp_root: Path):
    """盘根目录名是盘名；拿它当番号会盖到散在根上的每部片。"""
    root = tmp_root / "N0700"
    root.mkdir()
    _make(root, "随手拍.avi")
    paths = ShelfPaths(root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        assert not _assets(connection)["随手拍.avi"]["code"]
    finally:
        connection.close()


def test_a_work_already_in_unrecognized_is_recognised_on_the_next_scan(tmp_root: Path):
    """`未识别/` 里的目录名照样认：上一趟被搬进去的片，重扫就能认出番号、下一次归位搬回来。"""
    _make(tmp_root, "未识别/Tokyo-Hot n0926 東熱強制プレイに半泣き/_n0926.avi")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        row = _assets(connection)["未识别/Tokyo-Hot n0926 東熱強制プレイに半泣き/_n0926.avi"]
        assert row["code"] == "N0926" and row["content_type"] == "uncensored"
    finally:
        connection.close()


def test_dir_fallback_does_not_override_a_user_code(tmp_root: Path):
    _make(tmp_root, "Tokyo-Hot n0926 東熱強制プレイに半泣き/_n0926.avi")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        asset_id = next(iter(_assets(connection).values()))["id"]
        write_owned_fields(connection, "asset", asset_id, [FieldWrite("code", "N0001", USER_MANUAL)])
        scan(connection, paths, ShelfConfig())
        row = next(iter(_assets(connection).values()))
        assert row["code"] == "N0001" and owner_of(row["field_owners"], "code") == USER_MANUAL
    finally:
        connection.close()
