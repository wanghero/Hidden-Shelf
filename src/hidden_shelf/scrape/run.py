"""刮削编排：一个番号问哪几家、何时停、结果怎么落库，再补封面与头像。

流程思路取自 peach `library_processing.py` 的 `_query`（按档问、`settles` 短路、快照与「没有」记录），
commit 4d5266d327a5971773409b44316e3926bd37c6ba，AGPL-3.0-or-later。本项目每站各是一档、逐家短路
（用户 2026-10-29 决定「有一家答了就停」），没有复核队列，结算直接落库。

一趟的部件：`Cooldown`（按站冷却，`.shelf/sources/_cooldown.json`）、`Snapshots`（原始快照与「没有」，7 天）、
`SourceTransport`（按站 Cookie、主机间隔、预算）。`transport` 可注入假传输（测试）。
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from ..config import ShelfConfig
from ..netconfig import GlobalConfig
from ..paths import ShelfPaths
from . import routes
from .access import Cooldown, SourcePaused, SourceTransport, source_for
from .apply import apply_settled, should_scrape
from .avatars import install_avatars
from .covers import best_cover, candidates_from_records, install_online_cover
from .identity import identifies_code
from .settle import extract, settle
from .snapshots import Snapshots
from .sources import SITE_SOURCES, Session, SourceFailure
from .transport import DeadlineExceeded, HostLimiter, NotFound, Unavailable

Progress = Callable[[str], None]

#: 连着几个番号一个请求都连不上，就认为网络不可用，本趟不再问。
NETWORK_DOWN_AFTER = 3
#: 封面在快照里记「没有」时用的来源名。
COVER_SNAPSHOT = "cover"
#: 进度行里的字段名。
_FIELD_LABELS = {"title": "标题", "original_title": "原题", "studio": "厂牌", "series": "系列",
                 "release_date": "发行日", "performers": "演员", "tags": "标签"}


@dataclass
class ScrapeResult:
    asked: int = 0
    settled: int = 0
    covers: int = 0
    avatars: int = 0
    skipped: int = 0
    missing: int = 0
    failed: int = 0
    paused: list[str] = field(default_factory=list)
    network_down: bool = False


class _StopRun(Exception):
    """本趟预算用完或网络不可用：剩下的番号下趟再问。"""


def _stamp(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds")


def _groups(connection: sqlite3.Connection) -> list[list[sqlite3.Row]]:
    rows = connection.execute(
        "SELECT * FROM asset WHERE medium='video' AND vanished=0 AND code_key IS NOT NULL AND code_key<>'' "
        "ORDER BY code_key, part, id").fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["code_key"]), []).append(row)
    return list(grouped.values())


def _candidate_row(connection: sqlite3.Connection, members: Sequence[sqlite3.Row]) -> dict:
    """`should_scrape` 要的那一行：以第一碟为准，演员与标签数按整组算。"""
    head = members[0]
    ids = [int(member["id"]) for member in members]
    marks = ",".join("?" * len(ids))
    count = lambda role: int(connection.execute(
        f"SELECT count(DISTINCT entity_id) FROM asset_entity WHERE role=? AND asset_id IN ({marks})",
        (role, *ids)).fetchone()[0])
    return {**dict(head), "performer_count": count("performer"), "tag_count": count("tag")}


def _fields_of(payloads: Iterable[tuple[str, dict]]) -> set[str]:
    given: set[str] = set()
    for source, payload in payloads:
        given.update(candidate.field for candidate in extract(payload, source=source))
    return given


class _Scraper:
    def __init__(self, connection, paths, *, global_config, session, snapshots, progress, now, force, only_sources,
                 result):
        self.connection = connection
        self.paths = paths
        self.global_config = global_config
        self.session = session
        self.snapshots = snapshots
        self.progress = progress
        self.now = now
        self.force = force
        self.only_sources = set(only_sources) if only_sources else None
        self.result = result
        self.network_failures = 0

    # ---------- 来源 ----------

    def chain_for(self, code: str, row: dict) -> tuple[str, ...]:
        hints = (str(row.get("path") or ""), str(row.get("name") or ""), str(row.get("studio") or ""))
        chain = routes.route_for_code(code, *hints, overrides=self.global_config.routes)
        return tuple(source for source in chain
                     if source in SITE_SOURCES and self.global_config.enabled(source)
                     and (self.only_sources is None or source in self.only_sources))

    def ask(self, code: str, code_key: str, source: str) -> list[dict] | None:
        """问一家：先读新鲜快照；没有就请求。回这一家的记录列表，没有回 None。"""
        if source in self.result.paused or self.snapshots.fresh_miss(code_key, source):
            return None
        cached = self.snapshots.load(code_key, source)
        if cached is not None:
            records = cached.get("records")
            return [item for item in records if isinstance(item, dict)] if isinstance(records, list) else None
        site = SITE_SOURCES[source]()
        self.result.asked += 1
        try:
            records = site.records(code, session=self.session)
        except SourceFailure as failure:
            if failure.is_miss or failure.detail == "identity_mismatch":
                self.snapshots.save_miss(code_key, source, failure.reason.value, failure.message)
                self.result.missing += 1
                self.progress(f"{code} {source}：{failure.message}")
            else:
                self.progress(f"{code} {source} 未取得：{failure.message}")
            return None
        except SourcePaused as error:
            if source not in self.result.paused:
                self.result.paused.append(source)
            self.progress(f"{code} {source} 暂停：{error}")
            if "本趟" in str(error):
                raise _StopRun(str(error)) from error
            return None
        except httpx.TransportError as error:
            self.network_failures += 1
            self.progress(f"{code} {source} 连接失败：{error}")
            return None
        payloads = [record.payload() for record in records]
        verified = [payload for payload in payloads if identifies_code(code, payload)]
        if not verified:
            self.snapshots.save_miss(code_key, source, "identity_mismatch", "来源返回的番号不匹配")
            self.result.missing += 1
            self.progress(f"{code} {source}：来源返回的番号不匹配")
            return None
        self.network_failures = 0
        self.snapshots.save_result(code_key, source, {"records": verified})
        return verified

    # ---------- 一个番号 ----------

    def scrape_group(self, members: Sequence[sqlite3.Row]) -> None:
        head = members[0]
        code, code_key = str(head["code"]), str(head["code_key"])
        ids = [int(member["id"]) for member in members]
        row = _candidate_row(self.connection, members)
        wanted, missing = should_scrape(row, force=self.force, now=self.now())
        if not wanted:
            self.result.skipped += 1
            return
        chain = self.chain_for(code, row)
        if not chain:
            self.result.skipped += 1
            return
        required = routes.required_scalars(missing)
        wants_tags = "tags" in missing
        collected: list[tuple[str, dict]] = []
        stages = routes.stages_for_chain(chain)
        before = self.network_failures
        for index, stage in enumerate(stages):
            answered = False
            for source in routes.stage_members(stage, chain):
                records = self.ask(code, code_key, source)
                if records:
                    answered = True
                    collected.extend((source, payload) for payload in records)
            if not answered:
                continue
            following = stages[index + 1] if index + 1 < len(stages) else ""
            if routes.settles(required, _fields_of(collected), wants_tags=wants_tags, then=following):
                break
        if not collected:
            if self.network_failures > before and self.network_failures >= NETWORK_DOWN_AFTER:
                raise _StopRun("网络不可用，本趟跳过刮削")
            self.progress(f"{code} 没有来源给出资料")
            self.connection.execute("UPDATE asset SET scraped_at=? WHERE code_key=?", (_stamp(self.now()), code_key))
            self.connection.commit()
            return
        candidates = [candidate for source, payload in collected for candidate in extract(payload, source=source)]
        settled = settle(code, candidates)
        report = apply_settled(self.connection, ids, code, settled, now=_stamp(self.now()))
        self.result.settled += 1
        summary = "/".join(_FIELD_LABELS[name] for name in _FIELD_LABELS if name in settled)
        cover_note = ""
        if "cover" in missing or self.force:
            cover_note = self.fetch_cover(code, code_key, ids, collected)
        self.connection.commit()
        sources = ",".join(dict.fromkeys(source for source, _ in collected))
        line = f"{code} ← {sources} · {summary or '无新字段'}"
        if report.kept:
            line += f" · 保留 {'/'.join(_FIELD_LABELS.get(name, name) for name in report.kept)}"
        self.progress(line + (f" · {cover_note}" if cover_note else ""))

    def fetch_cover(self, code: str, code_key: str, ids: list[int], collected: list[tuple[str, dict]]) -> str:
        if self.snapshots.fresh_miss(code_key, COVER_SNAPSHOT) and not self.force:
            return ""
        candidates = candidates_from_records(code, collected)
        if not candidates:
            return ""
        try:
            winner, (width, height), data = best_cover(self.session.transport, code, candidates)
        except NotFound as error:
            self.snapshots.save_miss(code_key, COVER_SNAPSHOT, "not_found", str(error))
            return f"封面：{error}"
        except (Unavailable, httpx.TransportError, SourcePaused) as error:
            return f"封面未取得：{error}"
        owner = source_for(winner.url) or COVER_SNAPSHOT
        rel = install_online_cover(self.connection, self.paths, ids, code_key, data, owner)
        if not rel:
            return "封面保留本地那张"
        self.result.covers += 1
        return f"封面 {width}×{height}"


def scrape_assets(connection: sqlite3.Connection, paths: ShelfPaths, config: ShelfConfig, *,
                  global_config: GlobalConfig | None = None, transport=None, progress: Progress = lambda message: None,
                  force: bool = False, only_sources: Iterable[str] | None = None, now: Callable[[], float] = time.time,
                  max_requests: int = 0, max_seconds: float = 0) -> ScrapeResult:
    """给盘里每个番号补资料、封面，最后补女优头像。任一番号出错记下继续；网络不通提前返回，不抛。"""
    paths.ensure()
    global_config = global_config or GlobalConfig.load()
    result = ScrapeResult()
    cooldown = Cooldown(paths.sources / "_cooldown.json", now=now)
    snapshots = Snapshots(paths.sources, now=now)
    if transport is not None:
        source_transport = SourceTransport(cooldown, global_config, factory=lambda source: transport,
                                           limiter=HostLimiter({}, default=0.0), max_requests=max_requests,
                                           max_seconds=max_seconds)
    else:
        source_transport = SourceTransport(cooldown, global_config, max_requests=max_requests, max_seconds=max_seconds)
    session = Session(source_transport)
    scraper = _Scraper(connection, paths, global_config=global_config, session=session, snapshots=snapshots,
                       progress=progress, now=now, force=force, only_sources=only_sources, result=result)
    try:
        for members in _groups(connection):
            code = str(members[0]["code"])
            try:
                scraper.scrape_group(members)
            except _StopRun as stop:
                result.network_down = "网络" in str(stop)
                progress(str(stop))
                break
            except DeadlineExceeded:
                progress("本趟采集时间已用完，再跑一次接着采")
                break
            except Exception as error:  # noqa: BLE001 - 一个番号出错不连累其它
                result.failed += 1
                detail = f"{type(error).__name__}: {error}"
                connection.execute("UPDATE asset SET scrape_note=? WHERE code_key=?", (detail, members[0]["code_key"]))
                connection.commit()
                progress(f"{code} 出错：{detail}")
        if not result.network_down:
            result.avatars = install_avatars(connection, paths, session.transport, progress=progress)
    finally:
        connection.commit()
        source_transport.close()
    if cooldown.describe():
        for name, state in cooldown.describe().items():
            if name not in result.paused:
                result.paused.append(name)
    progress(f"刮削完成：问了 {result.asked} 次，落库 {result.settled} 个番号，封面 {result.covers}，头像 {result.avatars}，"
             f"跳过 {result.skipped}，没有 {result.missing}，出错 {result.failed}"
             + (f"，暂停 {','.join(result.paused)}" if result.paused else ""))
    return result
