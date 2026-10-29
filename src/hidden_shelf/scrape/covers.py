"""联网封面：候选地址的拼法与判据、量尺寸择优、下载落盘。

移植自 peach `src/peach/jav_cover_fetch.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）的 `Candidate`、`candidate_for`、`code_variants`、`cid_variants`、`dmm_cdn_images`、
`official_image_candidates`、`content_id_images`、`is_javdb_image`、`THUMBNAIL`、`is_cross_product_cover`、
`probe_size`、`_usable_candidates`、`_measure`、`_download_best`。去掉 Prestige API、MGS、DUGA 的现问、成功日志
复用、`known_sizes` 升级模式与诊断计数——只留「有没有候选没回话」来分 `NotFound`（来源的确定答复）与
`Unavailable`（这趟没问成）。

候选从各站记录的 `cover_urls` 来（`candidates_from_records`），javdb 的转存图不当封面；r18dev 与 dmm 给的
`content_id` 另展开成 DMM 新旧 CDN 的高清变体，主机名和路径不能当清晰度，所有候选一起量尺寸按像素面积挑。
"""
from __future__ import annotations

import io
import re
import sqlite3
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from ..field_owners import FieldWrite, auto_owner, is_protected, owner_of, write_owned_fields
from ..fsutil import atomic_path
from ..paths import ShelfPaths
from ..rules.codes import code_letter_stem, normalise_code_key
from . import transport as tp
from .access import SOURCES, source_for
from .transport import PROBE_BYTES, DeadlineExceeded, NotFound, Unavailable

#: 低于这个宽度的是缩略图或占位图，不当封套。实测最低的正片封套是 800 宽。
MIN_WIDTH = 700
#: 找不到大图时退而求其次的下限。素人系官方图只有 300×300，有图比没图好；147×200 的仍然太小。
SMALL_MIN_WIDTH = 240
#: 整张下载的上限。
IMAGE_LIMIT = 16 * 1024 * 1024
#: 页面与上游证据里可能混着剧照与缩略图，按文件名排除。
THUMBNAIL = re.compile(r"(thumb|small|icon|/ts/|-s\d|_s\.)", re.I)
#: FC2 缩放服务的高清档：路径带 `thumbnail` 却是 700 宽以上的真图。
FC2_HIRES = re.compile(r"https://contents-thumbnail\d*\.fc2\.com/w(?:7\d\d|[89]\d\d|\d{4,})/", re.I)
IMAGE_URL = re.compile(r"https?://[^\"'\\ )]+?\.(?:jpg|jpeg|png|webp)")

AWS_LEGACY_DIGITAL = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/{cid}pl.jpg"
AWS_MODERN = "https://awsimgsrc.dmm.com/dig/{kind}/{cid}/{cid}pl.jpg"
AWS_LEGACY = "https://awsimgsrc.dmm.co.jp/pics_dig/{kind}/{cid}/{cid}pl.jpg"
DMM_REFERER = "https://www.dmm.co.jp/"

#: DMM 的 content_id 一定带番号字母段：`ABW-232` -> `118abw232`、`MGT-164` -> `h_1711mgt00164`。
_DMM_CID = re.compile(
    r"/(?:pics_dig/|dig/)?(?P<kind>digital/(?:video|amateur)|mono/movie)"
    r"(?:/adult)?/(?P<cid>[^/]+)/",
    re.I,
)
#: 番号与 content_id 各自末尾那段数字。content_id 可能带 DVD 版尾缀（`49ha102r`）。
_CODE_NUMBER = re.compile(r"(\d+)\D*$")
_CID_NUMBER = re.compile(r"(\d+)[a-z]*$")
#: 图床文件名里的作品号：五到七位的独立数字段。`pl1654160016.07k.gif` 那种十位的是上传时间戳，不算作品号。
_FILE_NUMBER = re.compile(r"(?<!\d)\d{5,7}(?!\d)")
#: 图床给上传起的十六进制串（PHP `uniqid`，13 位）。`5dd29b14380eaPS.jpg` 里夹着的 `14380` 是串的一截。
_UPLOAD_HASH = re.compile(r"[0-9a-f]{13,}", re.I)


# ---------- 判据 ----------

def _fc2_names_another_work(code: str, url: str) -> bool:
    """FC2 番号的图，文件名写着别的作品号。JavArchive 的图床 img.javstore.net 按作品号起文件名。"""
    key = normalise_code_key(code)
    wanted = _CODE_NUMBER.search(key) if key.startswith("FC2") else None
    name = _UPLOAD_HASH.sub("", urlparse(url or "").path.rsplit("/", 1)[-1])
    numbers = {int(one) for one in _FILE_NUMBER.findall(name)}
    return bool(wanted and numbers) and int(wanted.group(1)) not in numbers


