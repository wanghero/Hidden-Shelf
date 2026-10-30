"""Kodi／Jellyfin 影片 NFO 的读取，以及视频与同目录 NFO、图片的配对。

移植自 peach `src/peach/library_nfo.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）。改动：去掉 SMB 分支与 `processing_traffic.record_media_read`；
`read_nfo` 只返回字典且键名固定（`title original_title code studio series release_date
year actors tags cover_url local_art plot`，没有的键不出现）；`SidecarIndex.for_video`
拆成 `nfo_for` / `images_for`。

配对规则照 peach：同主名 > 番号同一 > 目录唯一 `movie.nfo`；图片是 `<主名>-poster`、
与视频同名（不在连号图集里时）、单片目录下的 `poster/folder/cover`。
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .codes import VIDEO_EXTENSIONS, release_code_from_filename, release_code_from_text, same_release_code

POSTER_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.tbn', '.webp')
_NUMBERED = re.compile(r'(.*\D|)(\d+)(\D*)')
#: 只有明确的番号形状才参与 JAV 身份识别；通用 `<id>` 常是 IMDb／TMDb。
_CODE_SHAPE = re.compile(r'(?:[A-Za-z]{2,12}[-_]\d{2,8}|FC2[-_](?:PPV[-_])?\d+)', re.I)
#: 读取上限：1 MiB。NFO 是几 KB 的东西，再大就不是资料文件。
_MAX_BYTES = 1024 * 1024


def directory_files(directory: Path) -> dict[str, Path]:
    """目录里的普通文件，按 casefold 文件名索引。"""
    with os.scandir(directory) as entries:
        return {entry.name.casefold(): Path(entry.path) for entry in entries if entry.is_file()}


class SidecarIndex:
    """目录的影片、NFO 和连号图片分组；一份索引服务同目录的全部影片。"""

    def __init__(self, files: dict[str, Path]):
        self.files = files
        self.videos: list[Path] = []
        self.nfos: list[Path] = []
        self._nfo_codes: list[tuple[Path, str | None]] = []
        images = []
        for path in files.values():
            suffix = path.suffix.lower()
            if suffix in VIDEO_EXTENSIONS:
                self.videos.append(path)
            elif suffix == '.nfo':
                self.nfos.append(path)
                self._nfo_codes.append((path, release_code_from_filename(path.stem)))
            elif suffix in POSTER_EXTENSIONS:
                images.append(path)
        self.single = len(self.videos) == 1
        stems = {path.stem.casefold() for path in self.videos}
        # 连号图集（`X (1).jpg`、`X (2).jpg`…）不是某部视频的封面。
        self.numbered: dict[tuple[str, str], set[str]] = {}
        for image in images:
            match = _NUMBERED.fullmatch(image.stem.casefold())
            if match is not None and image.stem.casefold() not in stems:
                self.numbered.setdefault(match.group(1, 3), set()).add(match.group(2))
        self._shared: dict[str, bool] = {}
        self._video_codes: list[str | None] | None = None

    def _shared_movie(self, code: str | None) -> Path | None:
        if self.single:
            return self.files.get('movie.nfo')
        if not code or 'movie.nfo' not in self.files:
            return None
        if self._video_codes is None:
            self._video_codes = [release_code_from_filename(path.name) for path in self.videos]
        if code not in self._shared:
            self._shared[code] = all(same_release_code(code, value) for value in self._video_codes)
        return self.files.get('movie.nfo') if self._shared[code] else None

    def nfo_for(self, video: Path) -> Path | None:
        """`video` 的 NFO：同主名 > 番号同一且唯一 > 目录唯一 `movie.nfo`。"""
        nfo = self.files.get((video.stem + '.nfo').casefold())
        if nfo is None and self._nfo_codes:
            code = release_code_from_filename(video.name)
            matching = [path for path, value in self._nfo_codes if code and same_release_code(code, value)]
            if len(matching) == 1:
                nfo = matching[0]
            elif not matching:
                nfo = self._shared_movie(code)
        return nfo

    def images_for(self, video: Path) -> list[Path]:
        """`video` 的封面候选，按 `<主名>-poster`、同名、`poster/folder/cover` 的顺序。"""
        names = [video.stem + '-poster']
        match = _NUMBERED.fullmatch(video.stem.casefold())
        numbered = bool(match and self.numbered.get(match.group(1, 3), set()) - {match.group(2)})
        if not numbered:
            names.append(video.stem)
        if self.single:
            names.extend(['poster', 'folder', 'cover'])
        return [self.files[name.casefold() + extension] for name in names
                for extension in POSTER_EXTENSIONS if name.casefold() + extension in self.files]


def read_nfo(path: Path) -> dict:
    """读一个影片 NFO 成固定键的字典；拒绝 DTD／实体声明，限制体积。

    坏文件抛 `ValueError`，消息可以直接写进日志。
    """
    with path.open('rb') as handle:
        raw = handle.read(_MAX_BYTES + 1)
    # XML 的 UTF-16/32 编码包含零字节；声明检查同样覆盖这些编码。
    declarations = raw.replace(b'\x00', b'').upper()
    if len(raw) > _MAX_BYTES or b'<!DOCTYPE' in declarations or b'<!ENTITY' in declarations:
        raise ValueError('NFO 文件过大或包含实体声明')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError(f'NFO 不是合法 XML：{error}') from None
    if root.tag not in {'movie', 'episodedetails', 'musicvideo'}:
        raise ValueError('NFO 不是影片或单集资料')

    def text(*keys) -> str:
        return next(((root.findtext(key) or '').strip() for key in keys
                     if (root.findtext(key) or '').strip()), '')

    identifiers = [node.text for node in root.findall('uniqueid')
                   if node.get('type', '').lower() in {'javboss', 'jav', 'javid', 'dvdid', 'num'}]
    identifiers.extend([text('num'), text('sorttitle')])
    # 通用 id 常是 IMDb/TMDb；仅明确的番号形状参与 JAV 身份识别。
    for value in [text('id'), *(node.text or '' for node in root.findall('uniqueid'))]:
        if _CODE_SHAPE.fullmatch(value.strip()):
            identifiers.append(value)
    codes = {code for value in identifiers if (code := release_code_from_text(value or ''))}
    if len(codes) > 1:
        raise ValueError('NFO 包含多个不同番号')

    tags = list(dict.fromkeys(node.text.strip() for key in ('genre', 'tag')
                              for node in root.findall(key) if node.text and node.text.strip()))
    actors = [name for node in root.findall('actor')
              if (name := (node.findtext('name') or '').strip())]
    release_date = text('premiered', 'releasedate', 'aired', 'release')
    year = text('year') or (release_date[:4] if re.match(r'^\d{4}', release_date) else '')
    art_values = [value for value in (text('art/poster'), text('thumb[@aspect="poster"]'), text('thumb'),
                                      text('art/fanart'), text('fanart/thumb'))
                  if value]
    cover_url = next((value for value in art_values if '://' in value), '')
    local = next((value for value in art_values if '://' not in value), '')

    payload = {
        'title': text('title', 'localtitle', 'name'),
        'original_title': text('originaltitle'),
        'code': next(iter(codes), ''),
        'studio': text('studio', 'maker'),
        'series': text('set/name', 'set', 'showtitle'),
        'release_date': release_date,
        'year': year,
        'actors': actors,
        'tags': tags,
        'cover_url': cover_url,
        'local_art': local,
        'plot': text('plot', 'outline'),
    }
    return {key: value for key, value in payload.items() if value}


def local_art(video: Path, payload: dict) -> Path | None:
    """`payload['local_art']` 指向视频所在目录内的本地图片时返回它的绝对路径，其余 None。"""
    value = str(payload.get('local_art', '') or '')
    if not value or '://' in value:
        return None
    path = (video.parent / value).resolve()
    if path.is_relative_to(video.parent.resolve()) and path.is_file():
        return path
    return None
