"""归位计划。"""
from __future__ import annotations

from pathlib import Path

import pytest

from hidden_shelf import db
from hidden_shelf.config import ShelfConfig
from hidden_shelf.organize.plan import (
    SKIP_MISSING_FIELD,
    SKIP_TARGET_EXISTS,
    SKIP_TOO_LONG,
    SKIP_UNRECOGNIZED_KEEP,
    SKIP_VANISHED,
    build_plan,
    definition_of,
    placeholder_values,
)
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scan import scan


@pytest.fixture
def disk(tmp_root: Path):
    for rel in ("a/ABP-758.mp4", "b/259LUXU-1475-cd1.mp4", "b/259LUXU-1475-cd2.MP4", "c/随手拍.mp4"):
        target = tmp_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"0" * 8)
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    scan(connection, paths, ShelfConfig())
    connection.execute("UPDATE asset SET studio='Prestige' WHERE path='a/ABP-758.mp4'")
    connection.commit()
    yield tmp_root, paths, connection
    connection.close()


def _targets(plan):
    return {row.current_path: (row.action, row.target_path, row.reason) for row in plan.rows}


def test_plan_moves_to_studio_code_dir(disk):
    root, paths, connection = disk
    plan = build_plan(connection, paths, ShelfConfig())
    targets = _targets(plan)
    assert targets["a/ABP-758.mp4"] == ("move", "Prestige/ABP-758/ABP-758.mp4", "")
    assert plan.counts["move"] == 4 and plan.counts["skip"] == 0 and plan.counts["total"] == 4


def test_plan_unknown_studio(disk):
    root, paths, connection = disk
    plan = build_plan(connection, paths, ShelfConfig())
    targets = _targets(plan)
    assert targets["b/259LUXU-1475-cd1.mp4"][1] == "_未知厂牌/259LUXU-1475/259LUXU-1475-cd1.mp4"


def test_plan_multipart_same_dir(disk):
    root, paths, connection = disk
    targets = _targets(build_plan(connection, paths, ShelfConfig()))
    cd1 = targets["b/259LUXU-1475-cd1.mp4"][1]
    cd2 = targets["b/259LUXU-1475-cd2.MP4"][1]
    assert cd1 != cd2
    assert cd1.rsplit("/", 1)[0] == cd2.rsplit("/", 1)[0] == "_未知厂牌/259LUXU-1475"
    # 扩展名保留但小写化。
    assert cd2 == "_未知厂牌/259LUXU-1475/259LUXU-1475-cd2.mp4"


def test_plan_unrecognized_toggle(disk):
    root, paths, connection = disk
    targets = _targets(build_plan(connection, paths, ShelfConfig(move_unrecognized=True)))
    assert targets["c/随手拍.mp4"] == ("move", "未识别/c/随手拍.mp4", "")
    plan = build_plan(connection, paths, ShelfConfig(move_unrecognized=False))
    assert _targets(plan)["c/随手拍.mp4"] == ("skip", "", SKIP_UNRECOGNIZED_KEEP)
    assert plan.reasons == {SKIP_UNRECOGNIZED_KEEP: 1}


def test_plan_already_in_unrecognized_is_unchanged(disk):
    root, paths, connection = disk
    (root / "未识别" / "x").mkdir(parents=True)
    (root / "未识别" / "x" / "y.mp4").write_bytes(b"0")
    scan(connection, paths, ShelfConfig())
    plan = build_plan(connection, paths, ShelfConfig())
    assert "未识别/x/y.mp4" not in _targets(plan)
    assert plan.counts["unchanged"] == 1


def test_plan_duplicate_target_second_skips(disk):
    root, paths, connection = disk
    (root / "d").mkdir()
    (root / "d" / "ABP-758.mp4").write_bytes(b"1" * 9)
    scan(connection, paths, ShelfConfig())
    connection.execute("UPDATE asset SET studio='Prestige' WHERE path='d/ABP-758.mp4'")
    connection.commit()
    targets = _targets(build_plan(connection, paths, ShelfConfig()))
    assert targets["a/ABP-758.mp4"] == ("move", "Prestige/ABP-758/ABP-758.mp4", "")
    assert targets["d/ABP-758.mp4"] == ("skip", "Prestige/ABP-758/ABP-758.mp4", SKIP_TARGET_EXISTS)


def test_plan_target_occupied_on_disk(disk):
    root, paths, connection = disk
    (root / "Prestige" / "ABP-758").mkdir(parents=True)
    (root / "Prestige" / "ABP-758" / "ABP-758.mp4").write_bytes(b"stranger")
    targets = _targets(build_plan(connection, paths, ShelfConfig()))
    assert targets["a/ABP-758.mp4"] == ("skip", "Prestige/ABP-758/ABP-758.mp4", SKIP_TARGET_EXISTS)


