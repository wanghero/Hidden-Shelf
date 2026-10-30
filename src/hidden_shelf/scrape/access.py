"""采集来源的登记表、按站冷却与按来源传输。

思路取自 peach `src/peach/scraping_access.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）：`SOURCES` 只留本项目接了的 8 站；403 首停 `FIRST_BLOCKED_PAUSE` 连着再撞
翻倍到该站上限，429 按 `Retry-After`；通了一次就清记录。去掉浏览器传输、凭据库、流量计费与
`via` 两条路的区分。冷却记录住在 `HiddenShelf/sources/_cooldown.json`，一盘一份。
"""
from __future__ import annotations

import http.cookiejar
import json
import time
from email.utils import parsedate_to_datetime
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

import httpx

from ..fsutil import atomic_write_text
from ..netconfig import GlobalConfig
from .transport import USER_AGENT, HostLimiter, HttpRequest, HttpResponse, HttpxTransport, host_under

#: 8 站的登记。`cookie`：请求要带用户贴的 Cookie；`blocked_pause`：403 冷却的上限（秒），没登记的站 403 只报错不冷却。
SOURCES: dict[str, dict] = {
    "r18dev": {"label": "R18.dev", "domains": ("r18.dev",), "login": "https://r18.dev/"},
    "dmm": {"label": "DMM / FANZA", "domains": ("dmm.co.jp", "dmm.com"), "login": "https://www.dmm.co.jp/"},
    "1pondo": {"label": "一本道", "domains": ("1pondo.tv",), "login": "https://www.1pondo.tv/"},
    # FC2 的商品页、卖家页和图片存储（`storage*`、`contents-thumbnail*`）都在 fc2.com 底下。免登录可读。
    "fc2": {"label": "FC2", "domains": ("fc2.com",), "login": "https://adult.contents.fc2.com/"},
    # 下架 FC2 的最后一档。作品页在 javarchive.com、封面转存在 javstore.net 上，两边算同一个来源。
    "javarchive": {"label": "JavArchive", "domains": ("javarchive.com", "javstore.net"),
                   "login": "https://javarchive.com/", "blocked_pause": 6 * 3600},
    # 三家社区来源拒绝访问时回 403，不发 Retry-After：javdb 是出口 IP 超了配额（一封 3～7 日），
    # AVBase 是 Cloudflare 验证，JavBus 的 403 原因未取得。封期里接着问只会每条都再撞一次。
    "javdb": {"label": "JavDB", "domains": ("javdb.com", "jdbstatic.com", "jdbimgs.com"), "login": "https://javdb.com/",
              "cookie": True, "blocked_pause": 24 * 3600},
    "javbus": {"label": "JavBus", "domains": ("javbus.com",), "login": "https://www.javbus.com/",
               "cookie": True, "blocked_pause": 6 * 3600},
    "avbase": {"label": "AVBase", "domains": ("avbase.net",), "login": "https://www.avbase.net/",
               "blocked_pause": 6 * 3600},
}

#: 撞上拒绝访问后第一次停多久。`blocked_pause` 是上限，不是首停时长：那几家按出口 IP 计的封，
#: 实际封期常常远短于上限（peach 2026-09-22 实测 javdb 记下 24 小时只走了 6.6 小时）。
FIRST_BLOCKED_PAUSE = 900
#: 429 没给 Retry-After 时停多久。
DEFAULT_RATE_LIMIT_PAUSE = 900
#: 没登记上限的来源走 `blocked` 档时按这个封顶。
DEFAULT_BLOCKED_PAUSE = 24 * 3600
#: 各站主机间隔；没列的按默认 2 秒。javdb 页面与图床分别落在两个主机上，间隔要一起管。
HOST_INTERVALS = {"javdb.com": 3.0, "jdbstatic.com": 3.0, "jdbimgs.com": 3.0}


class SourcePaused(RuntimeError):
    """来源冷却期内（或本趟预算用完）停止请求。"""


