"""归位执行与回滚：备份库 → 动文件 → 改库，改库失败把文件改回去。

思路取自 peach `src/peach/organize.py` 的 `_rename`、`_move_one`、`apply_plan`、`rollback_batch`
（commit 4d5266d327a5971773409b44316e3926bd37c6ba，AGPL-3.0-or-later），按本项目重写：
单盘根、POSIX 相对路径、逐行 JSONL 批次日志、附属文件随视频搬去 `.shelf/legacy/<番号>/`
或跟着未识别视频进 `未识别/`。

只做同一卷内 `os.rename`，绝不删原始文件，绝不覆盖已存在的目标。
"""
from __future__ import annotations

import json
import os
import posixpath
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import ShelfConfig
from ..paths import UNRECOGNIZED_DIR, ShelfPaths
from .plan import SKIP_TARGET_EXISTS, Plan, build_plan

Progress = Callable[[str], None]
#: 只保留最近这么多份库备份。
BACKUP_KEEP = 5
#: 预演时终端最多打这么多条「现路径 → 目标」，其余只进清单文件（整块盘几万条会把终端刷死）。
PREVIEW_CONSOLE_LIMIT = 200


class OrganizeError(RuntimeError):
    """改库失败这类必须把文件改回去的情况。"""


@dataclass
class ApplyResult:
    moved: int = 0
    skipped: int = 0
    failed: int = 0
    batch_log: Path | None = None
    removed_dirs: int = 0


def backup_database(paths: ShelfPaths, connection: sqlite3.Connection | None = None) -> Path:
    """用 SQLite 在线备份把库复制到 `backups/shelf-<时间>.db`，只保留最近 `BACKUP_KEEP` 份。"""
    paths.backups.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination = paths.backups / f"shelf-{stamp}.db"
    counter = 1
    while destination.exists():
        destination = paths.backups / f"shelf-{stamp}-{counter}.db"
        counter += 1
    source = connection if connection is not None else sqlite3.connect(paths.db)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        if connection is None:
            source.close()
    backups = sorted(paths.backups.glob("shelf-*.db"))
    for old in backups[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)
    return destination


def _update_row(connection: sqlite3.Connection, asset_id: int, old_path: str, new_path: str) -> int:
    return connection.execute(
        "UPDATE asset SET path=?,name=? WHERE id=? AND path=?",
        (new_path, posixpath.basename(new_path), int(asset_id), old_path)).rowcount