def test_plan_unchanged_not_listed(disk):
    root, paths, connection = disk
    (root / "Prestige" / "ABP-758").mkdir(parents=True)
    (root / "a" / "ABP-758.mp4").rename(root / "Prestige" / "ABP-758" / "ABP-758.mp4")
    scan(connection, paths, ShelfConfig())
    connection.execute("UPDATE asset SET studio='Prestige' WHERE path='Prestige/ABP-758/ABP-758.mp4'")
    connection.commit()
    plan = build_plan(connection, paths, ShelfConfig())
    assert "Prestige/ABP-758/ABP-758.mp4" not in _targets(plan)
    assert plan.counts["unchanged"] == 1
    # 旧路径那一行已消失。
    assert _targets(plan)["a/ABP-758.mp4"] == ("skip", "", SKIP_VANISHED)


def test_plan_skips_vanished(disk):
    root, paths, connection = disk
    (root / "c" / "随手拍.mp4").unlink()
    scan(connection, paths, ShelfConfig())
    assert _targets(build_plan(connection, paths, ShelfConfig()))["c/随手拍.mp4"] == ("skip", "", SKIP_VANISHED)


def test_plan_missing_field_and_too_long(disk):
    root, paths, connection = disk
    plan = build_plan(connection, paths, ShelfConfig(dir_template="{year}/{code}"))
    assert _targets(plan)["a/ABP-758.mp4"] == ("skip", "", SKIP_MISSING_FIELD)
    connection.execute("UPDATE asset SET title=? WHERE path='a/ABP-758.mp4'", ("甲" * 119,))
    connection.commit()
    plan = build_plan(connection, paths, ShelfConfig(dir_template="{studio}/{title}/{title}", file_template="{code} {title}"))
    assert _targets(plan)["a/ABP-758.mp4"][2] == SKIP_TOO_LONG


def test_plan_asset_ids_scope(disk):
    root, paths, connection = disk
    asset_id = connection.execute("SELECT id FROM asset WHERE path='a/ABP-758.mp4'").fetchone()[0]
    plan = build_plan(connection, paths, ShelfConfig(), asset_ids=[asset_id])
    assert [row.current_path for row in plan.rows] == ["a/ABP-758.mp4"]
    assert build_plan(connection, paths, ShelfConfig(), asset_ids=[]).rows == []


def test_placeholder_values_and_definition(disk):
    root, paths, connection = disk
    connection.execute("UPDATE asset SET title='标题', release_date='2019-05-10', width=1920, height=1080 "
                       "WHERE path='b/259LUXU-1475-cd1.mp4'")
    row = connection.execute("SELECT * FROM asset WHERE path='b/259LUXU-1475-cd1.mp4'").fetchone()
    values = placeholder_values(row, ["甲", "乙", "丙", "丁"])
    assert values == {"code": "259LUXU-1475", "title": "标题", "studio": "", "series": "", "year": "2019",
                      "actors": "甲、乙、丙", "cd": "1", "definition": "1080p"}
    assert definition_of(3840, 2160) == "4K"
    assert definition_of(1080, 1920) == "1080p"
    assert definition_of(1280, 720) == "720p"
    assert definition_of(640, 480) == "SD"
    assert definition_of(None, None) == ""


def test_default_dir_template_carries_title_and_performers(disk):
    """用户 2026-11-01 定的默认目录名：`N0900 東熱鬼畜で人生初中出し-松下栞`。"""
    root, paths, connection = disk
    asset_id = connection.execute("SELECT id FROM asset WHERE path='a/ABP-758.mp4'").fetchone()[0]
    connection.execute("UPDATE asset SET code='N0900', code_key='N0900', studio='Tokyo-Hot', "
                       "title='東熱鬼畜で人生初中出し' WHERE id=?", (asset_id,))
    entity_id = connection.execute(
        "INSERT INTO entity(kind,canonical_name,normalized_name) VALUES('performer','松下栞','松下栞')").lastrowid
    connection.execute("INSERT INTO asset_entity(asset_id,entity_id,role,source) VALUES(?,?,'performer','auto:test')",
                       (asset_id, entity_id))
    connection.commit()
    targets = _targets(build_plan(connection, paths, ShelfConfig()))
    assert targets["a/ABP-758.mp4"][1] == "Tokyo-Hot/N0900 東熱鬼畜で人生初中出し-松下栞/N0900.mp4"

    # 标题还没刮到的作品退回只有番号，不会留下 `N0900 -` 这种尾巴。
    connection.execute("UPDATE asset SET title='' WHERE id=?", (asset_id,))
    connection.execute("DELETE FROM asset_entity WHERE asset_id=?", (asset_id,))
    connection.commit()
    assert _targets(build_plan(connection, paths, ShelfConfig()))["a/ABP-758.mp4"][1] == "Tokyo-Hot/N0900/N0900.mp4"
