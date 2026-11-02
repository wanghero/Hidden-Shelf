"""字段级归属：一条记录里每个真相字段现在的值是谁写的，以及谁能覆盖谁。

移植自 peach `src/peach/field_owners.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）。改动：去掉乐观并发（`check_revision` / `RevisionConflict`，没有并发
编辑界面）；表名、行 id、归属列、修订列改成参数；一次写入里每个字段可以有各自的归属
（`FieldWrite`），返回值是 `{字段: 是否真的写入}`。

归属串的形状是 `<写入者类别>:<标识>`，类别决定谁能覆盖谁：

- `user:manual`      用户在 `overrides.json` 里写的取值；
- `review:<来源>`    用户批准了某个来源的候选（本项目暂无复核界面，保留类别）；
- `auto:<来源>`      自动落库（`auto:nfo`、`auto:local`、`auto:frame`、计划 2 的各来源）；
- `scan:filename`    扫描从文件名推导；
- `scan:dirname`     扫描从所在目录名推导（文件名认不出时的退路）；
- `script:<脚本名>`  维护脚本批量写入。

覆盖规则只有一条：`user:*` 与 `review:*` 承载用户的判断，自动写入者一概不许改；
无主字段与 `auto:*`、`scan:*`、`script:*` 写的字段则谁都可以写。这条规则由
`write_owned_fields` 生成的 SQL 强制，不靠调用方自觉。

写入是一条 UPDATE，逐字段 `CASE WHEN` 决定写不写。按字段判而不是按行判是要点：
一次写入里某个字段被用户接管，不该连累同一批里其它无主字段也写不进去。
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

#: 用户手改。这是最高一级，任何自动写入者都覆盖不掉它。
USER_MANUAL = "user:manual"

#: 扫描从文件名推导出的取值。
SCAN_FILENAME = "scan:filename"

#: 扫描从所在目录名推导出的取值（文件名认不出时的退路，见 `scan.dir_fallback_code`）。
SCAN_DIRNAME = "scan:dirname"

#: 归属串里标识那一段的合法形状。
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]*")
#: 列名只允许普通标识符：它要拼进 SQL。
_COLUMN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: 用户的判断，自动写入者不得覆盖。
PROTECTED_PREFIXES: tuple[str, ...] = ("user:", "review:")
_OWNER_KINDS = frozenset({"user", "review", "auto", "scan", "script"})


def review_owner(provider: str) -> str:
    """用户批准了 `provider` 这个来源的候选。"""
    return "review:" + _identifier(provider)


def auto_owner(provider: str) -> str:
    """自动落库，取值来自 `provider`。"""
    return "auto:" + _identifier(provider)


def script_owner(name: str) -> str:
    """维护脚本批量写入；`name` 是脚本名，不带 `.py`。"""
    return "script:" + _identifier(name)


def _identifier(value: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"归属标识只能是小写字母、数字、下划线和连字符：{value!r}")
    return text


def _column(name: str) -> str:
    text = str(name or "")
    if not _COLUMN.fullmatch(text):
        raise ValueError(f"列名不是合法标识符：{name!r}")
    return text


def _check_owner(owner: str) -> str:
    kind, _, identifier = str(owner or "").partition(":")
    if kind not in _OWNER_KINDS:
        raise ValueError(f"归属串的类别不在清单里：{owner!r}")
    _identifier(identifier)
    return owner


def is_valid_owner(owner: str | None) -> bool:
    """归属串写法合不合规（`类别:标识`，类别在清单里）；别的库带来的归属先过这一关。"""
    try:
        _check_owner(str(owner or ""))
    except ValueError:
        return False
    return True


def is_protected(owner: str | None) -> bool:
    """这个归属是用户的判断吗；无主和自动写入者都不是。"""
    return str(owner or "").startswith(PROTECTED_PREFIXES)


def parse_owners(value: object) -> dict[str, str]:
    """把归属列解析成 `{列名: 归属串}`。解析不了就当无主。"""
    if isinstance(value, Mapping):
        parsed: object = value
    else:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError):
            return {}
    if not isinstance(parsed, Mapping):
        return {}
    return {str(key): str(owner) for key, owner in parsed.items()
            if isinstance(owner, str) and owner}


def owner_of(value: object, field: str | None) -> str:
    """某一个字段现在的归属；无主返回空串。"""
    if not field:
        return ""
    return parse_owners(value).get(field, "")


@dataclass(frozen=True)
class FieldWrite:
    """一次写入里的一个字段：写什么值、以谁的身份、是否只在当前为空时才写。"""

    field: str
    value: object
    owner: str
    require_empty: bool = False


def _writable_sql(column: str, owners_column: str, owner: str, require_empty: bool) -> str:
    """这个字段在这一行写得写不得，写成一段不带占位符的 SQL 条件。"""
    extracted = f"json_extract(COALESCE({owners_column},'{{}}'),'$.\"{column}\"')"
    if is_protected(owner):
        condition = "1"
    else:
        condition = (f"({extracted} IS NULL OR NOT ("
                     f"{extracted} LIKE 'user:%' OR {extracted} LIKE 'review:%'))")
    if require_empty:
        condition = f"({condition} AND trim(COALESCE({column},''))='')"
    return condition


def write_owned_fields(connection, table: str, row_id: int, writes: Sequence[FieldWrite], *,
                       owners_column: str = "field_owners",
                       revision_column: str = "revision") -> dict[str, bool]:
    """按字段归属写一行的若干字段，返回 `{字段: 是否写入}`。

    受保护（`user:*`、`review:*`）的字段，非保护身份写不进；`require_empty` 再加一道
    「当前值必须为空」。写入成功的字段把 owner 写进归属 JSON 列；任一取值真的变了，
    修订列加一。取值没变也要把归属换成最后一个写入者：回答的是「现在这个值算谁的」。
    """
    writes = list(writes)
    if not writes:
        return {}
    table = _column(table)
    owners_column = _column(owners_column)
    revision_column = _column(revision_column)
    fields = [_column(write.field) for write in writes]
    if len(set(fields)) != len(fields):
        raise ValueError(f"同一字段在一次写入里出现多次：{fields}")
    for write in writes:
        _check_owner(write.owner)

    before = connection.execute(
        f"SELECT {owners_column},{','.join(fields)} FROM {table} WHERE id=?", (int(row_id),)
    ).fetchone()
    if before is None:
        return {field: False for field in fields}
    current_owners = parse_owners(before[0])
    outcome: dict[str, bool] = {}
    for index, write in enumerate(writes):
        blocked = (not is_protected(write.owner) and is_protected(current_owners.get(write.field, "")))
        if write.require_empty and str(before[index + 1] or "").strip():
            blocked = True
        outcome[write.field] = not blocked

    assignments: list[str] = []
    assignment_params: list[object] = []
    owner_expression = f"COALESCE({owners_column},'{{}}')"
    owner_params: list[object] = []
    changed: list[str] = []
    changed_params: list[object] = []
    for write in writes:
        condition = _writable_sql(write.field, owners_column, write.owner, write.require_empty)
        assignments.append(f"{write.field}=CASE WHEN {condition} THEN ? ELSE {write.field} END")
        assignment_params.append(write.value)
        # `json_patch` 的任一参数是 NULL 时整个结果就是 NULL，所以基值走 COALESCE，
        # 写不得的字段给 `'{}'` 而不是 NULL——一个 NULL 会把整行的归属抹掉。
        owner_expression = (f"json_patch({owner_expression},"
                            f"CASE WHEN {condition} THEN json_object('{write.field}',?) "
                            f"ELSE '{{}}' END)")
        owner_params.append(write.owner)
        changed.append(f"({condition} AND {write.field} IS NOT ?)")
        changed_params.append(write.value)
    sql = (
        f"UPDATE {table} SET {','.join(assignments)},{owners_column}={owner_expression},"
        f"{revision_column}=COALESCE({revision_column},0)+(CASE WHEN {' OR '.join(changed)} "
        f"THEN 1 ELSE 0 END) WHERE id=?"
    )
    connection.execute(sql, [*assignment_params, *owner_params, *changed_params, int(row_id)])
    return outcome
