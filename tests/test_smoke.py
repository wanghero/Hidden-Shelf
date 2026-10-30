from pathlib import Path

import hidden_shelf


def test_version():
    assert hidden_shelf.__version__ == "1.4.4"


def test_fake_video(fake_video, tmp_path: Path):
    out = fake_video(tmp_path / "clip.mp4")
    assert out.exists()
    assert out.stat().st_size > 0
