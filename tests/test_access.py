"""来源冷却与按来源传输。部分断言搬自 peach `tests/test_metadata_sources.py` 的 `SiteCooldownTests`。"""
from __future__ import annotations

import json
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from hidden_shelf.netconfig import GlobalConfig, SourceSettings
from hidden_shelf.scrape.access import (
    FIRST_BLOCKED_PAUSE,
    SOURCES,
    Cooldown,
    SourcePaused,
    SourceTransport,
    cookie_jar,
    source_for,
)
from hidden_shelf.scrape.sources import FailureReason, Session, SiteConfig, SiteRecord, SiteSource, SourceFailure
from hidden_shelf.scrape.transport import USER_AGENT, HostLimiter, HttpRequest, HttpResponse


class Clock:
    def __init__(self, start=1_000_000.0):
        self.now = start

    def __call__(self):
        return self.now


def test_source_for_matches_domains():
    assert source_for("https://javdb.com/v/x") == "javdb"
    assert source_for("https://c0.jdbstatic.com/covers/x.jpg") == "javdb"
    assert source_for("https://www.javbus.com/ABW-358") == "javbus"
    assert source_for("https://api.video.dmm.co.jp/graphql") == "dmm"
    assert source_for("https://img.javstore.net/x.jpg") == "javarchive"
    assert source_for("https://example.com/") is None
    assert set(SOURCES) == {"r18dev", "dmm", "1pondo", "fc2", "javarchive", "javdb", "javbus", "avbase"}


def test_cooldown_blocked_doubles_to_cap(tmp_path: Path):
    clock = Clock()
    cooldown = Cooldown(tmp_path / "_cooldown.json", now=clock)
    assert cooldown.paused_until("javbus") == 0.0
    cooldown.pause("javbus", action="blocked")
    assert round(cooldown.paused_until("javbus") - clock.now) == FIRST_BLOCKED_PAUSE
    cooldown.pause("javbus", action="blocked")
    assert round(cooldown.paused_until("javbus") - clock.now) == 1800
    for _ in range(10):
        cooldown.pause("javbus", action="blocked")
    assert round(cooldown.paused_until("javbus") - clock.now) == SOURCES["javbus"]["blocked_pause"]
    cooldown.pause("javdb", action="blocked")
    assert cooldown.blocks("javdb") == 1
    with pytest.raises(ValueError):
        cooldown.pause("javdb", action="bogus")


def test_cooldown_rate_limited_uses_retry_after(tmp_path: Path):
    clock = Clock()
    cooldown = Cooldown(tmp_path / "_cooldown.json", now=clock)
    cooldown.pause("r18dev", action="rate_limited", retry_after=120)
    assert round(cooldown.paused_until("r18dev") - clock.now) == 120
    cooldown.pause("dmm", action="rate_limited")
    assert round(cooldown.paused_until("dmm") - clock.now) == 900
    assert cooldown.blocks("dmm") == 0


def test_cooldown_persists_and_clears(tmp_path: Path):
    clock = Clock()
    path = tmp_path / "_cooldown.json"
    Cooldown(path, now=clock).pause("javdb", action="blocked")
    again = Cooldown(path, now=clock)
    assert again.paused_until("javdb") > clock.now
    assert again.describe()["javdb"]["blocks"] == 1
    clock.now += FIRST_BLOCKED_PAUSE + 1
    assert again.paused_until("javdb") == 0.0
    assert again.describe() == {}
    again.clear("javdb")
    assert json.loads(path.read_text(encoding="utf-8")) == {}
    path.write_text("{broken", encoding="utf-8")
    assert Cooldown(path, now=clock).paused_until("javdb") == 0.0


def test_cookie_jar_scopes_to_source_domain():
    jar = cookie_jar("session=abc; theme=dark", "javdb")
    cookies = {cookie.name: cookie for cookie in jar}
    assert cookies["session"].value == "abc" and cookies["session"].domain == "javdb.com"
    assert len(cookie_jar("", "javdb")) == 0
    with pytest.raises(ValueError):
        cookie_jar("a=b\nc=d", "javdb")


def _fake(responses):
    calls = []

    def factory(source):
        def transport(request, timeout, limit):
            calls.append(request)
            answer = responses(request) if callable(responses) else responses
            if isinstance(answer, Exception):
                raise answer
            return answer
        return transport
    factory.calls = calls
    return factory


def _transport(tmp_path, responses, clock=None, config=None, **kwargs):
    clock = clock or Clock()
    cooldown = Cooldown(tmp_path / "_cooldown.json", now=clock)
    factory = _fake(responses)
    limiter = HostLimiter({}, default=0.0, clock=clock, sleep=lambda s: None)
    transport = SourceTransport(cooldown, config or GlobalConfig(), limiter=limiter, factory=factory, now=clock, **kwargs)
    return transport, factory.calls, cooldown, clock


