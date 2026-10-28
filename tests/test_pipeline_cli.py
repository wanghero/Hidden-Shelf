"""流水线与命令行端到端。依赖 fake_video（ffmpeg 不在则 skip）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from hidden_shelf import cli, pipeline
from hidden_shelf.paths import ShelfPaths


@pytest.fixture
def disk(tmp_root: Path, fake_video):
    fake_video(tmp_root / "a" / "ABP-758.mp4")
    (tmp_root / "a" / "ABP-758.nfo").write_text(
        "<movie><title>标题</title><studio>Prestige</studio><actor><name>甲</name></actor></movie>", encoding="utf-8")
    Image.new("RGB", (300, 200), "red").save(tmp_root / "a" / "ABP-758-poster.jpg")
    fake_video(tmp_root / "b" / "259LUXU-1475-cd1.mp4")
    fake_video(tmp_root / "c" / "随手拍.mp4")
    return tmp_root


def test_run_end_to_end(disk):
    result = pipeline.run(disk, progress=pipeline.ConsoleProgress())
    assert result.ok, result.error
    assert set(result.steps) == {"scan", "import", "organize", "media", "build"}
    assert (disk / "Prestige" / "ABP-758" / "ABP-758.mp4").is_file()
    assert (disk / "_未知厂牌" / "259LUXU-1475" / "259LUXU-1475-cd1.mp4").is_file()
    assert (disk / "未识别" / "c" / "随手拍.mp4").is_file()
    for name in ("a", "b", "c"):
        assert not (disk / name).exists(), name
    legacy = disk / ".shelf" / "legacy" / "ABP-758"
    assert (legacy / "ABP-758.nfo").is_file() and (legacy / "ABP-758-poster.jpg").is_file()
    assert (disk / ".shelf" / "sheets" / "ABP-758.jpg").is_file()
    assert (disk / ".shelf" / "covers" / "ABP-758.jpg").is_file()
    assert (disk / "index.html").is_file()
    assert '"ABP-758"' in (disk / ".shelf" / "site" / "data" / "works.js").read_text(encoding="utf-8")
    assert result.log_path and result.log_path.is_file()
    assert result.index_html == disk / "index.html"
    with sqlite3.connect(disk / ".shelf" / "shelf.db") as connection:
        runs = connection.execute("SELECT step,status FROM run ORDER BY id").fetchall()
        assert runs == [("scan", "ok"), ("import", "ok"), ("organize", "ok"), ("media", "ok"), ("build", "ok")]
        assert connection.execute("SELECT count(*) FROM asset WHERE vanished=1").fetchone()[0] == 0
        assert connection.execute("SELECT path FROM asset WHERE code='ABP-758'").fetchone()[0] == "Prestige/ABP-758/ABP-758.mp4"


def test_run_twice_is_stable(disk):
    pipeline.run(disk)
    second = pipeline.run(disk)
    assert second.ok
    assert second.steps["organize"]["moved"] == 0
    assert second.steps["scan"]["added"] == 0 and second.steps["scan"]["vanished"] == 0
    assert second.steps["media"]["sheets"] == 0
    assert (disk / "Prestige" / "ABP-758" / "ABP-758.mp4").is_file()


def test_run_single_steps(disk):
    first = pipeline.run(disk, steps=("scan",))
    assert first.ok and list(first.steps) == ["scan"] and first.index_html is None
    assert (disk / "a" / "ABP-758.mp4").is_file()


def test_run_records_failure(disk, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("炸了")

    monkeypatch.setattr(pipeline, "build_site", boom)
    result = pipeline.run(disk)
    assert not result.ok and result.failed_step == "build" and "炸了" in result.error
    assert {"scan", "import", "organize", "media"} <= set(result.steps)
    with sqlite3.connect(disk / ".shelf" / "shelf.db") as connection:
        assert connection.execute("SELECT status FROM run WHERE step='build'").fetchone()[0] == "failed"


def test_cli_no_move_unrecognized(disk, capsys):
    code = cli.main(["run", str(disk), "--no-move-unrecognized"])
    assert code == 0
    assert (disk / "c" / "随手拍.mp4").is_file()
    assert not (disk / "未识别").exists()
    out = capsys.readouterr().out
    assert "成品：" in out and str(disk / "index.html") in out
    # 持久化的配置没被命令行旗标改掉。
    from hidden_shelf.config import ShelfConfig
    assert ShelfConfig.load(ShelfPaths(disk)).move_unrecognized is True


def test_cli_templates_override(disk):
    assert cli.main(["scan", str(disk)]) == 0
    assert cli.main(["organize", str(disk), "--dir-template", "{code}", "--file-template", "{code}"]) == 0
    assert (disk / "ABP-758" / "ABP-758.mp4").is_file()


def test_cli_bad_root_exit_2(tmp_path: Path, capsys):
    assert cli.main(["run", str(tmp_path / "nope")]) == 2
    assert "不存在" in capsys.readouterr().err
    assert cli.main([]) == 2


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["--version"])
    assert caught.value.code == 0
    assert "shelf 0." in capsys.readouterr().out