def is_cross_product_cover(code: str, url: str) -> bool:
    """这个 URL 指向的是另一部片的封套。

    素人系番号在 avbase 上会连到 DVD 合集：`259LUXU-1475` 的页面主图取到的是 `SNG-021` 的封套
    （`118sng021`）。内容是同一段，封面却不是这部片的。判据落在 URL 上而不是抓取路径上。
    """
    if _fc2_names_another_work(code, url):
        return True
    stem = code_letter_stem(code)
    match = _DMM_CID.search(urlparse(url or "").path)
    if not stem or match is None:
        return False
    cid = match.group("cid").lower()
    if stem not in cid:
        return True
    # 字母段对上还不够：`YUJ-101` 取回的是 `yuj00011`，`CHU-201` 是 `chu00021`，`435MFC-135` 是
    # `h_1711mfcc00027`。数字段按整数比，补零和厂牌前缀都不影响。
    wanted, got = _CODE_NUMBER.search(code or ""), _CID_NUMBER.search(cid)
    return bool(wanted and got) and int(wanted.group(1)) != int(got.group(1))


def is_javdb_image(url: str = "", source: str = "") -> bool:
    """JavDB 转存图片只参与来源印证，不作为正式封面。"""
    domains = (*SOURCES["javdb"]["domains"], "tp.spfcas.com")
    for value in (url, source):
        value = str(value or "").strip().lower()
        if value in {"javdb", "javdb-page"}:
            return True
        host = urlparse(value).hostname if "://" in value else value
        if host and any(host == domain or host.endswith("." + domain) for domain in domains):
            return True
    return False


# ---------- 候选 ----------

PRODUCT_IMAGE = "product"
PREVIEW_IMAGE = "preview"
COVER_IMAGE = "cover"
_CANDIDATE_QUALITY = {PREVIEW_IMAGE: 0, COVER_IMAGE: 1, PRODUCT_IMAGE: 2}


@dataclass(frozen=True)
class Candidate:
    host: str
    url: str
    referer: str = DMM_REFERER
    kind: str = COVER_IMAGE


def candidate_quality(candidate: Candidate | None) -> int:
    return _CANDIDATE_QUALITY.get(candidate.kind if candidate else COVER_IMAGE, 1)


def code_variants(code: str) -> list[str]:
    """素人系番号带三位厂牌前缀，去掉才查得到：`278GYAN-017` -> `GYAN-017`。"""
    value = normalise_code_key(code)
    out = [value]
    stripped = re.sub(r"^\d{3}(?=[A-Z])", "", value)
    if stripped != value:
        out.append(stripped)
    return out


def cid_variants(content_id: str) -> list[str]:
    """数字段补到 5 位是必须的；带厂牌数字前缀的多半没有数字版，但仍试一次。"""
    cid = (content_id or "").strip().lower()
    if not cid:
        return []
    out = [cid]
    shape = re.match(r"^(\d{2,4})?([a-z]+)(\d+)$", cid)
    if shape:
        letters, digits = shape.group(2), shape.group(3)
        out.append(f"{letters}{int(digits):05d}")
        out.append(f"{letters}{digits}")
    return list(dict.fromkeys(out))


def referer_for(url: str) -> str:
    """图片请求带的 Referer：登记在 `access.SOURCES` 的站用它的登录页，MGS 用自己的，其余按 DMM。"""
    source = source_for(url)
    if source:
        return SOURCES[source]["login"]
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("mgstage.com"):
        return "https://www.mgstage.com/"
    if host.endswith("duga.jp"):
        return "https://duga.jp/"
    return DMM_REFERER


def candidate_for(url: str, *, kind: str | None = None) -> Candidate:
    parsed = urlparse(url)
    filename = Path(parsed.path).name.lower()
    if kind is None and "mgstage.com" in parsed.netloc.lower():
        if filename.startswith(("pb_e_", "pake-03_")):
            kind = PRODUCT_IMAGE
        elif "popsample" in filename:
            kind = PREVIEW_IMAGE
    return Candidate(parsed.netloc.lower(), url, referer_for(url), kind or COVER_IMAGE)


