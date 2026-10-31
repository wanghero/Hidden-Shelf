"""封面与九宫格复制到视频所在目录（计划 9 任务 2）。副本由 sidecar 表 `status='placed'` 认领。"""
from __future__ import annotations

from pathlib import Path

import pytest

from hidden_shelf import db
from hidden_shelf.config import ShelfConfig
from hidden_shelf.local_import import import_local
from hidden_shelf.media.place import place_images
from hidden_shelf.organize.apply import organize, rollback_batch
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scan import scan


@pytest.fixture
def disk(tmp_root: Path):
    (tmp_root / "a").mkdir()
    (tmp_root / "a" / "ABP-758.mp4").write_bytes(b"video")
    (tmp_root / "a" / "ABP-758-poster.jpg").write_bytes(b"user-poster")      # 用户自己的图
    (tmp_root / "b").mkdir()
    (tmp_root / "b" / "259LUXU-1475-cd1.mp4").write_bytes(b"cd1")
    (tmp_root / "b" / "259LUXU-1475-cd2.mp4").write_bytes(b"cd2")
    (tmp_root / "c").mkdir()
    (tmp_root / "c" / "随手拍.mp4").write_bytes(b"home")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    scan(connection, paths, ShelfConfig())
    import_local(connection, paths)
    # 假装媒体步已经做好了封面与九宫格。
    (paths.covers / "ABP-758.jpg").write_bytes(b"cover-abp")
    (paths.sheets / "ABP-758.jpg").write_bytes(b"sheet-abp")
    (paths.covers / "259LUXU-1475.jpg").write_bytes(b"cover-luxu")
    (paths.sheets / "259LUXU-1475-cd1.jpg").write_bytes(b"sheet-cd1")
    (paths.sheets / "259LUXU-1475-cd2.jpg").write_bytes(b"sheet-cd2")
    (paths.covers / "asset-home.jpg").write_bytes(b"cover-home")
    connection.execute("UPDATE asset SET cover_file='covers/ABP-758.jpg', sheet_file='sheets/ABP-758.jpg' WHERE code_key='ABP-758'")
    connection.execute("UPDATE asset SET cover_file='covers/259LUXU-1475.jpg' WHERE code_key='259LUXU-1475'")
    connection.execute("UPDATE asset SET sheet_file='sheets/259LUXU-1475-cd1.jpg' WHERE name='259LUXU-1475-cd1.mp4'")
    connection.execute("UPDATE asset SET sheet_file='sheets/259LUXU-1475-cd2.jpg' WHERE name='259LUXU-1475-cd2.mp4'")
    connection.execute("UPDATE asset SET cover_file='covers/asset-home.jpg' WHERE name='随手拍.mp4'")
    connection.commit()
    yield tmp_root, paths, connection
    connection.close()


def _placed(connection):
    return sorted(r[0] for r in connection.execute("SELECT path FROM sidecar WHERE status='placed'"))


def test_option_on_by_default_places_copies(disk):
    """用户 2026-10-30 定默认开；`--no-images-in-work-dir` 才收回。"""
    root, paths, connection = disk
    assert ShelfConfig().images_in_work_dir is True
    result = place_images(connection, paths, ShelfConfig())
    assert result.copied > 0 and result.removed == 0
    assert list(root.glob("*/*-cover.jpg")) and _placed(connection)
    result = place_images(connection, paths, ShelfConfig(images_in_work_dir=False))
    assert result.copied == 0 and result.removed > 0
    assert not list(root.glob("*/*-cover.jpg")) and _placed(connection) == []


