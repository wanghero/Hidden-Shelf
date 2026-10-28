"""按时间点抽单帧、把若干帧拼成一张图。

移植自 peach `src/peach/frame_capture.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）。去掉 `processing_control.checkpoint`、`ffmpeg_options`、SMB、硬解与诊断上报。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from PIL import Image


def readable_image(path: Path) -> bool:
    """图片须完整可解码；纯色 JPEG 也算有效画面。"""
    try:
        with Image.open(path) as image:
            image.load()
            return image.width > 0 and image.height > 0
    except (OSError, ValueError, Image.DecompressionBombError):
        return False


#: 部分视频把色彩原色写成 reserved（非法值），swscale 会拒绝缩放；声明为 bt709
#: 只是覆盖坏的元数据，不改动像素。
COLOR_OVERRIDE = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]

#: 只有坏色彩元数据才值得用 bt709 覆盖重试。无条件重试会让必然失败的文件每帧都白跑第二次。
COLOR_METADATA_ERROR = re.compile(
    r"(reserved|unsupported|invalid)[^\n]{0,60}(color|primaries|trc|space)"
    r"|(color|primaries|trc|space)[^\n]{0,60}(reserved|unsupported|invalid)",
    re.IGNORECASE,
)


def capture_frame(ffmpeg: str, path: Path | str, timestamp: float, destination: Path, *,
                  width: int | None = 480, color_override: bool = False,
                  timeout: float = 45) -> tuple[bool, str]:
    """抽一帧，返回（是否成功, stderr）。stderr 用于判断值不值得重试。

    `-ss` 在 `-i` 之前：那是输入端 seek，只解目标附近的帧。放到后面就是从头解码到
    那个时间点，两小时的片子抽最后一帧要几分钟。
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    command = [ffmpeg, "-y", "-v", "error"]
    if color_override:
        command += COLOR_OVERRIDE
    command += ["-ss", f"{max(0.0, timestamp):.2f}", "-i", str(path), "-frames:v", "1"]
    if width:
        command += ["-vf", f"scale={int(width)}:-2"]
    command += ["-q:v", "4", str(destination)]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=timeout,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        destination.unlink(missing_ok=True)
        return False, "ffmpeg timeout"
    except OSError as error:
        destination.unlink(missing_ok=True)
        return False, str(error)
    stderr = (completed.stderr or b"").decode("utf-8", "replace")
    ok = completed.returncode == 0 and readable_image(destination)
    if not ok:
        destination.unlink(missing_ok=True)
    return ok, stderr


def capture_with_retry(ffmpeg: str, path: Path | str, timestamp: float, destination: Path, *,
                       width: int | None = 480, timeout: float = 45) -> bool:
    """抽一帧；只在错误明说色彩元数据不合法时，带 bt709 声明重试一次。"""
    ok, stderr = capture_frame(ffmpeg, path, timestamp, destination, width=width, timeout=timeout)
    if not ok and COLOR_METADATA_ERROR.search(stderr):
        ok, _ = capture_frame(ffmpeg, path, timestamp, destination, width=width,
                              color_override=True, timeout=timeout)
    return ok


def tile_frames(ffmpeg: str, pattern: str, columns: int, rows: int, destination: Path, *,
                timeout: float = 60) -> bool:
    """把 `pattern`（形如 `dir/s%02d.jpg`）指的那串帧拼成 columns×rows 一张。

    帧要先按连续序号改好名再进来：`image2` 读的是序号序列，中间缺一个号它就在那里停下。
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    try:
        completed = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-i", pattern,
             "-filter_complex", f"tile={int(columns)}x{int(rows)}", "-q:v", "4", str(destination)],
            capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        destination.unlink(missing_ok=True)
        return False
    ok = completed.returncode == 0 and readable_image(destination)
    if not ok:
        destination.unlink(missing_ok=True)
    return ok
