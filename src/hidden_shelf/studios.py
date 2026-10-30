"""厂牌名的规范写法：几家来源把同一家片商写成日文、英文、缩写，库里和目录名只认一种。

用户 2026-10-30 定：カリビアンコム 用英文 **Caribbeancom**（目录名、站点厂牌页都按这个）。表以
`db.normalize_name` 的键查，所以大小写、全半角、空格都不影响命中；没登记的名字原样返回（只压空白）。

`canonicalize_existing` 给已经刮过的老库用：每次 `import` 步开头跑一遍，把 `asset.studio` 和厂牌实体改成
规范写法，归属不动；`user:*`/`review:*` 的字段不碰（用户自己写的字按用户的）。
"""
from __future__ import annotations

import sqlite3

from .db import normalize_name, strip_zero_width
from .field_owners import owner_of

#: 规范写法 → 各来源会给出的别名。只登记确认过的；加一家就在这里加一行。
STUDIO_CANONICAL: dict[str, tuple[str, ...]] = {
    "Caribbeancom": ("カリビアンコム", "Carib", "Caribbean", "Caribbeancom"),
    "Caribbeancompr": ("カリビアンコムプレミアム", "Caribbeancom Premium", "CaribbeancomPR", "Caribpr"),
}

_ALIAS_INDEX: dict[str, str] = {}
for _canonical, _aliases in STUDIO_CANONICAL.items():
    for _alias in (_canonical, *_aliases):
        _ALIAS_INDEX[normalize_name(_alias)] = _canonical


def canonical_studio(name: str | None) -> str:
    """厂牌名落库前过一遍：登记过的别名换成规范写法，其余只压空白。"""
    text = " ".join(strip_zero_width(name).split())
    if not text:
        return ""
    return _ALIAS_INDEX.get(normalize_name(text), text)


def _protected(field_owners: str | None) -> bool:
    owner = str(owner_of(field_owners, "studio") or "")
    return owner.startswith(("user:", "review:"))


def canonicalize_existing(connection: sqlite3.Connection) -> int:
    """把库里已有的厂牌别名改成规范写法；返回改了几条资产。

    资产：`asset.studio` 原地改，归属 JSON 不动（还是原来那家来源写的）。实体：规范名实体已存在就把关联
    并过去、删掉别名实体；不存在就把别名实体改名。
    """
    changed = 0
    rows = connection.execute("SELECT id, studio, field_owners FROM asset WHERE studio IS NOT NULL AND studio<>''").fetchall()
    for row in rows:
        canonical = canonical_studio(row["studio"])
        if canonical == row["studio"] or _protected(row["field_owners"]):
            continue
        connection.execute("UPDATE asset SET studio=? WHERE id=?", (canonical, row["id"]))
        changed += 1
    for entity in connection.execute("SELECT id, canonical_name FROM entity WHERE kind='studio'").fetchall():
        canonical = canonical_studio(entity["canonical_name"])
        if canonical == entity["canonical_name"]:
            continue
        normalized = normalize_name(canonical)
        target = connection.execute(
            "SELECT id FROM entity WHERE kind='studio' AND normalized_name=? AND id<>?",
            (normalized, entity["id"])).fetchone()
        if target is None:
            connection.execute("UPDATE entity SET canonical_name=?, normalized_name=? WHERE id=?",
                               (canonical, normalized, entity["id"]))
            continue
        connection.execute("UPDATE OR IGNORE asset_entity SET entity_id=? WHERE entity_id=?", (target["id"], entity["id"]))
        connection.execute("DELETE FROM asset_entity WHERE entity_id=?", (entity["id"],))
        connection.execute("DELETE FROM entity WHERE id=?", (entity["id"],))
    if changed:
        connection.commit()
    return changed
