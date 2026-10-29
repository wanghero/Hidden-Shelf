"""进度网页端到端：真流水线跑同一块盘，命令行打印的每一行正文与 SSE 里的消息一字不差（Review Focus 6）。"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from hidden_shelf import cli, pipeline
from hidden_shelf.serve.app import create_app
from hidden_shelf.serve.runner import RunManager

HEADERS = {"X-Shelf-Request": "1", "Origin": "http://127.0.0.1:8031"}
PREFIX = re.compile(r"^\[(扫描|导入|刮削|归位|媒体|出站)\] ")


def make_disk(root: Path, fake_video) -> Path:
    fake_video(root / "a" / "ABP-758.mp4")
    (root / "a" / "ABP-758.nfo").write_text(
        "<movie><title>标题</title><studio>Prestige</studio><actor><name>甲</name></actor></movie>", encoding="utf-8")
    Image.new("RGB", (300, 200), "red").save(root / "a" / "ABP-758-poster.jpg")
    fake_video(root / "b" / "259LUXU-1475-cd1.mp4")
    fake_video(root / "c" / "随手拍.mp4")
    return root


def normalize(text: str, root: Path) -> str:
    """盘根目录与时间戳（备份文件名、日志名）不比。"""
    return re.sub(r"\d{8}-\d{6}", "<time>", text.replace(str(root), "<root>"))


def cli_lines(root: Path, capsys) -> tuple[list[str], dict[str, dict], list[str]]:
    """命令行输出 → (每步 advance 正文, 每步完成 stats, 跳过/失败行)。"""
    assert cli.main(["run", str(root), "--offline"]) == 0
    out = capsys.readouterr().out
    progress, done, other = [], {}, []
    for line in out.splitlines():
        matched = PREFIX.match(line)
        if not matched:
            continue
        body = line[matched.end():]
        label = matched.group(1)
        if body.startswith("完成："):
            done[label] = json.loads(body[len("完成："):])
        elif body.startswith("跳过") or body.startswith("✗ "):
            other.append(normalize(body, root))
        else:
            progress.append(normalize(body, root))
    return progress, done, other


def sse_lines(root: Path, home: Path) -> tuple[list[str], dict[str, dict], list[str], dict]:
    manager = RunManager(home=home)
    client = TestClient(create_app(manager, opener=lambda uri: None, ping_seconds=0.05))
    response = client.post("/api/run", json={"root": str(root), "offline": True}, headers=HEADERS)
    assert response.status_code == 202, response.text
    run_id = response.json()["run"]
    assert manager.wait(timeout=180)
    events = []
    with client.stream("GET", f"/api/events?run={run_id}") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    progress, done, other = [], {}, []
    labels = pipeline.STEP_LABELS
    for event in events:
        if event["kind"] == "step.progress" and event["level"] == "info":
            progress.append(normalize(event["message"], root))
        elif event["kind"] == "step.done":
            done[labels[event["step"]]] = event["stats"]
        elif event["kind"] == "step.skipped":
            other.append(normalize(f"跳过{labels[event['step']]}（{event['message']}）", root))
        elif event["kind"] == "step.failed":
            other.append(normalize(f"✗ {labels[event['step']]}失败：{event['message']}", root))
    assert events[0]["kind"] == "run.start" and events[-1]["kind"] == "run.done"
    return progress, done, other, events[-1]["stats"]


def _strip_volatile(stats: dict, root: Path) -> dict:
    """路径与时间戳（批次日志名）归一后再比。"""
    out = {}
    for key, value in stats.items():
        if isinstance(value, dict):
            out[key] = _strip_volatile(value, root)
        elif isinstance(value, str):
            out[key] = normalize(value, root)
        else:
            out[key] = value
    return out


def test_serve_runs_a_real_disk_and_matches_cli_output(tmp_path: Path, fake_video, capsys):
    cli_root = make_disk(tmp_path / "cli", fake_video)
    web_root = tmp_path / "web"
    shutil.copytree(cli_root, web_root)
    progress_cli, done_cli, other_cli = cli_lines(cli_root, capsys)
    progress_web, done_web, other_web, result = sse_lines(web_root, tmp_path / "home")
    assert progress_cli and progress_cli == progress_web, "命令行与网页日志逐行一致"
    assert ({k: _strip_volatile(v, cli_root) for k, v in done_cli.items()}
            == {k: _strip_volatile(v, web_root) for k, v in done_web.items()}), "每步完成的 stats 一致"
    assert other_cli == other_web == ["跳过刮削（--offline）"]
    assert result["ok"] is True and result["cancelled"] is False and result["failed_step"] == ""
    assert result["index_html"] == str(web_root / "index.html") and (web_root / "index.html").is_file()
    assert (web_root / "Prestige" / "ABP-758" / "ABP-758.mp4").is_file()
    assert set(result["steps"]) == set(pipeline.STEPS)
    # 打开成品：index.html 在了就 200。
    manager = RunManager(home=tmp_path / "home")
    opened = []
    client = TestClient(create_app(manager, opener=opened.append))
    assert client.post("/api/open", json={"root": str(web_root)}, headers=HEADERS).status_code == 200
    assert opened == [(web_root / "index.html").resolve().as_uri()]
    assert manager.recent_roots() == [str(web_root.resolve())]
