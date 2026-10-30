"""刮削接入流水线、命令行与站点。全部离线：`conftest.isolated_home` 把 8 站停用。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from hidden_shelf import cli, db, entities, pipeline
from hidden_shelf.config import ShelfConfig
from hidden_shelf.local_import import import_local
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scan import scan
from hidden_shelf.site.build import build_site, read_data_js


@pytest.fixture
def disk(tmp_root: Path, fake_video):
    fake_video(tmp_root / "a" / "ABP-758.mp4")
    (tmp_root / "a" / "ABP-758.nfo").write_text(
        "<movie><title>标题</title><studio>Prestige</studio><actor><name>甲</name></actor></movie>", encoding="utf-8")
    return tmp_root


def _runs(disk):
    with sqlite3.connect(disk / "HiddenShelf" / "shelf.db") as connection:
        return connection.execute("SELECT step,status FROM run ORDER BY id").fetchall()


def test_pipeline_includes_scrape_and_continues_on_failure(disk, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("联网炸了")

    import hidden_shelf.scrape.run as run_module
    monkeypatch.setattr(run_module, "scrape_assets", boom)
    result = pipeline.run(disk)
    assert result.ok and result.index_html == disk / "index.html" and (disk / "index.html").is_file()
    assert list(result.steps) == ["scan", "import", "scrape", "organize", "media", "build"]
    assert result.steps["scrape"] == {"error": "RuntimeError: 联网炸了"}
    assert _runs(disk) == [("scan", "ok"), ("import", "ok"), ("scrape", "failed"), ("organize", "ok"), ("media", "ok"), ("build", "ok")]
    assert pipeline.STEPS == ("scan", "import", "scrape", "organize", "media", "build")


def test_pipeline_scrape_runs_offline_with_all_sources_disabled(disk):
    result = pipeline.run(disk)
    assert result.ok
    stats = result.steps["scrape"]
    assert (stats["asked"], stats["settled"], stats["skipped"], stats["network_down"]) == (0, 0, 1, False)
    assert _runs(disk)[2] == ("scrape", "ok")


def test_pipeline_scrape_skipped_by_option_or_config(disk):
    result = pipeline.run(disk, steps=("scan", "scrape"), scrape_options=pipeline.ScrapeOptions(offline=True))
    assert result.ok and result.steps["scrape"] == {"skipped": True, "reason": "--offline"}
    config = ShelfConfig(scrape=False)
    result = pipeline.run(disk, config=config, steps=("scrape",))
    assert result.steps["scrape"] == {"skipped": True, "reason": "config.scrape=false"}
    assert [status for step, status in _runs(disk) if step == "scrape"] == ["skipped", "skipped"]


def test_cli_offline_flag(disk):
    assert cli.main(["run", str(disk), "--offline"]) == 0
    assert ("scrape", "skipped") in _runs(disk)
    assert (disk / "index.html").is_file()


def test_cli_scrape_command_and_options(disk, capsys):
    assert cli.main(["scan", str(disk)]) == 0
    assert cli.main(["scrape", str(disk), "--sources", "r18dev,javdb", "--routes", "censored=r18dev", "--force-scrape"]) == 0
    assert _runs(disk)[-1] == ("scrape", "ok")
    assert cli.main(["scrape", str(disk), "--sources", "mgstage"]) == 2
    assert "未知来源" in capsys.readouterr().err
    assert cli.main(["scrape", str(disk), "--routes", "hentai=javdb"]) == 2
    assert "未知内容类型" in capsys.readouterr().err


def test_cli_config_prints_without_cookie_values(disk, isolated_home, capsys):
    (isolated_home / "config.json").write_text(json.dumps({
        "network": {"mode": "proxy", "proxy": "http://127.0.0.1:7890"},
        "sources": {"javdb": {"enabled": True, "cookie": "session=secret-value"}, "avbase": {"enabled": False, "cookie": ""}},
        "routes": {"censored": ["r18dev", "javdb"]}}), encoding="utf-8")
    assert cli.main(["config"]) == 0
    out = capsys.readouterr().out
    assert str(isolated_home / "config.json") in out
    assert "proxy（已保存代理地址）" in out and "http://127.0.0.1:7890" not in out
    assert "secret-value" not in out and "Cookie：有" in out and "Cookie：无" in out
    assert "javdb" in out and "停用" in out and '"censored": ["r18dev", "javdb"]' in out
    assert cli.main(["config", str(disk)]) == 0
    assert "冷却中：无" in capsys.readouterr().out
    assert cli.main(["config", str(disk / "nope")]) == 2


def test_site_build_performer_avatar_and_sources(tmp_root: Path):
    (tmp_root / "a").mkdir()
    (tmp_root / "a" / "ABW-358.mp4").write_bytes(b"0" * 10)
    (tmp_root / "a" / "ABW-358.nfo").write_text("<movie><title>t</title><actor><name>涼森れむ</name></actor></movie>", encoding="utf-8")
    paths = ShelfPaths(tmp_root)
    connection = db.connect(paths)
    try:
        scan(connection, paths, ShelfConfig())
        import_local(connection, paths)
        remu = entities.ensure_entity(connection, "performer", "涼森れむ")
        paths.avatars.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), "blue").save(paths.avatars / f"{remu}.jpg")
        connection.execute("UPDATE entity SET avatar_file=? WHERE id=?", (f"avatars/{remu}.jpg", remu))
        ghost = entities.ensure_entity(connection, "performer", "没文件的人")
        connection.execute("UPDATE entity SET avatar_file='avatars/999.jpg' WHERE id=?", (ghost,))
        connection.commit()
        paths.sources.mkdir(parents=True, exist_ok=True)
        (paths.sources / "ABW-358-r18dev.json").write_text(json.dumps({
            "fetched_at": "t", "source": "r18dev", "code": "ABW-358",
            "result": {"records": [{"source_url": "https://r18.dev/videos/vod/movies/detail/-/dvd_id=ABW-358/json"}]}}), encoding="utf-8")
        (paths.sources / "ABW-358-javdb.json").write_text(json.dumps({
            "fetched_at": "t", "source": "javdb", "code": "ABW-358", "error": {"reason": "not_found", "message": ""}}), encoding="utf-8")
        (paths.sources / "_cooldown.json").write_text("{}", encoding="utf-8")
        build_site(connection, paths, ShelfConfig())
    finally:
        connection.close()
    performers = read_data_js(paths.site_data / "entities.js")["performers"]
    assert {item["name"]: item["avatar"] for item in performers} == {"涼森れむ": f"HiddenShelf/avatars/{remu}.jpg"}
    works = read_data_js(paths.site_data / "works.js")
    assert works[0]["sources"] == [{"source": "r18dev", "url": "https://r18.dev/videos/vod/movies/detail/-/dvd_id=ABW-358/json"}]
