"""盘上目录布局与配置文件。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hidden_shelf.config import ShelfConfig
from hidden_shelf.paths import ShelfPaths


def test_paths_layout(tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    shelf = tmp_root / ".shelf"
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
    assert paths.relative(tmp_root / ".shelf" / "covers" / "x.jpg") == ".shelf/covers/x.jpg"
    assert paths.shelf_relative(tmp_root / ".shelf" / "covers" / "x.jpg") == "covers/x.jpg"


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
    assert config.dir_template == "{studio}/{code}"
    assert config.file_template == "{code}[-cd{cd}]"
    assert config.unknown_studio_dir == "_未知厂牌"
    assert config.code_patterns == []
    assert config.language == "zh"
    # 文件不存在时用默认值并落盘。
    assert paths.config.is_file()
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
