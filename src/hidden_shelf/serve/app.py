"""进度网页的 HTTP 层：一页静态界面、三个 JSON 接口、一条 SSE 流。只打算监听 127.0.0.1。

同源防护：`POST` 和 `GET /api/browse` 要带 `X-Shelf-Request: 1`，且 `Origin`（没有则 `Referer`）的主机是 `127.0.0.1` 或
`localhost`，否则 403——挡住别的网页借浏览器打 localhost。其余 `GET` 不查（页面、静态文件、状态、SSE）。
目录列举只列目录、不读文件（`browse.py`），响应 `no-store`。
SSE：先按 `Last-Event-ID` 补发，再订阅实时事件；运行已结束则补完即停；15 秒没事件发 `: ping` 保活。
"""
from __future__ import annotations

import queue
import webbrowser
from collections.abc import Callable, Iterator
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import __version__, pipeline
from .browse import BrowseError, list_directory, list_roots
from .events import RunLog
from .runner import RunBusy, RunManager, RunOptions
from .sources import LoginBusy, SourcePanel

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE_DIR = Path(__file__).parent / "templates"
#: 浏览器里页面的脚本发请求时带的头；别的站点的脚本借浏览器发不出这个头又过同源校验的请求。
REQUEST_HEADER = "x-shelf-request"
TRUSTED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
PING_SECONDS = 15.0
STATIC_TYPES = {".css": "text/css", ".js": "application/javascript", ".svg": "image/svg+xml", ".png": "image/png"}
#: 读本机目录结构的 GET 也要过同源校验。
GUARDED_GET_PATHS = frozenset({"/api/browse", "/api/sources"})


def _trusted_origin(request: Request) -> bool:
    if request.headers.get(REQUEST_HEADER) != "1":
        return False
    source = request.headers.get("origin") or request.headers.get("referer") or ""
    host = (urlsplit(source).hostname or "").lower()
    return host in TRUSTED_HOSTS


def sse_stream(log: RunLog, last_seq: int, *, ping_seconds: float = PING_SECONDS) -> Iterator[str]:
    """同步生成器：补发 → 实时 → 结束。Starlette 在线程池里迭代它，不堵事件循环。"""
    subscriber = log.subscribe()
    try:
        sent = last_seq
        for event in log.since(last_seq):
            yield event.to_sse()
            sent = event.seq
        # 订阅之前到订阅之后可能漏一截，再补一次。
        for event in log.since(sent):
            yield event.to_sse()
            sent = event.seq
        while True:
            try:
                item = subscriber.get(timeout=ping_seconds)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if item is None:
                for event in log.since(sent):
                    yield event.to_sse()
                return
            if item.seq <= sent:
                continue
            yield item.to_sse()
            sent = item.seq
    finally:
        log.unsubscribe(subscriber)


