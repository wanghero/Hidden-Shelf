"""盘上的目录布局：盘根目录 → `HiddenShelf/` 下各目录（设计文档 §4.2）。

全部派生产物都在 `<盘根>/HiddenShelf/` 下，媒体目录旁不写任何附属文件。库里的 `asset.path`
是相对盘根目录的 POSIX 串，`relative()` / `absolute()` 负责两头转换并拦住越界。

进库的那一串一律是 **NFC**（`nfc()`，见那里的注释）：macOS 把文件名以分解形式交给程序，
而程序写盘时用的是刮削来的合成形式，不归一的话同一个目录名在库里会有两种字节。
"""
from __future__ import annotations

import errno
import os
import unicodedata
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


def nfc(text: str) -> str:
    """文件名、路径串的统一写法：Unicode 合成形式（NFC）。

    macOS 读目录时把文件名**分解**后交给程序：`が` 回来是 `か` + 浊音符两个码位（NFD）。程序
    自己写盘用的却是刮削来的标题，网页给的是合成形式（NFC，`が` 一个码位）。两种字节在文件
    系统上指同一个文件（APFS 与 macOS 的 SMB 客户端比较时都忽略这个差别），但在 SQLite 的
    `asset.path UNIQUE` 眼里是两个不同的值——于是重扫时旧行对不上、被当成消失，另建一条没有
    任何资料的新行。2026-11-02 的真实盘上 253 个作品这样丢了资料，而且旧行还占着那个 path，
    让归位报 `UNIQUE constraint failed: asset.path`（207 个）或「目标已存在」（53 个）。

    所以凡是进库的名字都从这里过一遍。反过来不用管：NFC 串照样打得开 NFD 存着的文件。
    """
    return unicodedata.normalize("NFC", text)


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
        末尾没有 `config.json` 就写一份默认配置（`ShelfConfig.load` 自己不写盘）。
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
        if not self.config.is_file():
            from .config import ShelfConfig  # 局部导入：config 依赖本模块
            ShelfConfig().save(self)


    def relative(self, path: Path) -> str:
        """`path` 相对盘根目录的 POSIX 串；不在盘根下抛 `ValueError`。"""
        try:
            rel = Path(path).relative_to(self.root)
        except ValueError:
            raise ValueError(f"路径不在盘根目录下：{path}") from None
        return nfc(rel.as_posix())

    def shelf_relative(self, path: Path) -> str:
        """`path` 相对资料目录 `HiddenShelf/` 的 POSIX 串（库里 `cover_file` 等列用这种写法）。"""
        try:
            rel = Path(path).relative_to(self.shelf)
        except ValueError:
            raise ValueError(f"路径不在 {SHELF_DIR} 下：{path}") from None
        return nfc(rel.as_posix())

    def decomposed(self, rel: str) -> Path:
        """同一个相对串的**分解写法**（NFD）的绝对路径。

        库里一律存合成写法（见 `nfc`）。macOS 与 Windows 上两种写法打得开同一个文件，Linux 上
        打不开——所以凡是「按库里的路径找不到这个文件」的地方，再按这个写法找一次，老盘上分解
        写法存着的文件才不会在 Linux 上凭空消失。
        """
        return self.absolute(unicodedata.normalize("NFD", rel))

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
