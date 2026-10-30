"""目录列举后端（`serve/browse.py`）：只列目录、不越界、隐藏目录与资料目录 `HiddenShelf` 的规则、截断、根列表。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from hidden_shelf.paths import SHELF_DIR
from hidden_shelf.serve.browse import MAX_ENTRIES, BrowseError, Entry, Listing, list_directory, list_roots


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    disk = tmp_path / "disk"
    for name in ("Prestige", ".hidden", SHELF_DIR, "@eaDir", "中文 目录#1", f"Prestige/{SHELF_DIR}", "$RECYCLE.BIN", "System Volume Information"):
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
    for never in (SHELF_DIR, "@eaDir", "$RECYCLE.BIN", "System Volume Information"):
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
    (volumes / "Alpha" / SHELF_DIR).mkdir(parents=True)
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


# ---------- GET /api/browse ----------

from urllib.parse import quote  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from hidden_shelf.serve.app import create_app  # noqa: E402
from hidden_shelf.serve.runner import RunManager  # noqa: E402
from serve_fakes import fake_pipeline  # noqa: E402

HEADERS = {"X-Shelf-Request": "1", "Origin": "http://127.0.0.1:8031"}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    manager = RunManager(home=tmp_path / "home", run_pipeline=fake_pipeline())
    return TestClient(create_app(manager, opener=lambda uri: None, ping_seconds=0.05))


def test_browse_roots(client: TestClient):
    response = client.get("/api/browse", headers=HEADERS)
    assert response.status_code == 200
    roots = response.json()["roots"]
    assert roots and {"name", "path", "has_shelf"} <= set(roots[0])
    assert any(r["path"] == str(Path.home()) for r in roots)
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/browse?path=", headers=HEADERS).json()["roots"] == roots, "空 path 同缺省"


def test_browse_lists_tmp_dir(client: TestClient, tree: Path):
    response = client.get(f"/api/browse?path={quote(str(tree))}", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["path"] == str(tree) and data["parent"] == str(tree.parent)
    assert [e["name"] for e in data["entries"]] == ["Prestige", "中文 目录#1"]
    assert data["entries"][1]["path"] == str(tree / "中文 目录#1"), "空格、中文、# 原样取到"
    assert data["has_shelf"] is True and data["truncated"] is False and data["writable"] is True
    assert set(data) == {"path", "parent", "entries", "truncated", "has_shelf", "writable"}
    hidden = client.get(f"/api/browse?path={quote(str(tree))}&show_hidden=1", headers=HEADERS).json()
    assert ".hidden" in [e["name"] for e in hidden["entries"]]
    plain = client.get(f"/api/browse?path={quote(str(tree))}&show_hidden=0", headers=HEADERS).json()
    assert ".hidden" not in [e["name"] for e in plain["entries"]]


def test_browse_errors_map_status(client: TestClient, tree: Path, monkeypatch):
    missing = client.get(f"/api/browse?path={quote(str(tree / 'nope'))}", headers=HEADERS)
    assert missing.status_code == 404 and missing.json() == {"error": "目录不存在"}
    relative = client.get("/api/browse?path=relative", headers=HEADERS)
    assert relative.status_code == 400 and "绝对路径" in relative.json()["error"]
    dots = client.get(f"/api/browse?path={quote(str(tree / '..' / 'x'))}", headers=HEADERS)
    assert dots.status_code == 400 and ".." in dots.json()["error"]
    file_ = client.get(f"/api/browse?path={quote(str(tree / 'file.txt'))}", headers=HEADERS)
    assert file_.status_code == 400 and file_.json()["error"] == "不是目录"

    def denied(path):
        raise PermissionError(13, "Permission denied", str(path))
    monkeypatch.setattr(os, "scandir", denied)
    forbidden = client.get(f"/api/browse?path={quote(str(tree))}", headers=HEADERS)
    assert forbidden.status_code == 403 and forbidden.json() == {"error": "没有读取权限"}


def test_browse_requires_header_and_origin(client: TestClient, tree: Path):
    url = f"/api/browse?path={quote(str(tree))}"
    assert client.get(url).status_code == 403, "没有 X-Shelf-Request"
    assert client.get(url, headers={"X-Shelf-Request": "1"}).status_code == 403, "没有来源"
    evil = client.get(url, headers={"X-Shelf-Request": "1", "Origin": "https://evil.example"})
    assert evil.status_code == 403 and evil.json()["error"] == "请求来源不被信任"
    assert client.get(url, headers={"X-Shelf-Request": "1", "Referer": "http://localhost:8031/"}).status_code == 200
    assert client.get("/api/state", headers={"Origin": "https://evil.example"}).status_code == 200, "别的 GET 照旧不查"
