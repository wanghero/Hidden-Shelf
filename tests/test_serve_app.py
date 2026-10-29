"""进度网页的 HTTP 接口与 SSE 流。流水线是假的（`tests/test_runner.py` 的 `fake_pipeline`）。"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hidden_shelf.serve.app import create_app
from hidden_shelf.serve.runner import RunManager
from serve_fakes import fake_pipeline

HEADERS = {"X-Shelf-Request": "1", "Origin": "http://127.0.0.1:8031"}


def make_client(tmp_path: Path, runner, **options):
    opened = []
    manager = RunManager(home=tmp_path / "home", run_pipeline=runner)
    # 测试里 ping 间隔很短：TestClient 提前关掉流时要等生成器下一次 yield，长间隔会把测试拖住。
    app = create_app(manager, opener=opened.append, ping_seconds=options.pop("ping_seconds", 0.05))
    client = TestClient(app)
    client.manager = manager
    client.opened = opened
    return client


def read_events(client, run_id, *, last_event_id=None, limit=None):
    """读 SSE 直到流结束或拿够 `limit` 条，返回 `(事件 dict 列表, id 列表)`。"""
    headers = {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else {}
    events, ids = [], []
    with client.stream("GET", f"/api/events?run={run_id}", headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        current_id = None
        for line in response.iter_lines():
            if line.startswith("id: "):
                current_id = int(line[4:])
            elif line.startswith("data: "):
                events.append(json.loads(line[6:]))
                ids.append(current_id)
                if limit is not None and len(events) >= limit:
                    break
    return events, ids


def test_index_and_static(tmp_path: Path):
    client = make_client(tmp_path, fake_pipeline())
    page = client.get("/")
    assert page.status_code == 200 and "progress.js" in page.text and 'lang="zh-CN"' in page.text
    assert "http://" not in page.text.replace("http://127.0.0.1", "") and "https://" not in page.text, "页面不加载外网资源"
    assert client.get("/static/tokens.css").status_code == 200
    assert client.get("/static/tokens.css").headers["content-type"].startswith("text/css")
    assert client.get("/static/../pyproject.toml").status_code == 404
    assert client.get("/static/..%2Fpyproject.toml").status_code == 404
    assert client.get("/static/nope.js").status_code == 404
    assert client.get("/docs").status_code == 404, "不开 swagger"


def test_state_before_any_run(tmp_path: Path):
    client = make_client(tmp_path, fake_pipeline())
    state = client.get("/api/state").json()
    assert state["running"] is False and state["run"] is None and state["recent_roots"] == []
    assert state["steps_order"] == ["scan", "import", "scrape", "organize", "media", "build"]
    assert {row["status"] for row in state["steps"].values()} == {"waiting"}
    assert state["step_labels"]["scrape"] == "刮削" and state["version"]


def test_run_then_events_stream_in_order(tmp_path: Path, tmp_root: Path):
    client = make_client(tmp_path, fake_pipeline())
    response = client.post("/api/run", json={"root": str(tmp_root), "offline": True}, headers=HEADERS)
    assert response.status_code == 202
    run_id = response.json()["run"]
    client.manager.wait(timeout=10)
    events, ids = read_events(client, run_id)
    assert ids == list(range(1, len(ids) + 1))
    assert events[0]["kind"] == "run.start" and events[-1]["kind"] == "run.done"
    assert events[0]["run"] == run_id and events[0]["stats"]["options"]["offline"] is True
    assert any(e["kind"] == "step.progress" and "第一行" in e["message"] for e in events), "中文不转义"
    assert client.get("/api/state").json()["recent_roots"] == [str(tmp_root.resolve())]


def test_reconnect_with_last_event_id_resumes(tmp_path: Path, tmp_root: Path):
    gate = threading.Event()
    client = make_client(tmp_path, fake_pipeline(gate=gate))
    run_id = client.post("/api/run", json={"root": str(tmp_root)}, headers=HEADERS).json()["run"]
    first, first_ids = read_events(client, run_id, limit=3)
    assert first_ids == [1, 2, 3]
    gate.set()
    client.manager.wait(timeout=10)
    rest, rest_ids = read_events(client, run_id, last_event_id=3)
    assert rest_ids[0] == 4 and rest[0]["seq"] == 4, "从第 4 条接着收，不重发"
    assert rest[-1]["kind"] == "run.done"
    everything, _ = read_events(client, run_id)
    assert [e["seq"] for e in everything] == first_ids + rest_ids
    # 运行结束后带 Last-Event-ID 再连：补回 run.done 后流结束。
    tail, _ = read_events(client, run_id, last_event_id=rest_ids[-1] - 1)
    assert [e["kind"] for e in tail] == ["run.done"]
    empty, _ = read_events(client, run_id, last_event_id=rest_ids[-1])
    assert empty == []


def test_busy_and_cancel(tmp_path: Path, tmp_root: Path):
    gate = threading.Event()
    client = make_client(tmp_path, fake_pipeline(gate=gate, check_cancel=True))
    assert client.post("/api/cancel", headers=HEADERS).status_code == 409
    run_id = client.post("/api/run", json={"root": str(tmp_root)}, headers=HEADERS).json()["run"]
    second = client.post("/api/run", json={"root": str(tmp_root)}, headers=HEADERS)
    assert second.status_code == 409 and "已有一个运行" in second.json()["error"]
    read_events(client, run_id, limit=4)  # 等到第一步 done
    cancelled = client.post("/api/cancel", headers=HEADERS)
    assert cancelled.status_code == 202 and cancelled.json() == {"cancelled": True}
    gate.set()
    client.manager.wait(timeout=10)
    events, _ = read_events(client, run_id)
    assert events[-1]["kind"] == "run.cancelled"
    assert client.post("/api/cancel", headers=HEADERS).status_code == 409
    state = client.get("/api/state").json()
    assert state["running"] is False and state["result"]["cancelled"] is True
    # 结束后能开新一轮，序号从 1 起、run 换新。
    again = client.post("/api/run", json={"root": str(tmp_root)}, headers=HEADERS).json()["run"]
    assert again != run_id
    gate.set()
    client.manager.wait(timeout=10)
    events, ids = read_events(client, again)
    assert ids[0] == 1 and events[0]["run"] == again
    assert client.get(f"/api/events?run={run_id}").status_code == 404, "旧运行不再保留"


def test_bad_root_and_bad_json_are_400(tmp_path: Path, tmp_root: Path):
    client = make_client(tmp_path, fake_pipeline())
    response = client.post("/api/run", json={"root": str(tmp_root / "nope")}, headers=HEADERS)
    assert response.status_code == 400 and "不存在" in response.json()["error"]
    response = client.post("/api/run", content=b"{not json", headers={**HEADERS, "Content-Type": "application/json"})
    assert response.status_code == 400
    response = client.post("/api/run", json={"root": str(tmp_root), "offline": "yes"}, headers=HEADERS)
    assert response.status_code == 400 and "offline" in response.json()["error"]
    assert client.get("/api/state").json()["running"] is False


def test_open_requires_index_html(tmp_path: Path, tmp_root: Path):
    client = make_client(tmp_path, fake_pipeline())
    response = client.post("/api/open", json={"root": str(tmp_root)}, headers=HEADERS)
    assert response.status_code == 404 and "先跑一次" in response.json()["error"]
    assert client.opened == []
    (tmp_root / "index.html").write_text("<html></html>", encoding="utf-8")
    response = client.post("/api/open", json={"root": str(tmp_root)}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["opened"] == (tmp_root / "index.html").resolve().as_uri()
    assert client.opened == [response.json()["opened"]] and client.opened[0].startswith("file://")
    assert client.post("/api/open", json={}, headers=HEADERS).status_code == 404


def test_cross_site_post_is_rejected(tmp_path: Path, tmp_root: Path):
    client = make_client(tmp_path, fake_pipeline())
    body = {"root": str(tmp_root)}
    assert client.post("/api/run", json=body).status_code == 403, "没有 X-Shelf-Request"
    assert client.post("/api/run", json=body, headers={"X-Shelf-Request": "1"}).status_code == 403, "没有来源"
    evil = client.post("/api/run", json=body, headers={"X-Shelf-Request": "1", "Origin": "https://evil.example"})
    assert evil.status_code == 403 and evil.json()["error"] == "请求来源不被信任"
    assert client.post("/api/cancel", headers={"X-Shelf-Request": "1", "Origin": "http://127.0.0.1.evil.example"}).status_code == 403
    assert client.manager.state()["running"] is False and client.manager.recent_roots() == []
    ok = client.post("/api/run", json=body, headers={"X-Shelf-Request": "1", "Referer": "http://localhost:8031/"})
    assert ok.status_code == 202, "同源、带头：放行"
    client.manager.wait(timeout=10)
    assert client.get("/api/state", headers={"Origin": "https://evil.example"}).status_code == 200, "GET 不查"


def test_unknown_run_is_404(tmp_path: Path):
    client = make_client(tmp_path, fake_pipeline())
    assert client.get("/api/events?run=nope").status_code == 404
    assert client.get("/api/events").status_code == 404, "还没跑过"


def test_stream_pings_while_idle(tmp_path: Path, tmp_root: Path):
    gate = threading.Event()
    client = make_client(tmp_path, fake_pipeline(gate=gate), ping_seconds=0.05)
    run_id = client.post("/api/run", json={"root": str(tmp_root)}, headers=HEADERS).json()["run"]
    seen_ping = False
    with client.stream("GET", f"/api/events?run={run_id}") as response:
        for line in response.iter_lines():
            if line.startswith(": ping"):
                seen_ping = True
                break
    gate.set()
    client.manager.wait(timeout=10)
    assert seen_ping


# ---------- 前端静态资源的约束 ----------

def test_i18n_dictionaries_have_same_keys():
    import re
    from hidden_shelf.serve.app import STATIC_DIR
    text = (STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    zh = set(re.findall(r"^\s+'([\w.]+)':", text.split("var en = {")[0], re.M))
    en = set(re.findall(r"^\s+'([\w.]+)':", text.split("var en = {")[1], re.M))
    assert zh == en and len(zh) > 50


def test_progress_css_uses_only_tokens():
    import re
    from hidden_shelf.serve.app import STATIC_DIR
    css = (STATIC_DIR / "progress.css").read_text(encoding="utf-8")
    assert not re.findall(r"#[0-9a-fA-F]{3,6}\b|rgb\(", css)
    for name in ("tokens.css", "ripple.js", "i18n.js", "progress-core.js", "progress.js", "progress.css"):
        assert (STATIC_DIR / name).is_file(), name


def test_index_html_references_static_and_no_external_urls(tmp_path: Path):
    client = make_client(tmp_path, fake_pipeline())
    page = client.get("/").text
    for name in ("tokens.css", "progress.css", "i18n.js", "progress-core.js", "ripple.js", "progress.js"):
        assert f"/static/{name}" in page, name
    assert "http://" not in page and "https://" not in page, "页面不加载任何外网资源"
    assert 'data-steps="scan,import,scrape,organize,media,build"' in page
    assert "window.__shelfServe" in page and "stepLabels" in page and '"scrape"' in page
