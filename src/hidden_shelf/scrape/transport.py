"""传输层：请求/响应模型、httpx 传输（可选 curl_cffi）、按主机限速、重试与 HTTP 分档。

思路取自 peach `src/peach/http.py`（`HttpRequest`/`HttpResponse`、有界读取）、`scripting.HostLimiter`、
`user_agent.py` 与 `jav_cover_fetch._fetch`（退避重试、占位图与 404/非 2xx 分档），按本项目去掉
内网判据、浏览器传输与流量计费。

`Transport` 是一个可调用 `(HttpRequest, timeout秒, 最大字节) -> HttpResponse`；测试注入假的。
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from threading import Lock
from urllib.parse import urljoin, urlsplit

import httpx

#: 对外请求共用一份标准桌面 Chrome User-Agent（与 peach 同一串）。
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")
#: 量尺寸只需要 JPEG 头部，别把整张图拉下来。
PROBE_BYTES = 64 * 1024
#: 瞬时连接错误按这张表退避重试；四次都失败才交给调用方。
NETWORK_RETRY_DELAYS = (2, 4, 6, 8)
#: DMM 缺图时 302 到「NOW PRINTING」占位图，尺寸像一张正常封面。
PLACEHOLDER = re.compile(r"now_?printing", re.I)
PLACEHOLDER_REASON = "来源给的是「准备中」占位图"
REQUEST_TIMEOUT = 30.0
MAX_REDIRECTS = 6


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    #: 键已小写。
    headers: dict[str, str]
    body: bytes
    url: str


Transport = Callable[[HttpRequest, float, int], HttpResponse]


class PageTooLarge(ValueError):
    """响应正文超过调用方给的上限。"""


class Unavailable(RuntimeError):
    """来源没给出可用响应（非 2xx、占位图等）。"""


class NotFound(Unavailable):
    """来源明确说没有（404 或占位图）。"""


class DeadlineExceeded(RuntimeError):
    """动作预算已用尽。"""


def bounded_body(chunks: Iterable[bytes], limit: int) -> bytes:
    pieces: list[bytes] = []
    size = 0
    for chunk in chunks:
        size += len(chunk)
        if size > limit:
            raise PageTooLarge(f"响应超过 {limit} 字节")
        pieces.append(chunk)
    return b"".join(pieces)


class HttpxTransport:
    """基于 httpx.Client 的传输：不自动跟重定向，正文有界读取。"""

    def __init__(self, client: httpx.Client, *, owns_client: bool = True):
        self.client = client
        self.owns_client = owns_client

    def __call__(self, request: HttpRequest, timeout: float, max_bytes: int) -> HttpResponse:
        try:
            with self.client.stream(request.method, request.url, headers=request.headers,
                                    content=request.body, timeout=timeout, follow_redirects=False) as response:
                body = bounded_body(response.iter_bytes(), max_bytes)
                return HttpResponse(response.status_code,
                                    {key.lower(): value for key, value in response.headers.items()},
                                    body, str(response.url))
        except httpx.TransportError:
            raise
        except httpx.HTTPError as error:
            raise httpx.TransportError(str(error)) from error

    def close(self) -> None:
        if self.owns_client:
            self.client.close()


class CurlTransport:
    """`curl_cffi` 模拟浏览器 TLS 指纹的传输；没装就不可用。只给撞 Cloudflare 的站用。"""

    def __init__(self, *, impersonate: str = "chrome", client_options: dict | None = None):
        try:
            from curl_cffi import requests as curl_requests
        except ImportError as error:
            raise RuntimeError("curl_cffi 未安装：uv sync --extra fingerprint") from error
        options = dict(client_options or {})
        proxies = {"https": options["proxy"], "http": options["proxy"]} if options.get("proxy") else None
        self.session = curl_requests.Session(impersonate=impersonate, proxies=proxies,
                                             trust_env=options.get("trust_env", True), allow_redirects=False)

    @staticmethod
    def available() -> bool:
        try:
            import curl_cffi  # noqa: F401
        except ImportError:
            return False
        return True

    def __call__(self, request: HttpRequest, timeout: float, max_bytes: int) -> HttpResponse:
        from curl_cffi.requests.exceptions import RequestException
        try:
            response = self.session.request(request.method, request.url, headers=request.headers,
                                            data=request.body, timeout=timeout, stream=True)
            body = bounded_body(response.iter_content(), max_bytes)
        except RequestException as error:
            raise httpx.TransportError(str(error)) from error
        return HttpResponse(int(response.status_code), {k.lower(): v for k, v in response.headers.items()},
                            body, str(getattr(response, "url", request.url) or request.url))

    def close(self) -> None:
        self.session.close()


def host_under(host: str, key: str) -> bool:
    """`host` 是不是 `key` 本身或它的子域（按点边界）。"""
    host, key = host.lower().rstrip("."), key.lower().rstrip(".")
    return host == key or host.endswith("." + key)


class HostLimiter:
    """按主机分别限速：每个主机一把锁、一个下次可发时刻。键按点边界匹配。"""

    def __init__(self, intervals: dict[str, float] | None = None, *, default: float = 2.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.intervals = dict(intervals or {})
        self.default = default
        self.clock = clock
        self.sleep = sleep
        self._next: dict[str, float] = {}
        self._lock = Lock()

    def interval_for(self, host: str) -> float:
        for key, seconds in self.intervals.items():
            if host_under(host, key):
                return seconds
        return self.default

    def _bucket(self, host: str) -> str:
        for key in self.intervals:
            if host_under(host, key):
                return key
        return host.lower()

    def wait(self, host: str) -> None:
        bucket = self._bucket(host)
        with self._lock:
            now = self.clock()
            due = self._next.get(bucket, 0.0)
            if due > now:
                self.sleep(due - now)
                now = self.clock()
            self._next[bucket] = now + self.interval_for(host)


def follow_redirects(transport: Transport, request: HttpRequest, timeout: float, limit: int, *,
                     max_hops: int = MAX_REDIRECTS) -> HttpResponse:
    """跟重定向：只跟 HTTPS，跨域去掉 Cookie/Authorization/Host，303 改 GET。超过 `max_hops` 抛 `ValueError`。"""
    for _ in range(max_hops):
        response = transport(request, timeout, limit)
        location = response.headers.get("location")
        if response.status not in {301, 302, 303, 307, 308} or not location:
            return response
        target = urljoin(request.url, location)
        if urlsplit(target).scheme != "https":
            raise ValueError("采集重定向必须使用 HTTPS")
        cross_origin = urlsplit(target).netloc != urlsplit(request.url).netloc
        headers = {key: value for key, value in request.headers.items()
                   if not cross_origin or key.lower() not in {"cookie", "authorization", "host"}}
        request = HttpRequest("GET" if response.status == 303 else request.method, target, headers,
                              None if response.status == 303 else request.body)
    raise ValueError("采集重定向次数超过上限")


def _remaining(deadline: float | None) -> float | None:
    return None if deadline is None else deadline - time.monotonic()


def request_timeout(remaining: float | None) -> float:
    return REQUEST_TIMEOUT if remaining is None else max(0.0, min(REQUEST_TIMEOUT, remaining))


def fetch(transport: Transport, url: str, *, referer: str, limit: int, ranged: bool = False,
          extra_headers: dict[str, str] | None = None, deadline: float | None = None,
          method: str = "GET", body: bytes | None = None) -> bytes:
    """取一页：带 UA/Referer，连接错误按退避表重试，占位图与 404 抛 `NotFound`，其余非 2xx 抛 `Unavailable`。"""
    headers = {"User-Agent": USER_AGENT, "Referer": referer, "Accept-Language": "ja,en;q=0.9"}
    if extra_headers:
        headers.update(extra_headers)
    if ranged:
        headers["Range"] = f"bytes=0-{PROBE_BYTES - 1}"
    request = HttpRequest(method, url, headers, body)
    for attempt in range(len(NETWORK_RETRY_DELAYS) + 1):
        remaining = _remaining(deadline)
        if remaining is not None and remaining <= 0:
            raise DeadlineExceeded("动作预算已用尽")
        try:
            response = follow_redirects(transport, request, request_timeout(remaining), limit)
            break
        except httpx.TransportError:
            if attempt == len(NETWORK_RETRY_DELAYS):
                raise
            delay = NETWORK_RETRY_DELAYS[attempt]
            remaining = _remaining(deadline)
            if remaining is not None and remaining <= delay:
                raise DeadlineExceeded("动作预算已用尽")
            time.sleep(delay)
    if PLACEHOLDER.search(response.url or ""):
        raise NotFound(PLACEHOLDER_REASON)
    if response.status == 404:
        raise NotFound("HTTP 404")
    if response.status not in (200, 206):
        raise Unavailable(f"HTTP {response.status}")
    return response.body
