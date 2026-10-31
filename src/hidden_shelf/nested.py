"""合并子目录里的旧库（计划 10）。

用户先在 `盘/child/` 跑过，后来改以 `盘/` 为盘根再跑：扫描步跳过任何深度的 `HiddenShelf/`，所以子目录里的视频
已经以 `child/...` 的路径进了母库，只是资料是空的。本模块在「导入本地资料」步把子库 `shelf.db` 当本地资料读进来：
按「子目录相对路径 + 子库里的 `asset.path`」对上母库里的同一文件，把标量字段连同**原归属**带过去（母库已有的值不动），
艺人/标签/系列/厂牌关联合并到母库实体，封面/海报/九宫格/头像/快照文件复制过来，最后把子库目录整体搬到
`HiddenShelf/legacy/nested/<子目录>/` 留底（预演不搬）。子库只读；打不开就记日志跳过，不搬。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from . import entities
from .field_owners import FieldWrite, auto_owner, is_valid_owner, parse_owners, write_owned_fields
from .paths import SHELF_DIR, ShelfPaths
from .scan import SKIP_DIRS

Progress = Callable[[str], None]

#: 留底目录：`HiddenShelf/legacy/nested/<子目录相对路径，/ 换成 __>/`。
NESTED_LEGACY_DIR = "nested"
#: 子库里带归属的标量字段（与 `local_import` 的 NFO/overrides 字段一致，外加 `code`）。
_SCALARS = ("title", "original_title", "studio", "series", "release_date", "plot")
#: 探测结果：子库与母库的 size/mtime 相同才搬，省一次 ffprobe。
_PROBE = ("duration", "width", "height", "vcodec", "acodec", "container", "play_hint", "probed_at")
_LOCAL = auto_owner("local")


@dataclass
class NestedResult:
    libraries: int = 0
    assets: int = 0
    images: int = 0
    avatars: int = 0
    snapshots: int = 0
    moved: int = 0
    skipped: int = 0


def find_nested_libraries(root: Path) -> list[Path]:
    """所有深度上「含 `shelf.db` 的 `HiddenShelf/`」的父目录（子盘根），不含 root 自己；跳过系统目录与库目录本身。"""
    found: list[Path] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            children = sorted(child for child in directory.iterdir() if child.is_dir() and not child.is_symlink())
        except OSError:
            continue
        for child in children:
            if child.name.casefold() in SKIP_DIRS:
                if child.name == SHELF_DIR and directory != root and (child / "shelf.db").is_file():
                    found.append(directory)
                continue
            stack.append(child)
    return sorted(set(found))


def merge_nested_libraries(connection: sqlite3.Connection, paths: ShelfPaths, *,
                           progress: Progress = print, move: bool = True) -> NestedResult:
    result = NestedResult()
    for child_root in find_nested_libraries(paths.root):
        rel = paths.relative(child_root)
        result.libraries += 1
        child = ShelfPaths(child_root)
        try:
            source = sqlite3.connect(f"file:{child.db}?mode=ro", uri=True)
            source.row_factory = sqlite3.Row
            rows = source.execute("SELECT * FROM asset WHERE vanished=0 ORDER BY id").fetchall()
        except sqlite3.Error as error:
            progress(f"子目录 {rel}/ 的旧库读不了，跳过：{error}")
            result.skipped += 1
            continue
        try:
            progress(f"发现子目录里的旧库：{rel}/（{len(rows)} 条）")
            entity_map: dict[int, int] = {}
            for row in rows:
                if _merge_asset(connection, paths, child, rel, source, row, entity_map, result):
                    result.assets += 1
            result.avatars += _merge_avatars(connection, paths, child, source, entity_map)
            result.snapshots += _copy_snapshots(paths, child)
        finally:
            source.close()
        connection.commit()
        if move:
            _move_to_legacy(paths, child_root, rel)
            result.moved += 1
            progress(f"子库 {rel}/{SHELF_DIR}/ 与 index.html 已搬到 {SHELF_DIR}/legacy/{NESTED_LEGACY_DIR}/")
        else:
            progress(f"预演：子库 {rel}/{SHELF_DIR}/ 留在原地")
    if result.libraries:
        progress(f"合并子库：{result.libraries} 个库，{result.assets} 条资料，{result.images} 张图，"
                 f"{result.avatars} 个头像，{result.snapshots} 份快照")
    return result


def _merge_asset(connection, paths: ShelfPaths, child: ShelfPaths, rel: str, source: sqlite3.Connection,
                 row: sqlite3.Row, entity_map: dict[int, int], result: NestedResult) -> bool:
    parent_path = str(PurePosixPath(rel) / row["path"])
    target = connection.execute("SELECT * FROM asset WHERE path=? AND vanished=0", (parent_path,)).fetchone()
    if target is None:
        return False
    asset_id = int(target["id"])
    owners = parse_owners(row["field_owners"])

    def owner(field: str) -> str:
        value = owners.get(field, "")
        return value if is_valid_owner(value) else _LOCAL

    writes = [FieldWrite(field, row[field], owner(field), require_empty=True)
              for field in _SCALARS if str(row[field] or "").strip()]
    if row["code"] and not target["code"]:
        writes.append(FieldWrite("code", row["code"], owner("code"), require_empty=True))
    if writes:
        write_owned_fields(connection, "asset", asset_id, writes)
    if row["code"] and not target["code"]:
        connection.execute("UPDATE asset SET code_key=COALESCE(code_key,?),content_type=COALESCE(content_type,?) "
                           "WHERE id=? AND code IS NOT NULL", (row["code_key"], row["content_type"], asset_id))
    if row["scraped_at"] and not target["scraped_at"]:
        connection.execute("UPDATE asset SET scraped_at=?,scrape_note=? WHERE id=?",
                           (row["scraped_at"], row["scrape_note"], asset_id))
    if (target["probed_at"] is None and row["probed_at"]
            and row["size"] == target["size"] and row["mtime"] == target["mtime"]):
        connection.execute(f"UPDATE asset SET {','.join(f'{f}=?' for f in _PROBE)} WHERE id=?",
                           tuple(row[f] for f in _PROBE) + (asset_id,))

    # 关联：子库实体 → 母库实体（艺人走 resolve_performer，其余按名合并），来源与置信度照搬
    links = source.execute(
        "SELECT ae.entity_id, ae.role, ae.source, ae.confidence, e.kind, e.canonical_name "
        "FROM asset_entity ae JOIN entity e ON e.id=ae.entity_id WHERE ae.asset_id=?", (row["id"],)).fetchall()
    for link in links:
        entity_id = _resolve_entity(connection, source, link, entity_map)
        if entity_id is not None:
            entities.link(connection, asset_id, entity_id, link["role"], link["source"], float(link["confidence"]))

    # 图片：母库没有才复制；封面带原归属（抽帧兜底的照样是 auto:frame，联网时还会换）
    stem = target["code_key"] or f"asset-{asset_id}"
    for field, folder, name in (("cover_file", paths.covers, f"{stem}.jpg"),
                                ("poster_file", paths.posters, f"{stem}.jpg"),
                                ("sheet_file", paths.sheets, f"{stem}{_part_suffix(target)}.jpg")):
        if target[field] or not row[field]:
            continue
        origin = child.shelf_absolute(row[field])
        if not origin.is_file():
            continue
        destination = folder / name
        if not destination.exists():
            shutil.copy2(origin, destination)
        shelf_rel = paths.shelf_relative(destination)
        if field == "cover_file":
            write_owned_fields(connection, "asset", asset_id, [FieldWrite(field, shelf_rel, owner(field))])
        else:
            connection.execute(f"UPDATE asset SET {field}=? WHERE id=?", (shelf_rel, asset_id))
        result.images += 1
    return True


def _part_suffix(target: sqlite3.Row) -> str:
    part = str(target["part"] or "").strip()
    return f"-cd{part}" if part else ""


def _resolve_entity(connection, source: sqlite3.Connection, link: sqlite3.Row,
                    entity_map: dict[int, int]) -> int | None:
    child_id = int(link["entity_id"])
    if child_id in entity_map:
        return entity_map[child_id]
    kind, name = link["kind"], link["canonical_name"]
    try:
        if kind == "performer":
            refs = source.execute("SELECT provider, external_id FROM entity_external_ref WHERE entity_id=?",
                                  (child_id,)).fetchall()
            aliases = [r["alias"] for r in source.execute("SELECT alias FROM entity_alias WHERE entity_id=?",
                                                          (child_id,)).fetchall()]
            entity_id = entities.resolve_performer(connection, name, aliases=aliases)
            for ref in refs:
                entities.add_external_ref(connection, entity_id, ref["provider"], "performer", ref["external_id"])
        else:
            entity_id = entities.resolve_named(connection, kind, name)
    except ValueError:
        return None
    metadata = source.execute("SELECT metadata FROM entity WHERE id=?", (child_id,)).fetchone()
    try:
        extra = json.loads(metadata["metadata"] or "{}") if metadata else {}
    except ValueError:
        extra = {}
    if isinstance(extra, dict) and extra and not entities.metadata_of(connection, entity_id):
        entities.merge_metadata(connection, entity_id, extra)
    entity_map[child_id] = entity_id
    return entity_id


def _merge_avatars(connection: sqlite3.Connection, paths: ShelfPaths, child: ShelfPaths,
                   source: sqlite3.Connection, entity_map: dict[int, int]) -> int:
    """子库艺人的头像复制到母库 `avatars/<母库实体 id>.jpg`；母库已有头像的不动。"""
    count = 0
    for child_id, entity_id in entity_map.items():
        row = source.execute("SELECT avatar_file FROM entity WHERE id=?", (child_id,)).fetchone()
        if not row or not row["avatar_file"]:
            continue
        origin = child.shelf_absolute(row["avatar_file"])
        if not origin.is_file():
            continue
        current = connection.execute("SELECT avatar_file FROM entity WHERE id=?", (entity_id,)).fetchone()
        if current is None or current["avatar_file"]:
            continue
        destination = paths.avatars / f"{entity_id}{origin.suffix or '.jpg'}"
        if not destination.exists():
            shutil.copy2(origin, destination)
        connection.execute("UPDATE entity SET avatar_file=? WHERE id=?",
                           (paths.shelf_relative(destination), entity_id))
        count += 1
    return count


def _copy_snapshots(paths: ShelfPaths, child: ShelfPaths) -> int:
    count = 0
    if not child.sources.is_dir():
        return 0
    for snapshot in sorted(child.sources.glob("*.json")):
        if snapshot.name.startswith("_"):
            continue
        destination = paths.sources / snapshot.name
        if destination.exists():
            continue
        shutil.copy2(snapshot, destination)
        count += 1
    return count


def _move_to_legacy(paths: ShelfPaths, child_root: Path, rel: str) -> None:
    base = paths.legacy / NESTED_LEGACY_DIR
    base.mkdir(parents=True, exist_ok=True)
    name = rel.replace("/", "__")
    destination = base / name
    counter = 2
    while destination.exists():
        destination = base / f"{name}-{counter}"
        counter += 1
    destination.mkdir()
    shutil.move(str(child_root / SHELF_DIR), str(destination / SHELF_DIR))
    index_html = child_root / "index.html"
    if index_html.is_file():
        shutil.move(str(index_html), str(destination / "index.html"))
