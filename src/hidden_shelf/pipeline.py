"""流水线：scan → import → organize →（再 scan）→ media → build，每步记 `run` 表与日志文件。

`Progress` 是进度回调协议：命令行实现 `ConsoleProgress`，计划 3 的进度网页实现 SSE 版。
任一步抛异常：记录、停止后续步、返回结果里 `ok=False`。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import traceback
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path

from . import db
from .config import ShelfConfig
from .local_import import import_local
from .media import process_assets
from .organize.apply import organize
from .paths import ShelfPaths
from .scan import scan
from .site.build import build_site

STEPS: tuple[str, ...] = ("scan", "import", "organize", "media", "build")
STEP_LABELS = {"scan": "扫描", "import": "导入", "organize": "归位", "media": "媒体", "build": "出站"}


class Progress:
    """进度回调协议。默认实现什么都不做；子类按需覆盖。"""

    def step(self, name: str, total: int | None = None) -> None:
        pass

    def advance(self, n: int = 1, message: str = "") -> None:
        pass

    def log(self, level: str, message: str) -> None:
        pass

    def done(self, stats: dict) -> None:
        pass


class ConsoleProgress(Progress):
    """打印到终端：`[扫描] 信息`。"""

    def __init__(self, stream=None, verbose: bool = False):
        self.stream = stream or sys.stdout
        self.verbose = verbose
        self.current = ""

    def step(self, name: str, total: int | None = None) -> None:
        self.current = STEP_LABELS.get(name, name)
        print(f"== {self.current} ==", file=self.stream, flush=True)

    def advance(self, n: int = 1, message: str = "") -> None:
        if message:
            print(f"[{self.current}] {message}", file=self.stream, flush=True)

    def log(self, level: str, message: str) -> None:
        if level == "debug" and not self.verbose:
            return
        prefix = {"error": "✗ ", "warning": "! "}.get(level, "")
        print(f"[{self.current or '流水线'}] {prefix}{message}", file=self.stream, flush=True)

    def done(self, stats: dict) -> None:
        print(f"[{self.current}] 完成：{json.dumps(stats, ensure_ascii=False)}", file=self.stream, flush=True)


@dataclass
class RunResult:
    ok: bool = True
    steps: dict[str, dict] = field(default_factory=dict)
    error: str = ""
    failed_step: str = ""
    log_path: Path | None = None
    index_html: Path | None = None


def _stats(value) -> dict:
    if is_dataclass(value):
        data = asdict(value)
        return {key: (str(item) if isinstance(item, Path) else item) for key, item in data.items()}
    return dict(value or {})


def run(root: Path, *, config: ShelfConfig | None = None, steps: Sequence[str] = STEPS,
        progress: Progress | None = None) -> RunResult:
    """跑指定步骤。`organize` 之后会自动再 `scan` 一次（路径变了）。"""
    progress = progress or Progress()
    root = Path(root)
    paths = ShelfPaths(root)
    paths.ensure()
    config = config or ShelfConfig.load(paths)
    result = RunResult()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    result.log_path = paths.logs / f"run-{stamp}.log"
    unknown = [name for name in steps if name not in STEPS]
    if unknown:
        raise ValueError(f"不认识的步骤：{unknown}")

    connection = db.connect(paths)
    try:
        with result.log_path.open("a", encoding="utf-8") as handle:
            def write(line: str) -> None:
                handle.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")
                handle.flush()

            def emit(message: str) -> None:
                write(message)
                progress.advance(1, message)

            write(f"开始：{root}，步骤 {list(steps)}")
            for name in steps:
                progress.step(name)
                write(f"== {name} ==")
                run_id = _run_started(connection, name)
                try:
                    stats = _execute(name, connection, paths, config, emit)
                except Exception as error:  # noqa: BLE001 - 任何一步失败都要记录并停下
                    detail = f"{type(error).__name__}: {error}"
                    write(f"失败：{detail}\n{traceback.format_exc()}")
                    _run_finished(connection, run_id, "failed", {"error": detail})
                    progress.log("error", f"{STEP_LABELS.get(name, name)}失败：{detail}")
                    result.ok = False
                    result.error = detail
                    result.failed_step = name
                    break
                result.steps[name] = stats
                _run_finished(connection, run_id, "ok", stats)
                write(f"完成：{json.dumps(stats, ensure_ascii=False)}")
                progress.done(stats)
            if result.ok and "build" in steps:
                result.index_html = paths.index_html
    finally:
        connection.close()
    return result


def _execute(name: str, connection: sqlite3.Connection, paths: ShelfPaths, config: ShelfConfig, emit) -> dict:
    if name == "scan":
        return _stats(scan(connection, paths, config, progress=emit))
    if name == "import":
        return _stats(import_local(connection, paths, progress=emit))
    if name == "organize":
        stats = _stats(organize(connection, paths, config, progress=emit))
        # 路径变了，再扫一遍让库与盘一致（也把搬去 未识别/ 的附属文件登记好）。
        rescan = scan(connection, paths, config, progress=emit)
        stats["rescan"] = _stats(rescan)
        return stats
    if name == "media":
        return _stats(process_assets(connection, paths, progress=emit))
    if name == "build":
        return _stats(build_site(connection, paths, config, progress=emit))
    raise ValueError(name)


def _run_started(connection: sqlite3.Connection, step: str) -> int:
    cursor = connection.execute(
        "INSERT INTO run(started,step,status) VALUES(?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), step, "running"))
    connection.commit()
    return int(cursor.lastrowid)


def _run_finished(connection: sqlite3.Connection, run_id: int, status: str, stats: dict) -> None:
    connection.execute(
        "UPDATE run SET finished=?,status=?,stats=? WHERE id=?",
        (datetime.now().isoformat(timespec="seconds"), status, json.dumps(stats, ensure_ascii=False), run_id))
    connection.commit()
