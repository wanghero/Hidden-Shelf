"""把盘里已有的本地资料导入库：NFO、旧封面、`overrides.json`。

本地 NFO 与封面先于联网来源（计划 2）；用户在 `overrides.json` 里写的东西以 `user:manual`
身份合并，任何自动写入都覆盖不掉。原始文件一律不动，归位时才搬去 `HiddenShelf/legacy/`。
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import entities
from .field_owners import USER_MANUAL, FieldWrite, auto_owner, write_owned_fields
from .paths import ShelfPaths
from .rules.codes import normalise_code_key, part_marker
from .rules.nfo import read_nfo
from .scan import content_type_of
from .studios import canonical_studio, canonicalize_existing, fill_studios_from_code

Progress = Callable[[str], None]

NFO_OWNER = auto_owner("nfo")
LOCAL_OWNER = auto_owner("local")
#: NFO 里直接落到 asset 标量列的键。
_NFO_SCALARS = ("title", "original_title", "studio", "series", "release_date", "plot")
#: `overrides.json` 允许改的标量字段。
OVERRIDE_SCALARS = ("title", "original_title", "studio", "series", "release_date", "plot")
#: 封面来源优先级。
_COVER_PRIORITY = {"poster": 0, "cover": 1, "fanart": 2}


@dataclass
class ImportResult:
    nfo: int = 0
    covers: int = 0
    overrides: int = 0


def import_local(connection: sqlite3.Connection, paths: ShelfPaths, *,
                 progress: Progress = lambda message: None) -> ImportResult:
    """导入全部待处理的 NFO 与封面，最后合并 `overrides.json`。"""
    paths.ensure()
    result = ImportResult()
    # 老库里的厂牌别名先改成规范写法（カリビアンコム → Caribbeancom），之后归位与出站才会用新名字。
    renamed = canonicalize_existing(connection)
    if renamed:
        progress(f"厂牌名改成规范写法：{renamed} 条")
    # 番号形状独属一家的（Tokyo-Hot 的 n####、HEYZO），厂牌空着就直接补上，不等联网刮削。
    filled = fill_studios_from_code(connection)
    if filled:
        progress(f"按番号形状补上厂牌：{filled} 条")
    result.nfo = _import_nfos(connection, paths, progress)
    result.covers = _import_covers(connection, paths, progress)
    connection.commit()
    result.overrides = apply_overrides(connection, paths, progress=progress)
    progress(f"导入完成：{result.nfo} 个 NFO，{result.covers} 张封面，{result.overrides} 条覆盖")
    return result


def _siblings(connection: sqlite3.Connection, asset_id: int) -> list[sqlite3.Row]:
    """同一番号的全部碟（含自己）；没有番号就只有自己。"""
    row = connection.execute("SELECT id,code_key FROM asset WHERE id=?", (asset_id,)).fetchone()
    if row is None:
        return []
    if row["code_key"]:
        return connection.execute(
            "SELECT * FROM asset WHERE code_key=? AND vanished=0 ORDER BY part,id", (row["code_key"],)).fetchall()
    return connection.execute("SELECT * FROM asset WHERE id=?", (asset_id,)).fetchall()


def _import_nfos(connection, paths, progress) -> int:
    count = 0
    pending = connection.execute(
        "SELECT id,path,asset_id FROM sidecar WHERE kind='nfo' AND status='pending' AND asset_id IS NOT NULL "
        "ORDER BY path").fetchall()
    for sidecar in pending:
        source = paths.absolute(sidecar["path"])
        try:
            payload = read_nfo(source)
        except (OSError, ValueError) as error:
            progress(f"NFO 读不了，跳过 {sidecar['path']}：{error}")
            connection.execute("UPDATE sidecar SET status='failed' WHERE id=?", (sidecar["id"],))
            continue
        for asset in _siblings(connection, int(sidecar["asset_id"])):
            _apply_nfo(connection, asset, payload)
        connection.execute("UPDATE sidecar SET status='imported' WHERE id=?", (sidecar["id"],))
        count += 1
        progress(f"导入 NFO {sidecar['path']}")
    return count


def _apply_nfo(connection, asset: sqlite3.Row, payload: dict) -> None:
    asset_id = int(asset["id"])
    if payload.get("studio"):
        payload = {**payload, "studio": canonical_studio(payload["studio"])}
    writes = [FieldWrite(key, payload[key], NFO_OWNER) for key in _NFO_SCALARS if payload.get(key)]
    if payload.get("code") and not asset["code"]:
        writes.append(FieldWrite("code", payload["code"], NFO_OWNER, require_empty=True))
    if writes:
        write_owned_fields(connection, "asset", asset_id, writes)
    if payload.get("code") and not asset["code"]:
        current = connection.execute("SELECT code,name FROM asset WHERE id=?", (asset_id,)).fetchone()
        if current["code"]:
            connection.execute(
                "UPDATE asset SET code_key=?,part=?,content_type=? WHERE id=?",
                (normalise_code_key(current["code"]), part_marker(current["name"]),
                 content_type_of(current["name"], current["code"]), asset_id))
    for name in payload.get("actors", ()):
        entities.link(connection, asset_id, entities.ensure_entity(connection, "performer", name), "performer", "nfo")
    for name in payload.get("tags", ()):
        entities.link(connection, asset_id, entities.ensure_entity(connection, "tag", name), "tag", "nfo")
    if payload.get("studio"):
        entities.link(connection, asset_id, entities.ensure_entity(connection, "studio", payload["studio"]), "studio", "nfo")
    if payload.get("series"):
        entities.link(connection, asset_id, entities.ensure_entity(connection, "series", payload["series"]), "series", "nfo")


def _import_covers(connection, paths, progress) -> int:
    count = 0
    pending = connection.execute(
        "SELECT s.id,s.path,s.kind,s.asset_id FROM sidecar s "
        "WHERE s.kind IN ('poster','cover','fanart') AND s.status='pending' AND s.asset_id IS NOT NULL "
        "ORDER BY s.asset_id, s.path").fetchall()
    by_asset: dict[int, list[sqlite3.Row]] = {}
    for row in pending:
        by_asset.setdefault(int(row["asset_id"]), []).append(row)
    for asset_id, candidates in by_asset.items():
        asset = connection.execute("SELECT id,code_key FROM asset WHERE id=?", (asset_id,)).fetchone()
        if asset is None:
            continue
        stem = asset["code_key"] or f"asset-{asset_id}"
        destination = paths.covers / f"{stem}.jpg"
        installed = False
        for candidate in sorted(candidates, key=lambda row: (_COVER_PRIORITY[row["kind"]], row["path"])):
            if installed:
                connection.execute("UPDATE sidecar SET status='imported' WHERE id=?", (candidate["id"],))
                continue
            if install_image(paths.absolute(candidate["path"]), destination):
                installed = True
                rel = paths.shelf_relative(destination)
                for sibling in _siblings(connection, asset_id):
                    write_owned_fields(connection, "asset", int(sibling["id"]),
                                       [FieldWrite("cover_file", rel, LOCAL_OWNER)])
                connection.execute("UPDATE sidecar SET status='imported' WHERE id=?", (candidate["id"],))
                count += 1
                progress(f"导入封面 {candidate['path']} → {rel}")
            else:
                progress(f"图片读不了，跳过 {candidate['path']}")
                connection.execute("UPDATE sidecar SET status='failed' WHERE id=?", (candidate["id"],))
    return count


def install_image(source: Path, destination: Path, quality: int = 90) -> bool:
    """用 Pillow 打开、转 RGB、存 JPEG。坏图返回 False，不抛。"""
    try:
        with Image.open(source) as image:
            image.load()
            rgb = image.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        rgb.save(temporary, "JPEG", quality=quality)
        temporary.replace(destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        return False
    return True


def apply_overrides(connection: sqlite3.Connection, paths: ShelfPaths, *,
                    progress: Progress = lambda message: None) -> int:
    """读 `overrides.json`，以 `user:manual` 身份写进库。返回成功套用的条目数。

    格式：`{"<番号>": {"title": "...", "studio": "...", "performers": ["甲"], "tags": ["..."]}}`。
    番号按 `normalise_code_key` 匹配 `code_key`；找不到的条目记日志跳过。
    """
    if not paths.overrides.is_file():
        return 0
    try:
        raw = json.loads(paths.overrides.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        progress(f"overrides.json 读不了：{error}")
        return 0
    if not isinstance(raw, dict):
        progress("overrides.json 顶层不是对象，忽略")
        return 0
    applied = 0
    for code, fields in raw.items():
        if not isinstance(fields, dict):
            progress(f"overrides.json 里 {code!r} 的值不是对象，跳过")
            continue
        key = normalise_code_key(str(code))
        assets = connection.execute("SELECT id FROM asset WHERE code_key=? ORDER BY id", (key,)).fetchall()
        if not assets:
            progress(f"overrides.json 里的番号找不到对应文件，跳过：{code}")
            continue
        for asset in assets:
            asset_id = int(asset["id"])
            writes = [FieldWrite(name, str(fields[name]), USER_MANUAL)
                      for name in OVERRIDE_SCALARS if name in fields and fields[name] is not None]
            if writes:
                write_owned_fields(connection, "asset", asset_id, writes)
            for role, kind, name in (("performer", "performer", "performers"), ("tag", "tag", "tags")):
                if name not in fields:
                    continue
                values = fields[name] if isinstance(fields[name], list) else [fields[name]]
                entities.unlink(connection, asset_id, role, "user")
                for value in values:
                    text = str(value or "").strip()
                    if text:
                        entities.link(connection, asset_id, entities.ensure_entity(connection, kind, text), role, "user")
        applied += 1
    connection.commit()
    return applied