def create_app(manager: RunManager | None = None, *, static_dir: Path = STATIC_DIR, template_dir: Path = TEMPLATE_DIR,
               opener: Callable[[str], object] = webbrowser.open, ping_seconds: float = PING_SECONDS,
               panel: SourcePanel | None = None) -> FastAPI:
    manager = manager or RunManager()
    panel = panel or SourcePanel()
    app = FastAPI(title="Hidden Shelf 进度", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    environment = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    app.state.manager = manager

    @app.middleware("http")
    async def same_origin_guard(request: Request, call_next):
        guarded = request.method in ("POST", "PUT", "PATCH", "DELETE") or request.url.path in GUARDED_GET_PATHS
        if guarded and not _trusted_origin(request):
            return JSONResponse({"error": "请求来源不被信任"}, status_code=403)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        template = environment.get_template("progress.html.j2")
        return HTMLResponse(template.render(version=__version__, language="zh", steps=list(pipeline.STEPS),
                                           step_labels=pipeline.STEP_LABELS))

    @app.get("/static/{name:path}")
    def static(name: str):
        base = static_dir.resolve()
        target = (base / name).resolve()
        if base not in target.parents or not target.is_file():
            return JSONResponse({"error": "没有这个文件"}, status_code=404)
        return FileResponse(target, media_type=STATIC_TYPES.get(target.suffix, "application/octet-stream"),
                            headers={"Cache-Control": "no-cache"})

    @app.get("/api/state")
    def state() -> dict:
        return {**manager.state(), "version": __version__, "recent_roots": manager.recent_roots(),
                "steps_order": list(pipeline.STEPS), "step_labels": dict(pipeline.STEP_LABELS)}

    @app.post("/api/run")
    async def start(request: Request):
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({"error": "请求体不是合法 JSON"}, status_code=400)
        try:
            options = RunOptions.from_payload(payload)
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        try:
            run_id = manager.start(options)
        except RunBusy as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse({"run": run_id}, status_code=202)

    @app.post("/api/cancel")
    def cancel():
        if not manager.cancel():
            return JSONResponse({"error": "没有正在进行的运行"}, status_code=409)
        return JSONResponse({"cancelled": True}, status_code=202)

    @app.post("/api/open")
    async def open_result(request: Request):
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({"error": "请求体不是合法 JSON"}, status_code=400)
        root = Path(str((payload or {}).get("root") or "")).expanduser()
        index_html = root / "index.html"
        if not str(root.name) or not index_html.is_file():
            return JSONResponse({"error": "还没有成品，先跑一次"}, status_code=404)
        uri = index_html.resolve().as_uri()
        opener(uri)
        return {"opened": uri}

    @app.get("/api/browse")
    def browse(path: str = "", show_hidden: str = "0"):
        headers = {"Cache-Control": "no-store"}
        if not path:
            return JSONResponse({"roots": [asdict(root) for root in list_roots()]}, headers=headers)
        try:
            listing = list_directory(path, show_hidden=show_hidden == "1")
        except BrowseError as error:
            return JSONResponse({"error": error.message}, status_code=error.status, headers=headers)
        return JSONResponse(asdict(listing), headers=headers)

    async def _json(request: Request):
        try:
            payload = await request.json()
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else {}

    @app.get("/api/sources")
    def sources(root: str = ""):
        return JSONResponse(panel.list_sources(root or None), headers={"Cache-Control": "no-store"})

    @app.post("/api/sources")
    async def set_source(request: Request):
        payload = await _json(request)
        if payload is None:
            return JSONResponse({"error": "请求体不是合法 JSON"}, status_code=400)
        if not isinstance(payload.get("enabled"), bool):
            return JSONResponse({"error": "enabled 要是 true 或 false"}, status_code=400)
        try:
            panel.set_enabled(str(payload.get("name") or ""), payload["enabled"])
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        return {"ok": True}

    @app.post("/api/login")
    async def start_login(request: Request):
        payload = await _json(request)
        if payload is None:
            return JSONResponse({"error": "请求体不是合法 JSON"}, status_code=400)
        try:
            panel.start_login(str(payload.get("name") or ""))
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        except LoginBusy as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse({"started": True}, status_code=202)

    @app.post("/api/login/finish")
    async def finish_login(request: Request):
        payload = await _json(request)
        if payload is None:
            return JSONResponse({"error": "请求体不是合法 JSON"}, status_code=400)
        if not panel.finish_login(str(payload.get("name") or "")):
            return JSONResponse({"error": "这一站没有正在进行的登录"}, status_code=409)
        return JSONResponse({"finished": True}, status_code=202)

    @app.post("/api/cooldown/clear")
    async def clear_cooldown(request: Request):
        payload = await _json(request)
        if payload is None:
            return JSONResponse({"error": "请求体不是合法 JSON"}, status_code=400)
        try:
            cleared = panel.clear_cooldown(str(payload.get("root") or ""), str(payload.get("name") or "") or None)
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        return {"cleared": cleared}

    @app.get("/api/events")
    def events(request: Request, run: str | None = None):
        log = manager.log_for(run)
        if log is None:
            return JSONResponse({"error": "没有这次运行的记录"}, status_code=404)
        header = request.headers.get("last-event-id", "0")
        try:
            last_seq = max(0, int(header))
        except ValueError:
            last_seq = 0
        return StreamingResponse(sse_stream(log, last_seq, ping_seconds=ping_seconds), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})

    return app
