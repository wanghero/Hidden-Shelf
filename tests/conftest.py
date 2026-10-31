"""公共测试夹具。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """全局配置落在临时目录，9 站全部停用：测试里的流水线永远不碰网络。要联网行为的测试自己传 GlobalConfig。"""
    home = tmp_path_factory.mktemp("hidden-shelf-home")
    monkeypatch.setenv("HIDDEN_SHELF_HOME", str(home))
    disabled = {name: {"enabled": False, "cookie": ""} for name in
                ("r18dev", "dmm", "1pondo", "tokyohot", "fc2", "javarchive", "javdb", "javbus", "avbase")}
    (home / "config.json").write_text(json.dumps({"network": {"mode": "direct", "proxy": ""}, "sources": disabled,
                                                  "routes": {}}), encoding="utf-8")
    return home


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    """一个空的盘根目录（不预建 HiddenShelf，由被测代码负责）。"""
    root = tmp_path / "disk"
    root.mkdir()
    return root


@pytest.fixture
def fake_video():
    """用 ffmpeg lavfi 生成一段很短的 h264/aac mp4；ffmpeg 不在则跳过。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("系统没有 ffmpeg")

    def _make(path: Path, seconds: float = 2.0, size: str = "320x240") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={size}:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return path

    return _make
