"""实体层：艺人、厂牌、系列、标签的规范身份、别名、外站 ID 与资产关联。

计划 1 的 `ensure_entity` / `link` / `unlink` / `names_for` 不变；计划 2 Task 7 加别名与外站 ID。
`strip_zero_width`、`collapse_repeated_entity_name` 与「外站 ID 优先于名字」的解析顺序取自 peach
`src/peach/entities.py`（`upsert_asset_entity`、`resolve_entity`，commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）；去掉 creator 实体、合并重定向与扁平投影。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Iterable

from .db import normalize_name, strip_zero_width
from .kanji import fold_glyphs

KINDS = ("performer", "studio", "series", "tag")
#: 页面上「放大图片」这类按钮文字被当成人名抓回来过。
INVALID_PERSON_NAMES = frozenset({"画像を拡大する"})

__all__ = ["KINDS", "ensure_entity", "link", "unlink", "names_for", "strip_zero_width",
           "collapse_repeated_entity_name", "clean_person_name", "find_by_external_ref", "add_external_ref",
           "add_alias", "resolve_performer", "resolve_named", "merge_metadata", "metadata_of"]


def collapse_repeated_entity_name(name: str) -> str:
    """把 ``姓名 姓名`` 这类完整重复串收敛为一次。

    只处理以空白分隔、前后两半完全相同的高置信错误；不会碰 ``M M Produce``、无空白的叠字或带分隔符的内容标签。
    """
    original = str(name or "").strip()
    canonical = " ".join(original.split())
    parts = canonical.split(" ") if canonical else []
    half = len(parts) // 2
    if (len(parts) >= 2 and len(parts) % 2 == 0
            and [part.casefold() for part in parts[:half]] == [part.casefold() for part in parts[half:]]):
        return " ".join(parts[:half])
    return original


def clean_person_name(name: str | None) -> str:
    """人名落库前的清洗：去零宽字符、压空白、收敛重复串、剔按钮文字。"""
    canonical = " ".join(strip_zero_width(name).split())
    canonical = collapse_repeated_entity_name(canonical)
    return "" if canonical in INVALID_PERSON_NAMES else canonical


def ensure_entity(connection: sqlite3.Connection, kind: str, name: str) -> int:
    """按 `normalize_name` 合并同名实体，返回实体 id；名字为空抛 `ValueError`。"""
    if kind not in KINDS:
        raise ValueError(f"实体类型不在清单里：{kind!r}")
    canonical = " ".join(strip_zero_width(name).split())
    normalized = normalize_name(canonical)
    if not normalized:
        raise ValueError("实体名字是空的")
    row = connection.execute(
        "SELECT id FROM entity WHERE kind=? AND normalized_name=?", (kind, normalized)).fetchone()
    if row is not None:
        return int(row[0])
    cursor = connection.execute(
        "INSERT INTO entity(kind,canonical_name,normalized_name) VALUES(?,?,?)",
        (kind, canonical, normalized))
    return int(cursor.lastrowid)


def link(connection: sqlite3.Connection, asset_id: int, entity_id: int, role: str, source: str,
         confidence: float = 1.0) -> None:
    """建立资产与实体的关联；已有同 (资产, 实体, 角色) 的只更新来源与置信度。"""
    connection.execute(
        "INSERT INTO asset_entity(asset_id,entity_id,role,source,confidence) VALUES(?,?,?,?,?) "
        "ON CONFLICT(asset_id,entity_id,role) DO UPDATE SET source=excluded.source, "
        "confidence=excluded.confidence",
        (int(asset_id), int(entity_id), role, source, float(confidence)))


def unlink(connection: sqlite3.Connection, asset_id: int, role: str, source: str) -> int:
    """删掉某资产某角色下、某个来源写的全部关联，返回删掉的行数。"""
    return connection.execute(
        "DELETE FROM asset_entity WHERE asset_id=? AND role=? AND source=?",
        (int(asset_id), role, source)).rowcount


def names_for(connection: sqlite3.Connection, asset_id: int, role: str) -> list[str]:
    """某资产某角色下的实体规范名，用户写的排在前面，其余按写入顺序（NFO 里的主演在前）。"""
    return [str(row[0]) for row in connection.execute(
        "SELECT e.canonical_name FROM asset_entity ae JOIN entity e ON e.id=ae.entity_id "
        "WHERE ae.asset_id=? AND ae.role=? ORDER BY (ae.source<>'user'), ae.rowid",
        (int(asset_id), role))]


# ---------- 外站 ID 与别名 ----------

def find_by_external_ref(connection: sqlite3.Connection, kind: str, provider: str, external_id: str) -> int | None:
    """这家来源的这个 ID 已经挂在哪个实体上。"""
    row = connection.execute(
        "SELECT x.entity_id FROM entity_external_ref x JOIN entity e ON e.id=x.entity_id "
        "WHERE x.provider=? AND x.external_kind=? AND x.external_id=? AND e.kind=?",
        (provider, kind, str(external_id), kind)).fetchone()
    return int(row[0]) if row else None


def add_external_ref(connection: sqlite3.Connection, entity_id: int, provider: str, kind: str, external_id: str,
                     *, metadata: dict | None = None, now: str | None = None) -> bool:
    """把外站 ID 挂到实体上。同一个 ID 已属别的实体时不改、返回 False——指错实体要人工才能发现。"""
    text = str(external_id or "").strip()
    if not text:
        return False
    owner = find_by_external_ref(connection, kind, provider, text)
    if owner is not None and owner != int(entity_id):
        return False
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection.execute(
        "INSERT INTO entity_external_ref(entity_id,provider,external_kind,external_id,metadata,synced_at) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(provider,external_kind,external_id) DO UPDATE SET "
        "metadata=excluded.metadata, synced_at=excluded.synced_at",
        (int(entity_id), provider, kind, text, json.dumps(metadata or {}, ensure_ascii=False), stamp))
    return True


def add_alias(connection: sqlite3.Connection, entity_id: int, alias: str, source: str = "scrape",
              confidence: float = 1.0) -> bool:
    """登记一个别名。空的、与规范名相同的不登记；同来源同写法已有的不重复。"""
    text = " ".join(strip_zero_width(alias).split())
    normalized = normalize_name(text)
    if not normalized:
        return False
    row = connection.execute("SELECT normalized_name FROM entity WHERE id=?", (int(entity_id),)).fetchone()
    if row is None or row[0] == normalized:
        return False
    cursor = connection.execute(
        "INSERT OR IGNORE INTO entity_alias(entity_id,alias,normalized,source,confidence) VALUES(?,?,?,?,?)",
        (int(entity_id), text, normalized, source, float(confidence)))
    return cursor.rowcount > 0


def _by_name(connection: sqlite3.Connection, kind: str, normalized: str) -> int | None:
    row = connection.execute(
        "SELECT id FROM entity WHERE kind=? AND normalized_name=?", (kind, normalized)).fetchone()
    return int(row[0]) if row else None


def _by_unique_alias(connection: sqlite3.Connection, kind: str, normalized: str) -> int | None:
    """别名唯一命中才算；撞名返回 None 而不是随便挑一个。"""
    rows = connection.execute(
        "SELECT DISTINCT e.id FROM entity e JOIN entity_alias a ON a.entity_id=e.id "
        "WHERE e.kind=? AND a.normalized=? ORDER BY e.id LIMIT 2", (kind, normalized)).fetchall()
    return int(rows[0][0]) if len(rows) == 1 else None


def _by_folded_glyphs(connection: sqlite3.Connection, kind: str, folded: str) -> int | None:
    """字形折叠后唯一命中：`永瀬みなも` 与 `永濑みなも` 是同一个人。规范名与别名都参与。"""
    found: set[int] = set()
    for entity_id, name in connection.execute(
            "SELECT id, canonical_name FROM entity WHERE kind=?", (kind,)):
        if normalize_name(fold_glyphs(name)) == folded:
            found.add(int(entity_id))
    for entity_id, alias in connection.execute(
            "SELECT a.entity_id, a.alias FROM entity_alias a JOIN entity e ON e.id=a.entity_id WHERE e.kind=?", (kind,)):
        if normalize_name(fold_glyphs(alias)) == folded:
            found.add(int(entity_id))
    return next(iter(found)) if len(found) == 1 else None


def resolve_performer(connection: sqlite3.Connection, name: str, *, provider: str | None = None,
                      external_id: str | None = None, aliases: Iterable[str] = (),
                      former_names: Iterable[str] = (), now: str | None = None) -> int:
    """名字（可带外站 ID 与别名）→ 艺人实体 id。

    顺序：外站 ID 命中 > 规范名精确 > 唯一别名 > 旧名唯一命中 > 字形折叠唯一命中 > 新建。解出后登记外站 ID
    （已属别人的不抢）与别名（假名、罗马字、旧名）。名字为空抛 `ValueError`。
    """
    canonical = clean_person_name(name)
    normalized = normalize_name(canonical)
    if not normalized:
        raise ValueError("艺人名字是空的")
    entity_id = find_by_external_ref(connection, "performer", provider, external_id) if provider and external_id else None
    if entity_id is None:
        entity_id = _by_name(connection, "performer", normalized)
    if entity_id is None:
        entity_id = _by_unique_alias(connection, "performer", normalized)
    if entity_id is None:
        for former in former_names:
            key = normalize_name(former)
            entity_id = _by_name(connection, "performer", key) or _by_unique_alias(connection, "performer", key)
            if entity_id is not None:
                # 现名还没登记、旧名已在库里：挂到旧名那一位身上，现名成为她的别名。
                add_alias(connection, entity_id, canonical, source=provider or "scrape")
                break
    if entity_id is None:
        entity_id = _by_folded_glyphs(connection, "performer", normalize_name(fold_glyphs(canonical)))
        if entity_id is not None:
            add_alias(connection, entity_id, canonical, source=provider or "scrape")
    if entity_id is None:
        entity_id = ensure_entity(connection, "performer", canonical)
    if provider and external_id:
        add_external_ref(connection, entity_id, provider, "performer", str(external_id), now=now)
    for alias in (*aliases, *former_names):
        add_alias(connection, entity_id, alias, source=provider or "scrape")
    return entity_id


def resolve_named(connection: sqlite3.Connection, kind: str, name: str) -> int:
    """厂牌、系列、标签：规范名精确 > 唯一别名 > 新建。"""
    if kind not in KINDS:
        raise ValueError(f"实体类型不在清单里：{kind!r}")
    canonical = " ".join(strip_zero_width(name).split())
    normalized = normalize_name(canonical)
    if not normalized:
        raise ValueError("实体名字是空的")
    found = _by_name(connection, kind, normalized) or _by_unique_alias(connection, kind, normalized)
    return found if found is not None else ensure_entity(connection, kind, canonical)


# ---------- 实体元数据 ----------

def metadata_of(connection: sqlite3.Connection, entity_id: int) -> dict:
    row = connection.execute("SELECT metadata FROM entity WHERE id=?", (int(entity_id),)).fetchone()
    try:
        loaded = json.loads(row[0] or "{}") if row else {}
    except (ValueError, TypeError):
        loaded = {}
    return loaded if isinstance(loaded, dict) else {}


def merge_metadata(connection: sqlite3.Connection, entity_id: int, changes: dict) -> dict:
    """把几个键并进 `entity.metadata`（JSON），值为 None 的键删掉；返回合并后的整份。"""
    current = metadata_of(connection, entity_id)
    for key, value in changes.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    connection.execute("UPDATE entity SET metadata=? WHERE id=?",
                       (json.dumps(current, ensure_ascii=False), int(entity_id)))
    return current
