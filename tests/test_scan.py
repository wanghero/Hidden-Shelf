"""扫描：登记视频、附属文件与番号；重扫标记消失；不覆盖用户改过的番号。"""
from __future__ import annotations

from pathlib import Path

import pytest

from hidden_shelf import db, entities
from hidden_shelf.config import ShelfConfig
from hidden_shelf.field_owners import (
    USER_MANUAL,
    FieldWrite,
    auto_owner,
    owner_of,
    write_owned_fields,
)
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


def test_a_code_range_directory_is_never_a_fallback(tmp_root: Path):
    """用户 2026-11-02 的真实盘：`N1100-N1199/` 是收纳文件夹，区间头上的 N1100 不是这里任何一部片。

    v1.4.14 把这个目录里 88 个纯数字文件名的片全盖成了 N1100，还顺着错番号刮了一遍资料。
    """
    _make(tmp_root, "N1100-N1199/1101.mp4", "N1100-N1199/1102.mp4", "N1100-N1199/1199.mp4",
          "N0000-N0099/Tokyo Hot N0003.rm")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        result = scan(connection, paths, ShelfConfig())
        codes = {path: row["code"] for path, row in _assets(connection).items()}
        assert not codes["N1100-N1199/1101.mp4"]
        assert not codes["N1100-N1199/1102.mp4"]
        assert not codes["N1100-N1199/1199.mp4"]
        assert result.unrecognized == 3
        # 同一个区间目录里，文件名自己认得出的照常认——`.rm` 也是视频（v1.4.15）
        assert codes["N0000-N0099/Tokyo Hot N0003.rm"] == "N0003"
    finally:
        connection.close()


def test_dir_fallback_wants_one_unknown_video_or_real_disc_markers(tmp_root: Path):
    """认不出番号的视频多于一个时，只有各带不重复分卷标记的才算同一部片的多碟。"""
    _make(tmp_root,
          # 广告垃圾混在作品目录里：4 个都认不出，谁都不能认领目录名（用户 2026-11-02 的 n1120）
          "Tokyo-Hot n1120/美女裸聊.mp4", "Tokyo-Hot n1120/台湾UU聊天室.mp4",
          "Tokyo-Hot n1120/荷官自拍.mp4", "Tokyo-Hot n1120/裸聊直播.mp4",
          # 分卷：各带一个不重复的标记，是同一部片
          "Tokyo-Hot n0500/_n0500-cd1.avi", "Tokyo-Hot n0500/_n0500-cd2.avi",
          # 只有一个认不出的：照常用退路
          "Tokyo-Hot n0926 東熱強制プレイに半泣き/_n0926.avi")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        codes = {path: row["code"] for path, row in _assets(connection).items()}
        assert not codes["Tokyo-Hot n1120/美女裸聊.mp4"]
        assert not codes["Tokyo-Hot n1120/裸聊直播.mp4"]
        assert codes["Tokyo-Hot n0500/_n0500-cd1.avi"] == "N0500"
        assert codes["Tokyo-Hot n0500/_n0500-cd2.avi"] == "N0500"
        assert codes["Tokyo-Hot n0926 東熱強制プレイに半泣き/_n0926.avi"] == "N0926"
    finally:
        connection.close()


