"""媒体步骤：探测、抽帧兜底封面、九宫格、海报。失败只记日志、计数，不抛。"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..field_owners import FieldWrite, auto_owner, write_owned_fields
from ..paths import ShelfPaths
from . import fingerprint
from .covers import _cover_from_frame_safe, poster_from_cover
from .ffmpeg import FFmpegMissing, find_ffmpeg, find_ffprobe, probe
from .sheets import build_sheet

Progress = Callable[[str], None]
FRAME_OWNER = auto_owner("frame")


@dataclass
class MediaResult:
    probed: int = 0
    sheets: int = 0
    posters: int = 0
    frame_covers: int = 0
    failed: int = 0


def _stem(row: sqlite3.Row) -> str:
    return row["code_key"] or f"asset-{row['id']}"


def _sheet_stem(row: sqlite3.Row) -> str:
    stem = _stem(row)
    return f"{stem}-cd{row['part']}" if row["code_key"] and row["part"] else stem


def _siblings(connection, row: sqlite3.Row) -> list[int]:
    if row["code_key"]:
        return [int(r[0]) for r in connection.execute(
            "SELECT id FROM asset WHERE code_key=? AND vanished=0", (row["code_key"],))]
    return [int(row["id"])]


def play_hint_for(container: str, vcodec: str, acodec: str) -> str:
    """可播放性判定；计划 1 Task 12 的 `site.playability` 落地后由它接管。"""
    try:
        from ..site.playability import play_hint
    except ImportError:
        return ""
    return play_hint(container, vcodec, acodec)


def process_assets(connection: sqlite3.Connection, paths: ShelfPaths, *,
                   progress: Progress = lambda message: None,
                   sheet_columns: int = 3, sheet_rows: int = 3, frame_width: int = 480,
                   sheets: bool = True) -> MediaResult:
    """对库里未消失的视频：补探测、补封面（抽帧）、补九宫格（`sheets=False` 跳过，已有的照常登记）、补海报。"""
    paths.ensure()
    result = MediaResult()
    try:
        ffmpeg = find_ffmpeg()
        ffprobe = find_ffprobe()
    except FFmpegMissing as error:
        progress(str(error))
        raise
    rows = connection.execute(
        "SELECT * FROM asset WHERE medium='video' AND vanished=0 ORDER BY code_key, part, id").fetchall()
    total = len(rows)
    for index, row in enumerate(rows, 1):
        video = paths.absolute(row["path"])
        if not video.is_file():
            continue
        label = row["code_key"] or row["name"]
        # 1. 探测
        if row["probed_at"] is None:
            try:
                info = probe(video, ffprobe=ffprobe)
            except ValueError as error:
                result.failed += 1
                progress(f"[{index}/{total}] 探测失败 {row['path']}：{error}")
                connection.execute("UPDATE asset SET probed_at=? WHERE id=?",
                                   (datetime.now().isoformat(timespec="seconds"), row["id"]))
                connection.commit()
                continue
            connection.execute(
                "UPDATE asset SET duration=?,width=?,height=?,vcodec=?,acodec=?,container=?,play_hint=?,"
                "probed_at=? WHERE id=?",
                (info.duration, info.width, info.height, info.vcodec, info.acodec, info.container,
                 play_hint_for(info.container, info.vcodec, info.acodec),
                 datetime.now().isoformat(timespec="seconds"), row["id"]))
            connection.commit()
            result.probed += 1
            row = connection.execute("SELECT * FROM asset WHERE id=?", (row["id"],)).fetchone()
        duration = float(row["duration"] or 0)
        if not row["vcodec"]:
            # 上次探测就失败的文件，抽帧也不会成功。
            continue
        # 2. 没有封面就抽帧
        if not row["cover_file"]:
            destination = paths.covers / f"{_stem(row)}.jpg"
            if _cover_from_frame_safe(ffmpeg, video, destination, duration=duration):
                rel = paths.shelf_relative(destination)
                for asset_id in _siblings(connection, row):
                    write_owned_fields(connection, "asset", asset_id, [FieldWrite("cover_file", rel, FRAME_OWNER)])
                connection.commit()
                result.frame_covers += 1
                progress(f"[{index}/{total}] 抽帧封面 {label}")
                row = connection.execute("SELECT * FROM asset WHERE id=?", (row["id"],)).fetchone()
            else:
                result.failed += 1
                progress(f"[{index}/{total}] 抽帧封面失败 {row['path']}")
        # 3. 九宫格
        sheet = paths.sheets / f"{_sheet_stem(row)}.jpg"
        if sheets and not fingerprint.current(sheet, source=video):
            if build_sheet(ffmpeg, video, sheet, duration=duration, columns=sheet_columns,
                           rows=sheet_rows, frame_width=frame_width):
                fingerprint.remember(sheet, source=video)
                result.sheets += 1
                progress(f"[{index}/{total}] 九宫格 {label}")
            else:
                result.failed += 1
                progress(f"[{index}/{total}] 九宫格失败 {row['path']}")
        if sheet.is_file() and row["sheet_file"] != paths.shelf_relative(sheet):
            connection.execute("UPDATE asset SET sheet_file=? WHERE id=?", (paths.shelf_relative(sheet), row["id"]))
            connection.commit()
        # 4. 海报
        if row["cover_file"]:
            cover = paths.shelf_absolute(row["cover_file"])
            poster = paths.posters / f"{_stem(row)}.jpg"
            if cover.is_file() and not fingerprint.current(poster, source=cover):
                if poster_from_cover(cover, poster):
                    fingerprint.remember(poster, source=cover)
                    result.posters += 1
                else:
                    result.failed += 1
                    progress(f"[{index}/{total}] 海报失败 {row['cover_file']}")
            if poster.is_file() and row["poster_file"] != paths.shelf_relative(poster):
                for asset_id in _siblings(connection, row):
                    connection.execute("UPDATE asset SET poster_file=? WHERE id=?",
                                       (paths.shelf_relative(poster), asset_id))
                connection.commit()
    progress(f"媒体完成：探测 {result.probed}，九宫格 {result.sheets}，海报 {result.posters}，"
             f"抽帧封面 {result.frame_covers}，失败 {result.failed}")
    return result
