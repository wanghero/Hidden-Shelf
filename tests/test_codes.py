"""番号识别规则的回归测试。

前半是计划 1 Task 1 列出的用例（期望值以 peach 原函数实跑结果为准），后半整段搬自
peach `tests/test_jav_code_domain.py` 里不依赖数据库与其他模块的断言。
"""
from __future__ import annotations

import unittest

import pytest

from hidden_shelf.rules.codes import (
    CODE_BODY_STOPWORDS,
    REPOST_SITE_LABELS,
    VIDEO_EXTENSIONS,
    code_query_variants,
    code_release_date,
    compact_label,
    compile_code_patterns,
    is_amateur_code,
    is_code_body_stopword,
    is_jav_asset,
    is_jav_code,
    is_repost_site_label,
    is_uncensored_code,
    is_uncensored_release,
    jav_display_metadata,
    jav_edition_badges,
    jav_fallback_title,
    normalise_code_key,
    part_marker,
    release_code_from_filename,
    release_code_from_text,
    release_identity,
    same_release_code,
    scrapes_as_jav,
    strip_promo_markers,
    tokyo_hot_code,
    western_release_identity,
)

IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


@pytest.mark.parametrize("name,expected", [
    ("ABP-758.mp4", "ABP-758"),
    ("abp758.mp4", "ABP-758"),
    ("hhd800.com@ABP-758.mp4", "ABP-758"),
    ("[javdb.com]ABP-758-C.mp4", "ABP-758"),
    ("1080p ABP-758.mp4", "ABP-758"),
    ("259LUXU-1475.mp4", "259LUXU-1475"),
    ("092415_001.mp4", "092415_001"),
    ("092415-001.mp4", "092415-001"),
    ("HEYZO-1380.mp4", "HEYZO-1380"),
    ("FC2-PPV-1234567.mp4", "FC2-PPV-1234567"),
    ("VID_20241015_120000.mp4", None),
    ("IMG_1234.mp4", None),
    ("家庭录像.mp4", None),
    ("随手拍.mp4", None),
])
def test_release_code_from_filename(name, expected):
    assert release_code_from_filename(name) == expected


def test_date_code_separator_is_identity():
    assert normalise_code_key("092415_001") != normalise_code_key("092415-001")


def test_part_markers():
    # peach 的 `part_marker` 只返回卷号本身（`cd1` → `1`），不带 `cd` 前缀。
    assert part_marker("ABP-758-cd1.mp4") == "1"
    assert part_marker("ABP-758-CD2.mp4") == "2"
    assert part_marker("ABP-758-A.mp4") == "a"
    assert part_marker("ABP-758.mp4") == ""


def test_custom_pattern_first():
    patterns = compile_code_patterns([r"^(?P<code>MYLABEL\d{3})"])
    # 自定义规则抓到的那段仍过 `release_code_from_text` 归一化，所以会补出连字符。
    assert release_code_from_filename("MYLABEL001 whatever.mp4", patterns=patterns) == "MYLABEL-001"


def test_creator_filename_not_scraped_as_jav():
    code = release_code_from_filename("sumwall95 masturbation_1.mp4")
    assert code == "SUMWALL-095"
    assert scrapes_as_jav(code, None, creator="sumwall95") is False


def test_code_kinds():
    assert is_amateur_code("259LUXU-1475")
    assert is_uncensored_code("092415_001")
    assert code_release_date("092415_001") == "2015-09-24"
    assert code_release_date("ABP-758") is None


def test_strip_promo_markers_only_head_and_tail():
    assert strip_promo_markers("[98t.tv][98t.tv]ABW-251") == "ABW-251"
    assert strip_promo_markers("Hazel Moore - [FootFetishDaily.com] - Hardcore") == (
        "Hazel Moore - [FootFetishDaily.com] - Hardcore")


def test_edition_badges():
    assert jav_edition_badges("ABP-758-C.mp4", "ABP-758") == ["中字"]
    assert jav_edition_badges("ABP-758-UC.mp4", "ABP-758") == ["无码"]
    assert jav_edition_badges("ABP-758.mp4", "ABP-758") == []


def test_video_extensions_cover_common_containers():
    assert {".mp4", ".mkv", ".avi", ".wmv", ".iso"} <= VIDEO_EXTENSIONS


# ---------------------------------------------------------------------------
# 以下整段搬自 peach tests/test_jav_code_domain.py（去掉依赖账本与其他模块的用例）。
# ---------------------------------------------------------------------------


