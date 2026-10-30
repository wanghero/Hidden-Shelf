"""运行事件：`Progress` 回调 → 带序号、带时间戳的 `Event`，存进一次运行的环形缓冲，订阅者实时收、断线按序号补。

SSE 格式（计划 3 定）：每条 `id: <seq>`、`event: <kind>`、`data: <一行 JSON>`，JSON 键固定
`seq, ts, run, kind, step, level, message, stats`，没有的为 `null`。缓冲上限默认 5000 条，超出只淘汰最早的
`step.progress`；`run.*`、`step.start/done/failed/skipped` 永不淘汰，断线重连时里程碑一定补得回来。
"""
from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from ..pipeline import Progress

KINDS = ("run.start", "step.start", "step.progress", "step.done", "step.failed", "step.skipped",
         "run.done", "run.cancelled")
#: 永不淘汰的事件类型。
KEEP_ALWAYS = frozenset(KINDS) - {"step.progress"}
DEFAULT_LIMIT = 5000


@dataclass(frozen=True)
class Event:
    seq: int
    ts: str
    run: str
    kind: str
    step: str | None = None
    level: str | None = None
    message: str | None = None
    stats: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_sse(self) -> str:
        """`id:` / `event:` / `data:` 三行加空行；`data` 是一行 JSON，中文不转义。"""
        return f"id: {self.seq}\nevent: {self.kind}\ndata: {json.dumps(self.to_dict(), ensure_ascii=False)}\n\n"


class RunLog:
    """一次运行的事件缓冲：线程安全地追加、按序号读、订阅实时推送。"""

    def __init__(self, run_id: str, *, limit: int = DEFAULT_LIMIT, clock=time.time) -> None:
        self.run_id = run_id
        self.limit = limit
        self.clock = clock
        self._events: list[Event] = []
        self._seq = 0
        self._lock = threading.RLock()
        self._subscribers: list[queue.Queue] = []
        self.closed = False

    def _stamp(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec="milliseconds")

    def append(self, kind: str, *, step: str | None = None, level: str | None = None,
               message: str | None = None, stats: dict | None = None) -> Event:
        if kind not in KINDS:
            raise ValueError(f"未知事件类型：{kind!r}")
        with self._lock:
            if self.closed:
                raise RuntimeError("运行已结束，不再接受事件")
            self._seq += 1
            event = Event(self._seq, self._stamp(), self.run_id, kind, step, level, message,
                          dict(stats) if stats is not None else None)
            self._events.append(event)
            self._evict()
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(event)
        return event

    def _evict(self) -> None:
        """超限时丢最早的 `step.progress`；里程碑类一条不丢。"""
        while len(self._events) > self.limit:
            index = next((i for i, event in enumerate(self._events) if event.kind not in KEEP_ALWAYS), None)
            if index is None:
                return
            del self._events[index]

    def since(self, seq: int) -> list[Event]:
        """序号大于 `seq` 的事件，按序。"""
        with self._lock:
            return [event for event in self._events if event.seq > seq]

    @property
    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    @property
    def last_seq(self) -> int:
        return self._seq

    def subscribe(self) -> queue.Queue:
        """新订阅者只收订阅之后的事件；之前的用 `since()` 补。"""
        subscriber: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
            if self.closed:
                subscriber.put(None)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def close(self) -> None:
        """运行结束：给每个订阅者推一个 `None` 作结束标记。"""
        with self._lock:
            if self.closed:
                return
            self.closed = True
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(None)


class EventProgress(Progress):
    """把 `pipeline.Progress` 回调写进 `RunLog`。记住当前步名，`advance`/`log`/`done` 都挂在它上面。"""

    def __init__(self, log: RunLog) -> None:
        self.log_ = log
        self.current: str | None = None

    def step(self, name: str, total: int | None = None) -> None:
        self.current = name
        stats = {"total": total} if total is not None else None
        self.log_.append("step.start", step=name, stats=stats)

    def advance(self, n: int = 1, message: str = "") -> None:
        if message:
            self.log_.append("step.progress", step=self.current, level="info", message=message)

    def log(self, level: str, message: str) -> None:
        self.log_.append("step.progress", step=self.current, level=level or "info", message=message)

    def done(self, stats: dict) -> None:
        self.log_.append("step.done", step=self.current, stats=dict(stats or {}))

    def failed(self, name: str, error: str) -> None:
        self.log_.append("step.failed", step=name, level="error", message=error)

    def skipped(self, name: str, reason: str) -> None:
        self.log_.append("step.skipped", step=name, level="info", message=reason)


def event_from_dict(data: dict[str, Any]) -> Event:
    """`to_dict()` 的逆（测试与前端夹具用）。"""
    return Event(int(data["seq"]), str(data["ts"]), str(data["run"]), str(data["kind"]), data.get("step"),
                 data.get("level"), data.get("message"), data.get("stats"))
