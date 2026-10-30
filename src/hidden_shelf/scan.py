"""扫描盘根目录，把视频、附属文件和番号登记进库。

这是摄取入口，不是资料写入：它新增行、刷新 `size`／`mtime`／`last_seen`，番号只补空
（owner `scan:filename`，`require_empty`），用户改过的一律不碰。本次没见到的行标
`vanished=1`，见到的恢复 0；不删行。

遍历用显式栈加 `os.scandir`（peach `scan._walk` 的思路），每进一个目录报一次进度。
跳过资料目录 `HiddenShelf/` 与系统垃圾；`未识别/` 照常遍历，认不出番号的标 `content_type='unrecognized'`。
"""
from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import ShelfConfig
from .field_owners import SCAN_FILENAME, FieldWrite, write_owned_fields
from .paths import SHELF_DIR, ShelfPaths
from .rules.codes import (
    is_amateur_code,
    is_jav_code,
    is_uncensored_release,
    normalise_code_key,
    part_marker,
    release_code_from_filename,
    same_release_code,
)
from .rules.sidecars import ARTWORK, ARTWORK_DIRS, medium_of, sidecar_kind, video_stems
from .studios import is_uncensored_studio

#: 不进入的目录名（大小写不敏感）。`SHELF_DIR` 是我们自己的产物目录。
SKIP_DIRS = frozenset(name.casefold() for name in (
    SHELF_DIR, "@eadir", "@snapshot", "#recycle", "$recycle.bin", "system volume information",
    ".trashes", ".spotlight-v100", ".fseventsd", "lost+found",
))
#: 不登记的文件名。
SKIP_FILES = frozenset(name.casefold() for name in (".ds_store", "thumbs.db", "desktop.ini", "index.html"))
#: 缩略图产物的名字噪声，剥掉才露出主名：`X.mp4_thumbs.jpg`、`X_4x4_thumb.jpg`。
_THUMB_TAIL = re.compile(r"(?:_\d+x\d+_thumbs?|\.[a-z0-9]{2,5}_thumbs?|\.thumb)$", re.I)

Progress = Callable[[str], None]


@dataclass
class ScanResult:
    seen: int = 0
    added: int = 0
    updated: int = 0
    vanished: int = 0
    sidecars: int = 0
    unrecognized: int = 0


def content_type_of(name: str, code: str | None, studio: str | None = None) -> str:
    """按番号形状分类：`censored | amateur | uncensored | fc2 | other | unrecognized`。

    `studio` 是库里已有的厂牌：归位改名后文件名里的发行站名没了（`Catwalk CWPBD-120 …` → `CWPBD-120.mp4`），
    厂牌是登记过的无码片商就仍算无码，类型不随改名回落。
    """
    if not code:
        return "unrecognized"
    key = normalise_code_key(code)
    if key.startswith("FC2"):
        return "fc2"
    if is_uncensored_release(name, key) or is_uncensored_studio(studio):
        return "uncensored"
    if is_amateur_code(key):
        return "amateur"
    if is_jav_code(key):
        return "censored"
    return "other"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _walk(root: Path):
    """自顶向下产出 `(目录, 文件条目列表, 子目录列表)`；跳过 `SKIP_DIRS`。"""
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as scanner:
                entries = list(scanner)
        except OSError:
            continue
        files, dirs = [], []
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.casefold() not in SKIP_DIRS:
                        dirs.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    if entry.name.startswith("._") or entry.name.casefold() in SKIP_FILES:
                        continue
                    files.append(entry)
            except OSError:
                continue
        dirs.sort(key=lambda path: path.name)
        stack.extend(reversed(dirs))
        yield directory, sorted(files, key=lambda entry: entry.name), dirs


def _pair_sidecar(name: str, kind: str, videos: dict[str, int], codes: dict[int, str | None]) -> int | None:
    """附属文件配到同目录哪部视频：同主名 > 去掉图片后缀的主名 > 唯一视频 > 番号同一。"""
    stem = os.path.splitext(name)[0]
    lowered = stem.casefold()
    candidates = [lowered, _THUMB_TAIL.sub("", lowered)]
    head, dash, tail = lowered.rpartition("-")
    if dash and tail in ARTWORK:
        candidates.append(head)
    # 字幕的语言段：`ABC-123.chs.srt`。
    if kind == "subtitle" and "." in lowered:
        candidates.append(lowered.rpartition(".")[0])
    for candidate in candidates:
        if candidate in videos:
            return videos[candidate]
    if len(videos) == 1:
        return next(iter(videos.values()))
    code = release_code_from_filename(name)
    if code:
        matching = sorted({asset_id for asset_id, value in codes.items() if value and same_release_code(code, value)})
        if matching:
            return matching[0]
    return None