class RepostLabelTests(unittest.TestCase):
    def test_bare_label_and_full_domain_are_both_recognised(self):
        self.assertTrue(is_repost_site_label("HHD800"))
        self.assertTrue(is_repost_site_label("hhd800.com"))
        self.assertTrue(is_repost_site_label("www.98t.la"))

    def test_zero_padded_form_is_recognised_too(self):
        # `normalise_code_key` 把 `BEI88` 写成 `BEI-088`，而界面显示、SQL 谓词和
        # 重命名脚本比的都是补过零的那一种。只拦一种写法等于没拦。
        self.assertTrue(is_repost_site_label("BEI-088"))
        self.assertEqual(compact_label("BEI-088"), compact_label("bei88"))

    def test_real_codes_of_the_same_shape_are_not_labels(self):
        for code in ("MEYD911", "IPX219C", "476MLA-179", "ABW-132", "PBD390"):
            self.assertFalse(is_repost_site_label(code), code)

    def test_every_listed_label_is_stored_in_compact_form(self):
        for label in REPOST_SITE_LABELS:
            self.assertEqual(compact_label(label), label, label)


class NormalisationTests(unittest.TestCase):
    def test_watermark_codes_keep_their_digits_without_a_hyphen(self):
        self.assertEqual(normalise_code_key("HHD800"), "HHD800")
        self.assertEqual(normalise_code_key("AAVV333"), "AAVV333")
        self.assertEqual(normalise_code_key("BEI88"), "BEI88")

    def test_real_compact_codes_still_normalise(self):
        self.assertEqual(normalise_code_key("MEYD911"), "MEYD-911")
        self.assertEqual(normalise_code_key("IPVR00296"), "IPVR-296")
        self.assertEqual(normalise_code_key("476MLA179"), "476MLA-179")

    def test_watermark_is_not_a_jav_code(self):
        for code in ("HHD800", "hhd800.com", "AAVV333", "KFA33", "HJD2048", "BEI88"):
            self.assertFalse(is_jav_code(code), code)
            self.assertFalse(is_jav_code(normalise_code_key(code)), code)

    def test_watermark_is_not_a_jav_asset_even_with_release_evidence(self):
        self.assertFalse(is_jav_asset("HHD800", "S1 NO.1 STYLE"))
        self.assertFalse(is_jav_asset("HHD800", None, "2022-04-01"))
        self.assertFalse(is_jav_asset("HHD800", None, None, ("performer",)))
        self.assertTrue(is_jav_asset("PBD390", "MOODYZ"))


class ScrapeGateTests(unittest.TestCase):
    """`scrapes_as_jav` 只拦「创作者作品的文件名被读成番号」，不替代发行证据。"""

    def test_a_creator_filename_that_looks_like_a_code_is_not_asked_about(self):
        self.assertFalse(scrapes_as_jav("SUMWALL-095", None, "sunwall"))
        self.assertFalse(scrapes_as_jav("AERITH-2412", None, "oscarkim123"))
        self.assertFalse(scrapes_as_jav("DAO-001", None, "Retsu_dao"))

    def test_release_evidence_on_the_same_row_puts_it_back_in(self):
        self.assertTrue(scrapes_as_jav("ABW-358", "Prestige", "oscarkim123"))
        self.assertTrue(scrapes_as_jav("ABW-358", None, "oscarkim123", "2024-12-01"))
        self.assertTrue(scrapes_as_jav("ABW-358", None, "oscarkim123", None, ("performer",)))

    def test_a_release_system_shape_never_needs_the_rest_of_the_evidence(self):
        for code in ("FC2-PPV-1233719", "FC-437689", "300MIUM-698", "STP-26232",
                     "SIRO-3508", "071213-625"):
            self.assertTrue(scrapes_as_jav(code, None, "合集-洛丽塔 多创作者"), code)

    def test_a_row_without_a_creator_is_asked_about_before_anything_is_known(self):
        self.assertTrue(scrapes_as_jav("300NTK-625"))
        self.assertTrue(scrapes_as_jav("MIDE-001"))
        self.assertFalse(is_jav_asset("MIDE-001"), '同一条在浏览分类里仍然不算已坐实的发行物')

    def test_a_decided_region_outside_japan_stays_out(self):
        self.assertFalse(scrapes_as_jav("AR-032", "MIB", None, None, (), "kr"))
        self.assertTrue(scrapes_as_jav("MIDE-001", None, None, None, (), "jp"))