def test_source_transport_403_pauses_javdb_but_not_r18dev(tmp_path: Path):
    transport, calls, cooldown, clock = _transport(tmp_path, lambda r: HttpResponse(403, {}, b"", r.url))
    with pytest.raises(SourcePaused) as caught:
        transport(HttpRequest("GET", "https://javdb.com/v/1", {}, None), 5.0, 100)
    assert "Cookie" in str(caught.value)
    assert cooldown.blocks("javdb") == 1
    with pytest.raises(SourcePaused):
        transport(HttpRequest("GET", "https://javdb.com/v/2", {}, None), 5.0, 100)
    assert len(calls) == 1, "冷却期内第二部片一次都不问"
    response = transport(HttpRequest("GET", "https://r18.dev/x", {}, None), 5.0, 100)
    assert response.status == 403 and cooldown.paused_until("r18dev") == 0.0


def test_source_transport_429_uses_retry_after_and_success_clears(tmp_path: Path):
    state = {"status": 429}

    def respond(request):
        when = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=300))
        return HttpResponse(state["status"], {"retry-after": when}, b"", request.url)
    transport, calls, cooldown, clock = _transport(tmp_path, respond)
    with pytest.raises(SourcePaused):
        transport(HttpRequest("GET", "https://r18.dev/x", {}, None), 5.0, 100)
    assert 280 <= cooldown.paused_until("r18dev") - clock.now <= 310
    clock.now += 400
    state["status"] = 200
    cooldown.pause("r18dev", action="blocked")
    clock.now += FIRST_BLOCKED_PAUSE + 1
    assert transport(HttpRequest("GET", "https://r18.dev/x", {}, None), 5.0, 100).status == 200
    assert cooldown.blocks("r18dev") == 0


def test_source_transport_javbus_language_and_budget(tmp_path: Path):
    transport, calls, cooldown, clock = _transport(tmp_path, lambda r: HttpResponse(200, {}, b"", r.url), max_requests=2)
    transport(HttpRequest("GET", "https://www.javbus.com/ABW-358", {"Accept-Language": "ja"}, None), 5.0, 100)
    assert calls[0].headers["Accept-Language"] == "zh-CN,zh;q=0.9"
    transport(HttpRequest("GET", "https://r18.dev/x", {}, None), 5.0, 100)
    with pytest.raises(SourcePaused):
        transport(HttpRequest("GET", "https://r18.dev/y", {}, None), 5.0, 100)


def test_source_transport_wraps_connection_errors(tmp_path: Path):
    transport, calls, cooldown, clock = _transport(tmp_path, httpx.ConnectError("boom"))
    with pytest.raises(httpx.TransportError):
        transport(HttpRequest("GET", "https://r18.dev/x", {}, None), 5.0, 100)


def test_source_transport_respects_limiter(tmp_path: Path):
    waited = []
    clock = Clock()
    cooldown = Cooldown(tmp_path / "_cooldown.json", now=clock)

    class Limiter(HostLimiter):
        def wait(self, host):
            waited.append(host)
    transport = SourceTransport(cooldown, GlobalConfig(), limiter=Limiter({}), factory=_fake(lambda r: HttpResponse(200, {}, b"", r.url)))
    transport(HttpRequest("GET", "https://c0.jdbstatic.com/x.jpg", {}, None), 5.0, 100)
    assert waited == ["c0.jdbstatic.com"]


def test_source_transport_sends_cookie_only_to_its_domains(tmp_path: Path):
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("cookie")))
        return httpx.Response(200, content=b"ok", request=request)
    config = GlobalConfig(network_mode="direct", sources={"javdb": SourceSettings(cookie="session=abc")})
    cooldown = Cooldown(tmp_path / "_cooldown.json")
    transport = SourceTransport(cooldown, config, limiter=HostLimiter({}, default=0.0, sleep=lambda s: None),
                                httpx_transport=httpx.MockTransport(handler))
    transport(HttpRequest("GET", "https://javdb.com/v/1", {"User-Agent": "x"}, None), 5.0, 100)
    transport(HttpRequest("GET", "https://www.javbus.com/ABW-358", {}, None), 5.0, 100)
    assert seen[0][1] == "session=abc"
    assert seen[1][1] is None
    transport.close()


