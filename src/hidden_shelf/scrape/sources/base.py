"""站点解析器的统一契约：一个站一个类、取页与解析分开、按站配置进数据、一种返回模型、一张失败原因表。

移植自 peach `src/peach/sources/base.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）。改动：`Session.get/post` 调本项目 `scrape.transport.fetch`；去掉
`provider_error`（没有 `MetadataProviderError` 那一层，调用方直接看 `SourceFailure.kind`）。

四个部件各管一件事：

- `SiteConfig`：站名、主域与图床、请求间隔、是否带 Cookie、页面大小上限、所属档位。它是数据。
- `SiteSource`：`fetch(code, session=)` 取到作品页，`parse(page, code)` 从页面读出 `SiteRecord`，
  `query()` 把两步串起来，`records()` 交出这一站的全部记录。两者都包在 `holding()` 里：
  `fetch` 抛出的 HTTP 分档翻成 `SourceFailure`，要整站停下的细档写回来源冷却。
  测试只喂 `parse` 一张页面就能覆盖解析，不必起假传输。
- `SiteRecord`：一种返回模型。`payload()` 投影成快照那份 dict（`id`、`maker`、`actresses[].japanese_name`、
  `cover_urls`……），结算那一路认的就是它。
- `FailureReason`：一张失败原因表。`REASON_KINDS` 把它映到 `auth` / `unavailable` / `not_found` 三档，
  `COOLDOWN_ACTIONS` 说哪几档要把整站停下。

传输层自己的信号不经这张表：`SourcePaused`（冷却期）、`DeadlineExceeded`（动作预算）与
`httpx.TransportError`（连接未取得）由传输层抛出，`holding()` 原样放过。
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .. import transport as tp
from ..transport import NotFound, Unavailable


class FailureReason(StrEnum):
    """站点没给出结果的细档。语义在成员名，措辞由抛错的那一处写。"""

    #: 撞上 Cloudflare 的挑战页或拦截页：同一个出口再发结果不变。
    CLOUDFLARE_CHALLENGE = "cloudflare_challenge"
    #: 出口 IP 已被站方封禁（javdb 按出口 IP 计配额、超了封 3～7 天）。
    IP_BANNED = "ip_banned"
    #: 站方按地区拒绝这个出口。
    GEO_RESTRICTED = "geo_restricted"
    #: 登录墙、年龄门或 401/403：换一份 Cookie 才能继续。
    AUTH_REQUIRED = "auth_required"
    #: 站上没有这个番号（HTTP 404 或搜索无命中）。
    NOT_FOUND = "not_found"
    #: 站上有过、现已下架（HTTP 410 或下架页）。
    GONE = "gone"
    #: 页面在，结构却对不上解析器：站点改版，重试无用，也不是这部片没有。
    PARSE_ERROR = "parse_error"
    #: 请求成功却没解析出可用资料。
    NO_USABLE_METADATA = "no_usable_metadata"
    #: HTTP 429 或站方明说的限流。
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    #: 5xx。
    SERVER_ERROR = "server_error"
    #: 连接层失败：DNS、TLS、连接被重置。
    NETWORK = "network"


#: 细档 → 三档。`auth` 一档收「站方把我们挡在门外」的几种：同一份请求再发一次结果不变。
#: `parse_error` 归 `unavailable` 但不可重试：不是这部片没有，也不是等一会儿就好。
REASON_KINDS: dict[FailureReason, str] = {
    FailureReason.CLOUDFLARE_CHALLENGE: "auth",
    FailureReason.IP_BANNED: "auth",
    FailureReason.GEO_RESTRICTED: "auth",
    FailureReason.AUTH_REQUIRED: "auth",
    FailureReason.NOT_FOUND: "not_found",
    FailureReason.GONE: "not_found",
    FailureReason.NO_USABLE_METADATA: "not_found",
    FailureReason.PARSE_ERROR: "unavailable",
    FailureReason.RATE_LIMITED: "unavailable",
    FailureReason.TIMEOUT: "unavailable",
    FailureReason.SERVER_ERROR: "unavailable",
    FailureReason.NETWORK: "unavailable",
}
#: 这几档说明的是「这个出口对这一站发得太多、已被封或不在站方的服务地区」，整站要进冷却，不只是这一部片。
COOLDOWN_ACTIONS: dict[FailureReason, str] = {
    FailureReason.CLOUDFLARE_CHALLENGE: "blocked",
    FailureReason.IP_BANNED: "blocked",
    FailureReason.GEO_RESTRICTED: "blocked",
    FailureReason.RATE_LIMITED: "rate_limited",
}
#: 重试没有意义的细档。
PERMANENT_REASONS = frozenset({FailureReason.PARSE_ERROR})
#: 快照里记成「没有」的细档：来源的确定答复，期内不再问。
MISS_REASONS = frozenset({FailureReason.NOT_FOUND, FailureReason.GONE, FailureReason.NO_USABLE_METADATA})

#: Cloudflare 的验证页与拦截页的标题。只认标题：Cloudflare 往正常页里也注入 `challenge-platform` 脚本。
CHALLENGE_TITLE = re.compile(
    r"<title[^>]*>\s*(?:Just a moment\.\.\.|请稍候…|Attention Required! \| Cloudflare)\s*</title>")


def challenge_page(html: str | bytes) -> bool:
    """这一页是不是 Cloudflare 的验证页。站上有没有这部片，这一页说不了。"""
    text = html.decode("utf-8", "replace") if isinstance(html, bytes) else str(html)
    return bool(CHALLENGE_TITLE.search(text[:4096]))


#: 作品页的默认大小上限。javdb 详情页实测 90 KB、JavBus 作品页百余 KB，4 MiB 留的是改版余量。
DEFAULT_PAGE_LIMIT = 4 * 1024 * 1024
DEFAULT_INTERVAL = 2.0


class SourceFailure(RuntimeError):
    """一站没给出结果：`reason` 是细档，`message` 是给人看的那一句。"""

    def __init__(self, reason: FailureReason | str, message: str, *,
                 status_code: int = 0, detail: str = "") -> None:
        super().__init__(message)
        self.reason = FailureReason(reason)
        self.message = message
        self.status_code = status_code
        self.detail = detail or self.reason.value
        #: 冷却已经记过：嵌套的 `holding()` 不再记第二次。
        self.held = False

    @property
    def kind(self) -> str:
        return REASON_KINDS[self.reason]

    @property
    def cooldown_action(self) -> str:
        return COOLDOWN_ACTIONS.get(self.reason, "")

    @property
    def is_miss(self) -> bool:
        return self.reason in MISS_REASONS

    @property
    def retryable(self) -> bool:
        return self.kind == "unavailable" and self.reason not in PERMANENT_REASONS


def http_failure(error: Unavailable) -> SourceFailure:
    """`fetch` 抛出的 HTTP 分档（`HTTP 403`、`HTTP 429`、`HTTP 503`）→ 细档。措辞保留原文。"""
    text = str(error)
    if isinstance(error, NotFound):
        return SourceFailure(FailureReason.NOT_FOUND, text, status_code=404 if text == "HTTP 404" else 0)
    status = int(text[5:]) if text.startswith("HTTP ") and text[5:].isdigit() else 0
    if status in (401, 403):
        reason = FailureReason.AUTH_REQUIRED
    elif status == 429:
        reason = FailureReason.RATE_LIMITED
    elif status == 410:
        reason = FailureReason.GONE
    elif status >= 500:
        reason = FailureReason.SERVER_ERROR
    else:
        reason = FailureReason.NETWORK
    return SourceFailure(reason, text, status_code=status)


@dataclass(frozen=True)
class SiteConfig:
    """一站的配置。全是数据，站的类不带常量。"""

    #: 来源名，与 `policy.SOURCE_SPECS`、`access.SOURCES` 同键。
    name: str
    #: 措辞里的站名。
    label: str
    #: 解析器名，写进快照的 `provenance`。
    provider: str
    #: 作品页所在的主域，请求的 Referer 也取它。
    base_url: str
    #: 主域、镜像与图床的域名后缀。
    domains: tuple[str, ...]
    #: 链上的档位：`official` / `official_mirror` / `community`。
    stage: str
    #: 同主机两次请求的最短间隔（秒）。
    interval: float = DEFAULT_INTERVAL
    #: 请求要不要带用户在全局配置里贴的 Cookie。
    cookie: bool = False
    #: 作品页大小上限。
    page_limit: int = DEFAULT_PAGE_LIMIT

    @property
    def referer(self) -> str:
        return self.base_url + "/"


@dataclass(frozen=True)
class Page:
    """取回来的一张页面。`url` 是最终地址，解析器把它写进 `source_url`。"""

    url: str
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


@dataclass(frozen=True)
class Session:
    """一次查询的传输与预算：`transport` 是按来源带 Cookie、算冷却的那一个，`deadline` 是动作预算。"""

    transport: Any
    deadline: float | None = None

    def get(self, url: str, *, config: SiteConfig, referer: str = "",
            headers: Mapping[str, str] | None = None) -> Page:
        options = {"extra_headers": dict(headers)} if headers else {}
        return Page(url, tp.fetch(self.transport, url, referer=referer or config.referer,
                                  limit=config.page_limit, deadline=self.deadline, **options))

    def post(self, url: str, *, config: SiteConfig, body: bytes, referer: str = "",
             headers: Mapping[str, str] | None = None) -> Page:
        options = {"extra_headers": dict(headers)} if headers else {}
        return Page(url, tp.fetch(self.transport, url, referer=referer or config.referer,
                                  limit=config.page_limit, deadline=self.deadline,
                                  method="POST", body=body, **options))


@dataclass(frozen=True)
class SiteRecord:
    """一站给出的一部作品。字段是库里真相字段的直接投影，站上没有的留空。"""

    source: str
    provenance: str
    #: 站上读回的番号写法，`identifies_code` 拿它核身份；不是问的那个。
    code: str
    source_url: str
    title: str = ""
    #: 出演女优，每人一份 `{japanese_name, profile_source?, external_id?, thumb_url?}`。
    performers: tuple[Mapping[str, str], ...] = ()
    studio: str = ""
    label: str = ""
    series: str = ""
    director: str = ""
    release_date: str = ""
    #: 分钟。
    runtime: float | None = None
    #: `None` 表示这一站不给标签；空元组表示给了但为空。
    tags: tuple[str, ...] | None = None
    cover_urls: tuple[str, ...] = ()
    #: 整段简介，段落之间空一行。站上没有就留空。
    plot: str = ""
    confidence: float = 1.0
    #: 只有这一站才有的键，原样并进 `payload()`。
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def cover_url(self) -> str:
        return self.cover_urls[0] if self.cover_urls else ""

    def payload(self) -> dict:
        """快照那份 dict：键名沿用 `maker`、`actresses`、`genres` 的写法。"""
        payload: dict[str, Any] = dict(
            id=self.code, source_url=self.source_url, title=self.title,
            actresses=[dict(row) for row in self.performers],
            maker=self.studio, label=self.label, series=self.series, director=self.director,
            release_date=self.release_date, runtime=self.runtime,
            cover_urls=list(self.cover_urls), cover_url=self.cover_url)
        if self.plot:
            payload["plot"] = self.plot
        if self.tags is not None:
            payload["genres"] = list(self.tags)
        payload.update(self.extra)
        return payload


class SiteSource:
    """一站一个子类：`fetch` 取到作品页，`parse` 读出记录，`query` 串起来。"""

    DEFAULT: SiteConfig

    def __init__(self, config: SiteConfig | None = None) -> None:
        self.config = config or type(self).DEFAULT

    def fetch(self, code: str, *, session: Session) -> Page:
        """取到这个番号的作品页。要先搜索的站在这里搜；找不到抛 `SourceFailure(NOT_FOUND)`。"""
        raise NotImplementedError

    def parse(self, page: Page, code: str) -> SiteRecord:
        """从作品页读出记录。页面结构对不上抛 `SourceFailure(PARSE_ERROR)`，门页抛 `AUTH_REQUIRED`。"""
        raise NotImplementedError

    @contextmanager
    def holding(self, session: Session):
        """包住一次查询：`fetch` 的 HTTP 分档翻成 `SourceFailure`，要整站停下的细档写回来源冷却。"""
        try:
            yield
        except SourceFailure as failure:
            _hold(session, self.config.name, failure)
            raise
        except Unavailable as error:
            failure = http_failure(error)
            _hold(session, self.config.name, failure)
            raise failure from None

    def query(self, code: str, *, session: Session) -> SiteRecord:
        with self.holding(session):
            return self.parse(self.fetch(code, session=session), code)

    def records(self, code: str, *, session: Session) -> list[SiteRecord]:
        """这一站对这个番号给出的全部记录。多数站只有一条。"""
        return [self.query(code, session=session)]


def _hold(session: Session, source: str, failure: SourceFailure) -> None:
    """把 `failure` 的冷却档交给会话传输链上的 `hold`；一个失败只记一次。"""
    if not failure.cooldown_action or failure.held:
        return
    failure.held = True
    transport = session.transport
    while transport is not None and not callable(getattr(transport, "hold", None)):
        transport = getattr(transport, "inner", None)
    if transport is not None:
        transport.hold(source, failure.cooldown_action)
