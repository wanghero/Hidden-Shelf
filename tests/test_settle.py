"""来源分级结算。"""
from __future__ import annotations

import json
from pathlib import Path

from hidden_shelf.scrape.policy import LOCAL_NFO_SOURCE
from hidden_shelf.scrape.settle import Candidate, Settled, extract, normalized_release_date, settle
from hidden_shelf.scrape.sources import Page
from hidden_shelf.scrape.sources.r18dev import R18DevSource, with_japanese

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def _r18_record():
    detail = json.loads((FIXTURES / "r18dev-detail.json").read_text(encoding="utf-8"))
    combined = json.loads((FIXTURES / "r18dev-combined.json").read_text(encoding="utf-8"))
    page = Page("https://r18.dev/videos/vod/movies/detail/-/dvd_id=ABW-358/json", json.dumps(detail).encode())
    return with_japanese(R18DevSource().parse(page, "ABW-358"), combined)


def test_normalized_release_date():
    assert normalized_release_date("2023-05-26") == "2023-05-26"
    assert normalized_release_date("2021-05-06T15:00:00Z") == "2021-05-06"
    assert normalized_release_date(" 2023-05-26 ") == "2023-05-26"
    assert normalized_release_date("not a date") == ""
    assert normalized_release_date(None) == ""


def test_extract_candidates_from_record():
    record = _r18_record()
    found = {(row.field, row.source): row.value for row in extract(record)}
    assert found[("title", "r18dev")] == "涼森れむ流"
    assert found[("studio", "r18dev")] == "Prestige"
    assert found[("series", "r18dev")] == "保健室の先生"
    assert found[("release_date", "r18dev")] == "2023-05-26"
    assert found[("tags", "r18dev")] == ("スレンダー", "企画")
    assert found[("cover_urls", "r18dev")] == ("https://pics.dmm.co.jp/digital/video/118abw00358/118abw00358pl.jpg",)
    performers = found[("performers", "r18dev")]
    assert [row["name"] for row in performers] == ["涼森れむ"]
    assert performers[0]["external_id"] == "1051912" and performers[0]["profile_source"] == "r18dev"
    assert performers[0]["aliases"] == ["すずもりれむ", "Remu Suzumori"]
    assert ("original_title", "r18dev") not in found, "空值不出候选"
    # 快照字典同样能抽：来源名从参数或 `source` 键来。
    payload = record.payload()
    assert {row.field for row in extract(payload, source="r18dev")} == {row.field for row in extract(record)}
    assert extract({**payload, "source": "r18dev"})[0].source == "r18dev"
    # 空壳记录一个候选都没有。
    assert extract({"title": "", "actresses": [], "genres": [], "cover_urls": []}, source="javbus") == []
    # 描述性称呼在这里就剔掉。
    rows = extract({"actresses": [{"japanese_name": "美女6名"}, {"japanese_name": "涼森れむ"}]}, source="javdb")
    assert [row["name"] for row in rows[0].value] == ["涼森れむ"]


def test_settle_official_beats_community():
    candidates = [Candidate("title", "javdb 的标题", "javdb"), Candidate("title", "官方标题", "r18dev"),
                  Candidate("title", "DMM 标题", "dmm")]
    settled = settle("ABW-358", candidates)
    assert settled["title"] == Settled("DMM 标题", "dmm", (("官方标题", "r18dev"), ("javdb 的标题", "javdb")))
    only = settle("ABW-358", candidates[:2])
    assert (only["title"].value, only["title"].source) == ("官方标题", "r18dev")


def test_settle_javdb_beats_other_community_and_nfo_beats_everyone():
    candidates = [Candidate("studio", "甲", "avbase"), Candidate("studio", "乙", "javdb"), Candidate("studio", "丙", "javarchive")]
    assert settle("ABW-358", candidates)["studio"].source == "javdb"
    with_nfo = [*candidates, Candidate("studio", "丁", LOCAL_NFO_SOURCE)]
    assert settle("ABW-358", with_nfo)["studio"].source == LOCAL_NFO_SOURCE