class ExtractionTests(unittest.TestCase):
    def test_forum_url_wrapper_preserves_filename_and_custom_rules(self):
        for ending in ('[|url]', '[/url]'):
            for extension in ('', '.mp4'):
                with self.subTest(ending=ending, extension=extension):
                    name = '[url]www.98t.la@JUR-615.restored2.mp4' + ending + extension
                    self.assertEqual(release_code_from_filename(name), 'JUR-615')
        patterns = compile_code_patterns([r'^2024-(?<code>[a-z]+\d+)_'])
        self.assertEqual(release_code_from_filename(
            '[url]2024-abc123_片名.mp4[/url].mp4', patterns=patterns), 'ABC-123')
        self.assertEqual(release_code_from_filename(
            '[url]2024-abc123_片名.mp4[/url]', patterns=iter(patterns)), 'ABC-123')
        for name in ('[url]holiday.restored.mp4[/url]', '[url]ABW-358.mp4',
                     '[url][url]ABW-358.mp4[/url][/url]'):
            self.assertIsNone(release_code_from_filename(name), name)

    def test_explicit_remux_tail_identifies_one_release(self):
        self.assertEqual(release_code_from_filename(
            'LaForet Girl 41 Angel and Devil (LAFBD-41)[BD Remux].mkv'), 'LAFBD-041')
        for name in ('ABW-358 (ABW-359)[BD Remux].mkv',
                     'MKBD-S50 (ABW-358)[BD Remux].mkv',
                     'title (ABW-358) commentary.mkv'):
            self.assertIsNone(release_code_from_filename(name), name)

    def test_processing_labels_preserve_titles_and_date_separators(self):
        samples = {
            'SONE-852_^WM_iris3.mp4': 'SONE-852',
            'MIDA-574.restored_prob4.mp4': 'MIDA-574',
            'JUR-096_restored-S_2_prob4.mp4': 'JUR-096',
            'MIDA-234_WM_apo8_iris2.mp4': 'MIDA-234',
            'MIDA-590.restored_apf2_prob4.mp4': 'MIDA-590',
            'hhd800.com@SSIS-549-C_X1080X.mp4': 'SSIS-549',
            '169bbs.com@MEYD-951_[4K].mkv': 'MEYD-951',
            'SONE-054_000.mp4': 'SONE-054',
            '092415_001.restored.mp4': '092415_001',
            '092415-001.restored.mp4': '092415-001',
            'ABW-358_restored-notes.mp4': 'ABW-358',
        }
        for name, code in samples.items():
            with self.subTest(name=name):
                self.assertEqual(release_code_from_filename(name), code)

    def test_scannable_media_suffixes_preserve_short_release_codes(self):
        for suffix in sorted(VIDEO_EXTENSIONS | IMAGE):
            for name, code in ((f'LAF-41{suffix}', 'LAF-041'),
                               (f'MEYD911{suffix.upper()}', 'MEYD-911')):
                with self.subTest(name=name):
                    self.assertEqual(release_code_from_filename(name), code)
                    if suffix in VIDEO_EXTENSIONS:
                        self.assertEqual(jav_fallback_title(name, code), '')

    def test_media_suffixes_preserve_volumes_and_exclude_camera_names(self):
        for suffix in ('.mpg', '.flv', '.rmvb', '.m2ts', '.iso', '.strm'):
            with self.subTest(suffix=suffix):
                self.assertEqual(release_code_from_filename(f'LAF-41-CD2{suffix}'), 'LAF-041')
                self.assertEqual(release_code_from_filename(f'LAF-41-HD{suffix}'), 'LAF-041')
                self.assertEqual(release_code_from_filename(f'ABW-358-C{suffix}'), 'ABW-358')
                for stem in ('IMG_3092', 'VIDEO-2022', 'no0037_01', '[mtfdz.club]WX17.3'):
                    self.assertIsNone(release_code_from_filename(stem + suffix))

    def test_named_volume_suffix_preserves_the_release_code(self):
        for suffix in ('CD1', 'disc02', 'Part-3', 'DVD4', 'Vol_5'):
            with self.subTest(suffix=suffix):
                self.assertEqual(release_code_from_filename(f'ABW-358-{suffix}.mp4'), 'ABW-358')

    def test_watermark_chain_yields_the_real_code(self):
        self.assertEqual(release_code_from_filename("ABW-132.mp4"), "ABW-132")
        self.assertEqual(release_code_from_filename("IPX219C.mp4"), "IPX-219")
        self.assertEqual(release_code_from_filename("MEYD911.mp4"), "MEYD-911")
        self.assertEqual(release_code_from_filename("476MLA-179.mp4"), "476MLA-179")

    def test_fc2_ids_survive_the_compact_form(self):
        self.assertEqual(release_code_from_text("FC2-PPV-2909046"), "FC2-PPV-2909046")
        self.assertEqual(release_code_from_text("fc2802296"), "FC2-PPV-802296")

    def test_the_fc_dash_short_form_is_an_fc2_id(self):
        for name in ("FC-2052614-1.mp4", "FC-2052614_1.mp4", "FC-2052614.mp4",
                     "FC-2052614A.mp4", "FC-2052614-C.mp4"):
            self.assertEqual(release_code_from_filename(name), "FC2-PPV-2052614", name)
        self.assertEqual(release_code_from_filename("FC-437689-C.mp4"), "FC2-PPV-437689")
        self.assertEqual(normalise_code_key("FC-437689"), "FC2-PPV-437689")
        self.assertEqual(release_code_from_text("FC2052614"), "FC2-PPV-052614",
                         "不带分隔符的仍按 FC2 连写读")

    def test_labels_and_domains_extract_to_nothing(self):
        for text in ("HHD800", "hhd800.com", "www.98t.la", "AAVV333", "bei88"):
            self.assertIsNone(release_code_from_text(text), text)

    def test_what_the_volume_strip_leaves_must_be_a_whole_code(self):
        for name in ("[mtfdz.club]WX17.3", "DSCF27.1.jpg", "dao01(1).mp4", "wen66s.mp4"):
            self.assertIsNone(release_code_from_filename(name), name)
        self.assertEqual(release_code_from_filename("abp762-1.mp4"), "ABP-762")
        self.assertEqual(release_code_from_filename("ABW-358-2.mp4"), "ABW-358")
        self.assertEqual(release_code_from_filename("[98t.tv]SSIS-001-C.mp4"), "SSIS-001")


