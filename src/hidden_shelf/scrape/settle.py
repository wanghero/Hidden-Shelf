"""结算：几家来源各自交出的值，每个字段听谁的。

取值规则取自 peach `metadata_policy.chain_rank` / `sort_candidates` 与 `metadata_auto_apply._preferred_candidate`
（commit 4d5266d327a5971773409b44316e3926bd37c6ba，AGPL-3.0-or-later），以及 peach ADR-0034 决策三（日期式番号的
发行日只认番号那天）、ADR-0035 决策二（javbus 只在没别家时作证据）、ADR-0038 决策一（按链结算；同一家给两个值时
那一家不参与）。本项目没有候选复核队列：结算结果直接交 `apply` 落库，被压下去的值只留在 `Settled.overruled`
给日志看。

`cover_urls` 不在这里结算：封面要量尺寸再挑，交 `covers`。
"""
from __future__ import annotations

import re

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..rules.codes import code_release_date
from ..studios import canonical_studio
from .names import normalized_performers
from .policy import FALLBACK_SOURCES, FIELDS, blacklisted, chain_rank
from .sources.base import SiteRecord

#: 直接落到 `asset` 标量列的字段。
SCALAR_FIELDS = ("title", "original_title", "studio", "series", "release_date", "plot")
#: 整组取胜出那一家的字段。
LIST_FIELDS = ("tags", "performers")
#: 不结算、原样带给封面那一步的字段。
PASSTHROUGH_FIELDS = ("cover_urls",)


@dataclass(frozen=True)
class Candidate:
    field: str
    value: Any
    source: str
    confidence: float = 1.0


@dataclass(frozen=True)
class Settled:
    value: Any
    source: str
    #: 被压下去的 `(值, 来源)`，按链上的先后。
    overruled: tuple[tuple[Any, str], ...] = field(default_factory=tuple)


def normalized_plot(raw: object) -> str:
    """来源给的简介 → 段落用一个空行分开、行内空白折成一个空格的文本。"""
    lines = [" ".join(line.split()) for line in str(raw or "").replace("\r", "").split("\n")]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def normalized_release_date(raw: object) -> str:
    """来源给的发行日 → ISO 日期；带时间的取日期部分；读不出来回空串。"""
    value = str(raw or "").strip()
    if not value:
        return ""
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return ""


def extract(record: SiteRecord | Mapping[str, Any], *, source: str | None = None) -> list[Candidate]:
    """一份来源记录（`SiteRecord` 或快照里的 `payload()` 字典）→ 候选列表。空值不出候选。

    `performers` 经 `names.normalized_performers`（每人 `{name, external_id, thumb_url, aliases?, …}`），
    描述性称呼与剪不出艺名的企划名义在那里剔掉。
    """
    if isinstance(record, SiteRecord):
        payload = record.payload()
        name = record.source
        confidence = float(record.confidence)
    else:
        payload = dict(record)
        name = source or str(payload.get("source") or "")
        confidence = float(payload.get("confidence") or 1.0)
    if not name:
        raise ValueError("候选缺来源名")
    found: list[Candidate] = []

    def scalar(field_name: str, raw: object) -> None:
        text = " ".join(str(raw or "").split())
        if text:
            found.append(Candidate(field_name, text, name, confidence))

    scalar("title", payload.get("title"))
    scalar("original_title", payload.get("original_title"))
    # 厂牌先换成规范写法（カリビアンコム → Caribbeancom），几家来源写法不同也能在结算里对上。
    scalar("studio", canonical_studio(payload.get("maker") or payload.get("studio")))
    scalar("series", payload.get("series"))
    scalar("release_date", normalized_release_date(payload.get("release_date")))
    # 简介保留段落：只折行内空白，不把整段压成一行。老快照里 dmm/fc2/1pondo 的 `description` 也算。
    plot = normalized_plot(payload.get("plot") or payload.get("description"))
    if plot:
        found.append(Candidate("plot", plot, name, confidence))
    genres = payload.get("genres")
    if isinstance(genres, (list, tuple)):
        tags = tuple(dict.fromkeys(" ".join(str(tag).split()) for tag in genres if str(tag).strip()))
        if tags:
            found.append(Candidate("tags", tags, name, confidence))
    performers, _warnings = normalized_performers(payload.get("actresses"))
    if performers:
        found.append(Candidate("performers", tuple(performers), name, confidence))
    covers = payload.get("cover_urls")
    if isinstance(covers, (list, tuple)):
        urls = tuple(dict.fromkeys(str(url).strip() for url in covers if str(url or "").strip()))
        if urls:
            found.append(Candidate("cover_urls", urls, name, confidence))
    return found


def _drop_inconsistent_sources(rows: list[Candidate]) -> list[Candidate]:
    """同一家对同一个标量字段给出两个不同的值：这一家在这个字段上不参与（ADR-0038 决策一）。"""
    values: dict[str, set] = {}
    for row in rows:
        values.setdefault(row.source, set()).add(row.value)
    return [row for row in rows if len(values[row.source]) == 1]


def settle(code: str, candidates: Iterable[Candidate]) -> dict[str, Settled]:
    """每个字段按来源链结算。

    - 黑名单里的来源连候选都不算；
    - 日期式番号（`092415_001`）的 `release_date` 只认等于番号那天的候选；
    - 兜底来源（javbus）的值在同字段还有别家时不参与；
    - 同一家给出两个不同标量值时这一家跳过；
    - 标量取链首的值，列表字段取链首那一家的整组。
    """
    by_field: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        if candidate.field in PASSTHROUGH_FIELDS or candidate.field not in FIELDS:
            continue
        if blacklisted(candidate.field, candidate.source):
            continue
        by_field.setdefault(candidate.field, []).append(candidate)
    settled: dict[str, Settled] = {}
    dated = code_release_date(code)
    for field_name, rows in by_field.items():
        if field_name == "release_date" and dated:
            rows = [row for row in rows if row.value == dated]
        if field_name in SCALAR_FIELDS:
            rows = _drop_inconsistent_sources(rows)
        sources = {row.source for row in rows}
        if len(sources) > 1:
            rows = [row for row in rows if row.source not in FALLBACK_SOURCES]
        if not rows:
            continue
        rows.sort(key=lambda row: (chain_rank(field_name, row.source, code=code), -row.confidence))
        winner = rows[0]
        overruled = tuple((row.value, row.source) for row in rows[1:]
                          if row.value != winner.value or row.source != winner.source)
        settled[field_name] = Settled(winner.value, winner.source, overruled)
    return settled
