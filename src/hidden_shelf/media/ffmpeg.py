"""找系统 ffmpeg／ffprobe，并用 ffprobe 读时长、尺寸、编码。不托管二进制。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

INSTALL_HINT = "macOS 用 `brew install ffmpeg`，Debian/Ubuntu 用 `apt-get install -y ffmpeg`"


class FFmpegMissing(RuntimeError):
    """系统里找不到 ffmpeg 或 ffprobe。消息直接给用户看。"""


def _find(tool: str) -> str:
    found = shutil.which(tool)
    if not found:
        raise FFmpegMissing(f"找不到 {tool}，请先安装：{INSTALL_HINT}")
    return found


def find_ffmpeg() -> str:
    return _find("ffmpeg")


def find_ffprobe() -> str:
    return _find("ffprobe")


@dataclass(frozen=True)
class ProbeInfo:
    duration: float
    width: int
    height: int
    vcodec: str
    acodec: str
    container: str


def probe(path: Path | str, *, ffprobe: str | None = None, timeout: float = 60) -> ProbeInfo:
    """`ffprobe -show_streams -show_format`；读不出视频流抛 `ValueError`。"""
    tool = ffprobe or find_ffprobe()
    command = [tool, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"ffprobe 超时：{path}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise ValueError(f"ffprobe 失败：{detail[-1] if detail else '无输出'}")
    try:
        payload = json.loads(completed.stdout or b"{}")
    except ValueError as error:
        raise ValueError("ffprobe 输出不是 JSON") from error
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("没有视频流")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = payload.get("format") or {}
    duration = _float(fmt.get("duration")) or _float(video.get("duration")) or 0.0
    suffix = os.path.splitext(str(path))[1].lower().lstrip(".")
    return ProbeInfo(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        vcodec=str(video.get("codec_name") or ""),
        acodec=str(audio.get("codec_name") or "") if audio else "",
        container=suffix,
    )


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
