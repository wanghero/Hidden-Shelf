"""来源分级与字段结算策略。搬自 peach `tests/test_metadata_policy.py`，按 8 站裁剪。"""
from __future__ import annotations

import pytest

from hidden_shelf.rules.codes import is_uncensored_code
from hidden_shelf.scrape import routes
from hidden_shelf.scrape.policy import (
    CHAIN_COMMUNITY,
    CHAIN_FALLBACK,
    CHAIN_LOCAL_NFO,
    CHAIN_OFFICIAL,
    CHAIN_PREFERRED,
    CHAIN_UNKNOWN,
    FIELD_SOURCE_ORDER,
    FIELDS,
    LOCAL_NFO_SOURCE,
    POLICY_VERSION,
    SOURCE_SPECS,
    chain_rank,
    field_rank,
    owner_tier,
    preferred_tag_source,
    sort_candidates,
    source_tier,
)


def test_censored_tags_prefer_javdb_while_nfo_and_other_fields_keep_their_order():
    candidates = [{"source": "dmm"}, {"source": "javdb"}, {"source": "r18dev"}]
    assert sort_candidates("tags", candidates, code="ABW-220")[0]["source"] == "javdb"
    assert sort_candidates("tags", [*candidates, {"source": LOCAL_NFO_SOURCE}], code="ABW-220")[0]["source"] == LOCAL_NFO_SOURCE
    assert chain_rank("tags", LOCAL_NFO_SOURCE, code="ABW-220") < chain_rank("tags", "javdb", code="ABW-220")
    assert chain_rank("tags", "javdb", code="ABW-220") < chain_rank("tags", "dmm", code="ABW-220")
    for field in ("studio", "performers", "title", "release_date"):
        assert sort_candidates(field, candidates, code="ABW-220")[0]["source"] == "dmm"
    for code in ("FC2-PPV-1234567", "259LUXU-1475", "040221-001", "AR-101"):
        assert sort_candidates("tags", candidates, code=code)[0]["source"] == "dmm"
        assert preferred_tag_source(code) is None
    assert preferred_tag_source("ABW-220") == "javdb"
    assert not SOURCE_SPECS["javdb"].official


def test_every_source_the_chain_can_ask_is_registered_once():
    chain_sources = {source for chain in routes.ROUTES.values() for source in chain}
    assert chain_sources <= set(SOURCE_SPECS)
    assert set(SOURCE_SPECS) == chain_sources
    assert POLICY_VERSION.startswith("hidden-shelf-source-policy-")


def test_field_order_covers_every_field_with_registered_sources_only():
    assert set(FIELD_SOURCE_ORDER) == set(FIELDS)
    for field, order in FIELD_SOURCE_ORDER.items():
        assert len(order) == len(set(order)), field
        for source in order:
            assert source in SOURCE_SPECS, f"{field} 排了未登记的 {source}"
        assert set(order) == set(SOURCE_SPECS), field


def test_field_rank_counts_from_one_and_puts_unknown_sources_last():
    assert field_rank("tags", "dmm") == 1
    assert field_rank("tags", "r18dev") == 4
    assert field_rank("tags", "imaginary") == len(FIELD_SOURCE_ORDER["tags"]) + 1
    assert field_rank("tags", "javdb", code="ABW-220") == 0
    assert field_rank("tags", LOCAL_NFO_SOURCE, code="ABW-220") == -1


def test_every_field_uses_policy_order_and_explicit_official_metadata():
    candidates = [{"source": "javbus", "confidence": 0.99}, {"source": "r18dev", "confidence": 0.8},
                  {"source": "dmm", "confidence": 0.7}, {"source": "javdb", "confidence": 0.6}]
    for field in FIELD_SOURCE_ORDER:
        ordered = sort_candidates(field, candidates)
        assert ordered[0]["source"] == "dmm", field
        assert [row["field_rank"] for row in ordered] == sorted(row["field_rank"] for row in ordered)
    with pytest.raises(ValueError, match="未知元数据字段"):
        sort_candidates("runtime", candidates)


def test_publisher_outranks_the_mirror_on_release_date():
    """发行方自己那页（dmm、1pondo、fc2）在发行日上排在 r18dev 前面。"""
    for publisher in ("dmm", "1pondo", "fc2"):
        assert field_rank("release_date", publisher) < field_rank("release_date", "r18dev")
    assert field_rank("release_date", "r18dev") < field_rank("release_date", "javdb")


def test_uncensored_codes_are_told_apart_by_shape():
    assert is_uncensored_code("040221-001") and is_uncensored_code("HEYZO-1380")
    assert not is_uncensored_code("ABW-220") and not is_uncensored_code("259LUXU-1475")


def test_tiers():
    assert not SOURCE_SPECS["javbus"].official
    assert source_tier("javbus") == CHAIN_FALLBACK
    assert source_tier("javdb") == CHAIN_PREFERRED
    assert source_tier("avbase") == CHAIN_COMMUNITY
    assert source_tier("javarchive") == CHAIN_COMMUNITY
    for official in ("dmm", "r18dev", "1pondo", "fc2"):
        assert source_tier(official) == CHAIN_OFFICIAL
    assert source_tier(LOCAL_NFO_SOURCE) == CHAIN_LOCAL_NFO
    assert source_tier("imaginary") == CHAIN_UNKNOWN
    assert chain_rank("title", "javdb") < chain_rank("title", "avbase") < chain_rank("title", "javbus")
    assert chain_rank("title", "dmm") < chain_rank("title", "r18dev") < chain_rank("title", "javdb")


def test_owner_tier():
    assert owner_tier("auto:nfo") == CHAIN_LOCAL_NFO
    assert owner_tier("auto:local") == CHAIN_LOCAL_NFO
    assert owner_tier("auto:r18dev") == CHAIN_OFFICIAL
    assert owner_tier("auto:javdb") == CHAIN_PREFERRED
    assert owner_tier("auto:javbus") == CHAIN_FALLBACK
    assert owner_tier("auto:frame") > owner_tier("auto:javbus")
    assert owner_tier("") > owner_tier("auto:frame")
    assert owner_tier(None) > CHAIN_UNKNOWN
    assert owner_tier("user:manual") == -1 and owner_tier("review:javdb") == -1
    assert owner_tier("scan:filename") == CHAIN_UNKNOWN
    assert owner_tier("auto:bogus") == CHAIN_UNKNOWN
    # 跨次运行的覆盖判据：新来源层级严格更小才覆盖。
    assert source_tier("r18dev") < owner_tier("auto:javbus")
    assert not source_tier("avbase") < owner_tier("auto:r18dev")
    assert not source_tier("javdb") < owner_tier("auto:javdb")
