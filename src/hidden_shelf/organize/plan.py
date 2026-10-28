"""归位计划：每一行资产该搬到哪、为什么不搬。

思路取自 peach `src/peach/organize.py` 的 `placeholder_values`、`_definition`、`build_plan`
与 `SKIP_*`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，AGPL-3.0-or-later），按本项目的
单盘根、POSIX 相对路径与「未识别」开关重写。计划与执行共用这一份判据：什么算「会变的一行」、
目标路径怎么算出来、哪些行必须跳过。
"""
from __future__ import annotations

import os
import posixpath
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..config import ShelfConfig
from ..entities import names_for
from ..paths import UNRECOGNIZED_DIR, ShelfPaths
from ..rules.codes import is_jav_code, normalise_code_key
from .templates import MAX_PATH, missing_fields, render, validate_template

#: 跳过原因的固定写法。日志与站点按这几个键分组计数，所以它们是契约的一部分。
SKIP_MISSING_FIELD = "字段缺失"
SKIP_TARGET_EXISTS = "目标已存在"
SKIP_TOO_LONG = "路径过长"
SKIP_VANISHED = "文件不在"
SKIP_UNRECOGNIZED_KEEP = "未识别-保持原地"
SKIP_BAD_TEMPLATE = "模板不合法"


@dataclass
class PlanRow:
    asset_id: int
    current_path: str
    target_path: str
    action: str            # "move" | "skip"
    reason: str = ""


@dataclass
class Plan:
    rows: list[PlanRow] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {"total": 0, "unchanged": 0, "move": 0, "skip": 0})
    reasons: dict[str, int] = field(default_factory=dict)

    @property
    def moves(self) -> list[PlanRow]:
        return [row for row in self.rows if row.action == "move"]


def definition_of(width, height) -> str:
    """按短边给一档画质：`4K | 1080p | 720p | SD`；取不到尺寸就留空，让可选分组整段省略。"""
    try:
        lines = int(height or 0)
        columns = int(width or 0)
    except (TypeError, ValueError):
        return ""
    if not lines or not columns:
        return ""
    if columns < lines:
        # 竖屏素材按短边算，不然一条 1080×1920 会被报成 1920p。
        lines = columns
    for floor, label in ((2160, "4K"), (1080, "1080p"), (720, "720p")):
        if lines >= floor:
            return label
    return "SD"


def placeholder_values(row: sqlite3.Row, performers: Sequence[str] = ()) -> dict[str, str]:
    """一行资产的占位符取值，全部来自库里已落的字段。"""
    code = str(row["code"] or "")
    title = str(row["title"] or "") or str(row["original_title"] or "")
    release_date = str(row["release_date"] or "")
    part = str(row["part"] or "")
    return {
        "code": normalise_code_key(code) if is_jav_code(code) else code.strip(),
        "title": title.strip(),
        "studio": str(row["studio"] or "").strip(),
        "series": str(row["series"] or "").strip(),
        "year": release_date[:4] if len(release_date) >= 4 and release_date[:4].isdigit() else "",
        # 三个以上就不再往文件名里塞：名字会长到在资源管理器里看不见番号。
        "actors": "、".join(list(performers)[:3]),
        "cd": part,
        "definition": definition_of(row["width"], row["height"]),
    }


def _extension(name: str) -> str:
    stem, dot, ext = str(name).rpartition(".")
    return f".{ext.lower()}" if dot and stem else ""


def _occupied(paths: ShelfPaths, target: str, current: str) -> bool:
    """目标在盘上已被另一个文件占着（同一文件只改大小写不算）。"""
    absolute = paths.absolute(target)
    if not absolute.exists():
        return False
    try:
        return not os.path.samefile(absolute, paths.absolute(current))
    except OSError:
        return True


def build_plan(connection: sqlite3.Connection, paths: ShelfPaths, config: ShelfConfig, *,
               asset_ids: Sequence[int] | None = None) -> Plan:
    """给每一行视频算目标路径。已经就位的只计 `counts["unchanged"]`，不进 `rows`。"""
    plan = Plan()
    try:
        dir_template = validate_template(config.dir_template, directory=True)
        file_template = validate_template(config.file_template)
    except ValueError as error:
        dir_template = file_template = None
        template_error = str(error)

    ids = list(dict.fromkeys(int(value) for value in (asset_ids or ())))
    selected = f" AND id IN ({','.join('?' * len(ids))})" if asset_ids is not None else ""
    if asset_ids is not None and not ids:
        return plan
    rows = connection.execute(
        "SELECT * FROM asset WHERE medium='video'" + selected + " ORDER BY id", ids).fetchall()
    plan.counts["total"] = len(rows)

    def skip(row, reason: str, target: str = "") -> None:
        plan.counts["skip"] += 1
        plan.reasons[reason] = plan.reasons.get(reason, 0) + 1
        plan.rows.append(PlanRow(int(row["id"]), str(row["path"]), target, "skip", reason))

    # 目标撞名先按库里已知的路径判一遍：同一批里两行算出同一个名字，或者目标位置上
    # 已经躺着另一条记录，都在计划里就说清楚，而不是等执行到一半才报一行失败。
    claimed = {str(path).casefold(): int(aid) for aid, path in connection.execute(
        "SELECT id,path FROM asset WHERE vanished=0")}

    for row in rows:
        path = str(row["path"])
        if int(row["vanished"] or 0):
            skip(row, SKIP_VANISHED)
            continue
        ext = _extension(str(row["name"] or posixpath.basename(path)))
        if not row["code"]:
            if not config.move_unrecognized:
                skip(row, SKIP_UNRECOGNIZED_KEEP)
                continue
            if path.startswith(UNRECOGNIZED_DIR + "/"):
                plan.counts["unchanged"] += 1
                continue
            target = f"{UNRECOGNIZED_DIR}/{path}"
        else:
            if dir_template is None:
                skip(row, f"{SKIP_BAD_TEMPLATE}：{template_error}")
                continue
            values = placeholder_values(row, names_for(connection, int(row["id"]), "performer"))
            missing = set(missing_fields(dir_template, values)) if dir_template else set()
            if missing == {"studio"} and config.unknown_studio_dir:
                values = {**values, "studio": config.unknown_studio_dir}
                missing = set()
            missing |= set(missing_fields(file_template, values))
            if missing:
                skip(row, SKIP_MISSING_FIELD)
                continue
            target_dir = render(dir_template, values, directory=True) if dir_template else posixpath.dirname(path)
            target_name = render(file_template, values) if file_template else posixpath.splitext(row["name"])[0]
            if not target_name:
                skip(row, SKIP_MISSING_FIELD)
                continue
            target = f"{target_dir}/{target_name}{ext}" if target_dir else f"{target_name}{ext}"
        if target == path:
            plan.counts["unchanged"] += 1
            continue
        if len(target) > MAX_PATH:
            skip(row, SKIP_TOO_LONG, target)
            continue
        occupant = claimed.get(target.casefold())
        if occupant is not None and occupant != int(row["id"]):
            skip(row, SKIP_TARGET_EXISTS, target)
            continue
        if _occupied(paths, target, path):
            skip(row, SKIP_TARGET_EXISTS, target)
            continue
        claimed.pop(path.casefold(), None)
        claimed[target.casefold()] = int(row["id"])
        plan.counts["move"] += 1
        plan.rows.append(PlanRow(int(row["id"]), path, target, "move"))
    return plan
