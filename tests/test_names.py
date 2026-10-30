"""艺名清洗与字形折叠。断言搬自 peach `tests/test_composite_name_split.py`、`test_performer_localization.py`
与 `test_metadata_r18dev.py` 的演员用例。"""
from __future__ import annotations

import pytest

from hidden_shelf.entities import clean_person_name, collapse_repeated_entity_name, strip_zero_width
from hidden_shelf.kanji import JP_KANJI_TO_SIMPLIFIED, fold_glyphs, simplify_kanji
from hidden_shelf.scrape.names import (is_descriptive, is_planning_alias, normalized_performers, split_former_name,
                                       stage_name)


def test_fold_glyphs_and_simplify():
    assert fold_glyphs("涼森れむ") == "凉森れむ", "含假名也逐字换，这是比名字用的形"
    assert fold_glyphs("永瀬みなも") == "永濑みなも"
    assert fold_glyphs("野々宮蘭") == "野野宫兰"
    assert fold_glyphs("斎藤満里奈") == "斋藤满里奈" and "齐" not in fold_glyphs("斎藤満里奈")
    assert simplify_kanji("高山涼音") == "高山凉音"
    assert simplify_kanji("浜崎真緒") == "滨崎真绪"
    assert simplify_kanji("野々宮蘭") == "野野宫兰"
    assert simplify_kanji("桜咲姫莉") == "樱咲姬莉"
    assert simplify_kanji("辻井穂香") == "辻井穗香"
    assert simplify_kanji("安齋良良") == "安斋良良"
    assert simplify_kanji("斉藤美来") == "齐藤美来"
    # 含假名或拉丁字母的名字原样返回：半中半日的名字比原样留着更糟。
    assert simplify_kanji("飯岡かなこ") == "飯岡かなこ"
    assert simplify_kanji("Alice Shaku") == "Alice Shaku"
    assert simplify_kanji("凉森玲梦") == "凉森玲梦"
    assert simplify_kanji("") == ""
    assert all(len(key) == 1 and len(value) == 1 for key, value in JP_KANJI_TO_SIMPLIFIED.items())


def test_zero_width_and_repeated_names():
    assert strip_zero_width("‌斋藤亚美里") == "斋藤亚美里"
    assert strip_zero_width("比特ビット‌") == "比特ビット"
    assert strip_zero_width("👩‍👩") == "👩‍👩", "ZWJ 留着，emoji 靠它连字"
    assert collapse_repeated_entity_name("木村さん 木村さん") == "木村さん"
    assert collapse_repeated_entity_name("A B A B") == "A B"
    assert collapse_repeated_entity_name("M M Produce") == "M M Produce"
    assert clean_person_name("  涼森れむ ") == "涼森れむ"
    assert clean_person_name("画像を拡大する") == ""
    assert clean_person_name(None) == ""


def test_stage_name_cases():
    assert stage_name("本庄美奈子 30歳 元カフェ店員") == "本庄美奈子"
    assert stage_name("桜井奈々 28歳 某企業広報担当") == "桜井奈々"
    assert stage_name("マッチングアプリでオフパコ！！/はな/20歳") == "はな"
    assert stage_name("はな/19歳/看護師") == "はな"
    assert stage_name("超バドミントン部あかりちゃん 23歳 潮吹き部長") is None
    assert stage_name("佐倉井さん") is None
    assert stage_name("涼森れむ") == "涼森れむ"
    assert stage_name("") is None
    assert is_planning_alias("本庄美奈子 30歳 元カフェ店員")
    assert is_planning_alias("超バドミントン部あかりちゃん 23歳 潮吹き部長")
    assert is_planning_alias("佐倉井さん")
    assert not is_planning_alias("涼森れむ")


def test_descriptive_names_are_dropped():
    for name in ("145cm色白お嬢様", "美女6名", "牛逼", "人気焼肉店の看板娘", "犬好きFカップの音大生", "究極のGカップ"):
        assert is_descriptive(name), name
        performers, warnings = normalized_performers([{"japanese_name": name}])
        assert performers == [] and len(warnings) == 1, name
    for name in ("涼森れむ", "JULIA", "Cola酱", "Ssol", "三宮つばき"):
        assert not is_descriptive(name), name


def test_split_former_name():
    assert split_former_name("美谷朱音（美谷朱里）") == ("美谷朱音", "美谷朱里")
    assert split_former_name("七海ひな(旧・七瀬ひな)") == ("七海ひな", "七瀬ひな")
    # 年龄、描述、罗马字、几个旧名挤在一格：都不是「一个现名配一个旧名」。
    for name in ("Mana(23)", "みく（素人）", "Rei Mizuna (Rei Mizuna)", "美谷朱音（美谷朱里、朱里）", "ゆい（20歳）"):
        assert split_former_name(name) == (name, ""), name


def test_normalized_performers_dedup_and_aliases():
    rows = [
        {"japanese_name": "涼森れむ", "name_kana": "すずもりれむ", "name_romaji": "Remu Suzumori", "dmm_id": 1051912,
         "thumb_url": "https://pics.dmm.co.jp/mono/actjpgs/suzumori_remu.jpg", "profile_source": "r18dev"},
        {"japanese_name": "涼森れむ", "external_id": "a", "profile_source": "javdb"},
        {"japanese_name": "美谷朱音（美谷朱里）"},
        "梨奈",
        {"japanese_name": "本庄美奈子 30歳 元カフェ店員"},
        {"japanese_name": "超バドミントン部あかりちゃん 23歳 潮吹き部長"},
        {"japanese_name": "三宮つばき 三宮つばき"},
        {"japanese_name": "木村さん"},
        {"japanese_name": "Remu Suzumori"},
        {"japanese_name": ""},
        42,
    ]
    performers, warnings = normalized_performers(rows)
    assert [row["name"] for row in performers] == ["涼森れむ", "美谷朱音", "梨奈", "本庄美奈子", "三宮つばき", "Remu Suzumori"]
    assert performers[0] == {"name": "涼森れむ", "external_id": "1051912",
                             "thumb_url": "https://pics.dmm.co.jp/mono/actjpgs/suzumori_remu.jpg",
                             "aliases": ["すずもりれむ", "Remu Suzumori"], "profile_source": "r18dev"}
    assert (performers[1]["aliases"], performers[1]["former_names"]) == (["美谷朱里"], ["美谷朱里"])
    assert performers[2] == {"name": "梨奈", "external_id": "", "thumb_url": ""}
    assert "former_names" not in performers[0] and "aliases" not in performers[2]
    assert len(warnings) == 4
    assert any("已剪成艺名" in note and "本庄美奈子" in note for note in warnings)
    assert any("企划名义" in note and "あかりちゃん" in note for note in warnings)
    assert any("企划名义" in note and "木村さん" in note for note in warnings), "带敬称的是企划文案，剪不出艺名"
    assert any("重复片段" in note and "三宮つばき" in note for note in warnings)
    assert normalized_performers(None) == ([], [])
    assert normalized_performers([{"last_name": "三宮", "first_name": "つばき"}])[0][0]["name"] == "三宮つばき"
    assert normalized_performers([{"last_name": "Suzumori", "first_name": "Remu"}])[0][0]["name"] == "Suzumori Remu"
