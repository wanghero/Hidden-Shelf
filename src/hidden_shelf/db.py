"""SQLite 工作库 `.shelf/shelf.db`：连接、迁移、实体名归一。"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

from .paths import ShelfPaths

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
#: 归一化时抹掉的字符：空白与全半角标点、符号。
_STRIP = re.compile(r"[\s\W_]+", re.UNICODE)


def connect(paths: ShelfPaths) -> sqlite3.Connection:
    """打开（必要时新建）本盘的库，开 WAL 与外键，自动跑迁移。"""
    paths.shelf.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(paths.db)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    migrate(connection)
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


def normalize_name(name: str) -> str:
    """实体合并用的名字键：NFC、casefold、去空白与全半角标点。"""
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = _STRIP.sub("", text)
    return unicodedata.normalize("NFC", text.casefold())
