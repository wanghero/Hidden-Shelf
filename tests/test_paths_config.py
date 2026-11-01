"""盘上目录布局与配置文件。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hidden_shelf.config import DIR_TEMPLATE, LEGACY_DIR_TEMPLATE, ShelfConfig
from hidden_shelf.paths import SHELF_DIR, ShelfPaths


def test_paths_layout(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    shelf = tmp_root / SHELF_DIR
    assert paths.shelf == shelf
    assert paths.db == shelf / "shelf.db"
    assert paths.config == shelf / "config.json"
    assert paths.overrides == shelf / "overrides.json"
    assert paths.site == shelf / "site"
    assert paths.site_data == shelf / "site" / "data"
    assert paths.covers == shelf / "covers"
    assert paths.posters == shelf / "posters"
    assert paths.sheets == shelf / "sheets"
    assert paths.avatars == shelf / "avatars"
    assert paths.sources == shelf / "sources"
    assert paths.legacy == shelf / "legacy"
    assert paths.logs == shelf / "logs"
    assert paths.backups == shelf / "backups"
    assert paths.unrecognized == tmp_root / "未识别"
    assert paths.index_html == tmp_root / "index.html"
    paths.ensure()
    for directory in (paths.shelf, paths.site_data, paths.covers, paths.posters, paths.sheets,
                      paths.avatars, paths.sources, paths.legacy, paths.logs, paths.backups):
        assert directory.is_dir(), directory
    # `未识别/` 由归位按需建，`ensure()` 不建它。
    assert not paths.unrecognized.exists()


def test_relative_and_absolute_roundtrip(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    rel = paths.relative(tmp_root / "厂牌" / "ABP-758" / "ABP-758 #1.mp4")
    assert rel == "厂牌/ABP-758/ABP-758 #1.mp4"
    assert paths.absolute(rel) == tmp_root / "厂牌" / "ABP-758" / "ABP-758 #1.mp4"
    assert paths.relative(tmp_root / SHELF_DIR / "covers" / "x.jpg") == f"{SHELF_DIR}/covers/x.jpg"
    assert paths.shelf_relative(tmp_root / SHELF_DIR / "covers" / "x.jpg") == "covers/x.jpg"


def test_relative_rejects_outside(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    with pytest.raises(ValueError):
        paths.relative(tmp_root.parent / "elsewhere.mp4")
    with pytest.raises(ValueError):
        paths.absolute("../elsewhere.mp4")
    with pytest.raises(ValueError):
        paths.absolute("/abs/elsewhere.mp4")


def test_config_roundtrip_and_defaults(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    config = ShelfConfig.load(paths)
    assert config == ShelfConfig()
    assert config.move_unrecognized is True
    assert config.dir_template == "{studio}/{code}[ {title}][-{actors}]"
    assert config.file_template == "{code}[-cd{cd}]"
    assert config.unknown_studio_dir == "_未知厂牌"
    assert config.code_patterns == []
    assert config.language == "zh"
    # 文件不存在时只用默认值、不落盘；默认配置由 ensure() 写出。
    assert not paths.config.exists()
    paths.ensure()
    stored = json.loads(paths.config.read_text(encoding="utf-8"))
    assert stored["move_unrecognized"] is True

    config.move_unrecognized = False
    config.code_patterns = [r"^(?P<code>MYLABEL\d{3})"]
    config.save(paths)
    again = ShelfConfig.load(paths)
    assert again.move_unrecognized is False
    assert again.code_patterns == [r"^(?P<code>MYLABEL\d{3})"]
    assert len(again.compiled_patterns()) == 1


def test_config_ignores_unknown_keys_and_bad_types(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    paths.ensure()
    paths.config.write_text(json.dumps({"move_unrecognized": 0, "future_key": 1, "language": "en"}),
                            encoding="utf-8")
    config = ShelfConfig.load(paths)
    assert config.move_unrecognized is False
    assert config.language == "en"


def test_config_bad_json_falls_back_to_defaults(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    paths.ensure()
    paths.config.write_text("{not json", encoding="utf-8")
    config = ShelfConfig.load(paths)
    assert config == ShelfConfig()
    # 坏文件不覆盖：用户可能还要看它写了什么。
    assert paths.config.read_text(encoding="utf-8") == "{not json"


def test_shelf_dir_is_visible_ascii(tmp_path: Path):
    """资料目录是普通可见目录（用户 2026-10-29 定）：纯 ASCII、不以点或下划线开头、Windows 合法。"""
    assert SHELF_DIR == "HiddenShelf"
    assert not SHELF_DIR.startswith((".", "_")) and SHELF_DIR.isascii()
    assert SHELF_DIR.upper() not in {"CON", "PRN", "AUX", "NUL"} and not SHELF_DIR.endswith((".", " "))
    assert ShelfPaths(tmp_path).shelf == tmp_path / "HiddenShelf"


def test_ensure_migrates_legacy_dot_shelf(tmp_path: Path):
    """老盘上的 `.shelf/` 自动改名为 `HiddenShelf/`，内容原样，用户什么都不用做。"""
    from hidden_shelf.paths import migrate_legacy_dir
    (tmp_path / ".shelf" / "covers").mkdir(parents=True)
    (tmp_path / ".shelf" / "shelf.db").write_bytes(b"db")
    paths = ShelfPaths(tmp_path)
    paths.ensure()
    assert not (tmp_path / ".shelf").exists()
    assert (tmp_path / "HiddenShelf" / "shelf.db").read_bytes() == b"db"
    assert (tmp_path / "HiddenShelf" / "covers").is_dir()
    # 再来一次没有旧目录：返回 False，不抛。
    assert migrate_legacy_dir(tmp_path) is False


def test_migrate_returns_true_once(tmp_path: Path):
    from hidden_shelf.paths import migrate_legacy_dir
    assert migrate_legacy_dir(tmp_path) is False
    (tmp_path / ".shelf").mkdir()
    assert migrate_legacy_dir(tmp_path) is True
    assert (tmp_path / "HiddenShelf").is_dir() and not (tmp_path / ".shelf").exists()


def test_ensure_refuses_both_dirs(tmp_path: Path):
    """两个目录都在（用户手工复制过）：不合并、不猜，报错让人保留一个。"""
    from hidden_shelf.paths import ShelfLayoutConflict, check_layout
    (tmp_path / ".shelf").mkdir()
    (tmp_path / "HiddenShelf").mkdir()
    with pytest.raises(ShelfLayoutConflict, match="同时有"):
        ShelfPaths(tmp_path).ensure()
    with pytest.raises(ShelfLayoutConflict, match="同时有"):
        check_layout(tmp_path)
    # 两个目录都原样留着。
    assert (tmp_path / ".shelf").is_dir() and (tmp_path / "HiddenShelf").is_dir()
    # 只有旧目录时 check_layout 只检查、不改名。
    (tmp_path / "HiddenShelf").rmdir()
    check_layout(tmp_path)
    assert (tmp_path / ".shelf").is_dir()


def test_config_load_does_not_create_dir(tmp_path: Path):
    """读配置不能有副作用：老盘迁移发生在任何会创建 HiddenShelf/ 的动作之前，load 就不能建目录。"""
    paths = ShelfPaths(tmp_path)
    assert ShelfConfig.load(paths) == ShelfConfig()
    assert list(tmp_path.iterdir()) == []
    paths.ensure()
    assert paths.config.is_file()
    assert ShelfConfig.load(paths) == ShelfConfig()
    # 已有的配置 ensure() 不覆盖。
    ShelfConfig(move_unrecognized=False).save(paths)
    paths.ensure()
    assert ShelfConfig.load(paths).move_unrecognized is False


def test_old_default_dir_template_is_upgraded_but_a_custom_one_is_kept(tmp_root: Path):
    """1.4.11 及之前的盘上存着老的默认模板，读的时候升到带标题与出演者的新默认值。"""
    paths = ShelfPaths(tmp_root)
    paths.shelf.mkdir(parents=True, exist_ok=True)

    paths.config.write_text(json.dumps({"dir_template": LEGACY_DIR_TEMPLATE}), encoding="utf-8")
    assert ShelfConfig.load(paths).dir_template == DIR_TEMPLATE

    # 自己写过模板的盘一个字不动——哪怕写的只是番号。
    paths.config.write_text(json.dumps({"dir_template": "{code}"}), encoding="utf-8")
    assert ShelfConfig.load(paths).dir_template == "{code}"
