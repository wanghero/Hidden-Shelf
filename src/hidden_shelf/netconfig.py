"""跨盘全局配置 `~/.hidden-shelf/config.json`：代理三选一、各站 Cookie 与开关、来源链覆盖。

凭据只住在这里，不进盘里的任何文件、不进日志、不进快照。代理语义照 peach「直连 / 自定义代理 /
跟随环境」三选一（`environment` 读进程代理环境变量，`direct` 忽略它们，`proxy` 用给定地址）。
路径可用环境变量 `HIDDEN_SHELF_HOME` 覆盖（测试用）。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

NETWORK_MODES = ("environment", "direct", "proxy")
_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}


def home() -> Path:
    override = os.environ.get("HIDDEN_SHELF_HOME")
    return Path(override).expanduser() if override else Path.home() / ".hidden-shelf"


def config_path() -> Path:
    return home() / "config.json"


def validate_proxy(address: str) -> str:
    """带端口的 HTTP 或 SOCKS 代理地址；不合法抛 `ValueError`，消息给用户看。"""
    text = str(address or "").strip()
    try:
        parsed = urlsplit(text)
        valid = (parsed.scheme in _PROXY_SCHEMES and bool(parsed.hostname) and bool(parsed.port)
                 and not parsed.query and not parsed.fragment and parsed.path in {"", "/"})
    except ValueError:
        valid = False
    if not valid or any(char.isspace() for char in text):
        raise ValueError("请填写带端口的 HTTP 或 SOCKS 代理地址，如 http://127.0.0.1:7890")
    return text


@dataclass
class SourceSettings:
    enabled: bool = True
    cookie: str = ""


@dataclass
class GlobalConfig:
    network_mode: str = "environment"
    proxy: str = ""
    sources: dict[str, SourceSettings] = field(default_factory=dict)
    routes: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "GlobalConfig":
        """读配置；文件不存在时写出默认值。坏 JSON 用默认值但不覆盖文件。"""
        target = path or config_path()
        if not target.is_file():
            config = cls()
            config.save(target)
            return config
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        config = cls()
        network = raw.get("network") if isinstance(raw.get("network"), dict) else {}
        mode = str(network.get("mode") or "")
        if mode in NETWORK_MODES:
            config.network_mode = mode
        config.proxy = str(network.get("proxy") or "")
        sources = raw.get("sources") if isinstance(raw.get("sources"), dict) else {}
        for name, item in sources.items():
            if isinstance(item, dict):
                config.sources[str(name)] = SourceSettings(
                    enabled=bool(item.get("enabled", True)), cookie=str(item.get("cookie") or ""))
        routes = raw.get("routes") if isinstance(raw.get("routes"), dict) else {}
        for kind, chain in routes.items():
            if isinstance(chain, str):
                chain = [part.strip() for part in chain.split(",")]
            if isinstance(chain, list):
                config.routes[str(kind)] = [str(part).strip() for part in chain if str(part or "").strip()]
        return config

    def save(self, path: Path | None = None) -> None:
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "network": {"mode": self.network_mode, "proxy": self.proxy},
            "sources": {name: asdict(item) for name, item in self.sources.items()},
            "routes": dict(self.routes),
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def client_options(self) -> dict:
        """给 httpx.Client 的连接参数。"""
        if self.network_mode == "proxy":
            return {"trust_env": False, "proxy": validate_proxy(self.proxy)}
        return {"trust_env": self.network_mode == "environment"}

    def enabled(self, source: str) -> bool:
        item = self.sources.get(source)
        return True if item is None else bool(item.enabled)

    def cookie(self, source: str) -> str:
        item = self.sources.get(source)
        return "" if item is None else str(item.cookie or "")

    def describe(self) -> dict:
        """给人看的摘要：不带 Cookie 值，只说有没有。"""
        return {
            "path": str(config_path()),
            "network": {"mode": self.network_mode, "proxy_saved": bool(self.proxy)},
            "sources": {name: {"enabled": item.enabled, "cookie": bool(item.cookie)}
                        for name, item in self.sources.items()},
            "routes": dict(self.routes),
        }