class DatedCodeSeparatorTests(unittest.TestCase):
    """日期式番号的 `_` 与 `-` 是两个片商，归一化、查询和身份都不得折叠。"""

    def test_each_separator_keeps_its_own_key(self):
        self.assertEqual(normalise_code_key("092415_001"), "092415_001")
        self.assertEqual(normalise_code_key("092415-001"), "092415-001")
        self.assertEqual(normalise_code_key(" 092415_001 "), "092415_001")

    def test_each_supported_serial_length_reaches_filename_extraction(self):
        for separator in ('-', '_'):
            for number in ('01', '001', '0012'):
                code = f'040221{separator}{number}'
                with self.subTest(code=code):
                    self.assertEqual(release_code_from_text(code), code)
                    self.assertEqual(release_code_from_filename(f'{code}.mpg'), code)
                    self.assertEqual(release_code_from_filename(f'{code}-CD2.mkv'), code)
        for code in ('040221-1', '040221-00123', '135735_0012'):
            self.assertIsNone(release_code_from_filename(f'{code}.mpg'), code)

    def test_the_two_separators_are_two_different_releases(self):
        self.assertFalse(same_release_code("092415_001", "092415-001"))
        self.assertFalse(same_release_code("092416-001", "092415-001"))
        self.assertTrue(same_release_code("092415_001", "092415_001"))

    def test_queries_never_swap_the_separator(self):
        self.assertEqual(code_query_variants("092415_001"), ("092415_001",))
        self.assertEqual(code_query_variants("092415-001"), ("092415-001",))

    def test_a_separatorless_source_id_matches_either_maker(self):
        self.assertEqual(release_identity("040221001"), "040221001")
        self.assertTrue(same_release_code("040221001", "040221-001"))
        self.assertTrue(same_release_code("040221001", "040221_001"))
        self.assertFalse(same_release_code("040221001", "040222-001"))

    def test_filenames_hand_over_the_separator_they_carry(self):
        self.assertEqual(release_code_from_filename("1pondo-092415_001-FHD.mp4"),
                         "092415_001")
        self.assertEqual(release_code_from_filename("1pon-092415-001-fhd1_(new).mp4"),
                         "092415-001")
        self.assertEqual(release_code_from_text("092415_001"), "092415_001")

    def test_titles_still_strip_a_code_written_the_other_way(self):
        self.assertEqual(jav_fallback_title("1pon-092415-001-fhd1_(new).mp4",
                                            "092415_001"), "")

    def test_other_shapes_still_fold_their_underscore(self):
        self.assertEqual(normalise_code_key("ABW_232"), "ABW-232")
        self.assertEqual(normalise_code_key("300MIUM_1239"), "300MIUM-1239")
        self.assertEqual(normalise_code_key("fc2_ppv_802296"), "FC2-PPV-802296")

    def test_one_shared_shape_decides_dated_and_uncensored(self):
        for value in ("092415_001", "092415-001", "040221-0012"):
            self.assertTrue(is_jav_code(value), value)
            self.assertTrue(is_uncensored_code(value), value)
        for value in ("09241-001", "0924150-001", "092415-1", "ABW-232"):
            self.assertFalse(is_uncensored_code(value), value)


