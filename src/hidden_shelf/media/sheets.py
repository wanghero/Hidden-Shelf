"""九宫格：均匀取 columns×rows 帧，每帧单独抽，失败的帧用黑图占位，最后用 Pillow 拼。"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from ..fsutil import atomic_path
from .frames import capture_with_retry

#: 片头前这么多秒不取：多半是黑场或片商 logo。
SKIP_HEAD_SECONDS = 2.0


def sheet_timestamps(duration: float, frames: int, *, skip_head: float = SKIP_HEAD_SECONDS) -> list[float]:
    """`duration * (i + 0.5) / frames`，前 `skip_head` 秒跳过；短片按比例压缩。"""
    duration = max(0.0, float(duration or 0))
    if duration <= 0:
        return [0.0] * frames
    head = skip_head if duration > skip_head * 2 else 0.0
    span = duration - head
    return [min(duration - 0.1, head + span * (index + 0.5) / frames) for index in range(frames)]


def build_sheet(ffmpeg: str, video: Path, destination: Path, *, duration: float,
                columns: int = 3, rows: int = 3, frame_width: int = 480, quality: int = 85) -> bool:
    """生成九宫格。所有帧都抽不出来返回 False，不写文件。"""
    frames = columns * rows
    timestamps = sheet_timestamps(duration, frames)
    captured: list[Image.Image | None] = []
    with tempfile.TemporaryDirectory(prefix="shelf-sheet-") as temporary:
        for index, timestamp in enumerate(timestamps):
            frame_path = Path(temporary) / f"s{index:02d}.jpg"
            if capture_with_retry(ffmpeg, video, timestamp, frame_path, width=frame_width):
                try:
                    with Image.open(frame_path) as image:
                        captured.append(image.convert("RGB").copy())
                        continue
                except (OSError, ValueError):
                    pass
            captured.append(None)
    good = [image for image in captured if image is not None]
    if not good:
        return False
    cell_w = frame_width
    cell_h = round(good[0].height * cell_w / good[0].width) if good[0].width else round(cell_w * 9 / 16)
    sheet = Image.new("RGB", (cell_w * columns, cell_h * rows), "black")
    for index, image in enumerate(captured):
        if image is None:
            continue
        if image.size != (cell_w, cell_h):
            image = image.resize((cell_w, cell_h))
        sheet.paste(image, ((index % columns) * cell_w, (index // columns) * cell_h))
    with atomic_path(destination) as temporary_path:
        sheet.save(temporary_path, "JPEG", quality=quality)
    return True