def test_settle_javbus_only_when_alone():
    alone = settle("ABW-358", [Candidate("title", "兜底标题", "javbus")])
    assert alone["title"] == Settled("兜底标题", "javbus", ())
    paired = settle("ABW-358", [Candidate("title", "兜底标题", "javbus"), Candidate("title", "索引标题", "avbase")])
    assert paired["title"] == Settled("索引标题", "avbase", ())
    # 两家一致也不把 javbus 当证据，署名归另一家。
    same = settle("ABW-358", [Candidate("title", "同一个标题", "javbus"), Candidate("title", "同一个标题", "avbase")])
    assert same["title"].source == "avbase"


def test_settle_dated_code_release_date_must_match_code():
    """`092415_001` 自己写着 2015-09-24：javdb 的 2016-06-16 是转售商上架日，剔掉；javbus 对得上就取。"""
    candidates = [Candidate("release_date", "2016-06-16", "javdb"), Candidate("release_date", "2015-09-24", "javbus")]
    settled = settle("092415_001", candidates)
    assert settled["release_date"] == Settled("2015-09-24", "javbus", ())
    assert "release_date" not in settle("092415_001", candidates[:1])
    # 非日期式番号照链排。
    assert settle("ABW-358", candidates)["release_date"].source == "javdb"


def test_settle_same_source_two_values_is_skipped():
    """JavArchive 多条转存给出两个不同标题：这一家在标题上不参与。"""
    candidates = [Candidate("title", "甲", "javarchive"), Candidate("title", "乙", "javarchive"),
                  Candidate("title", "丙", "javdb")]
    assert settle("FC2-PPV-4137487", candidates)["title"] == Settled("丙", "javdb", ())
    assert "title" not in settle("FC2-PPV-4137487", candidates[:2])
    # 同一家两次给同一个值不算分歧。
    twice = [Candidate("title", "甲", "javarchive"), Candidate("title", "甲", "javarchive")]
    assert settle("FC2-PPV-4137487", twice)["title"] == Settled("甲", "javarchive", ())
    # 列表字段不按「同家分歧」剔：取链首那一家的第一组。
    lists = [Candidate("tags", ("a",), "javarchive"), Candidate("tags", ("b",), "javarchive")]
    assert settle("FC2-PPV-4137487", lists)["tags"].value == ("a",)


def test_settle_censored_tags_prefer_javdb():
    candidates = [Candidate("tags", ("ギリモザ", "単体作品"), "dmm"), Candidate("tags", ("高跟鞋", "絲襪"), "javdb"),
                  Candidate("tags", ("Slender",), "r18dev")]
    censored = settle("SSIS-057", candidates)["tags"]
    assert (censored.value, censored.source) == (("高跟鞋", "絲襪"), "javdb")
    assert censored.overruled == ((("ギリモザ", "単体作品"), "dmm"), (("Slender",), "r18dev"))
    amateur = settle("300MIUM-1239", candidates)["tags"]
    assert amateur.source == "dmm"
    # 整组取胜出那一家的，演员同理。
    performers = [Candidate("performers", ({"name": "甲"},), "javbus"), Candidate("performers", ({"name": "乙"}, {"name": "丙"}), "avbase")]
    assert settle("ABW-358", performers)["performers"].value == ({"name": "乙"}, {"name": "丙"})


def test_settle_ignores_passthrough_and_unknown_fields_and_sorts_by_confidence_within_rank():
    candidates = [Candidate("cover_urls", ("https://x/a.jpg",), "r18dev"), Candidate("runtime", 120, "r18dev"),
                  Candidate("title", "低", "javdb", 0.5), Candidate("title", "高", "javdb", 0.9)]
    settled = settle("ABW-358", candidates)
    assert set(settled) == set(), "同一家两个不同标题在标量上不参与；cover_urls 与未知字段不进结算"
    ranked = settle("ABW-358", [Candidate("title", "低", "avbase", 0.5), Candidate("title", "高", "javarchive", 0.9)])
    assert ranked["title"].source == "avbase", "层级先于置信度"
