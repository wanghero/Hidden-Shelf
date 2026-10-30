"""派生产物的来源指纹：源文件没变就不重做九宫格、海报。

移植自 peach `src/peach/artifact_rules.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later），去掉 `upgrade_rules` 规则版本与资源类来源。边车文件 `<产物>.rule` 存 JSON。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..fsutil import atomic_write_text

#: 规则版本：九宫格参数或海报裁法变了就加一，旧产物整批重做。
RULE = "hidden-shelf/1"


def fingerprint(source: Path) -> dict:
    """记录源身份和文件代际（大小、mtime、inode），不读正文。"""
    info = Path(source).stat()
    return {"size": int(info.st_size), "mtime_ns": int(info.st_mtime_ns), "ino": int(getattr(info, "st_ino", 0))}


def _rule_path(artifact: Path) -> Path:
    return Path(str(artifact) + ".rule")


def current(artifact: Path, *, source: Path, rule: str = RULE) -> bool:
    """产物还在、规则没变、源文件指纹与生成时一致，才算是最新的。"""
    try:
        if not Path(artifact).is_file():
            return False
        record = json.loads(_rule_path(artifact).read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("rule") != rule:
            return False
        return record.get("source") == fingerprint(source)
    except (OSError, ValueError, TypeError):
        return False


def remember(artifact: Path, *, source: Path, rule: str = RULE) -> None:
    """登记这份产物是按哪份源文件生成的。"""
    atomic_write_text(_rule_path(artifact), json.dumps(
        {"rule": rule, "source": fingerprint(source)}, ensure_ascii=False))