def test_hold_records_contract_reasons_like_a_refusal(tmp_path: Path):
    """自写站报出 COOLDOWN_ACTIONS 里的细档时整站进冷却；别的细档不记。"""
    transport, calls, cooldown, clock = _transport(tmp_path, lambda r: HttpResponse(200, {}, b"page", r.url))
    config = SiteConfig(name="javbus", label="JavBus", provider="javbus-page", base_url="https://www.javbus.com",
                        domains=("javbus.com",), stage="community")

    class Failing(SiteSource):
        DEFAULT = config
        reason = FailureReason.NOT_FOUND

        def fetch(self, code, *, session):
            return session.get(f"{self.config.base_url}/{code}", config=self.config)

        def parse(self, page, code):
            raise SourceFailure(self.reason, "demo")

    session = Session(transport)
    for reason in FailureReason:
        cooldown.clear("javbus")
        Failing.reason = reason
        with pytest.raises(SourceFailure):
            Failing().query("ABC-001", session=session)
        action = {"cloudflare_challenge": "blocked", "ip_banned": "blocked", "geo_restricted": "blocked",
                  "rate_limited": "rate_limited"}.get(reason.value, "")
        if action == "blocked":
            assert (round(cooldown.paused_until("javbus") - clock.now), cooldown.blocks("javbus")) == (FIRST_BLOCKED_PAUSE, 1)
        elif action == "rate_limited":
            assert (round(cooldown.paused_until("javbus") - clock.now), cooldown.blocks("javbus")) == (900, 0)
        else:
            assert cooldown.paused_until("javbus") == 0.0


def test_a_nested_query_counts_one_failure_once(tmp_path: Path):
    transport, calls, cooldown, clock = _transport(tmp_path, lambda r: HttpResponse(200, {}, b"page", r.url))
    config = SiteConfig(name="javdb", label="javdb", provider="javdb-page", base_url="https://javdb.com",
                        domains=("javdb.com",), stage="community")

    class Nested(SiteSource):
        DEFAULT = config

        def fetch(self, code, *, session):
            return session.get(f"{self.config.base_url}/{code}", config=self.config)

        def parse(self, page, code):
            raise SourceFailure(FailureReason.IP_BANNED, "demo")

        def query(self, code, *, session):
            with self.holding(session):
                return super().query(code, session=session)
    with pytest.raises(SourceFailure):
        Nested().query("ABC-001", session=Session(transport))
    assert cooldown.blocks("javdb") == 1


def test_source_transport_uses_saved_user_agent_and_cookie_for_any_source(tmp_path: Path):
    """登录抓来的 Cookie 绑着那个浏览器的 UA：有 UA 就用它；没登记 cookie: True 的站有 Cookie 也照样带
    （这里 avbase 没装 curl_cffi，走 httpx 这条）。"""
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("cookie"), request.headers.get("user-agent")))
        return httpx.Response(200, content=b"ok", request=request)
    config = GlobalConfig(network_mode="direct", sources={
        "avbase": SourceSettings(cookie="cf_clearance=zzz", user_agent="Mozilla/5.0 Mine"),
        "javdb": SourceSettings(cookie="session=abc")})
    cooldown = Cooldown(tmp_path / "_cooldown.json")
    transport = SourceTransport(cooldown, config, limiter=HostLimiter({}, default=0.0, sleep=lambda s: None),
                                httpx_transport=httpx.MockTransport(handler))
    transport(HttpRequest("GET", "https://www.avbase.net/works?q=x", {}, None), 5.0, 100)
    transport(HttpRequest("GET", "https://javdb.com/v/1", {}, None), 5.0, 100)
    assert seen[0][1] == "cf_clearance=zzz" and seen[0][2] == "Mozilla/5.0 Mine"
    assert seen[1][1] == "session=abc" and seen[1][2] == USER_AGENT
    transport.close()


def test_fingerprint_source_uses_curl_transport_without_cookies(tmp_path: Path, monkeypatch):
    """avbase 的 Cloudflare 看 TLS 指纹：装了 curl_cffi 就走 CurlTransport，且不带用户 Cookie（带了反而撞验证）。"""
    from hidden_shelf.scrape import access

    made = []

    class FakeCurl:
        def __init__(self, *, impersonate="chrome", client_options=None):
            made.append((impersonate, client_options))
        @staticmethod
        def available():
            return True
        def __call__(self, request, timeout, max_bytes):
            return HttpResponse(200, {}, b"ok", request.url)
        def close(self):
            pass
    monkeypatch.setattr(access, "CurlTransport", FakeCurl)
    config = GlobalConfig(network_mode="direct", sources={"avbase": SourceSettings(cookie="cf_clearance=zzz", user_agent="UA")})
    transport = SourceTransport(Cooldown(tmp_path / "_cooldown.json"), config, limiter=HostLimiter({}, default=0.0, sleep=lambda s: None))
    response = transport(HttpRequest("GET", "https://www.avbase.net/works?q=x", {}, None), 5.0, 100)
    assert response.status == 200 and made == [("chrome", {"trust_env": False})]
    assert isinstance(transport.transports["avbase"], FakeCurl)
    # javdb 不在指纹名单里，照旧 httpx。
    assert "javdb" not in transport.transports
    transport.close()
