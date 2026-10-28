"""实体层最小版：艺人、厂牌、系列、标签的规范身份与资产关联。计划 2 会扩展别名与外站 ID。"""
from __future__ import annotations

import sqlite3

from .db import normalize_name

KINDS = ("performer", "studio", "series", "tag")


def ensure_entity(connection: sqlite3.Connection, kind: str, name: str) -> int:
    """按 `normalize_name` 合并同名实体，返回实体 id；名字为空抛 `ValueError`。"""
    if kind not in KINDS:
        raise ValueError(f"实体类型不在清单里：{kind!r}")
    canonical = " ".join(str(name or "").split())
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
