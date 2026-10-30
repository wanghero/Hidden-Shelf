"""站点解析器契约。搬自 peach `tests/test_metadata_sources.py` 的 `ContractTests`、`FailureReasonTests`。"""
from __future__ import annotations

import httpx
import pytest

from hidden_shelf.scrape import transport as tp
from hidden_shelf.scrape.sources import (
    COOLDOWN_ACTIONS,
    MISS_REASONS,
    PERMANENT_REASONS,
    REASON_KINDS,
    FailureReason,
    Page,
    Session,
    SiteConfig,
    SiteRecord,
    SiteSource,
    SourceFailure,
    challenge_page,
    http_failure,
)
from hidden_shelf.scrape.transport import DeadlineExceeded, HttpResponse, NotFound, Unavailable

DEMO = SiteConfig(name="demo", label="Demo", provider="demo-page", base_url="https://demo.test",
                  domains=("demo.test",), stage="community")


class DemoSource(SiteSource):
    """最小的一站：作品页是 `/<番号>`，页面正文就是标题。"""

    DEFAULT = DEMO

    def fetch(self, code, *, session):
        return session.get(f"{self.config.base_url}/{code}", config=self.config)

    def parse(self, page, code):
        if page.text == "gate":
            raise SourceFailure(FailureReason.AUTH_REQUIRED, "Demo 要求登录")
        if page.text == "banned":
            raise SourceFailure(FailureReason.IP_BANNED, "封了")
        return SiteRecord(source=self.config.name, provenance=self.config.provider, code=code,
                          source_url=page.url, title=page.text)


def serve(pages):
    calls = []

    def call(request, timeout, limit):
        calls.append((request.url, request.headers.get("Referer"), limit))
        body = pages.get(request.url)
        if isinstance(body, Exception):
            raise body
        return HttpResponse(200 if body is not None else 404, {}, body or b"", request.url)

    call.calls = calls
    return call


def test_parse_reads_a_page_without_any_transport():
    record = DemoSource().parse(Page("https://demo.test/ABC-001", "標題".encode()), "ABC-001")
    assert (record.source, record.provenance, record.title, record.source_url) == (
        "demo", "demo-page", "標題", "https://demo.test/ABC-001")


def test_fetch_uses_the_config_for_referer_and_page_limit_and_query_chains_both_steps():
    transport = serve({"https://demo.test/ABC-001": "標題".encode()})
    record = DemoSource().query("ABC-001", session=Session(transport))
    assert record.title == "標題"
    assert transport.calls == [("https://demo.test/ABC-001", "https://demo.test/", DEMO.page_limit)]


def test_an_injected_config_replaces_the_default_one():
    mirror = SiteConfig(name="demo", label="Demo", provider="demo-page", base_url="https://mirror.test",
                        domains=("mirror.test",), stage="community", page_limit=1024)
    transport = serve({"https://mirror.test/ABC-001": b"x"})
    DemoSource(mirror).query("ABC-001", session=Session(transport))
    assert transport.calls == [("https://mirror.test/ABC-001", "https://mirror.test/", 1024)]
    assert DemoSource().config is DEMO


def test_one_request_can_name_its_own_referer_and_extra_headers():
    seen = []

    def transport(request, timeout, limit):
        seen.append((request.headers.get("Referer"), request.headers.get("X-Inertia")))
        return HttpResponse(200, {}, b"x", request.url)

    session = Session(transport)
    session.get("https://demo.test/ABC-001", config=DEMO)
    session.get("https://demo.test/ABC-001", config=DEMO, referer="https://demo.test/ABC-001", headers={"X-Inertia": "true"})
    assert seen == [("https://demo.test/", None), ("https://demo.test/ABC-001", "true")]


def test_post_sends_the_body_with_the_same_referer_limit_and_extra_headers():
    seen = []

    def transport(request, timeout, limit):
        seen.append((request.method, request.url, request.body, request.headers.get("Referer"),
                     request.headers.get("Content-Type"), limit))
        return HttpResponse(200, {}, b'{"data": {}}', request.url)

    page = Session(transport).post("https://demo.test/graphql", config=DEMO, body=b'{"query": "x"}',
                                   headers={"Content-Type": "application/json"})
    assert seen == [("POST", "https://demo.test/graphql", b'{"query": "x"}', "https://demo.test/",
                     "application/json", DEMO.page_limit)]
    assert (page.url, page.body) == ("https://demo.test/graphql", b'{"data": {}}')


def test_records_default_to_the_single_query_result():
    transport = serve({"https://demo.test/ABC-001": "標題".encode()})
    assert [record.title for record in DemoSource().records("ABC-001", session=Session(transport))] == ["標題"]
    with pytest.raises(SourceFailure):
        DemoSource().records("ABC-002", session=Session(transport))


def test_query_translates_http_tiers_into_reasons_and_keeps_the_wording():
    with pytest.raises(SourceFailure) as caught:
        DemoSource().query("ABC-001", session=Session(serve({})))
    assert (caught.value.reason, caught.value.status_code, str(caught.value)) == (FailureReason.NOT_FOUND, 404, "HTTP 404")
    assert caught.value.is_miss
    for status, reason in ((401, FailureReason.AUTH_REQUIRED), (403, FailureReason.AUTH_REQUIRED),
                           (410, FailureReason.GONE), (429, FailureReason.RATE_LIMITED),
                           (500, FailureReason.SERVER_ERROR), (503, FailureReason.SERVER_ERROR),
                           (418, FailureReason.NETWORK)):
        failure = http_failure(Unavailable(f"HTTP {status}"))
        assert (failure.reason, failure.status_code, failure.message) == (reason, status, f"HTTP {status}")
    assert http_failure(NotFound("来源给的是占位图")).reason == FailureReason.NOT_FOUND


