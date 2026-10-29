"""原始快照 `.shelf/sources/<番号>-<来源>.json`：有效 7 天，期内不重问；「没有」也记 7 天。

思路取自 peach `library_processing.py` 的 `_evidence_path`、`_cached_evidence` 与 `_MissCache`
（7 天同一个有效期：来源会补录、片子可能后来上架，两边同时到期才不会出现「没有」已经过期、
「有」还压着旧值）。只记来源的确定答复：成功的 `result` 与 `not_found` 类的 `error`；超时、5xx、
网络、限流、拒绝访问一概不写——「没拿到」不是「没有」。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from ..fsutil import atomic_write_text

TTL_SECONDS = 7 * 24 * 3600


class Snapshots:
    def __init__(self, root: Path, *, ttl: float = TTL_SECONDS, now=time.time):
        self.root = Path(root)
        self.ttl = ttl
        self.now = now

    def path(self, code_key: str, source: str) -> Path:
        return self.root / f"{code_key}-{source}.json"

    def _read(self, code_key: str, source: str) -> dict | None:
        path = self.path(code_key, source)
        try:
            if self.now() - path.stat().st_mtime > self.ttl:
                return None
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return loaded if isinstance(loaded, dict) else None

    def load(self, code_key: str, source: str) -> dict | None:
        """新鲜且有 `result` 的快照正文；否则 None。"""
        record = self._read(code_key, source)
        if record is None or not isinstance(record.get("result"), dict):
            return None
        return record["result"]

    def fresh_miss(self, code_key: str, source: str) -> bool:
        """这一站对这个番号说过「没有」且还在期内。"""
        record = self._read(code_key, source)
        return bool(record) and isinstance(record.get("error"), dict) and "result" not in record

    def _write(self, code_key: str, source: str, body: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"fetched_at": datetime.fromtimestamp(self.now()).isoformat(timespec="seconds"),
                   "source": source, "code": code_key, **body}
        atomic_write_text(self.path(code_key, source), json.dumps(payload, ensure_ascii=False, indent=1))

    def save_result(self, code_key: str, source: str, payload: dict) -> None:
        self._write(code_key, source, {"result": payload})

    def save_miss(self, code_key: str, source: str, reason: str, message: str = "") -> None:
        """只给来源的确定答复用（`not_found` 类与身份错配）；调用方保证不把临时失败写进来。"""
        self._write(code_key, source, {"error": {"reason": reason, "message": message}})

    def forget(self, code_key: str) -> int:
        removed = 0
        for path in self.root.glob(f"{code_key}-*.json"):
            path.unlink(missing_ok=True)
            removed += 1
        return removed

    def sources_for(self, code_key: str) -> list[str]:
        """这个番号已有快照的来源名（不论新鲜与否）。"""
        prefix = f"{code_key}-"
        return sorted(path.stem[len(prefix):] for path in self.root.glob(f"{code_key}-*.json"))
