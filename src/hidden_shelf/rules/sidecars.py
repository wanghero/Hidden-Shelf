"""附属文件判定：一个文件名是不是某部片旁边的封面、海报、NFO、字幕或缩略图。

移植自 peach `src/peach/scan.py` 第 52–75 行与 `medium_of` / `video_stems` / `is_sidecar`
（commit 4d5266d327a5971773409b44316e3926bd37c6ba，AGPL-3.0-or-later）。改动：

- `medium_of` 加 `nfo`、`subtitle` 两档，供导入和搬迁用；
- `is_sidecar` 去掉 `path` / `library_roots` 参数（本项目只有一个盘根），并把「与视频同名
  的图片」「与视频同名的字幕」也算作附属——peach 只决定登不登记，这里还要导入与留底；
- 新增 `sidecar_kind`，在 `is_sidecar` 之上按后缀分类。

判据只看名字，不读文件内容。
"""
from __future__ import annotations

import os
import re

from .codes import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, is_local_extra

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"})
ARCHIVE_EXTENSIONS = frozenset({".zip", ".rar", ".7z", ".tar", ".gz"})
SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".sup"})

#: Kodi／Jellyfin 的影片图片名（单写或挂在片名后面，如 `ABC-123-fanart.jpg`）。
#: 只在同目录有视频时算附属：没有正片的目录里，`cover.jpg` 是图集自己的封面。
ARTWORK = frozenset({
    "poster", "fanart", "thumb", "folder", "cover", "banner", "clearart", "clearlogo",
    "landscape", "disc", "discart", "logo", "backdrop", "keyart",
})
#: 装一部片剧照的整个子目录，只在上一层有视频时算附属。
ARTWORK_DIRS = frozenset({"extrafanart", "extrathumbs"})
#: 截图工具的产物，看名字就能认出来，不必看同目录：`X_4x4_thumb.jpg`（拼版缩略图）、
#: `X.mp4_thumbs.jpg`（MPC-HC 存缩略图）、`X.png.thumb.png`（图片的缩略图）。
_DERIVED_THUMB = re.compile(
    r"(?:_\d+x\d+_thumbs?|\.(?:" + "|".join(sorted(ext[1:] for ext in VIDEO_EXTENSIONS))
    + r")_thumbs?|\.(?:" + "|".join(sorted(ext[1:] for ext in IMAGE_EXTENSIONS)) + r")\.thumb)$",
    re.IGNORECASE)

#: 图片名后缀 → 附属文件类别。`folder.jpg` 在 Kodi 里就是封面。
_ARTWORK_KIND = {
    "poster": "poster", "keyart": "poster",
    "fanart": "fanart", "backdrop": "fanart",
    "cover": "cover", "folder": "cover",
    "thumb": "thumb",
}


def medium_of(name: str) -> str:
    """按扩展名分档：`video | image | audio | archive | nfo | subtitle | other`。"""
    suffix = os.path.splitext(name)[1].lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in ARCHIVE_EXTENSIONS:
        return "archive"
    if suffix == ".nfo":
        return "nfo"
    if suffix in SUBTITLE_EXTENSIONS:
        return "subtitle"
    return "other"


def video_stems(names) -> frozenset[str]:
    """一个目录里视频文件的片名（casefold），`is_sidecar` 拿它判同目录有没有正片。"""
    return frozenset(os.path.splitext(name)[0].casefold() for name in names
                     if medium_of(name) == "video" and not is_local_extra(name))


def _stem_without_language(stem: str) -> str:
    """字幕常带语言段：`ABC-123.chs.srt` 的主名是 `ABC-123`。"""
    head, dot, _tail = stem.rpartition(".")
    return head if dot and head else stem


def is_sidecar(name: str, videos: frozenset[str], *, artwork_dir: bool = False) -> bool:
    """`name` 是否为某部片的附属文件（不是作品本身）。

    `videos` 是同目录的 `video_stems`；`artwork_dir` 表示这个目录叫 `extrafanart` 之类、
    且上一层有视频。
    """
    return sidecar_kind(name, videos, artwork_dir=artwork_dir) is not None


def sidecar_kind(name: str, videos: frozenset[str], *, artwork_dir: bool = False) -> str | None:
    """附属文件的类别；不是附属文件返回 None。

    `nfo | poster | fanart | cover | thumb | subtitle | other`。`other` 是本地预告片、
    花絮这类 peach 认作附属媒体的视频，以及 `landscape`、`banner` 等用不上的图。
    """
    stem, suffix = os.path.splitext(name)
    medium = medium_of(name)
    if medium == "nfo":
        return "nfo"
    if is_local_extra(name):
        return "other"
    lowered = stem.casefold()
    if medium == "subtitle":
        return "subtitle" if videos and _stem_without_language(lowered) in videos else None
    if medium != "image":
        return None
    if artwork_dir:
        return "fanart"
    if _DERIVED_THUMB.search(stem):
        return "thumb"
    if not videos:
        return None
    if lowered in ARTWORK:
        return _ARTWORK_KIND.get(lowered, "other")
    if lowered in videos:
        return "cover"
    head, dash, tail = lowered.rpartition("-")
    if dash and tail in ARTWORK and head in videos:
        return _ARTWORK_KIND.get(tail, "other")
    return None
