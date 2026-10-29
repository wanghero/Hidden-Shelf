"""把结算结果写进库，以及判断一部片要不要去问。

落库口径（设计文档 §4.7，用户 2026-10-28 定的「最宽松」）：标量列以 `auto:<来源>` 身份写，`user:*`、`review:*`
由 `field_owners` 挡住；跨次运行只有**严格更高档**的来源才覆盖（`policy.source_tier` 数字更小），`auto:nfo` 与
`auto:local` 是 0 档，联网来源永远盖不掉；现值为空的谁都能填。演员与标签只增不删，关联记 `auto:<来源>`，用户
写的照旧在前。

演员落库思路取自 peach `metadata_auto_apply._apply_performer_candidate`（commit
4d5266d327a5971773409b44316e3926bd37c6ba，AGPL-3.0-or-later）：外站 ID 与别名跟着 `entities.resolve_performer`
走，`thumb_url` 存进 `entity.metadata.avatar_url` 给头像那一步读。去掉 peach 的「删旧的刮削关联再写」与
`asset_tag` 扁平投影。
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .. import entities
from ..field_owners import FieldWrite, auto_owner, is_protected, parse_owners, write_owned_fields
from ..rules.codes import scrapes_as_jav
from .policy import CHAIN_OFFICIAL, owner_tier, source_tier
from .routes import classify
from .settle import SCALAR_FIELDS, Settled

#: 几天内不重问同一个番号。
RESCRAPE_DAYS = 7
#: `should_scrape` 判「缺」的字段；`cover` 不是列，由调用方按封面归属给。
WANTED_FIELDS = ("title", "performers", "studio", "release_date", "tags", "cover")
#: 不去问任何来源的内容类型。
UNASKED_CONTENT = frozenset({"kmib", "other", "unknown"})
#: 标量字段写入时同步建实体、挂关联的角色。
_ENTITY_ROLES = {"studio": "studio", "series": "series"}


@dataclass
class ApplyReport:
    #: 写进去的字段 → 来源。
    written: dict[str, str] = field(default_factory=dict)
    #: 没写的字段 → 现归属（谁挡住的）。
    kept: dict[str, str] = field(default_factory=dict)
    performers: int = 0
    tags: int = 0


def _stamp(now) -> str:
    if isinstance(now, str):
        return now
    if isinstance(now, datetime):
        return now.astimezone(timezone.utc).isoformat(timespec="seconds")
    return datetime.fromtimestamp(float(now), timezone.utc).isoformat(timespec="seconds")


def may_replace(current_value: object, current_owner: str, source: str) -> bool:
    """这个来源的值能不能顶掉现值：现值为空谁都能填；否则来源层级要严格高于现归属；用户写的永不动。"""
    if is_protected(current_owner):
        return False
    if not str(current_value or "").strip():
        return True
    return source_tier(source) < owner_tier(current_owner)


def _has_link(connection: sqlite3.Connection, asset_id: int, entity_id: int, role: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM asset_entity WHERE asset_id=? AND entity_id=? AND role=?",
        (int(asset_id), int(entity_id), role)).fetchone() is not None


def _link_once(connection: sqlite3.Connection, asset_id: int, entity_id: int, role: str, owner: str) -> bool:
    """只增不删：已有的关联（无论谁写的）原样留着，不用 `link()` 的 upsert 把 `user` 改成 `auto`。"""
    if _has_link(connection, asset_id, entity_id, role):
        return False
    entities.link(connection, asset_id, entity_id, role, owner)
    return True


def _apply_scalars(connection, asset_id: int, row: sqlite3.Row, settled: Mapping[str, Settled],
                   report: ApplyReport) -> dict[str, str]:
    """标量列。返回这次真的写进去的 `{字段: 来源}`。"""
    owners = parse_owners(row["field_owners"])
    writes: list[FieldWrite] = []
    wanted: dict[str, str] = {}
    for name in SCALAR_FIELDS:
        decision = settled.get(name)
        if decision is None:
            continue
        current_owner = owners.get(name, "")
        if may_replace(row[name], current_owner, decision.source):
            writes.append(FieldWrite(name, decision.value, auto_owner(decision.source)))
            wanted[name] = decision.source
        else:
            report.kept.setdefault(name, current_owner or "")
    if not writes:
        return {}
    outcome = write_owned_fields(connection, "asset", asset_id, writes)
    written = {name: source for name, source in wanted.items() if outcome.get(name)}
    for name, source in written.items():
        report.written[name] = source
        role = _ENTITY_ROLES.get(name)
        if role:
            # 厂牌、系列是单值角色：这个资产上旧的自动关联换成新的；用户写的留着。
            connection.execute(
                "DELETE FROM asset_entity WHERE asset_id=? AND role=? AND source LIKE 'auto:%'", (asset_id, role))
            entity_id = entities.resolve_named(connection, role, settled[name].value)
            _link_once(connection, asset_id, entity_id, role, auto_owner(source))
    for name in wanted:
        if name not in written:
            report.kept.setdefault(name, owners.get(name, ""))
    return written


def _apply_performers(connection, asset_id: int, decision: Settled, report: ApplyReport, now: str) -> None:
    owner = auto_owner(decision.source)
    for performer in decision.value:
        if not isinstance(performer, Mapping) or not str(performer.get("name") or "").strip():
            continue
        provider = str(performer.get("profile_source") or decision.source)
        external_id = str(performer.get("external_id") or "").strip() or None
        entity_id = entities.resolve_performer(
            connection, str(performer["name"]), provider=provider, external_id=external_id,
            aliases=performer.get("aliases") or (), former_names=performer.get("former_names") or (), now=now)
        if _link_once(connection, asset_id, entity_id, "performer", owner):
            report.performers += 1
        thumb = str(performer.get("thumb_url") or "").strip()
        if thumb and not entities.metadata_of(connection, entity_id).get("avatar_url"):
            entities.merge_metadata(connection, entity_id, {"avatar_url": thumb, "avatar_source": provider})


def _apply_tags(connection, asset_id: int, decision: Settled, report: ApplyReport) -> None:
    owner = auto_owner(decision.source)
    for tag in decision.value:
        text = " ".join(str(tag or "").split())
        if not text:
            continue
        if _link_once(connection, asset_id, entities.resolve_named(connection, "tag", text), "tag", owner):
            report.tags += 1


def apply_settled(connection: sqlite3.Connection, asset_ids: Iterable[int], code: str,
                  settled: Mapping[str, Settled], *, now) -> ApplyReport:
    """把一个番号的结算结果写到它的每一碟上，写完记 `scraped_at`。"""
    report = ApplyReport()
    stamp = _stamp(now)
    ids = [int(asset_id) for asset_id in asset_ids]
    for asset_id in ids:
        row = connection.execute("SELECT * FROM asset WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            continue
        _apply_scalars(connection, asset_id, row, settled, report)
        if "performers" in settled:
            _apply_performers(connection, asset_id, settled["performers"], report, stamp)
        if "tags" in settled:
            _apply_tags(connection, asset_id, settled["tags"], report)
        connection.execute("UPDATE asset SET scraped_at=? WHERE id=?", (stamp, asset_id))
    return report


def _recent(scraped_at: object, now, days: int) -> bool:
    text = str(scraped_at or "").strip()
    if not text:
        return False
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    current = datetime.fromisoformat(_stamp(now))
    return current - moment < timedelta(days=days)


def should_scrape(row: Mapping[str, object], *, force: bool = False, now=None) -> tuple[bool, list[str]]:
    """这一行要不要去问，缺哪些。

    `row` 要有 `code`、`code_key`、`content_type`、`title`、`studio`、`release_date`、`field_owners`、`scraped_at`、
    `cover_file`，以及调用方算好的 `performer_count`、`tag_count`。没番号、未识别、韩国 MIB 与「其他体系」不问；
    创作者文件名撞出的假番号（`scrapes_as_jav`）不问。缺字段：`title/performers/studio/release_date` 为空或归属
    层级低于官方档的，`tags` 没关联的，`cover` 没封面或只有抽帧兜底的。`force` 全要；一项都不缺、或 7 天内问过
    且不 `force`，不问。
    """
    code = str(row.get("code") or "").strip()
    if not code or not str(row.get("code_key") or "").strip():
        return False, []
    if str(row.get("content_type") or "") == "unrecognized":
        return False, []
    hints = tuple(str(row.get(key) or "") for key in ("path", "name", "studio"))
    if classify(code, *hints) in UNASKED_CONTENT:
        return False, []
    if not scrapes_as_jav(code, str(row.get("studio") or "") or None):
        return False, []
    if force:
        return True, list(WANTED_FIELDS)
    owners = parse_owners(row.get("field_owners"))
    missing: list[str] = []
    for name in ("title", "studio", "release_date"):
        value = str(row.get(name) or "").strip()
        if not value or owner_tier(owners.get(name, "")) > CHAIN_OFFICIAL:
            missing.append(name)
    if not int(row.get("performer_count") or 0):
        missing.append("performers")
    if not int(row.get("tag_count") or 0):
        missing.append("tags")
    if not str(row.get("cover_file") or "").strip() or owners.get("cover_file", "") == auto_owner("frame"):
        missing.append("cover")
    ordered = [name for name in WANTED_FIELDS if name in missing]
    if not ordered:
        return False, []
    if _recent(row.get("scraped_at"), now if now is not None else datetime.now(timezone.utc), RESCRAPE_DAYS):
        return False, ordered
    return True, ordered
