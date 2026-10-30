"""传输层：有界读取、重定向规则、主机限速、重试与 HTTP 分档。"""
from __future__ import annotations

import httpx
import pytest

from hidden_shelf.scrape import transport as tp
from hidden_shelf.scrape.transport import (
    USER_AGENT,
    HostLimiter,
    HttpRequest,
    HttpResponse,
    HttpxTransport,
    NotFound,
    PageTooLarge,
    Unavailable,
    fetch,
    follow_redirects,
    host_under,
)


def _httpx(handler) -> HttpxTransport:
    return HttpxTransport(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False))


def test_httpx_transport_returns_response_and_bounds_body():
    def handler(request):
        return httpx.Response(200, headers={"X-A": "1"}, content=b"x" * 100, request=request)
    transport = _httpx(handler)
    response = transport(HttpRequest("GET", "https://example.com/a", {"User-Agent": USER_AGENT}, None), 5.0, 1000)
    assert isinstance(response, HttpResponse)
    assert (response.status, response.headers["x-a"], len(response.body), response.url) == (200, "1", 100, "https://example.com/a")
    with pytest.raises(PageTooLarge):
        transport(HttpRequest("GET", "https://example.com/a", {}, None), 5.0, 50)
    transport.close()


def test_httpx_transport_posts_body_and_does_not_follow_redirects():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["body"] = request.content
        if request.url.path == "/r":
            return httpx.Response(302, headers={"Location": "https://example.com/other"}, request=request)
        return httpx.Response(200, content=b"ok", request=request)
    transport = _httpx(handler)
    transport(HttpRequest("POST", "https://example.com/p", {}, b'{"q":1}'), 5.0, 100)
    assert seen == {"method": "POST", "body": b'{"q":1}'}
    response = transport(HttpRequest("GET", "https://example.com/r", {}, None), 5.0, 100)
    assert response.status == 302 and response.headers["location"] == "https://example.com/other"


def test_host_under_matches_on_dot_boundaries():
    assert host_under("javdb.com", "javdb.com")
    assert host_under("img.javdb.com", "javdb.com")
    assert not host_under("notjavdb.com", "javdb.com")
    assert not host_under("javdb.com.evil", "javdb.com")


def test_host_limiter_spaces_requests():
    clock = {"now": 100.0}
    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        clock["now"] += seconds

    limiter = HostLimiter({"javdb.com": 3.0}, default=2.0, clock=lambda: clock["now"], sleep=sleep)
    limiter.wait("example.com")
    limiter.wait("example.com")
    assert slept == [2.0]
    limiter.wait("img.javdb.com")
    limiter.wait("javdb.com")
    assert slept[-1] == 3.0
    clock["now"] += 10
    limiter.wait("example.com")
    assert len(slept) == 2


class _Script:
    """按顺序回放的假传输：元素是 HttpResponse 或要抛的异常。"""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls: list[HttpRequest] = []

    def __call__(self, request, timeout, limit):
        self.calls.append(request)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _ok(body=b"ok", url="https://example.com/x", status=200, headers=None):
    return HttpResponse(status, {k.lower(): v for k, v in (headers or {}).items()}, body, url)


def test_fetch_retries_transport_errors_then_raises(monkeypatch):
    delays: list[float] = []
    monkeypatch.setattr(tp.time, "sleep", delays.append)
    script = _Script(*[httpx.ConnectError("boom")] * 4, _ok())
    assert fetch(script, "https://example.com/x", referer="https://example.com/", limit=100) == b"ok"
    assert delays == [2, 4, 6, 8] and len(script.calls) == 5
    assert script.calls[0].headers["User-Agent"] == USER_AGENT
    assert script.calls[0].headers["Referer"] == "https://example.com/"
    failing = _Script(*[httpx.ConnectError("boom")] * 5)
    with pytest.raises(httpx.TransportError):
        fetch(failing, "https://example.com/x", referer="https://example.com/", limit=100)