def _rename(paths: ShelfPaths, old_rel: str, new_rel: str) -> None:
    source = paths.absolute(old_rel)
    target = paths.absolute(new_rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(source, target)


def _free_name(directory: Path, name: str) -> Path:
    """`directory/name` 被占着就在主名后加 `-1`、`-2`。"""
    candidate = directory / name
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    counter = 1
    while candidate.exists():
        candidate = directory / (f"{stem}-{counter}.{ext}" if ext else f"{stem}-{counter}")
        counter += 1
    return candidate


def _move_sidecars(connection, paths, asset_id: int, video_target: str, log) -> None:
    """该视频的附属文件：有番号的搬去 `legacy/<番号>/`，没番号的跟着视频进新目录。"""
    asset = connection.execute("SELECT code_key FROM asset WHERE id=?", (asset_id,)).fetchone()
    code_key = asset["code_key"] if asset else None
    sidecars = connection.execute(
        "SELECT id,path,kind FROM sidecar WHERE asset_id=? AND status<>'moved' ORDER BY path", (asset_id,)).fetchall()
    for sidecar in sidecars:
        source = paths.absolute(sidecar["path"])
        if not source.is_file():
            continue
        if code_key:
            directory = paths.legacy / code_key
        else:
            directory = paths.absolute(video_target).parent
        directory.mkdir(parents=True, exist_ok=True)
        destination = _free_name(directory, source.name)
        new_rel = paths.relative(destination)
        if new_rel == sidecar["path"]:
            continue
        try:
            os.rename(source, destination)
        except OSError as error:
            log({"kind": "sidecar", "sidecar_id": sidecar["id"], "from": sidecar["path"], "to": new_rel,
                 "ok": False, "error": str(error)})
            continue
        connection.execute("UPDATE sidecar SET status='moved', moved_to=? WHERE id=?", (new_rel, sidecar["id"]))
        log({"kind": "sidecar", "sidecar_id": sidecar["id"], "from": sidecar["path"], "to": new_rel, "ok": True})


def apply_plan(connection: sqlite3.Connection, paths: ShelfPaths, plan: Plan, *,
               progress: Progress = lambda message: None) -> ApplyResult:
    """执行计划：先备份库，再逐行动文件、改库、记日志。失败的行单独报，不影响其余行。"""
    paths.ensure()
    result = ApplyResult(skipped=sum(1 for row in plan.rows if row.action == "skip"))
    moves = plan.moves
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = paths.logs / f"organize-{stamp}.jsonl"
    counter = 1
    while log_path.exists():
        log_path = paths.logs / f"organize-{stamp}-{counter}.jsonl"
        counter += 1
    result.batch_log = log_path
    if not moves:
        log_path.touch()
        return result
    backup = backup_database(paths, connection)
    progress(f"库已备份到 {paths.relative(backup)}")

    with log_path.open("a", encoding="utf-8") as handle:
        def log(entry: dict) -> None:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()

        for index, row in enumerate(moves, 1):
            outcome = _move_one(connection, paths, row.asset_id, row.current_path, row.target_path)
            if outcome == "ok":
                result.moved += 1
                log({"kind": "asset", "asset_id": row.asset_id, "from": row.current_path,
                     "to": row.target_path, "ok": True})
                _move_sidecars(connection, paths, row.asset_id, row.target_path, log)
                connection.commit()
                progress(f"[{index}/{len(moves)}] {row.current_path} → {row.target_path}")
            elif outcome == SKIP_TARGET_EXISTS:
                result.skipped += 1
                log({"kind": "asset", "asset_id": row.asset_id, "from": row.current_path,
                     "to": row.target_path, "ok": False, "error": outcome})
                progress(f"[{index}/{len(moves)}] 跳过 {row.current_path}：{outcome}")
            else:
                result.failed += 1
                log({"kind": "asset", "asset_id": row.asset_id, "from": row.current_path,
                     "to": row.target_path, "ok": False, "error": outcome})
                progress(f"[{index}/{len(moves)}] 失败 {row.current_path}：{outcome}")
    return result


def _move_one(connection, paths, asset_id: int, old_path: str, new_path: str) -> str:
    """动一个文件并同步库；返回 `ok` 或跳过／失败原因。

    库写失败就把文件改回去：反过来留下的是一条指向不存在路径的行，而它看起来
    和正常的行没有任何区别。
    """
    source = paths.absolute(old_path)
    target = paths.absolute(new_path)
    if not source.exists():
        return "源文件不存在"
    if target.exists():
        try:
            same = os.path.samefile(source, target)
        except OSError:
            same = False
        if not same:
            return SKIP_TARGET_EXISTS
    try:
        _rename(paths, old_path, new_path)
    except OSError as error:
        return f"改名失败：{error.strerror or error}"
    try:
        if not _update_row(connection, asset_id, old_path, new_path):
            raise OrganizeError("数据库里这一行已经变了")
        connection.commit()
    except Exception as error:  # noqa: BLE001 - 任何改库失败都要把文件改回去
        connection.rollback()
        try:
            _rename(paths, new_path, old_path)
            return f"数据库写入失败，已改回原名：{error}"
        except OSError:
            return f"数据库写入失败且改不回原名，需要人工处理：{error}"
    return "ok"


def remove_empty_dirs(root: Path, *, protect: set[Path] | None = None) -> int:
    """自底向上删空目录。只删空的；`.shelf`、`未识别`、root 本身与 `protect` 不删。

    只有 `.DS_Store` 的目录视为空：先删 `.DS_Store` 再删目录。
    """
    protected = {root.resolve(), (root / ".shelf").resolve(), (root / UNRECOGNIZED_DIR).resolve()}
    protected |= {path.resolve() for path in (protect or set())}
    removed = 0
    for current, dirs, files in os.walk(root, topdown=False):
        directory = Path(current)
        resolved = directory.resolve()
        if resolved in protected or resolved.is_relative_to((root / ".shelf").resolve()):
            continue
        if files and all(name == ".DS_Store" for name in files):
            for name in files:
                try:
                    (directory / name).unlink()
                except OSError:
                    pass
        try:
            if not any(os.scandir(directory)):
                directory.rmdir()
                removed += 1
        except OSError:
            continue
    return removed


def rollback_batch(connection: sqlite3.Connection, paths: ShelfPaths, batch_log: Path) -> int:
    """按日志倒序把一个批次改回去并同步库；返回改回的条数。已被人手工改过的跳过。"""
    entries = [json.loads(line) for line in Path(batch_log).read_text(encoding="utf-8").splitlines() if line.strip()]
    restored = 0
    for entry in reversed(entries):
        if not entry.get("ok"):
            continue
        source = paths.absolute(entry["to"])
        target = paths.absolute(entry["from"])
        if not source.exists() or target.exists():
            continue
        try:
            _rename(paths, entry["to"], entry["from"])
        except OSError:
            continue
        if entry.get("kind") == "sidecar":
            connection.execute("UPDATE sidecar SET status='pending', moved_to=NULL WHERE id=?",
                               (entry["sidecar_id"],))
        else:
            _update_row(connection, int(entry["asset_id"]), entry["to"], entry["from"])
        connection.commit()
        restored += 1
    return restored


def organize(connection: sqlite3.Connection, paths: ShelfPaths, config: ShelfConfig, *,
             progress: Progress = lambda message: None) -> ApplyResult:
    """生成计划、执行、清空目录，并在 `organize_batch` 记一行。"""
    started = datetime.now().isoformat(timespec="seconds")
    plan = build_plan(connection, paths, config)
    progress(f"归位计划：{plan.counts['move']} 个要搬，{plan.counts['unchanged']} 个已就位，"
             f"{plan.counts['skip']} 个跳过")
    for reason, count in sorted(plan.reasons.items()):
        progress(f"  跳过原因 {reason}：{count}")
    result = apply_plan(connection, paths, plan, progress=progress)
    result.removed_dirs = remove_empty_dirs(paths.root)
    connection.execute(
        "INSERT INTO organize_batch(started,finished,log_path,status,moved,skipped) VALUES(?,?,?,?,?,?)",
        (started, datetime.now().isoformat(timespec="seconds"),
         paths.relative(result.batch_log) if result.batch_log else None,
         "ok" if not result.failed else "partial", result.moved, result.skipped))
    connection.commit()
    progress(f"归位完成：搬了 {result.moved} 个，跳过 {result.skipped} 个，失败 {result.failed} 个，"
             f"清掉空目录 {result.removed_dirs} 个")
    return result


def _write_plan_file(paths: ShelfPaths, plan: Plan) -> Path:
    """把整份计划写进 `logs/plan-<时间>.txt`：首行是汇总，之后每行 `MOVE\\t现路径\\t目标` 或 `SKIP\\t现路径\\t原因`。"""
    paths.logs.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    plan_path = paths.logs / f"plan-{stamp}.txt"
    counter = 1
    while plan_path.exists():
        plan_path = paths.logs / f"plan-{stamp}-{counter}.txt"
        counter += 1
    counts = plan.counts
    lines = [f"# Hidden Shelf 归位预演 {datetime.now().isoformat(timespec='seconds')}  "
             f"要搬 {counts['move']} / 已就位 {counts['unchanged']} / 跳过 {counts['skip']}"]
    for row in plan.rows:
        if row.action == "move":
            lines.append(f"MOVE\t{row.current_path}\t{row.target_path}")
        else:
            lines.append(f"SKIP\t{row.current_path}\t{row.reason}")
    plan_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return plan_path


def preview_organize(connection: sqlite3.Connection, paths: ShelfPaths, config: ShelfConfig, *,
                     progress: Progress = lambda message: None) -> dict:
    """归位预演：算出和 `organize` 一样的计划，只打印、只写清单文件，盘上一个文件不动。

    不备份库、不改名、不清空目录、不记 `organize_batch`。返回的字典就是流水线里这一步的 stats。
    """
    plan = build_plan(connection, paths, config)
    counts = plan.counts
    progress(f"预演：{counts['move']} 个要搬，{counts['unchanged']} 个已就位，{counts['skip']} 个跳过")
    for reason, count in sorted(plan.reasons.items()):
        progress(f"  跳过原因 {reason}：{count}")
    plan_path = _write_plan_file(paths, plan)
    shown = paths.relative(plan_path)
    moves = plan.moves
    for index, row in enumerate(moves[:PREVIEW_CONSOLE_LIMIT], 1):
        progress(f"[{index}/{len(moves)}] {row.current_path} → {row.target_path}")
    if len(moves) > PREVIEW_CONSOLE_LIMIT:
        progress(f"……还有 {len(moves) - PREVIEW_CONSOLE_LIMIT} 条，完整清单见 {shown}")
    progress(f"预演完成：没有动任何文件，清单：{shown}")
    return {
        "dry_run": True,
        "total": counts["total"],
        "move": counts["move"],
        "unchanged": counts["unchanged"],
        "skip": counts["skip"],
        "reasons": dict(sorted(plan.reasons.items())),
        "plan_file": paths.shelf_relative(plan_path),
    }