class TokyoHotShapeTests(unittest.TestCase):
    def test_the_canonical_form_is_uppercase_and_zero_padded(self):
        # 用户 2026-11-01 定：和别的番号一样大写（此前跟 peach 取小写）
        self.assertEqual(tokyo_hot_code("N0646"), "N0646")
        self.assertEqual(tokyo_hot_code("n646"), "N0646")
        self.assertEqual(tokyo_hot_code("k1234"), "K1234")
        self.assertEqual(tokyo_hot_code("RED123"), "RED-123")
        self.assertEqual(tokyo_hot_code("red_123"), "RED-123")
        self.assertEqual(tokyo_hot_code("ABW-132"), "")

    def test_the_key_the_identity_and_the_shape_gate_agree(self):
        self.assertEqual(normalise_code_key("n0646"), "N0646")
        self.assertEqual(release_identity("n0646"), "N0646")
        self.assertTrue(same_release_code("n646", "N0646"))
        self.assertTrue(is_jav_code("n0646") and is_jav_code("N0646"))
        self.assertTrue(is_uncensored_code("n0646"))
        self.assertEqual(code_query_variants("n0646"), ("N0646",))

    def test_kirari_numbers_carry_an_s_before_the_serial(self):
        for value in ("MKBD-S89", "MKBD-S118", "MKD-S89", "mkbd-s118"):
            self.assertTrue(is_jav_code(normalise_code_key(value)), value)
        for value in ("ABC-S12", "MKBD-S1", "MKBD-89S"):
            self.assertFalse(is_jav_code(normalise_code_key(value)), value)

    def test_kirari_codes_reach_text_filename_and_custom_rule_entrypoints(self):
        rules = compile_code_patterns([r'番号\{(?P<code>[^}]+)\}'])
        for code in ('MKBD-S94', 'MKD-S94', 'MKBD-S118', 'MKD-S1234'):
            self.assertTrue(is_uncensored_code(code.lower()), code)
            for suffix in ('', '-C', '-CD2', '_part1'):
                name = f'{code.lower()}{suffix}.mkv'
                with self.subTest(name=name):
                    self.assertEqual(release_code_from_filename(name), code)
            self.assertEqual(release_code_from_text(code.lower()), code)
            self.assertEqual(release_code_from_text(code.replace('-', '_')), code)
            self.assertEqual(release_code_from_filename(f'{code} 片名.mpg'), code)
            self.assertEqual(release_code_from_filename(f'番号{{{code}}}.mp4', patterns=rules), code)
        for code in ('ABC-S12', 'MKBD-S1', 'MKBD-S12345', 'MKBD-89S'):
            for suffix in ('.mkv', ' 片名.mp4'):
                self.assertIsNone(release_code_from_filename(code + suffix), code)

    def test_kirari_display_projects_titles_and_edition_badges(self):
        for separator in ('-', '_'):
            name = f'MKBD{separator}S94-C 作品标题.mkv'
            self.assertEqual(jav_display_metadata(name, 'MKBD-S94'), {
                'display_code': 'MKBD-S94', 'display_title': '作品标题',
                'edition_badges': ['中字', '无码']})
        self.assertEqual(jav_fallback_title('MKD-S118.mp4', 'MKD-S118'), '')

    def test_a_bare_number_is_read_only_at_the_head_of_the_name(self):
        self.assertEqual(release_code_from_filename("n1032.mkv"), "N1032")
        self.assertEqual(release_code_from_filename("n0762.mkv"), "N0762")
        self.assertEqual(
            release_code_from_filename("n1025_rena_yamamoto_ss_n_fhd.wmv"), "N1025")
        self.assertEqual(
            release_code_from_filename("n0890_mary_jane_lee_tb_n {ThePornGarage}.mp4"),
            "N0890")

    def test_the_site_name_licenses_a_number_further_in(self):
        self.assertEqual(release_code_from_filename("Tokyo-Hot n0646 HD.wmv"), "N0646")
        self.assertEqual(
            release_code_from_filename("Tokyo Hot (n1042)(Rena Yamamoto)[1080p].wmv"),
            "N1042")
        self.assertIsNone(release_code_from_filename("Tokyo-Hot.mp4"))

    def test_lookalikes_without_the_site_stay_out(self):
        self.assertIsNone(release_code_from_filename("no0037_01.wmv"))
        self.assertIsNone(release_code_from_filename("k12.mp4"))
        self.assertIsNone(release_code_from_filename("Rena n1042 clip.mp4"))

    def test_the_number_is_stripped_out_of_the_fallback_title(self):
        self.assertEqual(jav_fallback_title("Tokyo-Hot n0646 HD.wmv", "n0646"), "")
        self.assertEqual(
            jav_fallback_title("n1025_rena_yamamoto_ss_n_fhd.wmv", "n1025"),
            "rena yamamoto ss n")


