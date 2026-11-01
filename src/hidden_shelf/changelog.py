"""把 `CHANGELOG.md` 读成结构化条目，给进度网页的「更新记录」页用。

文件本身是 Keep a Changelog 格式，一个版本一节：

    ## 1.4.12 - 2026-11-01

    一句散文（可有可无）

    ### 变更

    - 一条

解析只认这三种行：`## 版本 - 日期`、`### 小标题`、`- 条目`。别的行当散文收在版本的
`note` 里。条目里的行内写法（`` `代码` ``、`**粗体**`）原样留着，由前端渲染——这边不碰
HTML，免得把一份 Markdown 转义成两种口径。

文件位置有两处：装进 wheel 的那份在包目录里（`pyproject.toml` 的 `force-include`），
从源码跑（`uv sync` 的可编辑安装）时包目录里没有，退回仓库根目录那份。两处都没有就回空
列表，页面显示「读不到更新记录」而不是报错——这一页只是说明，缺了不该挡住跑流水线。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

#: `## 1.4.12 - 2026-11-01`
_VERSION = re.compile(r"^##\s+(\S+)\s+-\s+(\S+)\s*$")
#: `### 变更`
_GROUP = re.compile(r"^###\s+(.+?)\s*$")
#: `- 一条`。条目可以折行，续行缩进两格。
_ITEM = re.compile(r"^-\s+(.*)$")
_CONTINUATION = re.compile(r"^\s{2,}(\S.*)$")


@dataclass
class Group:
    """一个版本里的一组条目，比如「变更」「新增」「修复」。"""
    title: str
    items: list[str] = field(default_factory=list)


@dataclass
class Entry:
    version: str
    date: str
    note: str = ""
    groups: list[Group] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"version": self.version, "date": self.date, "note": self.note,
                "groups": [{"title": group.title, "items": list(group.items)} for group in self.groups]}


def changelog_path() -> Path | None:
    """`CHANGELOG.md` 在哪；找不到回 `None`。"""
    for candidate in (Path(__file__).parent / "CHANGELOG.md",
                      Path(__file__).resolve().parents[2] / "CHANGELOG.md"):
        if candidate.is_file():
            return candidate
    return None


def parse(text: str) -> list[Entry]:
    """Markdown → 版本条目，顺序照文件里的（新的在前）。"""
    entries: list[Entry] = []
    group: Group | None = None
    notes: list[str] = []

    def close() -> None:
        if entries:
            entries[-1].note = " ".join(notes).strip()
        notes.clear()

    for line in text.replace("\r", "").split("\n"):
        version = _VERSION.match(line)
        if version:
            close()
            entries.append(Entry(version.group(1), version.group(2)))
            group = None
            continue
        if not entries:
            continue
        heading = _GROUP.match(line)
        if heading:
            group = Group(heading.group(1))
            entries[-1].groups.append(group)
            continue
        item = _ITEM.match(line)
        if item:
            if group is None:
                # 没有 `###` 小标题就直接列条目的版本：挂一个没标题的组。
                group = Group("")
                entries[-1].groups.append(group)
            group.items.append(item.group(1).strip())
            continue
        continuation = _CONTINUATION.match(line)
        if continuation and group is not None and group.items:
            group.items[-1] += " " + continuation.group(1).strip()
            continue
        if line.strip() and group is None:
            notes.append(line.strip())
    close()
    return entries


@lru_cache(maxsize=1)
def entries() -> tuple[dict, ...]:
    """解析好的条目（进程内只读一次）。读不到文件回空。"""
    path = changelog_path()
    if path is None:
        return ()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    return tuple(entry.as_dict() for entry in parse(text))
