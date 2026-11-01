"""番号身份核对。后半搬自 peach `tests/test_metadata.py` 的 `SourceIdentityTests`。"""
from __future__ import annotations

import pytest

from hidden_shelf.scrape.identity import identifies_code, validate_provider_code


def test_validate_provider_code():
    assert validate_provider_code("abw-358") == "ABW-358"
    assert validate_provider_code("n0646") == "N0646"
    assert validate_provider_code("092415_001") == "092415_001"
    assert validate_provider_code("FC2-PPV-1234567") == "FC2-PPV-1234567"
    assert validate_provider_code("259luxu-1475") == "259LUXU-1475"
    for bad in ("../x", "https://javdb.com/v/x", "ABW 358 片名", "", "ABW358"):
        with pytest.raises(ValueError):
            validate_provider_code(bad)


def test_explicit_release_suffix_is_not_satisfied_by_a_plain_or_different_product():
    assert identifies_code("DANDY-851C", {"content_id": "1dandy00851c"})
    assert not identifies_code("DANDY-851C", {"content_id": "1dandy00851"})
    assert not identifies_code("DANDY-851C", {"content_id": "1dandy00851ch"})
    assert not identifies_code("DANDY-851", {"content_id": "1dandy00851c"})


def test_prefixed_release_requires_matching_product_evidence():
    dvd = {"id": "JAC-040", "content_id": "118jac040",
           "source_url": "https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=118jac040/"}
    assert not identifies_code("390JAC-040", dvd)
    assert identifies_code("JAC-040", dvd)
    assert identifies_code("390JAC-040", {
        "id": "JAC-040", "source_url": "https://www.mgstage.com/product/product_detail/390JAC-040/"})


def test_verified_mgstage_prefixes_match_the_bare_dmm_release():
    for code, payload in (
            ("476MLA-234", {"id": "MLA-234", "content_id": "mla234"}),
            ("428SUKE-080", {"id": "SUKE-080", "content_id": "h_1711suke00080"}),
            ("336KBI-010", {"id": "KBI-010", "content_id": "118kbi00010"}),
            ("762FKOS-001", {"id": "FKOS-001", "content_id": "h_1721fkos00001"})):
        assert identifies_code(code, payload), code
    for code, payload in (
            ("348NTR-007", {"id": "NTR-007", "content_id": "1ntr00007"}),
            ("451HHH-022", {"id": "HHH-022", "content_id": "62hhh00022"}),
            ("550ENE-006", {"id": "ENE-006", "content_id": "ene006"})):
        assert not identifies_code(code, payload), code


def test_real_source_id_shapes_are_accepted():
    assert identifies_code("ABW-220", {"content_id": "118abw220"})
    assert identifies_code("IQQQ-026", {"content_id": "h_086iqqq00026"})
    assert identifies_code("MESU-088", {"id": "MESU-88"})
    assert identifies_code("259LUXU-1475", {
        "source_url": "https://www.mgstage.com/product/product_detail/259LUXU-1475/"})
    assert identifies_code("259LUXU-1475", {"id": "259LUXU-1475", "source_url": "https://www.avbase.net/works/259LUXU-1475"})


def test_unrelated_product_is_rejected_as_not_found():
    payload = {"id": "33938", "content_id": "33938", "source_url": "https://dl.getchu.com/i/item33938"}
    assert not identifies_code("ABW-220", payload)
    assert not identifies_code("259LUXU-1475", payload)
    assert not identifies_code("ABW-220", {})
    assert not identifies_code("ABW-2200", {"content_id": "118abw220"})
    assert not identifies_code("IY-104", {"id": "DIY-104", "source_url": "https://www.javbus.com/ja/DIY-104"})
    assert not identifies_code("DB-202", {"id": "DDB-202"})
    assert identifies_code("JBS-023", {"source_url": "https://www.javbus.com/ja/JBS-023"})


def test_fc2_bare_digits_are_the_same_release():
    for payload in ({"id": "3701252", "content_id": "3701252", "source_url": "https://fc2cmadb.com/articles/3701252"},
                    {"content_id": "3701252"}):
        assert identifies_code("FC2-PPV-3701252", payload)
    assert not identifies_code("FC2-PPV-3701252", {"id": "3701253"})


def test_javbus_loose_search_results_are_a_different_release():
    for code, returned in (("AR-101", "STAR-101"), ("AR-102", "ZMAR-102"), ("WX17", "WXSD-017"),
                           ("CD-101", "BCDP-101"), ("259LUXU-764", "259LUXU-1764"), ("259LUXU-164", "259LUXU-1642")):
        assert not identifies_code(code, {"id": returned, "content_id": returned,
                                          "source_url": f"https://www.javbus.com/ja/{returned}"}), f"{code} <- {returned}"