class DeliveryFilenameTests(unittest.TestCase):
    def test_a_dmm_delivery_name_carries_the_code_between_date_and_codec(self):
        self.assertEqual(release_code_from_filename("0112mide612-h264.mp4"), "MIDE-612")

    def test_the_date_prefix_is_four_digits_and_the_tail_is_a_codec(self):
        self.assertIsNone(release_code_from_filename("0112mide612-鈴村あいり.mp4"))
        self.assertIsNone(release_code_from_filename("259luxu1137-h264.mp4"))
        self.assertEqual(release_code_from_filename("259LUXU-1137.mp4"), "259LUXU-1137")

    def test_heyzo_writes_its_own_name_before_the_number(self):
        self.assertEqual(release_code_from_filename("heyzo_hd_1031_full.mp4"), "HEYZO-1031")
        self.assertEqual(release_code_from_filename("heyzo_lt_1380_full-1.mp4"), "HEYZO-1380")
        self.assertEqual(release_code_from_filename("HEYZO-1380.mp4"), "HEYZO-1380")

    def test_the_number_alone_is_not_a_heyzo_release(self):
        self.assertIsNone(release_code_from_filename("Banbi_20歳の女子大生_1080.mp4"))
        self.assertIsNone(release_code_from_filename("heyzo.mp4"))