def test_a_dirname_guess_is_recomputed_and_its_scraped_data_revoked(tmp_root: Path):
    """目录名猜的番号每次重算：这回猜不出了就撤掉它，连带撤掉顺着它刮来的资料。

    撤销的边界：按文件来的（本地厂牌、用户手写）留着，联网刮来的和文件名带着错番号的
    图片清掉。规则变过的盘（v1.4.14 → v1.4.15）就是靠这条自己恢复，不用手工动库。
    """
    work = "Tokyo-Hot n0926 東熱強制プレイに半泣き/_n0926.avi"
    _make(tmp_root, work)
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        row = _assets(connection)[work]
        asset_id = row["id"]
        assert row["code"] == "N0926" and owner_of(row["field_owners"], "code") == "scan:dirname"
        # 模拟上一趟顺着这个番号刮回来的资料
        write_owned_fields(connection, "asset", asset_id, [
            FieldWrite("title", "東熱強制プレイに半泣き", auto_owner("tokyohot")),
            FieldWrite("cover_file", "covers/N0926.jpg", auto_owner("tokyohot")),
            FieldWrite("sheet_file", "sheets/N0926.jpg", auto_owner("frame")),
            FieldWrite("studio", "Tokyo-Hot", auto_owner("local")),
            FieldWrite("plot", "用户自己写的简介", USER_MANUAL),
        ])
        connection.execute("UPDATE asset SET scraped_at='2026-11-01T00:00:00+00:00' WHERE id=?", (asset_id,))
        entities.link(connection, asset_id, entities.ensure_entity(connection, "performer", "松下栞"),
                      "performer", auto_owner("tokyohot"))
        entities.link(connection, asset_id, entities.ensure_entity(connection, "studio", "Tokyo-Hot"),
                      "studio", "local")
        connection.commit()

        # 同目录多了一部认得出别的番号的片：退路有了相反证据，这回算不出番号
        _make(tmp_root, "Tokyo-Hot n0926 東熱強制プレイに半泣き/N0601.mp4")
        scan(connection, paths, ShelfConfig())

        row = _assets(connection)[work]
        assert not row["code"], "猜错的番号撤掉"
        assert not row["code_key"] and row["content_type"] == "unrecognized"
        assert "code" not in row["field_owners"], "归属也撤掉，不是留个指向空值的归属"
        assert not row["title"], "联网刮来的标题跟着番号走"
        assert not row["cover_file"], "联网封面同理"
        assert not row["sheet_file"], "九宫格文件名带着错番号，哪怕是抽帧的也不能留"
        assert row["studio"] == "Tokyo-Hot", "auto:local 是按文件来的，不碰"
        assert row["plot"] == "用户自己写的简介", "用户写的一概不碰"
        assert row["scraped_at"] is None, "撤了番号就不该再免于复问"
        sources = {source for (source,) in connection.execute(
            "SELECT source FROM asset_entity WHERE asset_id=?", (asset_id,))}
        assert sources == {"local"}, "联网写的关联删掉，本地的留着"
    finally:
        connection.close()


def test_a_name_that_comes_back_decomposed_is_still_the_same_asset(tmp_root: Path):
    """macOS 把文件名分解后交回来（`が` → `か` + 浊音符），那还是上一趟那部片，不是新片。

    v1.4.16 及之前这一行会被判「消失」、另建一条没有资料的新行：真实盘上 253 个作品这样丢了
    标题、演员与 `scraped_at`，旧行还占着 `asset.path`，让归位报 UNIQUE 冲突。见 `paths.nfc`。
    """
    import unicodedata
    directory = "Tokyo-Hot/N0017 こんな娘が生カン・中出し!-滝沢美鈴"
    # 盘上按分解写法建目录与文件——macOS 读目录时交给程序的就是这个样子。
    decomposed = unicodedata.normalize("NFD", directory)
    (tmp_root / decomposed).mkdir(parents=True)
    (tmp_root / decomposed / "N0017.avi").write_bytes(b"x" * 16)
    connection = db.connect(ShelfPaths(tmp_root))
    paths = ShelfPaths(tmp_root)
    try:
        # 上一趟留下的那条：合成写法，刮好了资料，这一趟它的文件「看起来」换了个名字。
        asset_id = connection.execute(
            "INSERT INTO asset(path,name,medium,code,code_key,title,scraped_at,vanished,field_owners) "
            "VALUES(?,?,'video','N0017','N0017','こんな娘が生カン・中出し!','2026-11-01T00:00:00+00:00',1,'{}')",
            (f"{directory}/N0017.avi", "N0017.avi")).lastrowid
        connection.commit()

        result = scan(connection, paths, ShelfConfig())

        rows = connection.execute("SELECT * FROM asset WHERE medium='video'").fetchall()
        assert len(rows) == 1, "不该多出一条记录"
        row = rows[0]
        assert int(row["id"]) == asset_id and row["vanished"] == 0
        assert row["title"] == "こんな娘が生カン・中出し!" and row["scraped_at"] == "2026-11-01T00:00:00+00:00"
        assert row["path"] == f"{directory}/N0017.avi" == unicodedata.normalize("NFC", row["path"])
        assert row["name"] == "N0017.avi" and row["code"] == "N0017"
        assert result.added == 0 and result.vanished == 0
    finally:
        connection.close()