def test_fetch_tiers():
    with pytest.raises(NotFound) as caught:
        fetch(_Script(_ok(status=404)), "https://example.com/x", referer="r", limit=10)
    assert str(caught.value) == "HTTP 404"
    with pytest.raises(Unavailable) as caught:
        fetch(_Script(_ok(status=503)), "https://example.com/x", referer="r", limit=10)
    assert str(caught.value) == "HTTP 503"
    assert not isinstance(caught.value, NotFound)
    with pytest.raises(NotFound) as caught:
        fetch(_Script(_ok(url="https://pics.dmm.co.jp/mono/movie/adult/now_printing/now_printing.jpg")),
              "https://example.com/x", referer="r", limit=10)
    assert "占位图" in str(caught.value)
    assert fetch(_Script(_ok(status=206, body=b"part")), "https://example.com/x", referer="r", limit=10) == b"part"


def test_fetch_ranged_header_and_extra_headers_and_post():
    script = _Script(_ok(), _ok())
    fetch(script, "https://example.com/x", referer="r", limit=10, ranged=True, extra_headers={"X-Y": "z"})
    assert script.calls[0].headers["Range"] == "bytes=0-65535"
    assert script.calls[0].headers["X-Y"] == "z"
    fetch(script, "https://example.com/g", referer="r", limit=10, method="POST", body=b"{}")
    assert script.calls[1].method == "POST" and script.calls[1].body == b"{}"


def test_fetch_deadline():
    with pytest.raises(tp.DeadlineExceeded):
        fetch(_Script(_ok()), "https://example.com/x", referer="r", limit=10, deadline=tp.time.monotonic() - 1)


def test_redirect_rules():
    hop = _ok(status=302, headers={"Location": "/next"}, url="https://a.example/x")
    script = _Script(hop, _ok(url="https://a.example/next"))
    response = follow_redirects(script, HttpRequest("GET", "https://a.example/x", {"Cookie": "k=v"}, None), 5.0, 100)
    assert response.url == "https://a.example/next"
    assert script.calls[1].url == "https://a.example/next" and script.calls[1].headers["Cookie"] == "k=v"
    # 跨域去 Cookie
    script = _Script(_ok(status=301, headers={"Location": "https://b.example/y"}), _ok(url="https://b.example/y"))
    follow_redirects(script, HttpRequest("GET", "https://a.example/x", {"Cookie": "k=v", "Referer": "r"}, None), 5.0, 100)
    assert "Cookie" not in script.calls[1].headers and script.calls[1].headers["Referer"] == "r"
    # 303 改 GET 去 body
    script = _Script(_ok(status=303, headers={"Location": "https://a.example/z"}), _ok())
    follow_redirects(script, HttpRequest("POST", "https://a.example/x", {}, b"body"), 5.0, 100)
    assert script.calls[1].method == "GET" and script.calls[1].body is None
    # 只跟 HTTPS
    with pytest.raises(ValueError):
        follow_redirects(_Script(_ok(status=302, headers={"Location": "http://a.example/plain"})),
                         HttpRequest("GET", "https://a.example/x", {}, None), 5.0, 100)
    # 超过 6 跳
    loops = _Script(*[_ok(status=302, headers={"Location": "https://a.example/again"})] * 7)
    with pytest.raises(ValueError):
        follow_redirects(loops, HttpRequest("GET", "https://a.example/x", {}, None), 5.0, 100)


def test_fetch_follows_redirects():
    script = _Script(_ok(status=302, headers={"Location": "https://a.example/final"}), _ok(body=b"done", url="https://a.example/final"))
    assert fetch(script, "https://a.example/x", referer="r", limit=10) == b"done"


def test_curl_transport_optional():
    from hidden_shelf.scrape.transport import CurlTransport
    assert isinstance(CurlTransport.available(), bool)
    if not CurlTransport.available():
        with pytest.raises(RuntimeError):
            CurlTransport()