class TitledFilenameTests(unittest.TestCase):
    def test_a_title_after_the_code_does_not_hide_it(self):
        for name, code in (("CAWD-987 片名と女優名.mp4", "CAWD-987"),
                           ("GVH-520【中文字幕】片名.mp4", "GVH-520"),
                           ("SSIS-001-C 片名.mp4", "SSIS-001"),
                           ("ABW-358-CD1 片名.mp4", "ABW-358"),
                           ("[FHD] MIDV-999 片名.mp4", "MIDV-999"),
                           ("女優名 @DASD-409.mp4", "DASD-409"),
                           ("300MIUM-1239 片名.mp4", "300MIUM-1239")):
            self.assertEqual(release_code_from_filename(name), code, name)

    def test_an_edition_marker_between_code_and_title_is_not_title_text(self):
        for code in ('ABW-358', 'MKBD-S94'):
            for edition in ('C', 'CH', 'SUB', 'UC', 'U'):
                self.assertEqual(jav_fallback_title(f'{code}-{edition} 作品标题.mkv', code), '作品标题')
            self.assertEqual(jav_fallback_title(f'{code} Club 标题.mkv', code), 'Club 标题')

    def test_an_fc2_number_is_read_anywhere_in_the_name(self):
        for name in ("+++ FC2-PPV-1234567 片名 前編.mp4",
                     "+++ FC2-PPV-1234567_part1.mp4",
                     "【個人撮影】FC2PPV 1234567 片名.mp4",
                     "片名 fc2-ppv-1234567.mp4"):
            self.assertEqual(release_code_from_filename(name), "FC2-PPV-1234567", name)

    def test_only_the_first_ascii_run_may_be_the_code(self):
        self.assertIsNone(release_code_from_filename("Rena n1042 clip.mp4"))
        self.assertIsNone(release_code_from_filename("Morning ABP-123 talk.mp4"))

    def test_a_known_label_name_before_the_code_is_skipped(self):
        """转载站把厂牌名写在番号前面（`Catwalk CWPBD-120 …`）：登记过的无码厂牌名可以站在番号前面，
        别的英文词不行（上一条测试）。"""
        for name, code in (("Catwalk CWPBD-120 Miku Ohashi - Jav Uncensored Porn Tubes.mp4", "CWPBD-120"),
                           ("Catwalk Poison CWPBD-120.mp4", "CWPBD-120"),
                           ("catwalk_CWP-089 title.mp4", "CWP-089"),
                           ("Caribbeancom ABC-123 title.mp4", "ABC-123")):
            self.assertEqual(release_code_from_filename(name), code, name)
        self.assertTrue(is_uncensored_release("Catwalk CWPBD-120 Miku Ohashi.mp4", "CWPBD-120"))

    def test_a_glued_or_underscored_handle_in_a_title_is_not_a_code(self):
        for name in ("南叔(Nanshu969)片名.zip", "推特网黄「LOOKS199」片名.mp4",
                     "photo_83439@14-09-2021_07-01-18.jpg", "片名@yszl_0107.mp4",
                     "片名....vip1129.mp4"):
            self.assertIsNone(release_code_from_filename(name), name)

    def test_user_rules_run_before_the_built_in_ones(self):
        rules = compile_code_patterns([r"^\d{4}-(?<code>[a-z]+\d+)_", r"\{(\w+-\d+)\}"])
        self.assertEqual(release_code_from_filename("2024-abc123_片名.mp4", patterns=rules), "ABC-123")
        self.assertEqual(release_code_from_filename("片名 {SSIS-001}.mp4", patterns=rules), "SSIS-001")
        self.assertIsNone(release_code_from_filename("2024-abc123_片名.mp4"))
        loose = compile_code_patterns([r"^(\S+)"])
        self.assertEqual(release_code_from_filename("片名 CAWD-987.mp4", patterns=loose), "CAWD-987")

    def test_a_broken_user_rule_says_which_one(self):
        with self.assertRaisesRegex(ValueError, "第 2 条"):
            compile_code_patterns([r"(\w+-\d+)", "(unclosed"])
        self.assertEqual(compile_code_patterns(None), ())
        self.assertEqual(compile_code_patterns(["", "  "]), ())

    def test_a_short_episode_or_a_date_after_a_name_is_not_a_code(self):
        for name in ("ShinoAoi-15-1080p.mp4", "miru-10--Vccd67yz.mp4",
                     "美女【Daidai-77】片名.mp4", "TG-2025-01-27-232751475.mp4"):
            self.assertIsNone(release_code_from_filename(name), name)


class WesternDateShapeTests(unittest.TestCase):
    def test_the_identity_is_the_series_and_the_release_day(self):
        self.assertEqual(
            western_release_identity(
                "DorcelClub.24.12.02.Christy.White.XXX.1080p.HEVC.x265.PRT.mp4"),
            "DORCELCLUB.2024-12-02")
        self.assertEqual(
            western_release_identity("Vixen.2026.05.07.Scene.XXX.1080p.mp4"),
            "VIXEN.2026-05-07")
        self.assertEqual(
            western_release_identity(
                "E081. Shinaryen.19.11.08.Sexy.Babe.Suck.Big.Cock.Boyfriend "
                "And Rough Sex After Reading A Porn Story -【Shinaryen】.mp4"),
            "SHINARYEN.2019-11-08")

    def test_two_year_writings_of_one_scene_are_one_identity(self):
        self.assertTrue(same_release_code("Vixen.26.05.07", "Vixen.2026.05.07"))
        self.assertFalse(same_release_code("Vixen.26.05.07", "Vixen.26.05.08"))

    def test_no_jav_code_is_mined_out_of_a_western_name(self):
        for name in (
            "DorcelClub.24.12.02.Christy.White.XXX.1080p.HEVC.x265.PRT.mp4",
            "Vixen.2026.05.07.Scene.XXX.1080p.mp4",
            "E115. LIFESELECOTR.20.10.03.Shinaryen.My.Hot.Girlfriend -【Shinaryen】.mp4",
        ):
            self.assertIsNone(release_code_from_filename(name), name)
            self.assertFalse(is_jav_code(western_release_identity(name)), name)

    def test_a_date_inside_the_title_does_not_invent_a_series(self):
        self.assertEqual(
            western_release_identity(
                "E078. Redhead.Sucking.Big.Cock.And.Hard.Sex.2019.10.15 -【Shinaryen】.mp4"),
            "")
        self.assertEqual(
            western_release_identity(
                "E097. Gamer Girl Teen Fucked While She Plays（20.03.22）.mp4"), "")

    def test_an_impossible_month_or_day_is_not_a_release_date(self):
        self.assertEqual(western_release_identity("Series.24.13.02.Scene.mp4"), "")
        self.assertEqual(western_release_identity("Series.24.12.32.Scene.mp4"), "")


