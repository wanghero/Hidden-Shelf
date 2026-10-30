"""进度网页的「来源与登录」面板：各站开关、Cookie 有无、冷却状态，以及后台跑的登录流程（计划 8）。

登录在守护线程里跑 `scrape.login.capture_login`，浏览器窗口在跑 `shelf serve` 的这台机器上弹出；网页按
「我已登录完成」置 `finish`。状态只给布尔与人话，Cookie 值不出这个模块。开关与 Cookie 都落在
`~/.hidden-shelf/config.json`（每次读写都重新 `load`，与命令行改的互不覆盖）。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

from ..netconfig import GlobalConfig
from ..paths import ShelfPaths
from ..scrape import login as login_module
from ..scrape.access import SOURCES, Cooldown
from ..scrape.login import LOGIN_SOURCES, LoginError

LOGIN_STATUSES = ("idle", "running", "done", "failed")


class LoginBusy(RuntimeError):
    """这一站已经有一个登录窗口开着。"""


class SourcePanel:
    def __init__(self, *, capture=login_module.capture_login, availability=None, launch=None,
                 clock=time.time) -> None:
        self.capture = capture
        self._availability = availability or login_module.availability
        self._launch = launch
        self.clock = clock
        self._lock = threading.Lock()
        self._logins: dict[str, dict] = {}

    # ---------- 列表 ----------

    def list_sources(self, root: str | None = None) -> dict:
        config = GlobalConfig.load()
        cooldown = self._cooldown_for(root)
        hint = self._availability()
        rows = []
        order = list(LOGIN_SOURCES) + [name for name in SOURCES if name not in LOGIN_SOURCES]
        for name in order:
            spec = SOURCES[name]
            until = cooldown.paused_until(name) if cooldown else 0.0
            with self._lock:
                entry = self._logins.get(name) or {}
            rows.append({
                "name": name, "label": spec["label"], "enabled": config.enabled(name),
                "needs_login": name in LOGIN_SOURCES,
                "cookie": bool(config.cookie(name)), "user_agent": bool(config.user_agent(name)),
                "cooldown_until": datetime.fromtimestamp(until).isoformat(timespec="seconds") if until else None,
                "login": {"status": entry.get("status", "idle"), "message": entry.get("message", "")},
            })
        return {"sources": rows, "login_available": not hint, "login_hint": hint}

    @staticmethod
    def _cooldown_for(root: str | None) -> Cooldown | None:
        if not root:
            return None
        target = Path(root).expanduser()
        if not target.is_dir():
            return None
        path = ShelfPaths(target.resolve()).sources / "_cooldown.json"
        return Cooldown(path) if path.is_file() else None

    # ---------- 开关 ----------

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name not in SOURCES:
            raise ValueError(f"没有这个来源：{name}")
        config = GlobalConfig.load()
        item = config.sources.get(name)
        if item is None:
            from ..netconfig import SourceSettings
            item = config.sources[name] = SourceSettings()
        item.enabled = bool(enabled)
        config.save()

    # ---------- 登录 ----------

    def start_login(self, name: str) -> None:
        """开一个登录线程；不可用抛 `ValueError`（消息给用户看），同站已在登录抛 `LoginBusy`。"""
        if name not in LOGIN_SOURCES:
            raise ValueError(f"{name} 不在可登录的来源里（可登录：{'、'.join(LOGIN_SOURCES)}）")
        hint = self._availability()
        if hint:
            raise ValueError(hint)
        with self._lock:
            current = self._logins.get(name)
            if current and current["status"] == "running":
                raise LoginBusy(f"{SOURCES[name]['label']} 的登录窗口已经开着")
            finish = threading.Event()
            entry = {"status": "running", "message": "", "finish": finish}
            self._logins[name] = entry
        thread = threading.Thread(target=self._run_login, args=(name, entry), daemon=True)
        entry["thread"] = thread
        thread.start()

    def _run_login(self, name: str, entry: dict) -> None:
        def notify(text: str) -> None:
            with self._lock:
                entry["message"] = text
        config = GlobalConfig.load()
        kwargs = {"config": config, "finish": entry["finish"], "notify": notify,
                  "launch": self._launch or login_module.launch_browser}
        try:
            result = self.capture(name, **kwargs)
            config.save()
            message = f"已保存 {result.cookies} 个 Cookie" + ("，浏览器 UA 已记录" if result.user_agent else "")
            status = "done"
        except LoginError as error:
            message, status = str(error), "failed"
        except Exception as error:  # noqa: BLE001 - 线程里不能让异常消失
            message, status = f"登录流程出错：{type(error).__name__}: {error}", "failed"
        with self._lock:
            entry["status"], entry["message"] = status, message

    def finish_login(self, name: str) -> bool:
        with self._lock:
            entry = self._logins.get(name)
            if not entry or entry["status"] != "running":
                return False
            entry["finish"].set()
            return True

    # ---------- 冷却 ----------

    def clear_cooldown(self, root: str, name: str | None = None) -> list[str]:
        """清掉这块盘上的冷却记录（一家或全部）；返回清掉的来源名。盘根不对抛 `ValueError`。"""
        target = Path(str(root or "")).expanduser()
        if not str(root or "").strip() or not target.is_dir():
            raise ValueError("盘根目录不存在或不是目录")
        path = ShelfPaths(target.resolve()).sources / "_cooldown.json"
        if not path.is_file():
            return []
        cooldown = Cooldown(path)
        names = [name] if name else list(cooldown.describe().keys())
        cleared = []
        for item in names:
            if cooldown.blocks(item) or cooldown.paused_until(item):
                cooldown.clear(item)
                cleared.append(item)
        return cleared
