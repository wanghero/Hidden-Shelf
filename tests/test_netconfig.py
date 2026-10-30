"""跨盘全局配置 `~/.hidden-shelf/config.json`：代理三选一、各站 Cookie 与开关、路由覆盖。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hidden_shelf import netconfig
from hidden_shelf.netconfig import GlobalConfig, SourceSettings, validate_proxy


@pytest.fixture
def home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HIDDEN_SHELF_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_global_config_defaults_and_roundtrip(home: Path):
    config = GlobalConfig.load()
    assert config == GlobalConfig()
    assert config.network_mode == "environment" and config.proxy == "" and config.sources == {} and config.routes == {}
    assert netconfig.config_path() == home / "config.json"
    assert netconfig.config_path().is_file()
    config.network_mode = "proxy"
    config.proxy = "socks5h://127.0.0.1:1080"
    config.sources["javdb"] = SourceSettings(enabled=True, cookie="session=abc")
    config.sources["avbase"] = SourceSettings(enabled=False)
    config.routes["censored"] = ["r18dev", "javdb"]
    config.save()
    again = GlobalConfig.load()
    assert again == config
    stored = json.loads(netconfig.config_path().read_text(encoding="utf-8"))
    assert stored["sources"]["javdb"]["cookie"] == "session=abc"
    assert stored["network"]["mode"] == "proxy"


def test_bad_json_and_unknown_keys(home: Path):
    home.mkdir(parents=True)
    (home / "config.json").write_text("{nope", encoding="utf-8")
    assert GlobalConfig.load() == GlobalConfig()
    assert (home / "config.json").read_text(encoding="utf-8") == "{nope"
    (home / "config.json").write_text(json.dumps({
        "network": {"mode": "direct", "future": 1}, "sources": {"javdb": {"enabled": 0, "cookie": 5}},
        "routes": {"fc2": "fc2,javdb", "bogus": 3}, "extra": True}), encoding="utf-8")
    config = GlobalConfig.load()
    assert config.network_mode == "direct"
    assert config.sources["javdb"] == SourceSettings(enabled=False, cookie="5")
    assert config.routes == {"fc2": ["fc2", "javdb"]}


@pytest.mark.parametrize("address,ok", [
    ("http://127.0.0.1:7890", True),
    ("https://proxy.example:443", True),
    ("socks5://127.0.0.1:1080", True),
    ("socks5h://127.0.0.1:1080/", True),
    ("http://x", False),
    ("http://127.0.0.1:7890/path", False),
    ("http://127.0.0.1:7890?q=1", False),
    ("http://127.0.0.1: 7890", False),
    ("ftp://127.0.0.1:21", False),
    ("", False),
])
def test_proxy_validation(address, ok):
    if ok:
        assert validate_proxy(address) == address.strip()
    else:
        with pytest.raises(ValueError):
            validate_proxy(address)


def test_client_options_three_modes():
    assert GlobalConfig(network_mode="environment").client_options() == {"trust_env": True}
    assert GlobalConfig(network_mode="direct").client_options() == {"trust_env": False}
    assert GlobalConfig(network_mode="proxy", proxy="http://127.0.0.1:7890").client_options() == {
        "trust_env": False, "proxy": "http://127.0.0.1:7890"}
    with pytest.raises(ValueError):
        GlobalConfig(network_mode="proxy", proxy="").client_options()


def test_source_helpers():
    config = GlobalConfig(sources={"javdb": SourceSettings(enabled=False, cookie="a=b")})
    assert config.enabled("javdb") is False
    assert config.enabled("r18dev") is True
    assert config.cookie("javdb") == "a=b"
    assert config.cookie("r18dev") == ""


def test_describe_hides_cookie_values():
    config = GlobalConfig(network_mode="proxy", proxy="http://127.0.0.1:7890",
                          sources={"javdb": SourceSettings(cookie="secret=1")})
    text = json.dumps(config.describe(), ensure_ascii=False)
    assert "secret=1" not in text
    assert config.describe()["sources"]["javdb"]["cookie"] is True
