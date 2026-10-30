"""封面与竖版海报。

海报裁法取 peach `jav_poster_crop.py` 的 `ratio` 先验（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）：宽高比在 `SLEEVE_RATIO_MIN`～`SLEEVE_RATIO_MAX` 之间视为 DVD 封套，
从右缘量 `高 × PANEL_ASPECT` 宽做正封；不做 OpenCV 折痕检测。其余图整图等比缩放到 2:3 居中裁。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from ..fsutil import atomic_path
from .frames import capture_with_retry

#: 封套的宽高比下限。低于它按竖版正封处理：整张就是正封，没有可裁的横向余量。
SLEEVE_RATIO_MIN = 1.2
#: 上限之外是 16:9 官方剧照，整幅都是画面，没有「正面那一块」可推。
SLEEVE_RATIO_MAX = 1.65
#: 正封宽高比先验：没找到折痕时按它从右缘量回去。
PANEL_ASPECT = 0.704
#: 非封套图的海报比例。
POSTER_ASPECT = 2 / 3


def poster_box(width: int, height: int) -> tuple[int, int, int, int]:
    """海报在原图上的裁切框 `(x0, y0, x1, y1)`。"""
    ratio = width / height if height else 0
    if SLEEVE_RATIO_MIN <= ratio < SLEEVE_RATIO_MAX:
        panel = round(height * PANEL_ASPECT)
        return (max(0, width - panel), 0, width, height)
    if ratio > POSTER_ASPECT:
        target_w = round(height * POSTER_ASPECT)
        left = (width - target_w) // 2
        return (left, 0, left + target_w, height)
    target_h = round(width / POSTER_ASPECT)
    top = max(0, (height - target_h) // 2)
    return (0, top, width, min(height, top + target_h))


def poster_from_cover(cover: Path, destination: Path, *, quality: int = 90) -> bool:
    """从封面裁出竖版海报。坏图返回 False。"""
    try:
        with Image.open(cover) as image:
            image.load()
            rgb = image.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError):
        return False
    if not rgb.width or not rgb.height:
        return False
    poster = rgb.crop(poster_box(rgb.width, rgb.height))
    try:
        with atomic_path(destination) as temporary:
            poster.save(temporary, "JPEG", quality=quality)
    except OSError:
        return False
    return True


def cover_from_frame(ffmpeg: str, video: Path, destination: Path, *, duration: float) -> bool:
    """没有任何封面时从视频抽一帧：取 `max(2, duration × 0.2)` 秒那一帧，不缩放。"""
    duration = float(duration or 0)
    timestamp = max(2.0, duration * 0.2)
    if duration > 0:
        timestamp = min(timestamp, max(0.0, duration - 0.1))
    with atomic_path(destination) as temporary:
        ok = capture_with_retry(ffmpeg, video, timestamp, temporary, width=None)
        if not ok:
            raise _Skip()
    return True


class _Skip(Exception):
    """让 `atomic_path` 删掉临时文件、不替换目标。"""


def _cover_from_frame_safe(ffmpeg: str, video: Path, destination: Path, *, duration: float) -> bool:
    try:
        return cover_from_frame(ffmpeg, video, destination, duration=duration)
    except _Skip:
        return False
