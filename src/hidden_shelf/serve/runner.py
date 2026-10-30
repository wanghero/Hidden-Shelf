"""运行管理器：一次只跑一条流水线，在守护线程里跑，事件写进 `RunLog`，状态由事件归约。

进程内一把锁保证单运行；不做跨进程锁（命令行与网页同时跑同一盘不在保护范围）。取消只置标志，
`pipeline.run` 在步与步之间检查。最近用过的盘根目录存 `<home>/recent.json`（与全局配置同目录），只存路径。
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .. import pipeline
from ..config import ShelfConfig
from ..fsutil import atomic_write_text
from ..netconfig import home as config_home
from ..paths import (RootNotWritable, ShelfLayoutConflict, ShelfPaths, check_layout, check_writable,
                     migrate_legacy_dir)
from .events import Event, EventProgress, RunLog

RECENT_LIMIT = 10
STATUS_WAITING, STATUS_RUNNING, STATUS_DONE, STATUS_FAILED, STATUS_SKIPPED = "waiting", "running", "done", "failed", "skipped"


class RunBusy(RuntimeError):
    """已有一个运行在进行中。"""


@dataclass(frozen=True)
class RunOptions:
    root: Path
    move_unrecognized: bool = True
    offline: bool = False
    force_scrape: bool = False
    #: 只预演：归位只列清单，媒体与出站跳过，`HiddenShelf/` 之外不动。
    dry_run: bool = False
    #: 封面与九宫格复制到视频所在目录；None 表示按盘上配置，给了就写进盘上配置（它是盘的设置，不是一次性的）。
    images_in_work_dir: bool | None = None
    steps: tuple[str, ...] = pipeline.STEPS

    @classmethod
    def from_payload(cls, data: Any) -> "RunOptions":
        """网页发来的 JSON → 选项。目录不存在、步名未知、布尔字段不是 JSON 布尔都抛 `ValueError`（给用户看的中文）。"""
        if not isinstance(data, dict):
            raise ValueError("请求体要是一个 JSON 对象")
        raw_root = str(data.get("root") or "").strip()
        if not raw_root:
            raise ValueError("请填写盘根目录")
        root = Path(raw_root).expanduser()
        if not root.is_dir():
            raise ValueError(f"盘根目录不存在或不是目录：{raw_root}")
        try:
            check_writable(root)
            check_layout(root)
        except (RootNotWritable, ShelfLayoutConflict) as error:
            raise ValueError(str(error)) from None
        flags = {}
        for key, default in (("move_unrecognized", True), ("offline", False), ("force_scrape", False),
                             ("dry_run", False)):
            value = data.get(key, default)
            if not isinstance(value, bool):
                raise ValueError(f"{key} 要是 true 或 false")
            flags[key] = value
        images = data.get("images_in_work_dir")
        if images is not None and not isinstance(images, bool):
            raise ValueError("images_in_work_dir 要是 true 或 false")
        flags["images_in_work_dir"] = images
        steps = data.get("steps", list(pipeline.STEPS))
        if not isinstance(steps, list) or not steps or any(step not in pipeline.STEPS for step in steps):
            raise ValueError(f"步骤只能是 {'、'.join(pipeline.STEPS)} 的子集")
        ordered = tuple(step for step in pipeline.STEPS if step in steps)
        return cls(root=root.resolve(), steps=ordered, **flags)

    def to_dict(self) -> dict:
        return {"root": str(self.root), "move_unrecognized": self.move_unrecognized, "offline": self.offline,
                "force_scrape": self.force_scrape, "dry_run": self.dry_run, "images_in_work_dir": self.images_in_work_dir,
                "steps": list(self.steps)}


def _plain(value: Any) -> Any:
    """`RunResult` 之类 → 可 JSON 的字典；`Path` 转字符串。"""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def reduce_state(events: list[Event], steps_order: tuple[str, ...] = pipeline.STEPS) -> dict:
    """事件 → 页面状态：每步 waiting/running/done/failed/skipped，最后一条消息，结束结果。前端 `progress-core.js` 同一套规则。"""
    steps = {name: {"status": STATUS_WAITING, "stats": None, "error": None, "message": None, "started_at": None,
                    "finished_at": None} for name in steps_order}
    state: dict[str, Any] = {"run": None, "root": None, "options": None, "started_at": None, "finished_at": None,
                             "running": False, "cancel_requested": False, "result": None, "steps": steps,
                             "last_seq": 0}
    for event in events:
        state["last_seq"] = event.seq
        if event.kind == "run.start":
            state.update(run=event.run, started_at=event.ts, running=True, result=None, finished_at=None)
            stats = event.stats or {}
            state["root"] = stats.get("root")
            state["options"] = stats.get("options")
            continue
        if event.kind in ("run.done", "run.cancelled"):
            state.update(running=False, finished_at=event.ts, result={**(event.stats or {}), "cancelled": event.kind == "run.cancelled"})
            continue
        row = steps.get(event.step or "")
        if row is None:
            continue
        if event.kind == "step.start":
            row.update(status=STATUS_RUNNING, started_at=event.ts, message=None)
        elif event.kind == "step.progress":
            if event.level == "warning" and (event.message or "").startswith("收到停止请求"):
                state["cancel_requested"] = True
            if row["status"] == STATUS_RUNNING:
                row["message"] = event.message
        elif event.kind == "step.done":
            row.update(status=STATUS_DONE, stats=event.stats, finished_at=event.ts)
        elif event.kind == "step.failed":
            row.update(status=STATUS_FAILED, error=event.message, finished_at=event.ts)
        elif event.kind == "step.skipped":
            row.update(status=STATUS_SKIPPED, message=event.message, finished_at=event.ts)
    return state


class RunManager:
    def __init__(self, *, home: Path | None = None, run_pipeline: Callable[..., pipeline.RunResult] = pipeline.run,
                 clock: Callable[[], float] = time.time) -> None:
        self.home = Path(home) if home is not None else config_home()
        self.run_pipeline = run_pipeline
        self.clock = clock
        self._lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._log: RunLog | None = None
        self._cancel = threading.Event()
        self._options: RunOptions | None = None

    # ---------- 运行 ----------

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def _new_run_id(self) -> str:
        stamp = datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{secrets.token_hex(3)}"

    def start(self, options: RunOptions) -> str:
        """开一次运行，立刻返回 run id；已有运行在跑抛 `RunBusy`。"""
        if not self._lock.acquire(blocking=False):
            raise RunBusy("已有一个运行在进行中，等它结束或先停止")
        try:
            log = RunLog(self._new_run_id(), clock=self.clock)
            with self._state_lock:
                self._log = log
                self._options = options
                self._cancel.clear()
            log.append("run.start", stats={"root": str(options.root), "steps": list(options.steps),
                                           "options": options.to_dict()})
            self.remember_root(options.root)
            thread = threading.Thread(target=self._work, args=(log, options), name=f"shelf-run-{log.run_id}", daemon=True)
            self._thread = thread
            thread.start()
        except BaseException:
            self._lock.release()
            raise
        return log.run_id

    def _work(self, log: RunLog, options: RunOptions) -> None:
        try:
            paths = ShelfPaths(options.root)
            # 老盘迁移在读配置之前；顺序不能反，否则读配置之后的建目录会抢先建出 HiddenShelf/。
            # 这里显式调一次是为了把那句话记进网页日志（ensure() 自己也会调，幂等）。
            if migrate_legacy_dir(options.root):
                log.append("step.progress", level="info", message=pipeline.MIGRATED_NOTE)
            paths.ensure()
            config = ShelfConfig.load(paths)
            config.move_unrecognized = options.move_unrecognized
            if options.images_in_work_dir is not None and options.images_in_work_dir != config.images_in_work_dir:
                config.images_in_work_dir = options.images_in_work_dir
                config.save(paths)
            scrape_options = pipeline.ScrapeOptions(offline=options.offline, force=options.force_scrape)
            result = self.run_pipeline(options.root, config=config, steps=options.steps, progress=EventProgress(log),
                                       scrape_options=scrape_options, cancel=self._cancel.is_set,
                                       dry_run=options.dry_run)
            stats = _plain(result)
            log.append("run.cancelled" if getattr(result, "cancelled", False) else "run.done", stats=stats)
        except Exception as error:  # noqa: BLE001 - 线程里的异常要落成事件，不能静默消失
            detail = f"{type(error).__name__}: {error}"
            try:
                log.append("run.done", stats={"ok": False, "error": detail, "failed_step": "", "steps": {}})
            except RuntimeError:
                pass
        finally:
            log.close()
            self._lock.release()

    def cancel(self) -> bool:
        """运行中置取消标志并记一条警告；没在跑返回 False。"""
        with self._state_lock:
            log = self._log
            if not self.running or log is None or log.closed:
                return False
            self._cancel.set()
            try:
                log.append("step.progress", level="warning", message="收到停止请求：当前步完成后不再继续")
            except RuntimeError:
                return False
            return True

    def wait(self, timeout: float | None = None) -> bool:
        """等当前运行结束（测试用）。"""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    # ---------- 状态 ----------

    def log_for(self, run_id: str | None = None) -> RunLog | None:
        """当前或最近一次运行的日志；给了 run id 就要对得上。"""
        with self._state_lock:
            log = self._log
        if log is None or (run_id and log.run_id != run_id):
            return None
        return log

    def state(self) -> dict:
        with self._state_lock:
            log = self._log
        if log is None:
            state = reduce_state([])
        else:
            state = reduce_state(log.events)
            state["run"] = log.run_id
        state["running"] = self.running
        state["cancel_requested"] = state["cancel_requested"] or self._cancel.is_set() and self.running
        return state

    # ---------- 最近目录 ----------

    @property
    def recent_path(self) -> Path:
        return self.home / "recent.json"

    def recent_roots(self) -> list[str]:
        try:
            loaded = json.loads(self.recent_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(loaded, list):
            return []
        return [str(item) for item in loaded if isinstance(item, str) and item][:RECENT_LIMIT]

    def remember_root(self, root: Path | str) -> list[str]:
        text = str(root)
        roots = [text, *(item for item in self.recent_roots() if item != text)][:RECENT_LIMIT]
        self.home.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.recent_path, json.dumps(roots, ensure_ascii=False, indent=1))
        return roots
