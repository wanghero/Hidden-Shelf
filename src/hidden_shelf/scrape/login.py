"""在浏览器里登录来源站，把该站 Cookie 与浏览器 UA 存进全局配置（计划 8）。

要登录的站（`LOGIN_SOURCES`）：javdb 有登录墙与配额，javbus 有年龄门。avbase 不在这里：它的 Cloudflare 看的是
TLS 指纹，靠 `access.FINGERPRINT_SOURCES` 走 `curl_cffi`，带浏览器 Cookie 反而撞验证（2026-10-30 实测）。
流程：弹出一个有头的 Chromium（Playwright），停在该站的登录页；用户自己登录或过验证；程序每半秒抓一次该站
域名下的 Cookie 快照，用户关掉窗口或按「完成」就用最后一份快照落盘。窗口一关 Cookie 就拿不到了，所以快照
必须每轮都留。凭据只进 `~/.hidden-shelf/config.json`，`notify` 的每一句都不带 Cookie 值。

`launch(url)` 回一个浏览器句柄（`cookies() / user_agent() / closed() / close()`），默认实现 `launch_browser`
用 Playwright；测试传假句柄。Playwright 是可选依赖：`uv sync --extra login` 再 `uv run playwright install chromium`。
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..netconfig import GlobalConfig
from .access import SOURCES, host_under

#: 要登录或要过验证的来源，按面板里的顺序。
LOGIN_SOURCES: tuple[str, ...] = ("javdb", "javbus")
INSTALL_HINT = ("没装 Playwright，登录功能不可用。先执行：\n"
                "  uv sync --extra login\n"
                "  uv run playwright install chromium")
#: 等用户登录最多这么久（秒）。
LOGIN_TIMEOUT = 600


class LoginError(RuntimeError):
    """给用户看的登录失败原因。"""


@dataclass
class LoginResult:
    cookies: int
    user_agent: str


def _import_playwright():
    from playwright.sync_api import sync_playwright  # noqa: F401  延迟导入：可选依赖
    return sync_playwright


def availability() -> str:
    """空串表示能用；否则是给用户看的安装说明。"""
    try:
        _import_playwright()
    except ImportError:
        return INSTALL_HINT
    return ""


def login_url(source: str) -> str:
    spec = SOURCES.get(source) or {}
    return str(spec.get("login_url") or spec.get("login") or "")


class _PlaywrightHandle:
    """Playwright 有头 Chromium 的句柄。`closed()` 以用户把窗口（最后一个页面）关掉为准。"""

    def __init__(self, url: str):
        sync_playwright = _import_playwright()
        self._manager = sync_playwright()
        self._playwright = self._manager.__enter__()
        try:
            self._browser = self._playwright.chromium.launch(headless=False)
        except Exception as error:  # noqa: BLE001 - Playwright 的错误类型随版本变
            self._manager.__exit__(None, None, None)
            message = str(error)
            if "Executable doesn't exist" in message or "playwright install" in message:
                raise LoginError("Playwright 还没下载浏览器：uv run playwright install chromium") from error
            raise LoginError(f"打不开浏览器：{message.splitlines()[0] if message else error}") from error
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._page.goto(url, wait_until="domcontentloaded")

    def cookies(self) -> list[dict]:
        try:
            return list(self._context.cookies())
        except Exception:  # noqa: BLE001 - 窗口刚关掉时取不到，当这一轮没有
            return []

    def user_agent(self) -> str:
        try:
            return str(self._page.evaluate("navigator.userAgent"))
        except Exception:  # noqa: BLE001
            return ""

    def closed(self) -> bool:
        try:
            return not self._browser.is_connected() or not self._context.pages
        except Exception:  # noqa: BLE001
            return True

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            self._manager.__exit__(None, None, None)


def launch_browser(url: str):
    return _PlaywrightHandle(url)


def cookie_header(cookies: list[dict], source: str) -> str:
    """Playwright 的 Cookie 列表 → 只含该站域名的一行 Cookie 请求头。同名以后出现的为准。"""
    domains = SOURCES.get(source, {}).get("domains", ())
    picked: dict[str, str] = {}
    for item in cookies:
        domain = str(item.get("domain") or "").lstrip(".").lower()
        name = str(item.get("name") or "")
        if not name or not any(host_under(domain, base) for base in domains):
            continue
        picked[name] = str(item.get("value") or "")
    return "; ".join(f"{name}={value}" for name, value in picked.items())


def capture_login(source: str, *, config: GlobalConfig, finish: threading.Event,
                  notify: Callable[[str], None] = print, launch=launch_browser,
                  poll_seconds: float = 0.5, timeout: float = LOGIN_TIMEOUT) -> LoginResult:
    """弹浏览器让用户登录 `source`，把该站 Cookie 与 UA 写进 `config`（不 `save`，调用方决定）。"""
    if source not in LOGIN_SOURCES:
        raise LoginError(f"{source} 不在可登录的来源里（可登录：{'、'.join(LOGIN_SOURCES)}）")
    label = SOURCES[source]["label"]
    handle = launch(login_url(source))
    notify(f"浏览器已打开 {label}，请在里面登录或完成验证；登录完成后关掉窗口，或在这里点「完成」")
    deadline = time.monotonic() + timeout
    last_header, user_agent = "", ""
    try:
        while True:
            snapshot = cookie_header(handle.cookies(), source)
            if snapshot:
                last_header = snapshot
            agent = handle.user_agent()
            if agent:
                user_agent = agent
            if finish.is_set() or handle.closed():
                break
            if time.monotonic() >= deadline:
                raise LoginError(f"等待登录超时（{int(timeout)} 秒），什么都没改")
            time.sleep(poll_seconds)
    finally:
        handle.close()
    if not last_header:
        raise LoginError(f"没有拿到 {label} 的 Cookie，原来的设置没动")
    config.set_login(source, last_header, user_agent)
    return LoginResult(cookies=len(last_header.split("; ")), user_agent=user_agent)