def test_query_passes_parse_failures_through_and_leaves_transport_signals_alone(monkeypatch):
    with pytest.raises(SourceFailure) as caught:
        DemoSource().query("ABC-001", session=Session(serve({"https://demo.test/ABC-001": b"gate"})))
    assert caught.value.reason == FailureReason.AUTH_REQUIRED

    class Paused(RuntimeError):
        pass

    monkeypatch.setattr(tp, "NETWORK_RETRY_DELAYS", ())
    for signal in (Paused("来源正在冷却"), DeadlineExceeded("动作预算已用尽"), httpx.TransportError("来源连接未取得")):
        with pytest.raises(type(signal)):
            DemoSource().query("ABC-001", session=Session(serve({"https://demo.test/ABC-001": signal})))


def test_the_record_projects_into_the_snapshot_shaped_payload():
    record = SiteRecord(source="demo", provenance="demo-page", code="ABC-001", source_url="https://demo.test/ABC-001",
                        title="標題", performers=({"japanese_name": "女優"},), studio="片商", runtime=90,
                        cover_urls=("https://demo.test/a.jpg", "https://demo.test/b.jpg"))
    assert record.cover_url == "https://demo.test/a.jpg"
    assert record.payload() == {
        "id": "ABC-001", "source_url": "https://demo.test/ABC-001", "title": "標題",
        "actresses": [{"japanese_name": "女優"}], "maker": "片商", "label": "", "series": "", "director": "",
        "release_date": "", "runtime": 90, "cover_urls": ["https://demo.test/a.jpg", "https://demo.test/b.jpg"],
        "cover_url": "https://demo.test/a.jpg"}
    tagged = SiteRecord(source="demo", provenance="demo-page", code="ABC-001", source_url="", tags=(), extra={"plot": "剧情"})
    payload = tagged.payload()
    assert (payload["genres"], payload["plot"], payload["cover_urls"], payload["cover_url"]) == ([], "剧情", [], "")
    assert "genres" not in record.payload()


def test_the_table_has_twelve_reasons_each_with_a_kind():
    assert {reason.value for reason in FailureReason} == {
        "cloudflare_challenge", "ip_banned", "geo_restricted", "auth_required", "not_found", "gone",
        "parse_error", "no_usable_metadata", "rate_limited", "timeout", "server_error", "network"}
    assert set(REASON_KINDS) == set(FailureReason)
    assert set(REASON_KINDS.values()) == {"auth", "unavailable", "not_found"}
    assert {reason for reason, kind in REASON_KINDS.items() if kind == "not_found"} == MISS_REASONS
    assert PERMANENT_REASONS == {FailureReason.PARSE_ERROR}
    assert SourceFailure(FailureReason.PARSE_ERROR, "x").retryable is False
    assert SourceFailure(FailureReason.TIMEOUT, "x").retryable is True
    assert SourceFailure(FailureReason.NOT_FOUND, "x").retryable is False


def test_only_bans_and_rate_limits_pause_a_whole_site():
    assert COOLDOWN_ACTIONS == {FailureReason.CLOUDFLARE_CHALLENGE: "blocked", FailureReason.IP_BANNED: "blocked",
                                FailureReason.GEO_RESTRICTED: "blocked", FailureReason.RATE_LIMITED: "rate_limited"}
    for reason in FailureReason:
        assert SourceFailure(reason, "").cooldown_action == COOLDOWN_ACTIONS.get(reason, "")


def test_challenge_page_titles():
    assert challenge_page(b"<html><head><title>Just a moment...</title></head></html>")
    assert challenge_page("<title>Attention Required! | Cloudflare</title>")
    assert challenge_page("<title>请稍候…</title>")
    assert not challenge_page("<title>ABW-358 | JavDB</title><script src=challenge-platform></script>")


class _Holding:
    def __init__(self, inner):
        self.inner = inner
        self.held = []

    def __call__(self, request, timeout, limit):
        return self.inner(request, timeout, limit)

    def hold(self, source, action):
        self.held.append((source, action))


def test_holding_records_cooldown_once_through_the_transport_chain():
    held = _Holding(serve({"https://demo.test/ABC-001": b"banned"}))

    class Outer:
        def __init__(self, inner):
            self.inner = inner

        def __call__(self, request, timeout, limit):
            return self.inner(request, timeout, limit)

    source = DemoSource()
    session = Session(Outer(held))
    with pytest.raises(SourceFailure):
        with source.holding(session):
            source.query("ABC-001", session=session)
    assert held.held == [("demo", "blocked")]
    # 没有 hold 的传输链不记，也不报错。
    plain = serve({"https://demo.test/ABC-001": b"banned"})
    with pytest.raises(SourceFailure):
        DemoSource().query("ABC-001", session=Session(plain))
    # 不进冷却的细档不记。
    held2 = _Holding(serve({"https://demo.test/ABC-001": b"gate"}))
    with pytest.raises(SourceFailure):
        DemoSource().query("ABC-001", session=Session(held2))
    assert held2.held == []