def scan(connection: sqlite3.Connection, paths: ShelfPaths, config: ShelfConfig, *,
         progress: Progress = lambda message: None) -> ScanResult:
    """遍历盘根目录并登记。返回计数。"""
    result = ScanResult()
    patterns = config.compiled_patterns()
    now = _now()
    existing = {row["path"]: (int(row["id"]), row["size"], row["mtime"])
                for row in connection.execute("SELECT id,path,size,mtime FROM asset")}
    seen_ids: set[int] = set()
    seen_sidecars: set[str] = set()
    parent_videos: dict[Path, dict[str, int]] = {}

    for directory, files, _dirs in _walk(paths.root):
        rel_dir = paths.relative(directory) if directory != paths.root else ""
        progress(f"扫描 {rel_dir or '/'}")
        names = [entry.name for entry in files]
        stems = video_stems(names)
        artwork_dir = (directory.name.casefold() in ARTWORK_DIRS
                       and bool(parent_videos.get(directory.parent)))
        videos: dict[str, int] = {}
        codes: dict[int, str | None] = {}
        pending_sidecars: list[tuple[str, str]] = []

        for entry in files:
            name = entry.name
            rel = paths.relative(Path(entry.path))
            medium = medium_of(name)
            if medium == "video" and os.path.splitext(name)[0].casefold() in stems:
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                asset_id, added, updated, code = _register_video(
                    connection, rel, name, stat.st_size, stat.st_mtime, now, existing, patterns)
                seen_ids.add(asset_id)
                videos[os.path.splitext(name)[0].casefold()] = asset_id
                codes[asset_id] = code
                result.seen += 1
                result.added += added
                result.updated += updated
                if not code:
                    result.unrecognized += 1
                continue
            kind = sidecar_kind(name, stems, artwork_dir=artwork_dir)
            if kind is not None:
                pending_sidecars.append((rel, kind))

        if artwork_dir and not videos:
            videos = parent_videos.get(directory.parent, {})
            codes = {asset_id: None for asset_id in videos.values()}
        parent_videos[directory] = videos
        for rel, kind in pending_sidecars:
            asset_id = _pair_sidecar(os.path.basename(rel), kind, videos, codes)
            _register_sidecar(connection, rel, kind, asset_id)
            seen_sidecars.add(rel)
            result.sidecars += 1

    # 本次没见到的视频标消失；见到的在 upsert 里已恢复 0。
    missing = [asset_id for path, (asset_id, _size, _mtime) in existing.items() if asset_id not in seen_ids]
    for offset in range(0, len(missing), 900):
        portion = missing[offset:offset + 900]
        connection.execute(
            f"UPDATE asset SET vanished=1 WHERE id IN ({','.join('?' * len(portion))})", portion)
    result.vanished = len(missing)
    # 还没处理、文件又已经不在的附属文件登记直接删掉；处理过的留作历史。
    stale = [row["path"] for row in connection.execute("SELECT path FROM sidecar WHERE status='pending'")
             if row["path"] not in seen_sidecars]
    for offset in range(0, len(stale), 900):
        portion = stale[offset:offset + 900]
        connection.execute(f"DELETE FROM sidecar WHERE path IN ({','.join('?' * len(portion))})", portion)
    connection.commit()
    progress(f"扫描完成：{result.seen} 个视频，{result.sidecars} 个附属文件，{result.vanished} 个消失")
    return result


def _register_video(connection, rel: str, name: str, size: int, mtime: float, now: str,
                    existing: dict, patterns) -> tuple[int, int, int, str | None]:
    """登记一部视频，返回 `(asset_id, 新增数, 更新数, 现在的番号)`。"""
    known = existing.get(rel)
    if known is None:
        cursor = connection.execute(
            "INSERT INTO asset(path,name,medium,size,mtime,first_seen,last_seen,vanished) "
            "VALUES(?,?,?,?,?,?,?,0)", (rel, name, "video", size, mtime, now, now))
        asset_id, added, updated = int(cursor.lastrowid), 1, 0
    else:
        asset_id = known[0]
        changed = (known[1] != size) or (known[2] is None or abs(float(known[2]) - mtime) > 1e-6)
        connection.execute(
            "UPDATE asset SET name=?,size=?,mtime=?,last_seen=?,vanished=0 WHERE id=?",
            (name, size, mtime, now, asset_id))
        if changed:
            # 文件内容变了，上次的探测结果作废，媒体步骤会重新探测。
            connection.execute("UPDATE asset SET probed_at=NULL WHERE id=?", (asset_id,))
        added, updated = 0, int(changed)
    code = release_code_from_filename(name, patterns=patterns)
    if code:
        write_owned_fields(connection, "asset", asset_id,
                           [FieldWrite("code", code, SCAN_FILENAME, require_empty=True)])
    # 派生列按库里现在的番号算：用户改过的番号在上一步没被覆盖，派生列要跟着它。
    current, studio = connection.execute("SELECT code, studio FROM asset WHERE id=?", (asset_id,)).fetchone()
    key = normalise_code_key(current) if current else None
    connection.execute("UPDATE asset SET code_key=?,part=?,content_type=? WHERE id=?",
                       (key, part_marker(name) if current else "", content_type_of(name, current, studio), asset_id))
    return asset_id, added, updated, current


def _register_sidecar(connection, rel: str, kind: str, asset_id: int | None) -> None:
    connection.execute(
        "INSERT INTO sidecar(asset_id,path,kind) VALUES(?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET asset_id=excluded.asset_id, kind=excluded.kind "
        "WHERE sidecar.status='pending'", (asset_id, rel, kind))
