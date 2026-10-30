"""流水线：scan → import → scrape → organize →（再 scan）→ media → build，每步记 `run` 表与日志文件。

`Progress` 是进度回调协议：命令行实现 `ConsoleProgress`，计划 3 的进度网页实现 SSE 版。
任一步抛异常：记录、停止后续步、返回结果里 `ok=False`。唯一的例外是 `scrape`：它失败只记本步 `failed`，
后续步照跑——联网不通不该拦住本地整理。`config.scrape` 为假或 `offline=True` 时 `scrape` 记 `skipped`。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path

from . import db
from .config import ShelfConfig
from .local_import import import_local
from .media import process_assets
from .organize.apply import organize, preview_organize
from .paths import ShelfPaths
from .scan import scan
from .site.build import build_site

STEPS: tuple[str, ...] = ("scan", "import", "scrape", "organize", "media", "build")
STEP_LABELS = {"scan": "扫描", "import": "导入", "scrape": "刮削", "organize": "归位", "media": "媒体", "build": "出站"}
#: 失败不中断后续步的那一步。
_SOFT_STEPS = frozenset({"scrape"})


@dataclass
class ScrapeOptions:
    """这一趟刮削的命令行开关。"""

    offline: bool = False
    force: bool = False
    only_sources: tuple[str, ...] | None = None
    routes: dict[str, list[str]] | None = None


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

    def failed(self, name: str, error: str) -> None:
        """一步失败（`scrape` 软失败与其它硬失败都走这里）。"""

    def skipped(self, name: str, reason: str) -> None:
        """一步被跳过（`--offline`、`config.scrape=false`）。"""


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

    def failed(self, name: str, error: str) -> None:
        label = STEP_LABELS.get(name, name)
        print(f"[{label}] ✗ {label}失败：{error}", file=self.stream, flush=True)

    def skipped(self, name: str, reason: str) -> None:
        label = STEP_LABELS.get(name, name)
        print(f"[{label}] 跳过{label}（{reason}）", file=self.stream, flush=True)


@dataclass
class RunResult:
    ok: bool = True
    steps: dict[str, dict] = field(default_factory=dict)
    error: str = ""
    failed_step: str = ""
    log_path: Path | None = None
    index_html: Path | None = None
    #: 调用方经 `cancel` 回调在步与步之间停下了；`ok` 仍是已跑步骤的结果。
    cancelled: bool = False
    #: 预演：`organize` 只列清单，`media`、`build` 跳过，`.shelf/` 之外一个字节没动。
    dry_run: bool = False


def _skip_reason(name: str, config: ShelfConfig, scrape_options: ScrapeOptions, dry_run: bool) -> str | None:
    """这一步该不该跳过；返回原因字符串，不跳过返回 `None`。"""
    if name == "scrape":
        if scrape_options.offline:
            return "--offline"
        if not config.scrape:
            return "config.scrape=false"
    if dry_run and name in ("media", "build"):
        return "--dry-run"
    return None


def _stats(value) -> dict:
    if is_dataclass(value):
        data = asdict(value)
        return {key: (str(item) if isinstance(item, Path) else item) for key, item in data.items()}
    return dict(value or {})


def run(root: Path, *, config: ShelfConfig | None = None, steps: Sequence[str] = STEPS,
        progress: Progress | None = None, scrape_options: ScrapeOptions | None = None,
        cancel: Callable[[], bool] | None = None, dry_run: bool = False) -> RunResult:
    """跑指定步骤。`organize` 之后会自动再 `scan` 一次（路径变了）。

    `cancel()` 只在每步开始前检查：为真就不再开后续步，`result.cancelled = True`。步内不打断——归位是事务、
    刮削每个番号后提交，当前步跑完才停，没有半成品。

    `dry_run=True` 是预演：前三步照常（它们只写 `.shelf/`，是算出计划的前提），`organize` 改成
    `preview_organize` 只列清单且不再 rescan，`media`、`build` 记 `skipped`；盘上 `.shelf/` 之外不动。
    """
    progress = progress or Progress()
    root = Path(root)
    paths = ShelfPaths(root)
    paths.ensure()
    config = config or ShelfConfig.load(paths)
    scrape_options = scrape_options or ScrapeOptions()
    result = RunResult(dry_run=dry_run)
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

            write(f"开始：{root}，步骤 {list(steps)}" + ("（预演）" if dry_run else ""))
            for name in steps:
                if cancel is not None and cancel():
                    result.cancelled = True
                    write(f"已取消：在 {STEP_LABELS.get(name, name)} 之前停下")
                    progress.log("warning", f"已取消：在{STEP_LABELS.get(name, name)}之前停下")
                    break
                progress.step(name)
                write(f"== {name} ==")
                reason = _skip_reason(name, config, scrape_options, dry_run)
                if reason is not None:
                    stats = {"skipped": True, "reason": reason}
                    run_id = _run_started(connection, name)
                    _run_finished(connection, run_id, "skipped", stats)
                    result.steps[name] = stats
                    write(f"跳过：{reason}")
                    progress.skipped(name, reason)
                    continue
                run_id = _run_started(connection, name)
                try:
                    stats = _execute(name, connection, paths, config, emit, scrape_options, dry_run)
                except Exception as error:  # noqa: BLE001 - 任何一步失败都要记录
                    detail = f"{type(error).__name__}: {error}"
                    write(f"失败：{detail}\n{traceback.format_exc()}")
                    _run_finished(connection, run_id, "failed", {"error": detail})
                    progress.failed(name, detail)
                    if name in _SOFT_STEPS:
                        result.steps[name] = {"error": detail}
                        continue
                    result.ok = False
                    result.error = detail
                    result.failed_step = name
                    break
                result.steps[name] = stats
                _run_finished(connection, run_id, "ok", stats)
                write(f"完成：{json.dumps(stats, ensure_ascii=False)}")
                progress.done(stats)
            if result.ok and "build" in result.steps and not result.steps["build"].get("skipped"):
                result.index_html = paths.index_html
    finally:
        connection.close()
    return result


def _execute(name: str, connection: sqlite3.Connection, paths: ShelfPaths, config: ShelfConfig, emit,
             scrape_options: ScrapeOptions, dry_run: bool = False) -> dict:
    if name == "scan":
        return _stats(scan(connection, paths, config, progress=emit))
    if name == "import":
        return _stats(import_local(connection, paths, progress=emit))
    if name == "scrape":
        from .netconfig import GlobalConfig
        from .scrape.run import scrape_assets
        global_config = GlobalConfig.load()
        if scrape_options.routes:
            global_config.routes = dict(scrape_options.routes)
        return _stats(scrape_assets(connection, paths, config, global_config=global_config, progress=emit,
                                    force=scrape_options.force, only_sources=scrape_options.only_sources))
    if name == "organize":
        if dry_run:
            # 预演只列清单，路径没变，不用再扫。
            return preview_organize(connection, paths, config, progress=emit)
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
