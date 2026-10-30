"""进度网页的目录列举：给「浏览」弹窗用，只列目录、不读文件、不跟符号链接、不越界。

规则：
- `path` 必须是绝对路径，`..` 段拒绝；不存在 404、不是目录 400、无权限 403，其余 `OSError` 也按 403。
- 默认不显示点开头的隐藏目录；资料目录 `HiddenShelf` 永远不显示（它是产物），但告诉前端该目录「已有藏片阁库」（`has_shelf`）。
- 系统目录（群晖 `@eaDir`、Windows 回收站与卷信息、macOS 索引与废纸篓）永远不显示。
- 单个子项 `stat` 失败就跳过那一项，不让整层失败（macOS `/Volumes` 里拔掉后残留的卷常这样）。
- 最多 `MAX_ENTRIES` 条，超出截断并告知。
"""
from __future__ import annotations

import os
import string
import sys
from dataclasses import dataclass
from pathlib import Path

from ..paths import SHELF_DIR

MAX_ENTRIES = 2000
#: 永远不显示的目录名（任何层级）。
NEVER_SHOW = frozenset({SHELF_DIR, "@eaDir", "$RECYCLE.BIN", "System Volume Information", ".Spotlight-V100", ".Trashes", ".fseventsd"})
#: 手动验证用的只读钩子：把 macOS 风格的卷目录指到别处（`HIDDEN_SHELF_VOLUMES=/tmp/卷`）。不写配置、不进文档以外的任何地方。
VOLUMES_ENV = "HIDDEN_SHELF_VOLUMES"


class BrowseError(Exception):
    """列举失败：`status` 是对应的 HTTP 状态码（400/403/404），`message` 给用户看。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Entry:
    name: str
    path: str
    has_shelf: bool


@dataclass(frozen=True)
class Listing:
    path: str
    parent: str | None
    entries: list[Entry]
    truncated: bool
    has_shelf: bool
    writable: bool


def _has_shelf(path: Path) -> bool:
    try:
        return (path / SHELF_DIR).is_dir()
    except OSError:
        return False


def _entry(path: Path, name: str | None = None) -> Entry:
    return Entry(name=name or path.name or str(path), path=str(path), has_shelf=_has_shelf(path))


def _subdirs(base: Path) -> list[Path]:
    """`base` 下的子目录，只给根列表用（卷与挂载点常是符号链接，这里跟）；`base` 不存在或读不了回空。"""
    try:
        with os.scandir(base) as scanner:
            found = []
            for entry in scanner:
                try:
                    if entry.is_dir():
                        found.append(Path(entry.path))
                except OSError:
                    continue
            return found
    except OSError:
        return []


def _default_volumes() -> Path | None:
    override = os.environ.get(VOLUMES_ENV)
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path("/Volumes")
    return None


def list_roots(*, home: Path | None = None, volumes: Path | None = None) -> list[Entry]:
    """浏览的起点：用户目录第一，其余按名排序。不存在或无权限的根跳过，不抛。

    macOS：home + `/Volumes/*`；Linux：home + `/` + `/mnt/*` + `/media/<用户>/*`；Windows：home + 每个存在的盘符。
    `volumes` 显式给了就只按 macOS 风格列它（测试与手动验证用）。
    """
    home = Path(home) if home is not None else Path.home()
    volumes = volumes if volumes is not None else _default_volumes()
    candidates: list[Path] = []
    if volumes is not None:
        candidates.extend(_subdirs(volumes))
    elif sys.platform == "win32":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            try:
                if drive.exists():
                    candidates.append(drive)
            except OSError:
                continue
    else:
        candidates.append(Path("/"))
        candidates.extend(_subdirs(Path("/mnt")))
        for user_dir in _subdirs(Path("/media")):
            candidates.extend(_subdirs(user_dir))
    roots: list[Entry] = []
    try:
        if home.is_dir():
            roots.append(_entry(home))
    except OSError:
        pass
    rest: list[Entry] = []
    seen = {home}
    for candidate in sorted(candidates, key=lambda p: (p.name or str(p)).casefold()):
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            if not candidate.is_dir():
                continue
        except OSError:
            continue
        rest.append(_entry(candidate))
    return roots + rest


def list_directory(raw: str, *, show_hidden: bool = False, limit: int = MAX_ENTRIES) -> Listing:
    """列 `raw` 下的子目录。校验失败抛 `BrowseError`。"""
    text = str(raw or "")
    path = Path(text)
    if not text or not path.is_absolute():
        raise BrowseError(400, "路径必须是绝对路径")
    if ".." in path.parts:
        raise BrowseError(400, "路径不能包含 ..")
    try:
        if not path.exists():
            raise BrowseError(404, "目录不存在")
        if not path.is_dir():
            raise BrowseError(400, "不是目录")
    except PermissionError:
        raise BrowseError(403, "没有读取权限") from None
    except OSError as error:
        raise BrowseError(403, f"读不了：{error.strerror or error}") from None
    entries: list[Entry] = []
    truncated = False
    try:
        with os.scandir(path) as scanner:
            for item in scanner:
                name = item.name
                if name in NEVER_SHOW or (not show_hidden and name.startswith(".")):
                    continue
                try:
                    if not item.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                entries.append(_entry(Path(item.path), name))
    except PermissionError:
        raise BrowseError(403, "没有读取权限") from None
    except OSError as error:
        raise BrowseError(403, f"读不了：{error.strerror or error}") from None
    entries.sort(key=lambda e: e.name.casefold())
    if len(entries) > limit:
        entries = entries[:limit]
        truncated = True
    parent = path.parent
    return Listing(path=str(path), parent=None if parent == path else str(parent), entries=entries, truncated=truncated,
                   has_shelf=_has_shelf(path), writable=os.access(path, os.W_OK))