class BudgetExhausted(SourcePaused):
    """本趟的请求次数或时间预算用完：跟单站冷却不同，这是整趟都该停的信号。"""


def hostname_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def source_for(url: str) -> str | None:
    host = hostname_of(url)
    return next((name for name, spec in SOURCES.items()
                 if any(host_under(host, domain) for domain in spec["domains"])), None)


def cookie_jar(header: str, source: str) -> http.cookiejar.CookieJar:
    """用户贴的一行 Cookie 请求头 → 只对这一站域名生效的 jar。多行或格式坏的抛 `ValueError`。"""
    jar = http.cookiejar.CookieJar()
    text = str(header or "").strip()
    if not text:
        return jar
    if "\r" in text or "\n" in text:
        raise ValueError("请粘贴一行 Cookie 请求头")
    parsed = SimpleCookie()
    try:
        parsed.load(text)
    except CookieError as error:
        raise ValueError("Cookie 请求头格式无效") from error
    domain = (urlsplit(SOURCES[source]["login"]).hostname or "").removeprefix("www.")
    for name, item in parsed.items():
        jar.set_cookie(http.cookiejar.Cookie(
            0, name, item.value, None, False, domain, True, True, "/", True, True, None, True, None, None, {}, False))
    return jar


class Cooldown:
    """按站的冷却记录：`{来源: {"until": 到几点, "blocks": 连着撞了几次}}`，原子写盘。"""

    def __init__(self, path: Path, *, now=time.time):
        self.path = Path(path)
        self.now = now
        self._lock = RLock()
        self._state: dict[str, dict] = {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._state = {str(name): {"until": float(item.get("until") or 0), "blocks": int(item.get("blocks") or 0)}
                               for name, item in loaded.items() if isinstance(item, dict)}
        except (OSError, ValueError, TypeError):
            self._state = {}

    def _save(self) -> None:
        atomic_write_text(self.path, json.dumps(self._state, ensure_ascii=False, indent=1))

    def paused_until(self, source: str) -> float:
        """来源还在冷却就返回到几点，否则 0。"""
        until = float(self._state.get(source, {}).get("until") or 0)
        return until if until > self.now() else 0.0

    def blocks(self, source: str) -> int:
        return int(self._state.get(source, {}).get("blocks") or 0)

    def pause(self, source: str, *, action: str, retry_after: float | None = None) -> float:
        """按两档把来源停下，返回冷却到几点。`blocked` 首停 15 分钟、连着翻倍到上限；`rate_limited` 按 `retry_after`。"""
        with self._lock:
            blocks = self.blocks(source)
            if action == "blocked":
                blocks += 1
                limit = SOURCES.get(source, {}).get("blocked_pause") or DEFAULT_BLOCKED_PAUSE
                until = self.now() + min(FIRST_BLOCKED_PAUSE * 2 ** (blocks - 1), limit)
            elif action == "rate_limited":
                until = self.now() + max(0.0, float(retry_after if retry_after is not None else DEFAULT_RATE_LIMIT_PAUSE))
            else:
                raise ValueError(f"未知冷却档：{action!r}")
            self._state[source] = {"until": max(until, self.now() + 1), "blocks": blocks}
            self._save()
            return until

    def clear(self, source: str) -> None:
        with self._lock:
            if source in self._state:
                del self._state[source]
                self._save()

    def describe(self) -> dict[str, dict]:
        """给人看的：每站还要冷却多少秒、撞了几次。"""
        now = self.now()
        return {name: {"remaining": max(0, round(item["until"] - now)), "blocks": item["blocks"]}
                for name, item in self._state.items() if item["until"] > now}


def retry_after_seconds(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return max(0.0, float(int(text)))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(text).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return None


class SourceTransport:
    """按来源复用连接池、带该站 Cookie、按主机限速、算冷却与本趟预算。

    `factory(source) -> Transport` 注入假传输（测试）；`httpx_transport` 注入 httpx 的传输（MockTransport）。
    """

    def __init__(self, cooldown: Cooldown, config: GlobalConfig | None = None, *,
                 limiter: HostLimiter | None = None, factory=None, httpx_transport: httpx.BaseTransport | None = None,
                 max_requests: int = 0, max_seconds: float = 0, now=time.monotonic):
        self.cooldown = cooldown
        self.config = config or GlobalConfig()
        self.limiter = limiter or HostLimiter(HOST_INTERVALS)
        self.factory = factory
        self.httpx_transport = httpx_transport
        self.max_requests = max_requests
        self.deadline = now() + max_seconds if max_seconds else 0.0
        self.now = now
        self.requests = 0
        self.transports: dict[str | None, object] = {}

    def __call__(self, request: HttpRequest, timeout: float, max_bytes: int) -> HttpResponse:
        source = source_for(request.url)
        if source == "javbus":
            # 中文作品页：javbus 按 Accept-Language 出中文字段名，解析器认的就是中文。
            headers = {key: value for key, value in request.headers.items() if key.lower() != "accept-language"}
            request = HttpRequest(request.method, request.url, {**headers, "Accept-Language": "zh-CN,zh;q=0.9"}, request.body)
        if self.max_requests and self.requests >= self.max_requests:
            raise BudgetExhausted("本趟采集次数已用完，再跑一次接着采")
        if self.deadline:
            timeout = min(timeout, self.deadline - self.now())
            if timeout <= 0:
                raise BudgetExhausted("本趟采集时间已用完，再跑一次接着采")
        key = source or hostname_of(request.url)
        if self.cooldown.paused_until(key):
            raise SourcePaused(f"来源 {key} 正在冷却，本趟不再请求")
        self.limiter.wait(hostname_of(request.url))
        if source not in self.transports:
            self.transports[source] = self._transport_for(source)
        self.requests += 1
        try:
            response = self.transports[source](request, timeout, max_bytes)
        except httpx.TransportError as error:
            raise httpx.TransportError(f"来源连接未取得：{error}") from error
        if response.status == 429:
            self.cooldown.pause(key, action="rate_limited", retry_after=retry_after_seconds(response.headers.get("retry-after", "")))
            raise SourcePaused(f"来源 {key} 限流，已记录冷却时间")
        blocked_pause = SOURCES.get(source or "", {}).get("blocked_pause")
        if response.status == 403 and blocked_pause:
            self.cooldown.pause(key, action="blocked")
            hint = "；请在全局配置里更新它的 Cookie" if SOURCES[source].get("cookie") else ""
            raise SourcePaused(f"来源 {key} 拒绝访问，暂停向它请求一段时间{hint}")
        if response.status < 400 and self.cooldown.blocks(key):
            # 这一趟通了，封已经解除：清掉记录，下次撞上从最短的一档重新起算。
            self.cooldown.clear(key)
        return response

    def hold(self, source: str, action: str) -> None:
        """契约报的冷却细档（`SourceFailure.cooldown_action`）写回这个来源的冷却记录。"""
        if action not in {"blocked", "rate_limited"} or source not in SOURCES:
            return
        self.cooldown.pause(source, action=action)

    def _transport_for(self, source: str | None):
        if self.factory is not None:
            return self.factory(source)
        options = dict(self.config.client_options())
        if self.httpx_transport is not None:
            options.pop("proxy", None)
            options["trust_env"] = False
            options["transport"] = self.httpx_transport
        cookies = None
        if source and SOURCES[source].get("cookie") and self.config.cookie(source):
            cookies = cookie_jar(self.config.cookie(source), source)
        client = httpx.Client(**options, follow_redirects=False, headers={"User-Agent": USER_AGENT}, cookies=cookies)
        return HttpxTransport(client)

    def close(self) -> None:
        for transport in self.transports.values():
            close = getattr(transport, "close", None)
            if callable(close):
                close()
        self.transports.clear()