def test_placed_images_survive_rescan_and_organize(disk):
    root, paths, connection = disk
    config = ShelfConfig(images_in_work_dir=True, dir_template="{code}")
    result = place_images(connection, paths, config)
    assert result.copied == 5
    assert (root / "a" / "ABP-758-cover.jpg").read_bytes() == b"cover-abp"
    assert (root / "a" / "ABP-758-sheet.jpg").read_bytes() == b"sheet-abp"
    assert (root / "b" / "259LUXU-1475-cover.jpg").read_bytes() == b"cover-luxu", "多碟共用一张封面"
    assert (root / "b" / "259LUXU-1475-cd1-sheet.jpg").read_bytes() == b"sheet-cd1"
    assert (root / "b" / "259LUXU-1475-cd2-sheet.jpg").read_bytes() == b"sheet-cd2"
    assert not list((root / "c").glob("*.jpg")), "没番号的不放"
    assert _placed(connection) == ["a/ABP-758-cover.jpg", "a/ABP-758-sheet.jpg", "b/259LUXU-1475-cd1-sheet.jpg",
                                   "b/259LUXU-1475-cd2-sheet.jpg", "b/259LUXU-1475-cover.jpg"]
    # 再扫一遍：副本不被登记成待导入附属文件，封面来源不变，再放一遍什么都不拷。
    scan(connection, paths, config)
    import_local(connection, paths)
    assert len(_placed(connection)) == 5
    assert connection.execute("SELECT count(*) FROM sidecar WHERE status='pending' AND path LIKE '%-cover.jpg'").fetchone()[0] == 0
    assert (paths.covers / "ABP-758.jpg").read_bytes() == b"cover-abp"
    assert place_images(connection, paths, config).copied == 0
    # 归位：副本跟着视频进新目录，用户自己的海报照旧进 legacy。
    result = organize(connection, paths, config)
    assert result.moved == 4   # 三部有番号的 + 随手拍 进 未识别/
    assert (root / "ABP-758" / "ABP-758.mp4").is_file()
    assert (root / "ABP-758" / "ABP-758-cover.jpg").read_bytes() == b"cover-abp"
    assert (root / "ABP-758" / "ABP-758-sheet.jpg").is_file()
    assert (root / "259LUXU-1475" / "259LUXU-1475-cover.jpg").is_file()
    assert (root / "259LUXU-1475" / "259LUXU-1475-cd2-sheet.jpg").is_file()
    assert (paths.legacy / "ABP-758" / "ABP-758-poster.jpg").is_file()
    assert "ABP-758/ABP-758-cover.jpg" in _placed(connection)
    # 回滚放回去，记录也跟着回去。
    rollback_batch(connection, paths, result.batch_log)
    assert (root / "a" / "ABP-758-cover.jpg").is_file() and "a/ABP-758-cover.jpg" in _placed(connection)


def test_placed_images_removed_when_option_off(disk):
    root, paths, connection = disk
    on = ShelfConfig(images_in_work_dir=True)
    place_images(connection, paths, on)
    (root / "a" / "my-own.jpg").write_bytes(b"mine")
    result = place_images(connection, paths, ShelfConfig(images_in_work_dir=False))
    assert result.removed == 5 and _placed(connection) == []
    assert not (root / "a" / "ABP-758-cover.jpg").exists()
    assert (root / "a" / "my-own.jpg").is_file() and (root / "a" / "ABP-758-poster.jpg").is_file()


def test_placed_image_refreshes_when_source_changes_and_never_overwrites_user_file(disk):
    root, paths, connection = disk
    on = ShelfConfig(images_in_work_dir=True)
    # 用户自己有一张同名的：扫描登记成 pending 的附属文件，程序不覆盖。
    (root / "b" / "259LUXU-1475-cover.jpg").write_bytes(b"user-cover")
    scan(connection, paths, on)
    place_images(connection, paths, on)
    assert (root / "b" / "259LUXU-1475-cover.jpg").read_bytes() == b"user-cover"
    # 封面换了（内容大小变）→ 重拷。
    (paths.covers / "ABP-758.jpg").write_bytes(b"cover-abp-v2!")
    assert place_images(connection, paths, on).copied == 1
    assert (root / "a" / "ABP-758-cover.jpg").read_bytes() == b"cover-abp-v2!"
