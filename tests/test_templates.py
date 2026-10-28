"""归位路径模板。后半的断言搬自 peach `tests/test_organize.py`（模板部分）。"""
from __future__ import annotations

import pytest

from hidden_shelf.organize.templates import (
    MAX_COMPONENT,
    PLACEHOLDERS,
    TemplateError,
    clean_filename,
    missing_fields,
    render,
    required_fields,
    sanitise_component,
    template_fields,
    validate_template,
)

VALUES = {
    "code": "ABC-123", "title": "标题", "studio": "厂牌", "series": "系列",
    "year": "2024", "actors": "甲、乙", "cd": "2", "definition": "1080p",
}


def test_optional_group_drops_when_missing():
    assert render("{code}[-cd{cd}]", {"code": "ABP-758"}) == "ABP-758"
    assert render("{code}[-cd{cd}]", {"code": "ABP-758", "cd": "1"}) == "ABP-758-cd1"


def test_illegal_chars_and_reserved_names():
    assert render("{title}", {"title": "甲?乙:丙*丁"}) == "甲_乙_丙_丁"
    assert render("{title}", {"title": "CON"}) == "_CON"
    assert sanitise_component("nul.mp4") == "_nul.mp4"


def test_validate_rejects_escape():
    for template in ("../{code}", "/abs/{code}", "{unknown}", "C:\\{code}", "..\\{code}", "{code}/x"):
        with pytest.raises(TemplateError):
            validate_template(template)
    with pytest.raises(TemplateError):
        validate_template("{studio}/../{code}", directory=True)


def test_truncates_middle_not_tail():
    long_title = "甲" * 300 + "尾巴"
    rendered = render("{code} {title}", {"code": "ABP-758", "title": long_title})
    assert rendered.startswith("ABP-758 ")
    assert "…" in rendered
    assert rendered.endswith("尾巴")
    assert len(rendered) <= MAX_COMPONENT


def test_directory_template_allows_slash():
    assert validate_template("{studio}/{code}", directory=True) == "{studio}/{code}"
    assert render("{studio}/{code}", VALUES, directory=True) == "厂牌/ABC-123"
    with pytest.raises(TemplateError):
        validate_template("{studio}/{code}")


def test_fields_and_missing():
    assert template_fields("{studio}/{code}[-cd{cd}]") == frozenset({"studio", "code", "cd"})
    assert required_fields("{studio}/{code}[-cd{cd}]") == frozenset({"studio", "code"})
    assert missing_fields("{studio}/{code}[-cd{cd}]", {"code": "X-1"}) == frozenset({"studio"})
    assert missing_fields("{code}[-cd{cd}]", {"code": "X-1"}) == frozenset()
    assert set(PLACEHOLDERS) == {"code", "title", "studio", "series", "year", "actors", "cd", "definition"}


def test_empty_template_renders_empty():
    assert render("", VALUES) == ""
    assert validate_template("   ") == ""


# ---- 搬自 peach tests/test_organize.py ----

CASES = [
    ("{code}", {}, "ABC-123"),
    ("{code}[ {title}]", {}, "ABC-123 标题"),
    ("{number}", {}, "ABC-123"),
    ("{number} {title}", {}, "ABC-123 标题"),
    ("{number}[ {title}]", {"title": ""}, "ABC-123"),
    ("{number}[ {title}]", {}, "ABC-123 标题"),
    ("{number}[ CD{cd}]", {"cd": ""}, "ABC-123"),
    ("{number}[ CD{cd}]", {}, "ABC-123 CD2"),
    ("[{studio} ][{series} ]{number}", {"series": ""}, "厂牌 ABC-123"),
    ("{number} [{definition}]", {}, "ABC-123 1080p"),
    ("{number} [完整版]", {}, "ABC-123 完整版"),
    ("{number} {{x}}", {}, "ABC-123 {x}"),
    ("{number} [[x]]", {}, "ABC-123 [x]"),
    ("{number}[ ({year})][ {actors}]", {"year": ""}, "ABC-123 甲、乙"),
]


@pytest.mark.parametrize("template,overrides,expected", CASES)
def test_render_table(template, overrides, expected):
    assert render(template, {**VALUES, **overrides}) == expected


def test_missing_required_field_is_reported():
    values = {**VALUES, "title": ""}
    assert missing_fields("{number} {title}", values) == frozenset({"title"})
    assert render("{number} {title}", values) == "ABC-123"


def test_optional_field_is_not_required():
    assert missing_fields("{number}[ {title}]", {**VALUES, "title": ""}) == frozenset()


def test_directory_template_keeps_layers():
    assert render("{studio}/{number}", VALUES, directory=True) == "厂牌/ABC-123"


@pytest.mark.parametrize("original,expected", [
    ('01_First Part⧹⧹Second Part⧹⧹Last Scene.mp4', '01_First Part Second Part Last Scene.mp4'),
    ('★ 标题💎👑✨ → 片段 �.mp4', '标题 片段.mp4'),
    ('标题＼＼片段﹨补充／附录.mp4', '标题 片段 补充 附录.mp4'),
    ('标题\ue519\u200b\ufeff\x00片段.mp4', '标题片段.mp4'),
    ('👩🏽\u200d💻标题❤️\ufe0f.mp4', '标题.mp4'),
    ('【中日文】 café ガール 168㎝ 1920×1080 (2).mp4', '【中日文】 café ガール 168㎝ 1920×1080 (2).mp4'),
    ('★💎.mp4', '★💎.mp4'),
    ('★CON.mp4', '_CON.mp4'),
])
def test_filename_symbols_and_invalid_unicode_are_removed(original, expected):
    assert clean_filename(original) == expected
    assert clean_filename(expected) == expected


def test_illegal_characters_become_underscore():
    assert sanitise_component('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"


def test_trailing_dot_and_space_are_dropped():
    assert sanitise_component("名字. ") == "名字"


def test_reserved_device_name_is_prefixed():
    assert sanitise_component("CON") == "_CON"
    assert sanitise_component("nul.mp4") == "_nul.mp4"


def test_long_value_is_truncated_from_the_middle():
    value = sanitise_component("甲" * 400)
    assert len(value) <= 120
    assert "…" in value


@pytest.mark.parametrize("template", [
    "..\\{number}", "../{number}", "C:\\{number}", "/{number}", "{number}/{title}",
    "{unknown}", "{number", "{number}]", "[{number}",
])
def test_escaping_templates_are_rejected(template):
    with pytest.raises(TemplateError):
        validate_template(template)


def test_directory_template_may_layer_but_not_escape():
    assert validate_template("{studio}\\{number}", directory=True) == "{studio}/{number}"
    with pytest.raises(TemplateError):
        validate_template("{studio}/../{number}", directory=True)


def test_value_cannot_introduce_a_layer():
    assert render("{title}", {"title": "a/../b"}) == "a_.._b"
