"""把刮削/生成好的封面与九宫格复制一份到视频所在目录（计划 9 任务 2，用户 2026-10-30 要的选项）。

默认关（`ShelfConfig.images_in_work_dir=False`，设计文档「媒体目录旁不写任何附属文件」照旧）。开了之后，媒体步
末尾把 `HiddenShelf/covers/<番号>.jpg` 复制成 `<番号>-cover.jpg`、`HiddenShelf/sheets/<碟>.jpg` 复制成
`<视频主名>-sheet.jpg`，放到视频旁边；`sidecar` 表记 `status='placed'`，扫描不会再把它当待导入的本地封面，
归位时跟着视频进新目录（不进 legacy），关掉选项时只删这些自己放的副本（用户自己的图片不认识就不碰）。
真相仍在 `HiddenShelf/` 里，副本随时可以重新生成。
"""
from __future__ import annotations

import posixpath
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from ..config import ShelfConfig
from ..paths import ShelfPaths

Progress = Callable[[str], None]
PLACED = "placed"


@dataclass
class PlaceResult:
    copied: int = 0
    removed: int = 0
    failed: int = 0


def _targets(row: sqlite3.Row) -> list[tuple[str, str, str]]:
    """这一行要放的副本：`(来源相对资料目录, 目标相对盘根, kind)`。没番号的不放。"""
    if not row["code_key"]:
        return []
    directory = posixpath.dirname(row["path"])
    stem = posixpath.splitext(row["name"])[0]
    out = []
    if row["cover_file"]:
        out.append((row["cover_file"], posixpath.join(directory, f"{row['code_key']}-cover.jpg"), "cover"))
    if row["sheet_file"]:
        out.append((row["sheet_file"], posixpath.join(directory, f"{stem}-sheet.jpg"), "thumb"))
    return out


def place_images(connection: sqlite3.Connection, paths: ShelfPaths, config: ShelfConfig, *,
                 progress: Progress = lambda message: None) -> PlaceResult:
    """选项开：补齐副本（内容变了就重拷）；选项关：删掉自己放过的副本。幂等。"""
    result = PlaceResult()
    placed_rows = connection.execute("SELECT id, path FROM sidecar WHERE status=?", (PLACED,)).fetchall()
    if not config.images_in_work_dir:
        for row in placed_rows:
            target = paths.absolute(row["path"])
            if target.is_file():
                try:
                    target.unlink()
                    result.removed += 1
                except OSError as error:
                    result.failed += 1
                    progress(f"删不掉副本 {row['path']}：{error.strerror or error}")
                    continue
            connection.execute("DELETE FROM sidecar WHERE id=?", (row["id"],))
        connection.commit()
        if result.removed:
            progress(f"已收回放在视频旁的图片副本 {result.removed} 张")
        return result
    # 记录还在、文件没了（用户删了）：清掉记录，下面会重放。
    for row in placed_rows:
        if not paths.absolute(row["path"]).is_file():
            connection.execute("DELETE FROM sidecar WHERE id=?", (row["id"],))
    rows = connection.execute(
        "SELECT * FROM asset WHERE medium='video' AND vanished=0 AND code_key IS NOT NULL ORDER BY code_key, part, id").fetchall()
    wanted: set[str] = set()
    for row in rows:
        for source_rel, target_rel, kind in _targets(row):
            source = paths.shelf_absolute(source_rel)
            if not source.is_file():
                continue
            wanted.add(target_rel)
            target = paths.absolute(target_rel)
            existing = connection.execute("SELECT status FROM sidecar WHERE path=?", (target_rel,)).fetchone()
            if existing is not None and existing["status"] != PLACED:
                # 同名文件是用户自己的（扫描登记过的附属文件），不覆盖。
                continue
            if target.is_file() and target.stat().st_size == source.stat().st_size:
                connection.execute(
                    "INSERT INTO sidecar(asset_id,path,kind,status) VALUES(?,?,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET asset_id=excluded.asset_id, status=excluded.status",
                    (int(row["id"]), target_rel, kind, PLACED))
                continue
            try:
                shutil.copyfile(source, target)
            except OSError as error:
                result.failed += 1
                progress(f"放不进 {target_rel}：{error.strerror or error}")
                continue
            connection.execute(
                "INSERT INTO sidecar(asset_id,path,kind,status) VALUES(?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET asset_id=excluded.asset_id, status=excluded.status",
                (int(row["id"]), target_rel, kind, PLACED))
            result.copied += 1
    # 视频没了或番号变了，留下的副本收回。
    for row in connection.execute("SELECT id, path FROM sidecar WHERE status=?", (PLACED,)).fetchall():
        if row["path"] in wanted:
            continue
        target = paths.absolute(row["path"])
        if target.is_file():
            try:
                target.unlink()
                result.removed += 1
            except OSError:
                result.failed += 1
                continue
        connection.execute("DELETE FROM sidecar WHERE id=?", (row["id"],))
    connection.commit()
    if result.copied or result.removed:
        progress(f"视频旁的图片副本：新放 {result.copied} 张，收回 {result.removed} 张")
    return result
