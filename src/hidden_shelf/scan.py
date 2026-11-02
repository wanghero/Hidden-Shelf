"""扫描盘根目录，把视频、附属文件和番号登记进库。

这是摄取入口，不是资料写入：它新增行、刷新 `size`／`mtime`／`last_seen`，番号只补空
（owner `scan:filename`，`require_empty`），用户改过的一律不碰。本次没见到的行标
`vanished=1`，见到的恢复 0；不删行。

遍历用显式栈加 `os.scandir`（peach `scan._walk` 的思路），每进一个目录报一次进度。
跳过资料目录 `HiddenShelf/` 与系统垃圾；`未识别/` 照常遍历，认不出番号的标 `content_type='unrecognized'`。

番号优先从文件名认（`scan:filename`）；文件名认不出时退一步用所在目录名（`scan:dirname`，
见 `dir_fallback_code`）——下载来的片常把番号只写在目录上，文件名却是 `_n0926.avi`、
`net_n0972.avi` 这种前面黏了字的写法。目录名猜出来的番号**每次扫描重算**：规则改了或目录
变了就跟着改，猜错的连同顺着它刮来的资料一起撤（`revoke_dirname_guess`）。文件名认出的
与用户改过的照旧只补空、不重算。
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
from .field_owners import (
    LOCAL_AUTO_OWNERS,
    SCAN_DIRNAME,
    SCAN_FILENAME,
    FieldWrite,
    clear_owned_fields,
    is_protected,
    owner_of,
    parse_owners,
    write_owned_fields,
)
from .paths import SHELF_DIR, ShelfPaths, nfc
from .rules.codes import (
    is_amateur_code,
    is_code_range,
    is_jav_code,
    is_uncensored_release,
    normalise_code_key,
    part_marker,
    release_code_from_filename,
    release_code_from_text,
    same_release_code,
    tokyo_hot_code,
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


def dir_fallback_code(dir_name: str, video_names: list[str], *, patterns=()) -> str:
    """目录名里的番号，用作文件名认不出时的退路；用不上回空串。

    下载来的片常把番号只写在目录上（`Tokyo-Hot n0926 東熱強制プレイに半泣き/_n0926.avi`），
    文件名前面黏着 `_`、`net_`、`com_` 这类字头，番号就不在它该在的位置上，整部片因此落进
    `未识别/`。目录名本身是认得出的，这里就用它。

    三道闸，任一不过整条退路作废——宁可继续当未识别，也不给文件安错番号：

    1. **目录名是番号区间**（`N1100-N1199`，见 `is_code_range`）：那是收纳文件夹的名字，
       区间头上的编号不是这里任何一部片的番号。
    2. **有相反证据**：同目录另有视频的文件名认出了别的番号，说明这个目录装的不止一部片，
       目录名代表不了谁。认出的番号与目录名一致（`n0867.avi` 和 `com_n0867.avi` 同在
       `Tokyo-Hot n0867-AVI/`）不算打架。
    3. **认不出番号的视频多于一个**：只有当它们各带一个不重复的分卷标记（`_n0500-cd1.avi`
       与 `-cd2.avi`）才算同一部片的多碟；否则是一堆各不相干的片凑在一个目录里
       （`N1100-N1199/1101.mp4 … 1199.mp4`、广告垃圾视频），谁都不能认领目录名。

    v1.4.14 只有第 2 道闸，真实盘上把 `N1100-N1199/` 里 88 个纯数字文件名的片全盖成了
    `N1100`：它们的文件名一个番号都认不出，在「相反证据」这条规则眼里就是没有反对意见。

    用户自定义正则只对文件名生效，目录名走内置规则。
    """
    if is_code_range(dir_name):
        return ""
    wanted = release_code_from_text(dir_name)
    if not wanted:
        return ""
    unknown: list[str] = []
    for name in video_names:
        found = release_code_from_filename(name, patterns=patterns)
        if not found:
            unknown.append(name)
        elif not same_release_code(found, wanted):
            return ""
    if len(unknown) > 1:
        markers = [part_marker(name) for name in unknown]
        if not all(markers) or len(set(markers)) != len(markers):
            return ""
    return wanted


#: 跟着番号来的资料字段：番号撤了它们也不该留在这一行上。`code_key`、`part`、`content_type`
#: 由 `_register_video` 末尾按新番号重算，不进这张单子。
GUESSED_FIELDS = ("title", "original_title", "studio", "series", "release_date", "plot",
                  "cover_file", "poster_file", "sheet_file")


def revoke_dirname_guess(connection: sqlite3.Connection, asset_id: int, old_code: str) -> list[str]:
    """撤掉一个猜错的目录名番号，以及顺着它写进来的资料；返回清掉的字段名（含 `code`）。

    撤两类：联网刮削写的字段（`auto:<来源>`；`field_owners.LOCAL_AUTO_OWNERS` 里那几个
    是按文件来的，本地 NFO、本地旧封面、抽帧兜底，跟番号对不对无关，不碰），以及图片列里
    文件名就带着这个错番号的那几项——`covers/N1100.jpg` 是别人的封面，哪怕归属写着抽帧
    兜底也不能留着。`user:*`、`review:*` 由 `clear_owned_fields` 挡住。

    `scraped_at` 一并清掉：那个时间戳记的是「这个番号问过网了」，番号没了它就没有意义，
    留着还会让这一行在 7 天内免于复问（`scrape.apply.should_scrape`）。

    `code` 连归属一起撤，所以调用方紧接着写新番号时不会被 `require_empty` 挡住——这正是
    「猜的值每次重算」要的效果：撤掉旧的猜测，再按这回的规则写。
    """
    row = connection.execute(
        f"SELECT field_owners,{','.join(GUESSED_FIELDS)} FROM asset WHERE id=?", (int(asset_id),)).fetchone()
    if row is None:
        return []
    owners = parse_owners(row["field_owners"])
    key = (normalise_code_key(old_code) or old_code).casefold()
    doomed = []
    for field in GUESSED_FIELDS:
        current = owners.get(field, "")
        scraped = current.startswith("auto:") and current not in LOCAL_AUTO_OWNERS
        tagged = field.endswith("_file") and key and key in str(row[field] or "").casefold()
        if scraped or tagged:
            doomed.append(field)
    cleared = clear_owned_fields(connection, "asset", asset_id, ["code", *doomed])
    connection.execute("UPDATE asset SET scraped_at=NULL,scrape_note=NULL WHERE id=?", (int(asset_id),))
    marks = ",".join("?" * len(LOCAL_AUTO_OWNERS))
    connection.execute(
        f"DELETE FROM asset_entity WHERE asset_id=? AND source LIKE 'auto:%' AND source NOT IN ({marks})",
        (int(asset_id), *sorted(LOCAL_AUTO_OWNERS)))
    return cleared


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
        # 名字一进来就归一成 NFC：番号识别、分卷与附属文件配对、入库全用同一种写法（见 `paths.nfc`）。
        names = [nfc(entry.name) for entry in files]
        stems = video_stems(names)
        artwork_dir = (nfc(directory.name).casefold() in ARTWORK_DIRS
                       and bool(parent_videos.get(directory.parent)))
        videos: dict[str, int] = {}
        codes: dict[int, str | None] = {}
        pending_sidecars: list[tuple[str, str]] = []
        video_names = [nfc(entry.name) for entry in files
                       if medium_of(entry.name) == "video"
                       and os.path.splitext(entry.name)[0].casefold() in stems]
        # 盘根不作退路：根目录名是盘名，它认出来的番号会盖到散在根上的每部片。
        fallback = ("" if directory == paths.root
                    else dir_fallback_code(nfc(directory.name), video_names, patterns=patterns))

        for entry in files:
            name = nfc(entry.name)
            rel = paths.relative(Path(entry.path))
            medium = medium_of(name)
            if medium == "video" and os.path.splitext(name)[0].casefold() in stems:
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                asset_id, added, updated, code = _register_video(
                    connection, rel, name, stat.st_size, stat.st_mtime, now, existing, patterns,
                    fallback=fallback)
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
                    existing: dict, patterns, *, fallback: str = "") -> tuple[int, int, int, str | None]:
    """登记一部视频，返回 `(asset_id, 新增数, 更新数, 现在的番号)`。

    `fallback` 是所在目录名认出的番号（`dir_fallback_code`），只在文件名认不出时用。
    """
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
    owner = SCAN_FILENAME
    if not code and fallback:
        code, owner = fallback, SCAN_DIRNAME
    # 上回靠目录名猜的番号每次重算：规则改了（或目录改了）就该跟着改，这是它和
    # `scan:filename` 的区别——猜的值不配享受 `require_empty` 那种「写进去就算数」。
    guessed = connection.execute(
        "SELECT code, field_owners FROM asset WHERE id=?", (asset_id,)).fetchone()
    previous = str(guessed["code"] or "")
    if (previous and owner_of(guessed["field_owners"], "code") == SCAN_DIRNAME
            and str(code or "") != previous):
        revoke_dirname_guess(connection, asset_id, previous)
    if code:
        write_owned_fields(connection, "asset", asset_id,
                           [FieldWrite("code", code, owner, require_empty=True)])
    # 派生列按库里现在的番号算：用户改过的番号在上一步没被覆盖，派生列要跟着它。
    current, studio, owners = connection.execute(
        "SELECT code, studio, field_owners FROM asset WHERE id=?", (asset_id,)).fetchone()
    # 规范写法变过（v1.4.11 东京热编号由小写改大写）：自动写入的番号跟着改，用户改过的不碰。
    canonical = tokyo_hot_code(current) if current else ""
    if canonical and canonical != current and not is_protected(owner_of(owners, "code")):
        connection.execute("UPDATE asset SET code=? WHERE id=?", (canonical, asset_id))
        current = canonical
    key = normalise_code_key(current) if current else None
    connection.execute("UPDATE asset SET code_key=?,part=?,content_type=? WHERE id=?",
                       (key, part_marker(name) if current else "", content_type_of(name, current, studio), asset_id))
    return asset_id, added, updated, current


def _register_sidecar(connection, rel: str, kind: str, asset_id: int | None) -> None:
    connection.execute(
        "INSERT INTO sidecar(asset_id,path,kind) VALUES(?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET asset_id=excluded.asset_id, kind=excluded.kind "
        "WHERE sidecar.status='pending'", (asset_id, rel, kind))