def _unique(candidates: Iterable[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    return [candidate for candidate in candidates
            if candidate.url and not (candidate.url in seen or seen.add(candidate.url))]


def dmm_cdn_images(url: str) -> list[Candidate]:
    """一个 DMM 图片地址 → 原地址加新旧两条 CDN 路径。主机名和路径不能当清晰度，三条都要量尺寸。"""
    clean = (url or "").split("?", 1)[0]
    parsed = urlparse(clean)
    match = _DMM_CID.search(parsed.path)
    candidates = [candidate_for(clean)] if IMAGE_URL.fullmatch(clean) else []
    if not match:
        return candidates
    kind = match.group("kind").lower()
    cid = match.group("cid").lower()
    candidates.extend([candidate_for(AWS_MODERN.format(kind=kind, cid=cid)),
                       candidate_for(AWS_LEGACY.format(kind=kind, cid=cid))])
    return _unique(candidates)


def official_image_candidates(url: str) -> list[Candidate]:
    """别处给的一个封面地址里，能当官方候选的那几条：只认 DMM 与 MGS 的官方图路径。社区站图床的地址不认。"""
    clean = (url or "").split("?", 1)[0].strip()
    if not IMAGE_URL.fullmatch(clean):
        return []
    if _DMM_CID.search(urlparse(clean).path):
        return dmm_cdn_images(clean)
    if urlparse(clean).netloc.lower().endswith("mgstage.com"):
        return [candidate_for(clean)]
    return []


def content_id_images(content_id: str) -> list[Candidate]:
    """DMM 数字版的 content_id → 新旧 CDN 上的封套地址。"""
    candidates: list[Candidate] = []
    for cid in cid_variants(content_id):
        candidates.extend([candidate_for(AWS_MODERN.format(kind="digital/video", cid=cid)),
                           candidate_for(AWS_LEGACY_DIGITAL.format(cid=cid))])
    return _unique(candidates)


#: 给出 `content_id` 就展开 DMM CDN 变体的来源。
_CONTENT_ID_SOURCES = frozenset({"r18dev", "dmm"})


def usable_candidates(code: str, candidates: Iterable[Candidate]) -> list[Candidate]:
    """去重，去掉缩略图（FC2 的高清档除外）与别的作品的封套。"""
    return _unique(candidate for candidate in candidates
                   if (not THUMBNAIL.search(candidate.url) or FC2_HIRES.match(candidate.url))
                   and not is_cross_product_cover(code, candidate.url))


def candidates_from_records(code: str, records: Iterable[tuple[str, dict]]) -> list[Candidate]:
    """各站记录（`(来源名, payload)`）→ 封面候选。javdb 的图不进；DMM 地址与 `content_id` 展开成 CDN 变体。"""
    found: list[Candidate] = []
    for source, payload in records:
        if not isinstance(payload, dict):
            continue
        for url in payload.get("cover_urls") or ():
            clean = str(url or "").split("?", 1)[0].strip()
            if not clean.startswith("https://") or is_javdb_image(clean, source):
                continue
            expanded = dmm_cdn_images(clean) if _DMM_CID.search(urlparse(clean).path) else [candidate_for(clean)]
            found.extend(expanded)
        if source in _CONTENT_ID_SOURCES and payload.get("content_id"):
            found.extend(content_id_images(str(payload["content_id"])))
    return usable_candidates(code, found)


# ---------- 量尺寸与下载 ----------

def probe_size(transport, candidate: Candidate, *, deadline: float | None = None) -> tuple[int, int]:
    """只拉图片头部量尺寸（Range 请求），别把整张 1 MB 的图拉下来。"""
    head = tp.fetch(transport, candidate.url, referer=candidate.referer, limit=PROBE_BYTES * 2, ranged=True,
                    deadline=deadline)
    return Image.open(io.BytesIO(head)).size


def _sleep_within(delay: float, deadline: float | None) -> None:
    if delay <= 0:
        return
    if deadline is not None and time.monotonic() + delay > deadline:
        raise DeadlineExceeded("动作预算已用尽")
    time.sleep(delay)


def _measure(transport, candidates: Sequence[Candidate], *, delay: float, deadline: float | None):
    """逐张量尺寸。返回 `(量到的 [(候选, (w, h))], 有没有候选没回话)`。

    404、占位图、解不开是来源回过话；连接断开、5xx、拒绝访问是没回话——有一张没回话，量不出就不算来源的确定答复。
    """
    measured: list[tuple[Candidate, tuple[int, int]]] = []
    unanswered = False
    for candidate in candidates:
        try:
            size = probe_size(transport, candidate, deadline=deadline)
        except httpx.TransportError:
            unanswered = True
            continue
        except NotFound:
            continue
        except Unavailable:
            unanswered = True
            continue
        except (UnidentifiedImageError, OSError, ValueError):
            continue
        finally:
            _sleep_within(delay, deadline)
        measured.append((candidate, size))
    return measured, unanswered


def _download_best(transport, measured, *, minimum_width: int, deadline: float | None):
    """按像素面积择优，同尺寸优先商品图，预览图只作末档。动图只有下完整张才认得出，跳过。"""
    animated = failed = 0
    ordered = sorted(measured, key=lambda item: (candidate_quality(item[0]) > 0, item[1][0] * item[1][1],
                                                 candidate_quality(item[0])), reverse=True)
    for candidate, size in ordered:
        try:
            data = tp.fetch(transport, candidate.url, referer=candidate.referer, limit=IMAGE_LIMIT, deadline=deadline)
        except (Unavailable, httpx.TransportError):
            failed += 1
            continue
        try:
            with Image.open(io.BytesIO(data)) as image:
                moving = bool(getattr(image, "is_animated", False))
                image.load()
                actual = image.size
        except (OSError, ValueError, Image.DecompressionBombError):
            continue
        if moving:
            animated += 1
            continue
        if actual != size or actual[0] < minimum_width:
            continue
        return candidate, actual, data
    if animated and animated == len(measured):
        raise NotFound("候选都是动图")
    if failed:
        raise Unavailable("可用候选完整下载都失败")
    raise NotFound("候选下载后尺寸都对不上")


def best_cover(transport, code: str, candidates: Iterable[Candidate], *, minimum_width: int = MIN_WIDTH,
               delay: float = 0.0, deadline: float | None = None) -> tuple[Candidate, tuple[int, int], bytes]:
    """封面择优：量尺寸 → 够宽的按像素面积挑 → 整张下载核实。

    全部太小时用 `SMALL_MIN_WIDTH` 再筛一次（素人系官方图只有 300 宽）。一张都不行时：每张都回过话就是来源的
    确定答复，抛 `NotFound`；有一张断在连接、5xx 或拒绝访问上，抛 `Unavailable`。
    """
    usable = usable_candidates(code, candidates)
    if not usable:
        raise NotFound("没有可用的封面候选")
    measured, unanswered = _measure(transport, usable, delay=delay, deadline=deadline)
    wide = [item for item in measured if item[1][0] >= minimum_width]
    if not wide:
        wide = [item for item in measured if item[1][0] >= SMALL_MIN_WIDTH]
        minimum_width = SMALL_MIN_WIDTH
    if not wide:
        if unanswered:
            raise Unavailable("封面候选都没问成或只有缩略图")
        raise NotFound("封面候选只有缩略图或占位图" if measured else "封面候选地址都没有图")
    try:
        return _download_best(transport, wide, minimum_width=minimum_width, deadline=deadline)
    except NotFound:
        if unanswered:
            raise Unavailable("封面候选没问成") from None
        raise


# ---------- 落盘 ----------

#: 联网封面能顶掉的现归属：没有、或只是抽帧兜底。本地旧封面（`auto:local`）与用户的不动。
_REPLACEABLE_COVER_OWNERS = frozenset({"", auto_owner("frame")})


def install_online_cover(connection: sqlite3.Connection, paths: ShelfPaths, asset_ids: Iterable[int], code_key: str,
                         data: bytes, source: str) -> str:
    """把下好的图写成 `covers/<code_key>.jpg`，`cover_file` 以 `auto:<source>` 身份写到每一碟。

    哪一碟都写不得（归属是本地封面或用户的）就连文件也不写，返回空串；写了就顺手删旧海报的指纹，让 `media` 步重做海报。
    """
    ids = [int(asset_id) for asset_id in asset_ids]
    rows = {asset_id: connection.execute("SELECT cover_file, field_owners FROM asset WHERE id=?", (asset_id,)).fetchone()
            for asset_id in ids}
    writable = [asset_id for asset_id, row in rows.items() if row is not None
                and (not str(row["cover_file"] or "").strip()
                     or owner_of(row["field_owners"], "cover_file") in _REPLACEABLE_COVER_OWNERS)
                and not is_protected(owner_of(row["field_owners"], "cover_file"))]
    if not writable:
        return ""
    destination = paths.covers / f"{code_key}.jpg"
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        rgb = image.convert("RGB")
    with atomic_path(destination) as temporary:
        rgb.save(temporary, "JPEG", quality=90)
    rel = paths.shelf_relative(destination)
    for asset_id in writable:
        write_owned_fields(connection, "asset", asset_id, [FieldWrite("cover_file", rel, auto_owner(source))])
    poster_rule = paths.posters / f"{code_key}.jpg.rule"
    poster_rule.unlink(missing_ok=True)
    return rel
