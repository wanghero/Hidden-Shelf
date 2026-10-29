"""出站：查询库 → 视图模型 → `.shelf/site/data/*.js` → 渲染 `<root>/index.html` → 拷静态文件。

站点从 `file://` 打开，所以数据只能是 `<script src>` 加载的 `.js`（`window.__shelf.*` 赋值），
视频与图片一律是相对盘根目录的 POSIX 路径（**不**预先 URL 编码，编码在前端 `encodeMediaPath` 做）。
不加载任何外网资源。
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import __version__
from ..config import ShelfConfig
from ..fsutil import atomic_write_text
from ..organize.plan import definition_of
from ..paths import ShelfPaths

Progress = Callable[[str], None]

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE_DIR = Path(__file__).parent / "templates"
#: 单个 data 文件序列化后超过这个大小就按 works 分片。
SPLIT_BYTES = 5 * 1024 * 1024
#: 静态文件在 index.html 里的引用顺序（data/* 插在 i18n 之后、shelf-core 之前）。
STATIC_ORDER = ("tokens.css", "app.css", "i18n.js", "shelf-core.js", "ripple.js", "app.js")
_KINDS = {"censored", "amateur", "uncensored", "fc2", "other"}


@dataclass
class BuildResult:
    works: int = 0
    performers: int = 0
    studios: int = 0
    series: int = 0
    tags: int = 0
    unrecognized: int = 0
    data_files: list[str] = field(default_factory=list)


def to_js(value) -> str:
    """紧凑 JSON，`</script` 转义成 `<\\/script`，U+2028/2029 转义。"""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (text.replace("</", "<\\/")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _assign(name: str, value, *, append: bool = False) -> str:
    head = "window.__shelf=window.__shelf||{};"
    if append:
        return f"{head}window.__shelf.{name}=(window.__shelf.{name}||[]).concat({to_js(value)});\n"
    return f"{head}window.__shelf.{name}={to_js(value)};\n"


def _part_key(part: str) -> tuple[int, int, str]:
    part = str(part or "")
    if not part:
        return (0, 0, "")
    if part.isdigit():
        return (1, int(part), "")
    return (2, 0, part)


def _shelf_path(rel: str | None) -> str | None:
    return f".shelf/{rel}" if rel else None


def _entity_links(connection: sqlite3.Connection, role: str) -> dict[int, list[int]]:
    """资产 → 实体 id 列表（用户写的在前，其余按写入顺序）。"""
    found: dict[int, list[int]] = {}
    for row in connection.execute(
        "SELECT asset_id,entity_id FROM asset_entity WHERE role=? ORDER BY asset_id,(source<>'user'),rowid", (role,)):
        bucket = found.setdefault(int(row[0]), [])
        if int(row[1]) not in bucket:
            bucket.append(int(row[1]))
    return found


def _source_links(paths: ShelfPaths) -> dict[str, list[dict]]:
    """每个番号的来源出处 `[{source, url}]`，从 `.shelf/sources/<番号>-<来源>.json` 的成功快照里读。"""
    found: dict[str, list[dict]] = {}
    if not paths.sources.is_dir():
        return found
    for path in sorted(paths.sources.glob("*-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or not isinstance(record.get("result"), dict):
            continue
        code, source = str(record.get("code") or ""), str(record.get("source") or "")
        records = record["result"].get("records")
        first = records[0] if isinstance(records, list) and records and isinstance(records[0], dict) else record["result"]
        url = str(first.get("source_url") or "").strip()
        if code and source and url.startswith("https://"):
            found.setdefault(code, []).append({"source": source, "url": url})
    return found


def _avatars(connection: sqlite3.Connection, paths: ShelfPaths) -> dict[int, str]:
    """艺人 id → 头像的站内相对路径（文件在才算）。"""
    found: dict[int, str] = {}
    for row in connection.execute("SELECT id, avatar_file FROM entity WHERE kind='performer' AND avatar_file IS NOT NULL"):
        rel = str(row["avatar_file"] or "").strip()
        if rel and paths.shelf_absolute(rel).is_file():
            found[int(row["id"])] = f".shelf/{rel}"
    return found


def _view_model(connection: sqlite3.Connection, config: ShelfConfig,
                paths: ShelfPaths | None = None) -> tuple[list[dict], dict, list[dict], dict]:
    rows = connection.execute(
        "SELECT * FROM asset WHERE medium='video' AND vanished=0 ORDER BY code_key, id").fetchall()
    performers_of = _entity_links(connection, "performer")
    tags_of = _entity_links(connection, "tag")
    entity_names = {int(r["id"]): r["canonical_name"] for r in connection.execute("SELECT id,canonical_name FROM entity")}
    source_links = _source_links(paths) if paths is not None else {}
    avatars = _avatars(connection, paths) if paths is not None else {}

    groups: dict[str, list[sqlite3.Row]] = {}
    unrecognized: list[dict] = []
    for row in rows:
        if row["code_key"]:
            groups.setdefault(row["code_key"], []).append(row)
        else:
            unrecognized.append({
                "id": int(row["id"]), "path": row["path"], "name": row["name"], "size": row["size"],
                "duration": row["duration"], "play_hint": row["play_hint"] or "",
                "container": row["container"], "vcodec": row["vcodec"], "acodec": row["acodec"],
                "addedAt": row["first_seen"],
            })

    works: list[dict] = []
    performer_count: dict[int, int] = {}
    tag_count: dict[int, int] = {}
    studio_count: dict[str, int] = {}
    series_count: dict[str, int] = {}
    for code_key, members in groups.items():
        members = sorted(members, key=lambda r: (_part_key(r["part"]), int(r["id"])))
        head = members[0]
        performers: list[int] = []
        tags: list[int] = []
        for member in members:
            for entity_id in performers_of.get(int(member["id"]), []):
                if entity_id not in performers:
                    performers.append(entity_id)
            for entity_id in tags_of.get(int(member["id"]), []):
                if entity_id not in tags:
                    tags.append(entity_id)
        parts = [{
            "id": int(m["id"]), "path": m["path"], "name": m["name"], "part": m["part"] or "",
            "size": m["size"], "duration": m["duration"], "container": m["container"],
            "vcodec": m["vcodec"], "acodec": m["acodec"], "play_hint": m["play_hint"] or "",
            "sheet": _shelf_path(m["sheet_file"]),
        } for m in members]
        durations = [float(m["duration"]) for m in members if m["duration"]]
        release_date = head["release_date"] or ""
        studio = head["studio"] or ""
        series = head["series"] or ""
        kind = head["content_type"] if head["content_type"] in _KINDS else "other"
        work = {
            "id": code_key,
            "code": head["code"],
            "title": head["title"] or "",
            "originalTitle": head["original_title"] or "",
            "studio": studio,
            "series": series,
            "date": release_date,
            "year": int(release_date[:4]) if release_date[:4].isdigit() else None,
            "performers": performers,
            "tags": tags,
            "plot": head["plot"] or "",
            "duration": sum(durations) if durations else None,
            "width": head["width"],
            "height": head["height"],
            "definition": definition_of(head["width"], head["height"]),
            "kind": kind,
            "parts": parts,
            "cover": _shelf_path(head["cover_file"]),
            "poster": _shelf_path(head["poster_file"]),
            "sheet": _shelf_path(head["sheet_file"]),
            "addedAt": min((m["first_seen"] for m in members if m["first_seen"]), default=None),
            "size": sum(int(m["size"] or 0) for m in members),
            "sources": source_links.get(code_key, []),
        }
        works.append(work)
        for entity_id in performers:
            performer_count[entity_id] = performer_count.get(entity_id, 0) + 1
        for entity_id in tags:
            tag_count[entity_id] = tag_count.get(entity_id, 0) + 1
        if studio:
            studio_count[studio] = studio_count.get(studio, 0) + 1
        if series:
            series_count[series] = series_count.get(series, 0) + 1

    def roster(counter: dict[int, int]) -> list[dict]:
        return sorted(({"id": entity_id, "name": entity_names.get(entity_id, ""), "count": count}
                       for entity_id, count in counter.items()),
                      key=lambda item: (-item["count"], item["name"]))

    entities = {
        "performers": [{**item, "avatar": avatars.get(item["id"])} for item in roster(performer_count)],
        "studios": sorted(({"id": name, "name": name, "count": count} for name, count in studio_count.items()),
                          key=lambda item: (-item["count"], item["name"])),
        "series": sorted(({"id": name, "name": name, "count": count} for name, count in series_count.items()),
                         key=lambda item: (-item["count"], item["name"])),
        "tags": roster(tag_count),
    }
    totals = {
        "totalDuration": sum(float(r["duration"] or 0) for r in rows),
        "totalBytes": sum(int(r["size"] or 0) for r in rows),
    }
    return works, entities, unrecognized, totals


def _split_works(works: list[dict], limit: int) -> list[list[dict]]:
    """按序列化大小分片，每片不超过 `limit`（单项本身超限时独占一片）。"""
    if len(to_js(works).encode("utf-8")) <= limit:
        return [works]
    chunks: list[list[dict]] = []
    current: list[dict] = []
    size = 2
    for work in works:
        piece = len(to_js(work).encode("utf-8")) + 1
        if current and size + piece > limit:
            chunks.append(current)
            current, size = [], 2
        current.append(work)
        size += piece
    if current:
        chunks.append(current)
    return chunks


def build_site(connection: sqlite3.Connection, paths: ShelfPaths, config: ShelfConfig, *,
               progress: Progress = lambda message: None, split_bytes: int | None = None) -> BuildResult:
    """生成全部站点产物。"""
    paths.ensure()
    limit = SPLIT_BYTES if split_bytes is None else split_bytes
    works, entities, unrecognized, totals = _view_model(connection, config, paths)
    progress(f"出站：{len(works)} 部作品，{len(unrecognized)} 个未识别")

    # 清掉上次的 data 文件，避免旧分片残留。
    for old in paths.site_data.glob("*.js"):
        old.unlink()
    data_files: list[str] = []
    chunks = _split_works(works, limit)
    if len(chunks) == 1:
        atomic_write_text(paths.site_data / "works.js", _assign("works", chunks[0]))
        data_files.append("works.js")
    else:
        for index, chunk in enumerate(chunks, 1):
            name = f"works-{index}.js"
            atomic_write_text(paths.site_data / name, _assign("works", chunk, append=True))
            data_files.append(name)
    atomic_write_text(paths.site_data / "entities.js", _assign("entities", entities))
    data_files.append("entities.js")
    atomic_write_text(paths.site_data / "unrecognized.js", _assign("unrecognized", unrecognized))
    data_files.append("unrecognized.js")
    meta = {
        "version": __version__,
        "builtAt": datetime.now().isoformat(timespec="seconds"),
        "language": config.language,
        "counts": {
            "works": len(works), "performers": len(entities["performers"]), "studios": len(entities["studios"]),
            "series": len(entities["series"]), "tags": len(entities["tags"]), "unrecognized": len(unrecognized),
        },
        **totals,
        "dataFiles": ["meta.js", *data_files],
    }
    atomic_write_text(paths.site_data / "meta.js", _assign("meta", meta))
    data_files = ["meta.js", *data_files]

    for name in STATIC_ORDER:
        shutil.copyfile(STATIC_DIR / name, paths.site / name)

    environment = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape(["html"]))
    html = environment.get_template("index.html.j2").render(
        site_dir=".shelf/site", data_files=data_files, version=__version__,
        language=config.language, built_at=meta["builtAt"])
    atomic_write_text(paths.index_html, html)
    progress(f"出站完成：{paths.index_html}")
    return BuildResult(
        works=len(works), performers=len(entities["performers"]), studios=len(entities["studios"]),
        series=len(entities["series"]), tags=len(entities["tags"]), unrecognized=len(unrecognized),
        data_files=data_files)


_DATA_RE = re.compile(r"window\.__shelf\.(\w+)=(?:\(window\.__shelf\.\w+\|\|\[\]\)\.concat\()?(.*?)\)?;\s*$", re.S)


def read_data_js(path: Path):
    """把我们自己生成的 data 文件解析回 Python 值（测试与诊断用）。"""
    text = Path(path).read_text(encoding="utf-8")
    match = _DATA_RE.search(text)
    if not match:
        raise ValueError(f"不是 shelf data 文件：{path}")
    return json.loads(match.group(2).replace("<\\/", "</"))
