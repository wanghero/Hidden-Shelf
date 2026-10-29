"""按内容类型的来源链。搬自 peach `tests/test_metadata_routes.py`，期望按裁剪后的表改。"""
from __future__ import annotations

import pytest

from hidden_shelf.scrape.policy import SOURCE_SPECS
from hidden_shelf.scrape.routes import (
    COMMUNITY_SOURCES,
    CONTENT_TYPES,
    OFFICIAL_STAGE,
    ROUTES,
    classify,
    official_route,
    parse_route_overrides,
    required_scalars,
    route,
    route_for_code,
    settles,
    stage_members,
    stages_for_code,
)


@pytest.mark.parametrize("code,expected", [
    ("ABW-220", "censored"), ("DASS-468", "censored"), ("IPX-060", "censored"),
    ("300MIUM-1239", "amateur"), ("259LUXU-1475", "amateur"), ("SIRO-3508", "amateur"), ("STP-26232", "amateur"),
    ("092415_001", "uncensored"), ("040221-001", "uncensored"), ("HEYZO-1380", "uncensored"), ("n0780", "uncensored"),
    ("FC2-PPV-1812235", "fc2"), ("fc2-ppv-1233719", "fc2"),
    ("YUJ-103", "kmib"), ("NOAH-101", "kmib"),
    ("", "unknown"), (None, "unknown"),
    ("ABF-123", "censored"), ("ABP-999", "censored"),
])
def test_the_shape_of_the_code_decides_the_type(code, expected):
    assert classify(code) == expected


def test_every_type_has_a_chain():
    assert set(ROUTES) == set(CONTENT_TYPES)


@pytest.mark.parametrize("code,hints,expected", [
    ("LUXU-688", (r"B:\番号\_未知厂牌\LUXU-688\259LUXU-688.mp4", "ラグジュTV"), "amateur"),
    ("FC-43768", (r"B:\MVP\FC-437689可爱的素人妹子-C\FC-437689-C.mp4",), "fc2"),
    ("TZ-105", (r"B:\番号\TZ-105\[ThZu.Cc]兔子先生TZ-105K杯神乳美体享受.mp4",), "other"),
    ("MXGD-3721", (r"B:\云下载\07\网红丝袜女神小魔女大尺度私拍啪啪视频合集\MXGD3721.MP4",), "other"),
    ("GFE-180", (r"B:\番号\wankzvr-elena-koshka-GFE-180_180x180_3dh_LR.mp4",), "other"),
    ("UWFR-085", (r"A:\Pack From Shared\pen\UWFr85dczsVeysGg.mp4",), "unsure"),
    ("KUZU-25010", (r"A:\Pack From Shared\pen\KUZU_250103-U_iris3.mp4",), "unsure"),
])
def test_the_local_evidence_splits_what_only_looks_censored(code, hints, expected):
    assert classify(code, *hints) == expected


@pytest.mark.parametrize("code,hint", [
    ("MIDE-612", r"R:\hjd2048.com-0112mide612-h264\0112mide612-h264.mp4"),
    ("LXVS-039", r"R:\Prestige\LXVS-039\[FHD]LXVS-039\118lxvs00039.mp4"),
    ("SDMU-725", r"R:\SDMU-725\1sdmu00725hhb.mp4"),
    ("BBZA-007", r"R:\HD-bbza-007\HD-BBZA-007.mp4"),
    ("DVAJ-185", r"R:\第一會所新片@SIS001@(アリスJAPAN)(DVAJ-185)ひたすら.mp4"),
    ("ABP-123", r"R:\media\movie.mp4"),
    ("ABP-758", "Prestige/ABP-758/ABP-758.mp4"),
])
def test_the_usual_ways_a_release_file_is_named_stay_censored(code, hint):
    assert classify(code, hint) == "censored"


def test_other_systems_ask_nobody_and_unsure_codes_ask_only_the_indexes():
    assert route_for_code("TZ-105", r"B:\番号\TZ-105\兔子先生TZ-105.mp4") == ()
    assert stages_for_code("UWFR-085", r"A:\pen\UWFr85dczsVeysGg.mp4") == ("avbase", "javbus", "javdb")


def test_members_are_sources_we_have_a_parser_for():
    for content, chain in ROUTES.items():
        for source in chain:
            assert source in SOURCE_SPECS, (content, source)
    assert set(SOURCE_SPECS) == {"r18dev", "dmm", "1pondo", "fc2", "javarchive", "avbase", "javbus", "javdb"}


def test_censored_asks_the_mirror_then_dmm_then_the_indexes_with_javdb_last():
    assert ROUTES["censored"] == ("r18dev", "dmm", "avbase", "javbus", "javdb")
    assert route_for_code("ABW-220") == ("r18dev", "dmm", "avbase", "javbus", "javdb")
    assert route_for_code("SSIS-057") == ("r18dev", "dmm", "avbase", "javbus", "javdb")
    for unported in ("prestige", "faleno", "dahlia", "makers", "mgstage", "avsox", "fc2cmadb", "fc2ppvdb", "javten"):
        assert unported not in SOURCE_SPECS
        for chain in ROUTES.values():
            assert unported not in chain


