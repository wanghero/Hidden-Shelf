"""`CHANGELOG.md` → 进度网页「更新记录」页的条目。"""
from __future__ import annotations

from hidden_shelf import changelog
from hidden_shelf.serve.app import create_app
from hidden_shelf.serve.runner import RunManager

SAMPLE = """# 更新日志

格式遵循 Keep a Changelog。

## 1.4.12 - 2026-11-01

一句散文。

### 变更

- 第一条带 `代码`。
- 第二条很长，
  续行缩进两格。

## 0.4.0 - 2026-10-30

第一个面向外人的版本。

### 新增

- 归位预演。
"""


def test_parse_reads_versions_groups_items_and_notes():
    entries = changelog.parse(SAMPLE)
    assert [entry.version for entry in entries] == ["1.4.12", "0.4.0"]
    first = entries[0]
    assert first.date == "2026-11-01" and first.note == "一句散文。"
    assert [group.title for group in first.groups] == ["变更"]
    assert first.groups[0].items == ["第一条带 `代码`。", "第二条很长， 续行缩进两格。"]
    assert entries[1].note == "第一个面向外人的版本。" and entries[1].groups[0].items == ["归位预演。"]
    # 标题前的说明不属于任何版本
    assert all("Keep a Changelog" not in entry.note for entry in entries)


def test_parse_tolerates_a_version_without_group_headings():
    entries = changelog.parse("## 9.9.9 - 2026-01-01\n\n- 只有条目没有小标题\n")
    assert entries[0].groups[0].title == "" and entries[0].groups[0].items == ["只有条目没有小标题"]
    assert changelog.parse("完全不是更新日志") == []


def test_repository_changelog_is_readable_and_newest_first():
    entries = changelog.entries()
    assert entries, "仓库里应当读得到 CHANGELOG.md"
    from hidden_shelf import __version__
    assert entries[0]["version"] == __version__, "最新一节要是当前版本"
    assert all(entry["date"] and entry["groups"] for entry in entries)


def test_progress_page_ships_the_changelog_and_a_route_to_it():
    from fastapi.testclient import TestClient

    from hidden_shelf import __version__
    with TestClient(create_app(RunManager())) as client:
        body = client.get("/").text
        assert "changelog: [" in body and __version__ in body
        script = client.get("/static/progress.js").text
        assert "'#/changelog'" in script and "renderChangelog" in script
        assert "'changelog.current'" in client.get("/static/i18n.js").text
