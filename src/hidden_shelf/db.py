"""SQLite 工作库 `HiddenShelf/shelf.db`：连接、迁移、实体名归一。"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from .paths import ShelfPaths, nfc

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
#: 归一化时抹掉的字符：空白与全半角标点、符号。
_STRIP = re.compile(r"[\s\W_]+", re.UNICODE)
#: 规范名里要剥掉的零宽字符（取自 peach `entities.ZERO_WIDTH`）。上游译名夹带过 `‌斋藤亚美里`：页面上和普通名字
#: 一模一样，但 `strip()` 不认它们不是空白，于是同一个人能存成两个实体。U+200D（ZWJ）不在名单里——emoji 靠它连字。
ZERO_WIDTH = str.maketrans({"​": None, "‌": None, "⁠": None, "﻿": None})


def connect(paths: ShelfPaths) -> sqlite3.Connection:
    """打开（必要时新建）本盘的库，开 WAL 与外键，自动跑迁移。"""
    paths.shelf.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(paths.db)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    migrate(connection)
    normalize_stored_paths(connection)
    return connection


def schema_version(connection: sqlite3.Connection) -> int:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
    if not exists:
        return 0
    row = connection.execute("SELECT max(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def migrate(connection: sqlite3.Connection) -> None:
    """按文件名顺序执行 `migrations/*.sql`，每个执行完登记版本。"""
    current = schema_version(connection)
    for script in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(script.name.split("_", 1)[0])
        if version <= current:
            continue
        connection.executescript(script.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO schema_version(version) VALUES(?)", (version,))
        connection.commit()


#: 合并两条记录时不按「谁空谁补」走的列：`path`/`name` 由调用方定，`vanished` 取「只要有一条还在
#: 盘上就算在」，`first_seen` 取更早的那个，`field_owners` 单独合并，`revision` 只增。其余列（文件
#: 事实与刮来的资料）一律是留下的那条缺哪项就从另一条补——只增不减，不覆盖任何已有的值。
_MERGE_SKIP = frozenset({"id", "path", "name", "vanished", "first_seen", "field_owners", "revision"})


def _pick_survivor(connection: sqlite3.Connection, first: int, second: int) -> tuple[int, int]:
    """同一个文件的两条记录，留哪条删哪条：刮过的优先，都刮过或都没刮就留先建的那条。"""
    rows = {int(row["id"]): row for row in connection.execute(
        f"SELECT id,scraped_at FROM asset WHERE id IN ({first},{second})")}
    scraped = [asset_id for asset_id in (first, second)
               if str(rows[asset_id]["scraped_at"] or "").strip()]
    keep = scraped[0] if len(scraped) == 1 else min(first, second)
    return keep, second if keep == first else first


def _owners(raw: object) -> dict[str, str]:
    try:
        parsed = json.loads(str(raw or "{}"))
    except ValueError:
        return {}
    return {str(key): str(value) for key, value in parsed.items()} if isinstance(parsed, dict) else {}


def merge_assets(connection: sqlite3.Connection, keep: int, drop: int) -> None:
    """把 `drop` 这条记录并进 `keep` 再删掉它：`keep` 空着的列从 `drop` 补，归属跟着一起过来。

    只增不减：`keep` 上已有的值、归属、关联一个都不动。两处在用——`normalize_stored_paths` 把同一个
    文件的两种写法并成一条；归位发现目标路径被一条**已消失**的记录占着时把它并进来让位（那条记录
    的文件早就不在那个位置上了，否则不会标消失），不然 `asset.path UNIQUE` 会让那次搬迁整个回滚：
    2026-11-02 的真实盘上一次 207 个「数据库写入失败，已改回原名」就是这么来的。
    """
    keep, drop = int(keep), int(drop)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(asset)")
               if row[1] not in _MERGE_SKIP]
    rows = {int(row["id"]): row for row in connection.execute(
        f"SELECT * FROM asset WHERE id IN ({keep},{drop})")}
    if keep not in rows or drop not in rows or keep == drop:
        return
    survivor, gone = rows[keep], rows[drop]
    fills = {name: gone[name] for name in columns
             if not str(survivor[name] or "").strip() and str(gone[name] or "").strip()}
    # 补过来的那些列，归属也跟着来；`keep` 自己的归属优先。
    owners = {**{name: owner for name, owner in _owners(gone["field_owners"]).items() if name in fills},
              **_owners(survivor["field_owners"])}
    fills["field_owners"] = json.dumps(owners, ensure_ascii=False, sort_keys=True)
    # 两条里只要有一条还在盘上，这个文件就还在；`first_seen` 取更早的那个。
    fills["vanished"] = min(int(survivor["vanished"]), int(gone["vanished"]))
    seen = [str(row["first_seen"] or "") for row in (survivor, gone) if str(row["first_seen"] or "")]
    if seen:
        fills["first_seen"] = min(seen)
    assignments = ",".join(f"{name}=?" for name in fills)
    connection.execute(f"UPDATE asset SET {assignments},revision=revision+1 WHERE id=?",
                       (*fills.values(), keep))
    # 演员、标签、厂牌的关联只增不减；`keep` 上已有的那条（主键撞上）原样留着。
    connection.execute(
        "INSERT OR IGNORE INTO asset_entity(asset_id,entity_id,role,source,confidence) "
        "SELECT ?,entity_id,role,source,confidence FROM asset_entity WHERE asset_id=?", (keep, drop))
    connection.execute("UPDATE sidecar SET asset_id=? WHERE asset_id=?", (keep, drop))
    connection.execute("DELETE FROM asset WHERE id=?", (drop,))


def normalize_stored_paths(connection: sqlite3.Connection) -> int:
    """把库里存着的 `asset.path`/`asset.name` 与 `sidecar.path` 归一成 NFC，返回改动的行数。

    `connect()` 每次都跑一遍，幂等且便宜（全是 NFC 时一个字节都不写）。归一之后撞上另一条记录，
    说明那两条记录是同一个文件的两种写法（起因见 `paths.nfc`）：按 `_pick_survivor` 留一条、
    `_merge_assets` 把另一条并进去。`sidecar` 没有要保住的资料，重复的直接删掉，扫描会照常重新登记。

    这就是 1.4.16 及之前跑出来的盘的恢复路径：原来那条带资料的记录重新认领盘上的文件，番号、
    标题、演员、`scraped_at` 全回来，不用重新联网刮；目录名也会在下一趟归位自己改回带标题的写法。
    """
    changed = 0
    rows = connection.execute("SELECT id,path,name FROM asset").fetchall()
    holder = {row["path"]: int(row["id"]) for row in rows}
    gone: set[int] = set()
    for row in rows:
        asset_id, path = int(row["id"]), row["path"]
        if asset_id in gone:
            continue
        wanted, wanted_name = nfc(path), nfc(row["name"])
        if wanted == path and wanted_name == row["name"]:
            continue
        twin = holder.get(wanted)
        if wanted != path and twin is not None and twin != asset_id:
            keep, drop = _pick_survivor(connection, twin, asset_id)
            merge_assets(connection, keep, drop)
            gone.add(drop)
            holder.pop(path, None)
            holder[wanted] = keep
            connection.execute("UPDATE asset SET path=?,name=? WHERE id=?", (wanted, wanted_name, keep))
        else:
            connection.execute("UPDATE asset SET path=?,name=? WHERE id=?", (wanted, wanted_name, asset_id))
            holder.pop(path, None)
            holder[wanted] = asset_id
        changed += 1
    sidecars = connection.execute("SELECT id,path FROM sidecar").fetchall()
    taken = {row["path"]: int(row["id"]) for row in sidecars}
    for row in sidecars:
        sidecar_id, path = int(row["id"]), row["path"]
        wanted = nfc(path)
        if wanted == path:
            continue
        twin = taken.get(wanted)
        if twin is not None and twin != sidecar_id:
            connection.execute("DELETE FROM sidecar WHERE id=?", (max(twin, sidecar_id),))
            taken[wanted] = min(twin, sidecar_id)
        else:
            connection.execute("UPDATE sidecar SET path=? WHERE id=?", (wanted, sidecar_id))
            taken[wanted] = sidecar_id
        taken.pop(path, None)
        changed += 1
    if changed:
        connection.commit()
    return changed


def strip_zero_width(name: str | None) -> str:
    return str(name or "").translate(ZERO_WIDTH)


def normalize_name(name: str) -> str:
    """实体合并用的名字键：去零宽字符、NFKC、casefold、去空白与全半角标点。"""
    text = unicodedata.normalize("NFKC", strip_zero_width(name))
    text = _STRIP.sub("", text)
    return unicodedata.normalize("NFC", text.casefold())
