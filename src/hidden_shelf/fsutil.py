"""原子落盘：先写同目录临时文件再 `os.replace`，结果只有旧内容或新内容，没有半成品。

思路取自 peach `src/peach/fsutil.py`（去掉 Windows 读者占用重试与权限位收紧）。
临时文件与目标同目录（`os.replace` 只在同一卷上原子）、带随机段（并发不互删）、
沿用目标扩展名（FFmpeg 与 PIL 按扩展名定格式）。
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_path(target: Path | str, *, suffix: str | None = None) -> Iterator[Path]:
    """产出一个同目录的临时路径；正常退出就原子替换 `target`，出错就把它删掉。"""
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tail = destination.suffix if suffix is None else suffix
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex[:12]}.tmp{tail}")
    try:
        yield temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    try:
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_bytes(target: Path | str, data: bytes) -> Path:
    with atomic_path(target) as temporary:
        temporary.write_bytes(data)
    return Path(target)


def atomic_write_text(target: Path | str, text: str, *, encoding: str = "utf-8") -> Path:
    with atomic_path(target) as temporary:
        temporary.write_text(text, encoding=encoding)
    return Path(target)
