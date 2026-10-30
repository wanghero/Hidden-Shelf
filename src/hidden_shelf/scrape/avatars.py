"""女优官方头像：`entity.metadata.avatar_url` 非空、`avatar_file` 为空的艺人，取图落 `avatars/<entity_id>.jpg`。

地址由 `scrape.apply` 在落库演员时存进元数据（r18dev 的 `ACTRESS_IMAGE`，图在 DMM 的头像目录下）。这里不量尺寸，
直接下（上限 2 MiB），Pillow 转正、RGB、最长边 512。失败记日志不抛：404 把地址从元数据里拿掉免得每趟再撞，
其余（连接、5xx、冷却）留着下趟再试。一次运行最多 `limit` 个。
"""
from __future__ import annotations

import io
import json
import sqlite3
from collections.abc import Callable

import httpx
from PIL import Image, ImageOps

from .. import entities
from ..fsutil import atomic_path
from ..paths import ShelfPaths
from . import transport as tp
from .access import SourcePaused
from .covers import referer_for
from .transport import DeadlineExceeded, NotFound, Unavailable

AVATAR_LIMIT = 2 * 1024 * 1024
AVATAR_EDGE = 512
DEFAULT_BATCH = 200

Progress = Callable[[str], None]


def pending_avatars(connection: sqlite3.Connection, *, limit: int = DEFAULT_BATCH) -> list[tuple[int, str, str]]:
    """待取头像的艺人：`(entity_id, 名字, 地址)`，按 id 顺序。"""
    found: list[tuple[int, str, str]] = []
    for row in connection.execute(
            "SELECT id, canonical_name, metadata FROM entity WHERE kind='performer' "
            "AND (avatar_file IS NULL OR trim(avatar_file)='') ORDER BY id"):
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except (ValueError, TypeError):
            continue
        url = str((metadata or {}).get("avatar_url") or "").strip() if isinstance(metadata, dict) else ""
        if url.startswith("https://"):
            found.append((int(row["id"]), str(row["canonical_name"]), url))
        if len(found) >= limit:
            break
    return found


def _render(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        upright = ImageOps.exif_transpose(image) or image
        rgb = upright.convert("RGB")
    rgb.thumbnail((AVATAR_EDGE, AVATAR_EDGE))
    return rgb


def install_avatars(connection: sqlite3.Connection, paths: ShelfPaths, transport, *,
                    progress: Progress = lambda message: None, limit: int = DEFAULT_BATCH,
                    deadline: float | None = None) -> int:
    """取回并落盘待取的头像，返回新装上的张数。"""
    installed = 0
    for entity_id, name, url in pending_avatars(connection, limit=limit):
        try:
            data = tp.fetch(transport, url, referer=referer_for(url), limit=AVATAR_LIMIT, deadline=deadline)
            image = _render(data)
        except NotFound:
            entities.merge_metadata(connection, entity_id, {"avatar_url": None, "avatar_missing": url})
            progress(f"[头像] {name} 官方头像不存在，不再取")
            continue
        except SourcePaused as error:
            progress(f"[头像] {name} 暂停：{error}")
            break
        except DeadlineExceeded:
            progress("[头像] 本趟预算用完，其余下趟再取")
            break
        except (Unavailable, httpx.TransportError) as error:
            progress(f"[头像] {name} 未取得：{error}")
            continue
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            progress(f"[头像] {name} 图解不开：{error}")
            continue
        destination = paths.avatars / f"{entity_id}.jpg"
        with atomic_path(destination) as temporary:
            image.save(temporary, "JPEG", quality=88)
        connection.execute("UPDATE entity SET avatar_file=? WHERE id=?", (paths.shelf_relative(destination), entity_id))
        installed += 1
        progress(f"[头像] {name} ← {url}")
    connection.commit()
    return installed