def test_amateur_goes_to_the_indexes_then_r18dev_and_never_dmm():
    for code in ("300MIUM-1239", "259LUXU-1475", "SIRO-4630"):
        assert route_for_code(code) == ("avbase", "javbus", "javdb", "r18dev")


def test_dmm_is_only_on_the_censored_chain():
    for content, chain in ROUTES.items():
        assert ("dmm" in chain) == (content == "censored"), content
    assert ROUTES["censored"].index("dmm") == ROUTES["censored"].index("r18dev") + 1
    assert "dmm" in OFFICIAL_STAGE


def test_uncensored_never_asks_r18dev():
    for code in ("040221-001", "HEYZO-1380", "n0780"):
        assert "r18dev" not in route_for_code(code)
        assert route_for_code(code) == ("avbase", "javbus", "javdb")


def test_a_dated_code_only_asks_1pondo_when_this_file_says_so():
    assert route_for_code("112312_478", "R:/media/1pon/112312_478-1pon-whole1_hd.mp4") == ("1pondo", "avbase", "javbus", "javdb")
    assert route_for_code("040221-001", "R:/media/Carib-040221-001-FHD/040221-001-carib.mp4") == ("avbase", "javbus", "javdb")
    assert route_for_code("112312_478", "一本道") == ("1pondo", "avbase", "javbus", "javdb")


def test_fc2_asks_the_shop_then_the_archive_then_javdb_only():
    assert route_for_code("FC2-PPV-1812235") == ("fc2", "javarchive", "javdb")
    assert "r18dev" not in route_for_code("FC2-PPV-1812235")
    assert "avbase" not in route_for_code("FC2-PPV-1812235")


def test_korean_mib_and_a_missing_code_ask_nobody():
    assert route_for_code("YUJ-103") == ()
    assert route_for_code("") == ()


def test_official_and_community_do_not_overlap():
    assert set(OFFICIAL_STAGE) & set(COMMUNITY_SOURCES) == set()
    assert official_route("FC2-PPV-1812235") == ("fc2", "javarchive")
    assert official_route("ABW-220") == ("r18dev", "dmm")


def test_every_source_is_its_own_stage():
    """综合索引三家不合成一档：有一家答了就停（用户 2026-10-29 决定）。"""
    assert stages_for_code("ABW-220") == ("r18dev", "dmm", "avbase", "javbus", "javdb")
    assert stages_for_code("300MIUM-1239") == ("avbase", "javbus", "javdb", "r18dev")
    assert stages_for_code("040221-001") == ("avbase", "javbus", "javdb")
    assert stages_for_code("FC2-PPV-1812235") == ("fc2", "javarchive", "javdb")
    assert stages_for_code("YUJ-103") == ()
    chain = route_for_code("FC2-PPV-1812235")
    assert stage_members("fc2", chain) == ("fc2",)
    assert stage_members("javdb", chain) == ("javdb",)
    assert stage_members("r18dev", chain) == ()


def test_only_the_scalar_fields_this_row_still_misses_count():
    assert required_scalars(("title", "tags", "studio")) == ("title", "studio")
    assert required_scalars(("tags",)) == ()


def test_settles():
    assert settles(("title", "studio"), ("title", "studio", "tags"))
    assert not settles(("title", "performers"), ("title", "studio"))
    # 要的本来就不是标量，第一家给出资料就停。
    assert settles((), ())
    scalars = ("title", "performers", "studio", "release_date")
    assert settles(scalars, (*scalars, "tags"), wants_tags=True, then="dmm")
    # 缺标签时在官方档之间多问一家；下一档是综合索引或 dmm 就停。
    assert not settles(scalars, scalars, wants_tags=True, then="r18dev")
    assert not settles(scalars, scalars, wants_tags=True, then="1pondo")
    assert settles(scalars, scalars, wants_tags=True, then="dmm")
    assert settles(scalars, scalars, wants_tags=True, then="avbase")
    assert settles(scalars, scalars, wants_tags=True, then="")
    assert settles(scalars, scalars, wants_tags=False, then="r18dev")
    assert not settles(("title", "release_date"), ("title", "studio", "tags"), then="r18dev")


def test_an_override_replaces_the_whole_chain():
    overrides = parse_route_overrides("censored=r18dev,javdb")
    assert route("censored", overrides=overrides) == ("r18dev", "javdb")
    assert route_for_code("ABW-220", overrides=overrides) == ("r18dev", "javdb")
    assert route("uncensored", overrides=overrides) == ROUTES["uncensored"]
    assert route_for_code("FC2-PPV-1812235", overrides=parse_route_overrides({"fc2": ()})) == ()
    assert parse_route_overrides("fc2=fc2;censored=r18dev") == parse_route_overrides({"fc2": ["fc2"], "censored": ["r18dev"]})
    assert parse_route_overrides(None) == {}


def test_unknown_names_are_refused_instead_of_silently_dropped():
    with pytest.raises(ValueError, match="未知内容类型"):
        parse_route_overrides("hentai=javdb")
    with pytest.raises(ValueError, match="未知来源"):
        parse_route_overrides("censored=mgstage")
    with pytest.raises(ValueError, match="类型=来源"):
        parse_route_overrides("censored")
    with pytest.raises(ValueError):
        route("bogus")
