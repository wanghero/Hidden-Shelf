"""标签中 / 英 / 日对照（计划 9 任务 4）。"""
from __future__ import annotations

import pytest

from hidden_shelf.tags_i18n import TAG_NAMES, tag_names


@pytest.mark.parametrize("raw,expected", [
    ("巨乳", {"zh": "巨乳", "en": "Big tits", "ja": "巨乳"}),
    ("單體作品", {"zh": "单体作品", "en": "Featured actress", "ja": "単体作品"}),   # javbus 繁体
    ("单体作品", {"zh": "单体作品", "en": "Featured actress", "ja": "単体作品"}),   # javdb 简体
    ("Creampie", {"zh": "中出", "en": "Creampie", "ja": "中出し"}),                 # 英文
    ("ＯＬ", {"zh": "OL", "en": "Office lady", "ja": "OL"}),                         # 全角折半角
    ("苗條", {"zh": "苗条", "en": "Slender", "ja": "スレンダー"}),
    ("养胸", {"zh": "养胸", "en": "养胸", "ja": "养胸"}),                            # 表里没有：原样
    ("", {"zh": "", "en": "", "ja": ""}),
    (None, {"zh": "", "en": "", "ja": ""}),
])
def test_tag_names(raw, expected):
    assert tag_names(raw) == expected


def test_table_rows_are_well_formed():
    seen = set()
    for row in TAG_NAMES:
        assert len(row) >= 3 and all(isinstance(item, str) and item.strip() for item in row[:3]), row
        assert row[0] not in seen, f"日文名重复：{row[0]}"
        seen.add(row[0])