class CodeBodyStopwordTests(unittest.TestCase):
    def test_the_camera_and_structure_words_yield_nothing(self):
        self.assertIsNone(release_code_from_filename("IMG_3092 (2).mp4"))
        self.assertIsNone(release_code_from_filename("IMG_7195 (2).mov"))
        self.assertIsNone(release_code_from_filename("video_2025-09-02_20-07-50.mp4"))
        self.assertIsNone(release_code_from_filename("no0037_01.wmv"))
        self.assertIsNone(release_code_from_filename("part 18.mp4"))

    def test_a_phone_capture_is_not_a_dated_release(self):
        self.assertIsNone(release_code_from_filename("VID_20241015_071039_730.mp4"))
        self.assertIsNone(release_code_from_filename("VID_20220818_125735_816.mp4"))

    def test_an_impossible_month_or_day_is_not_a_dated_code(self):
        self.assertFalse(is_jav_code("135735_816"))
        self.assertFalse(is_uncensored_code("125745_816"))
        self.assertIsNone(release_code_from_text("125735_816"))

    def test_the_real_dated_releases_still_parse(self):
        self.assertEqual(release_code_from_filename("1pondo-092415_001-FHD.mp4"),
                         "092415_001")
        self.assertEqual(release_code_from_filename("040221-001-carib-1080p.mp4"),
                         "040221-001")
        self.assertEqual(release_code_from_filename("122614_001-1pon-whole1_hd.avi"),
                         "122614_001")

    def test_a_maker_code_that_starts_with_a_stopword_is_kept(self):
        self.assertEqual(release_code_from_filename("[K-MIB]NOAH-101(NOAH)(1).mp4"),
                         "NOAH-101")
        self.assertFalse(is_code_body_stopword("NOAH-101"))
        self.assertTrue(is_code_body_stopword("IMG_3092"))

    def test_a_stopword_already_stored_in_the_ledger_is_not_a_jav_code(self):
        for stored in ("VIDEO-2022", "VIDEO-2025", "IMG-3092"):
            self.assertFalse(is_jav_code(stored), stored)
            self.assertFalse(is_jav_asset(stored, "S1 NO.1 STYLE"), stored)
        self.assertTrue(is_jav_code("NOAH-101"))

    def test_a_stored_date_code_with_an_impossible_day_is_not_a_jav_code(self):
        self.assertFalse(is_jav_code("125735-816"))
        self.assertFalse(is_jav_code("131454-967"))
        self.assertTrue(is_jav_code("092415-001"))

    def test_the_table_holds_upper_case_letters_only(self):
        for word in CODE_BODY_STOPWORDS:
            self.assertEqual(word, word.upper(), word)
            self.assertTrue(word.isalpha(), word)


class PromoDomainStrippingTests(unittest.TestCase):
    def test_a_domain_in_front_of_the_code_is_dropped(self):
        self.assertEqual(release_code_from_filename("www.98T.la@ABW-358-U.mp4"),
                         "ABW-358")
        self.assertEqual(release_code_from_filename("www.xxx.com@ABC-123.mp4"),
                         "ABC-123")
        self.assertEqual(release_code_from_filename("[xxx.cc]ABC-123.mp4"), "ABC-123")

    def test_a_domain_behind_the_code_is_dropped(self):
        self.assertEqual(release_code_from_filename("ABC-123@xxx.net.mp4"), "ABC-123")
        self.assertEqual(release_code_from_filename("ABP-762-fuckbe.com.mp4"), "ABP-762")
        self.assertEqual(release_code_from_filename("259LUXU-1004-fuckbe.com.mp4"),
                         "259LUXU-1004")
        self.assertEqual(
            release_code_from_filename("WAAA-415-UNCENSORED-nyap2p.com.mp4"), "WAAA-415")

    def test_an_fc2_id_behind_a_domain_is_still_an_fc2_id(self):
        self.assertEqual(release_code_from_filename("www.98T.la@FC2-1292985.mp4"),
                         "FC2-PPV-1292985")

    def test_a_bare_watermark_is_still_not_a_code(self):
        for text in ("hhd800.com", "www.98t.la", "HHD800"):
            self.assertIsNone(release_code_from_text(text), text)
