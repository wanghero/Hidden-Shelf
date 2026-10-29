"""目录列举后端（`serve/browse.py`）：只列目录、不越界、隐藏目录与 `.shelf` 的规则、截断、根列表。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from hidden_shelf.serve.browse import MAX_ENTRIES, BrowseError, Entry, Listing, list_directory, list_roots


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    disk = tmp_path / "disk"
    for name in ("Prestige", ".hidden", ".shelf", "@eaDir", "中文 目录#1", "Prestige/.shelf", "$RECYCLE.BIN", "System Volume Information"):
        (disk / name).mkdir(parents=True)
    (disk / "file.txt").write_text("x", encoding="utf-8")
    return disk


def test_list_directory_only_visible_dirs(tree: Path, tmp_path: Path):
    listing = list_directory(str(tree))
    assert isinstance(listing, Listing)
    assert [e.name for e in listing.entries] == ["Prestige", "中文 目录#1"]
    assert listing.path == str(tree) and listing.parent == str(tmp_path)
    assert listing.has_shelf is True and listing.truncated is False and listing.writable is True
    prestige = next(e for e in listing.entries if e.name == "Prestige")
    assert prestige.has_shelf is True and prestige.path == str(tree / "Prestige")
    other = next(e for e in listing.entries if e.name == "中文 目录#1")
    assert other.has_shelf is False and other.path == str(tree / "中文 目录#1")


def test_show_hidden_includes_dot_dirs_but_never_shelf_or_system_dirs(tree: Path):
    names = [e.name for e in list_directory(str(tree), show_hidden=True).entries]
    assert ".hidden" in names
    for never in (".shelf", "@eaDir", "$RECYCLE.BIN", "System Volume Information"):
        assert never not in names, never
    assert "file.txt" not in names


def test_symlinked_dirs_are_not_followed(tree: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, tree / "link")
    except (OSError, NotImplementedError):
        pytest.skip("没有符号链接")
    assert "link" not in [e.name for e in list_directory(str(tree)).entries]


def test_root_listing_has_no_parent(tmp_path: Path):
    anchor = Path(tmp_path.anchor)
    listing = list_directory(str(anchor), limit=1)
    assert listing.parent is None and listing.path == str(anchor)


@pytest.mark.parametrize("raw,status,fragment", [
    ("relative/x", 400, "绝对路径"),
    ("", 400, "绝对路径"),
    ("/a/../b", 400, ".."),
])
def test_rejects_bad_paths(raw: str, status: int, fragment: str):
    with pytest.raises(BrowseError) as caught:
        list_directory(raw)
    assert caught.value.status == status and fragment in caught.value.message


def test_missing_is_404(tmp_path: Path):
    with pytest.raises(BrowseError) as caught:
        list_directory(str(tmp_path / "nope"))
    assert caught.value.status == 404 and caught.value.message == "目录不存在"


def test_file_is_400(tree: Path):
    with pytest.raises(BrowseError) as caught:
        list_directory(str(tree / "file.txt"))
    assert caught.value.status == 400 and caught.value.message == "不是目录"


def test_permission_error_is_403(tree: Path, monkeypatch):
    def denied(path):
        raise PermissionError(13, "Permission denied", str(path))
    monkeypatch.setattr(os, "scandir", denied)
    with pytest.raises(BrowseError) as caught:
        list_directory(str(tree))
    assert caught.value.status == 403 and caught.value.message == "没有读取权限"


def test_unreadable_child_is_skipped(tree: Path, monkeypatch):
    real_scandir = os.scandir

    class Flaky:
        def __init__(self, entry):
            self._entry = entry
            self.name = entry.name
            self.path = entry.path

        def is_dir(self, follow_symlinks=True):
            if self.name == "Prestige":
                raise OSError(5, "I/O error")
            return self._entry.is_dir(follow_symlinks=follow_symlinks)

    class Scanner:
        def __init__(self, path):
            self._inner = real_scandir(path)

        def __enter__(self):
            return (Flaky(e) for e in self._inner.__enter__())

        def __exit__(self, *args):
            return self._inner.__exit__(*args)

    monkeypatch.setattr(os, "scandir", Scanner)
    assert [e.name for e in list_directory(str(tree)).entries] == ["中文 目录#1"]


def test_truncates(tmp_path: Path):
    many = tmp_path / "many"
    for i in range(5):
        (many / f"d{i}").mkdir(parents=True)
    listing = list_directory(str(many), limit=3)
    assert [e.name for e in listing.entries] == ["d0", "d1", "d2"] and listing.truncated is True
    assert list_directory(str(many), limit=5).truncated is False
    assert MAX_ENTRIES == 2000


def test_sorted_casefold(tmp_path: Path):
    mixed = tmp_path / "mixed"
    for name in ("b", "A", "c", "B2"):
        (mixed / name).mkdir(parents=True)
    assert [e.name for e in list_directory(str(mixed)).entries] == ["A", "b", "B2", "c"]


def test_roots_macos_style(tmp_path: Path):
    volumes = tmp_path / "Volumes"
    (volumes / "zeta").mkdir(parents=True)
    (volumes / "Alpha" / ".shelf").mkdir(parents=True)
    (volumes / "file").write_text("x", encoding="utf-8")
    home = tmp_path / "home" / "wanghero"
    home.mkdir(parents=True)
    roots = list_roots(home=home, volumes=volumes)
    assert all(isinstance(r, Entry) for r in roots)
    assert [r.name for r in roots] == ["wanghero", "Alpha", "zeta"]
    assert roots[0].path == str(home) and roots[1].has_shelf is True and roots[2].has_shelf is False
    # 卷目录不存在：只剩 home，不抛。
    assert [r.name for r in list_roots(home=home, volumes=tmp_path / "missing")] == ["wanghero"]
    # home 不存在：跳过。
    assert list_roots(home=tmp_path / "ghost", volumes=tmp_path / "missing") == []


def test_roots_default_includes_home_and_never_raises():
    roots = list_roots()
    assert any(r.path == str(Path.home()) for r in roots)
    assert all(Path(r.path).is_dir() for r in roots)
