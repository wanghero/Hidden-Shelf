"""盘上的目录布局：盘根目录 → `HiddenShelf/` 下各目录（设计文档 §4.2）。

全部派生产物都在 `<盘根>/HiddenShelf/` 下，媒体目录旁不写任何附属文件。库里的 `asset.path`
是相对盘根目录的 POSIX 串，`relative()` / `absolute()` 负责两头转换并拦住越界。
"""
from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

#: 资料目录名（用户 2026-10-29 定：普通可见目录，不藏在点开头的隐藏文件夹里，要考虑 Windows）。
#: 纯 ASCII、不以点或下划线开头、不是 Windows 保留名、不含尾随点或空格，exFAT/NTFS/APFS 都合法；
#: 大小写不敏感的文件系统上 `hiddenshelf/` 视作同一目录。全仓库只在这里写死，别处一律引用它。
SHELF_DIR = "HiddenShelf"
#: 改名前的旧目录名（v0.4.0 及之前）。只在迁移代码里出现：老盘上见到它就改名成 `SHELF_DIR`。
LEGACY_SHELF_DIR = ".shelf"
#: 认不出番号的视频集中搬到这个目录（设置开关可关）。
UNRECOGNIZED_DIR = "未识别"


@dataclass(frozen=True)
class ShelfPaths:
    root: Path

    @property
    def shelf(self) -> Path:
        return self.root / SHELF_DIR

    @property
    def db(self) -> Path:
        return self.shelf / "shelf.db"

    @property
    def config(self) -> Path:
        return self.shelf / "config.json"

    @property
    def overrides(self) -> Path:
        return self.shelf / "overrides.json"

    @property
    def site(self) -> Path:
        return self.shelf / "site"

    @property
    def site_data(self) -> Path:
        return self.site / "data"

    @property
    def covers(self) -> Path:
        return self.shelf / "covers"

    @property
    def posters(self) -> Path:
        return self.shelf / "posters"

    @property
    def sheets(self) -> Path:
        return self.shelf / "sheets"

    @property
    def avatars(self) -> Path:
        return self.shelf / "avatars"

    @property
    def sources(self) -> Path:
        return self.shelf / "sources"

    @property
    def legacy(self) -> Path:
        return self.shelf / "legacy"

    @property
    def logs(self) -> Path:
        return self.shelf / "logs"

    @property
    def backups(self) -> Path:
        return self.shelf / "backups"

    @property
    def unrecognized(self) -> Path:
        return self.root / UNRECOGNIZED_DIR

    @property
    def index_html(self) -> Path:
        return self.root / "index.html"

    def ensure(self) -> None:
        """建全部 `HiddenShelf/` 下的目录。`未识别/` 由归位按需建。盘不可写抛 `RootNotWritable`（带怎么办）。

        开头先把老盘的 `.shelf/` 改名（`migrate_legacy_dir`）；两个目录都在抛 `ShelfLayoutConflict`。
        """
        migrate_legacy_dir(self.root)
        for directory in (self.shelf, self.site, self.site_data, self.covers, self.posters,
                          self.sheets, self.avatars, self.sources, self.legacy, self.logs,
                          self.backups):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                if error.errno in _NOT_WRITABLE_ERRNOS:
                    raise RootNotWritable(self.root, error.errno) from error
                raise


    def relative(self, path: Path) -> str:
        """`path` 相对盘根目录的 POSIX 串；不在盘根下抛 `ValueError`。"""
        try:
            rel = Path(path).relative_to(self.root)
        except ValueError:
            raise ValueError(f"路径不在盘根目录下：{path}") from None
        return rel.as_posix()

    def shelf_relative(self, path: Path) -> str:
        """`path` 相对资料目录 `HiddenShelf/` 的 POSIX 串（库里 `cover_file` 等列用这种写法）。"""
        try:
            rel = Path(path).relative_to(self.shelf)
        except ValueError:
            raise ValueError(f"路径不在 {SHELF_DIR} 下：{path}") from None
        return rel.as_posix()

    def absolute(self, rel: str) -> Path:
        """把库里的相对 POSIX 串还原成绝对路径；带 `..` 或绝对写法的拒绝。"""
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts or not str(rel):
            raise ValueError(f"不是盘根下的相对路径：{rel!r}")
        return self.root.joinpath(*pure.parts)

    def shelf_absolute(self, rel: str) -> Path:
        """资料目录下的相对路径还原成绝对路径。"""
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts or not str(rel):
            raise ValueError(f"不是 {SHELF_DIR} 下的相对路径：{rel!r}")
        return self.shelf.joinpath(*pure.parts)


#: 建目录时这些错误码都意味着「这块盘写不了」，不是程序的问题。
_NOT_WRITABLE_ERRNOS = frozenset({errno.EROFS, errno.EACCES, errno.EPERM})


class RootNotWritable(OSError):
    """盘根目录写不了。`errno` 是原因（`EROFS` 只读文件系统、`EACCES`/`EPERM` 没权限），`str()` 是给用户看的话。"""

    def __init__(self, root: Path, code: int = errno.EROFS) -> None:
        super().__init__(code, writability_hint(root, code), str(root))

    def __str__(self) -> str:
        return str(self.strerror)


def writability_hint(root: Path, code: int = errno.EROFS) -> str:
    cause = "这块盘是只读文件系统" if code == errno.EROFS else "当前用户对这块盘没有写权限"
    return (f"盘根目录不可写：{root}。{cause}。藏片阁要在盘根目录写 {SHELF_DIR}/ 和 index.html，所以跑不了。"
            "最常见的原因是 macOS 默认把 NTFS 格式的盘只读挂载：装 NTFS 驱动（Paragon、Tuxera 等），"
            "或把盘改成 exFAT/APFS；也检查一下盘的写保护开关和「显示简介 → 共享与权限」。")


def check_writable(root: Path) -> None:
    """开跑之前先问一句能不能写，不动盘上任何东西；写不了抛 `RootNotWritable`。"""
    if not os.access(root, os.W_OK):
        raise RootNotWritable(root, errno.EROFS)


class ShelfLayoutConflict(RuntimeError):
    """盘根目录同时有旧的 `.shelf/` 和新的 `HiddenShelf/`（用户手工复制过）：不合并、不猜，让人保留一个。"""

    def __init__(self, root: Path) -> None:
        super().__init__(f"盘根目录同时有 {LEGACY_SHELF_DIR}/ 和 {SHELF_DIR}/，请保留一个再运行：{root}")


def check_layout(root: Path) -> None:
    """开跑之前只检查、不改名：两个资料目录都在就抛 `ShelfLayoutConflict`。"""
    root = Path(root)
    if (root / LEGACY_SHELF_DIR).is_dir() and (root / SHELF_DIR).is_dir():
        raise ShelfLayoutConflict(root)


def migrate_legacy_dir(root: Path) -> bool:
    """老盘的 `.shelf/` 改名为 `HiddenShelf/`，同卷 `os.rename`、不碰内容；改了返回 True，没有旧目录返回 False。

    两个都在抛 `ShelfLayoutConflict`；改名失败（只读盘、没权限）抛 `RootNotWritable` 同一句话。
    库里的相对路径都相对资料目录，不用改库；旧 `index.html` 还指着 `.shelf/`，下一次出站会重写。
    """
    root = Path(root)
    legacy = root / LEGACY_SHELF_DIR
    if not legacy.is_dir():
        return False
    check_layout(root)
    try:
        os.rename(legacy, root / SHELF_DIR)
    except OSError as error:
        if error.errno in _NOT_WRITABLE_ERRNOS:
            raise RootNotWritable(root, error.errno) from error
        raise
    return True
