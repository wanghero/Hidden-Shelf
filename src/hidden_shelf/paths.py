"""盘上的目录布局：盘根目录 → `.shelf/` 下各目录（设计文档 §4.2）。

全部派生产物都在 `<盘根>/.shelf/` 下，媒体目录旁不写任何附属文件。库里的 `asset.path`
是相对盘根目录的 POSIX 串，`relative()` / `absolute()` 负责两头转换并拦住越界。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

#: 认不出番号的视频集中搬到这个目录（设置开关可关）。
UNRECOGNIZED_DIR = "未识别"


@dataclass(frozen=True)
class ShelfPaths:
    root: Path

    @property
    def shelf(self) -> Path:
        return self.root / ".shelf"

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
        """建全部 `.shelf/` 下的目录。`未识别/` 由归位按需建。"""
        for directory in (self.shelf, self.site, self.site_data, self.covers, self.posters,
                          self.sheets, self.avatars, self.sources, self.legacy, self.logs,
                          self.backups):
            directory.mkdir(parents=True, exist_ok=True)

    def relative(self, path: Path) -> str:
        """`path` 相对盘根目录的 POSIX 串；不在盘根下抛 `ValueError`。"""
        try:
            rel = Path(path).relative_to(self.root)
        except ValueError:
            raise ValueError(f"路径不在盘根目录下：{path}") from None
        return rel.as_posix()

    def shelf_relative(self, path: Path) -> str:
        """`path` 相对 `.shelf/` 的 POSIX 串（库里 `cover_file` 等列用这种写法）。"""
        try:
            rel = Path(path).relative_to(self.shelf)
        except ValueError:
            raise ValueError(f"路径不在 .shelf 下：{path}") from None
        return rel.as_posix()

    def absolute(self, rel: str) -> Path:
        """把库里的相对 POSIX 串还原成绝对路径；带 `..` 或绝对写法的拒绝。"""
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts or not str(rel):
            raise ValueError(f"不是盘根下的相对路径：{rel!r}")
        return self.root.joinpath(*pure.parts)

    def shelf_absolute(self, rel: str) -> Path:
        """`.shelf/` 下相对路径还原成绝对路径。"""
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts or not str(rel):
            raise ValueError(f"不是 .shelf 下的相对路径：{rel!r}")
        return self.shelf.joinpath(*pure.parts)
