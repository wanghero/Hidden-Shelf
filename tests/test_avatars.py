"""女优官方头像落盘。"""
from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest
from PIL import Image

from hidden_shelf import db, entities
from hidden_shelf.paths import ShelfPaths
from hidden_shelf.scrape.avatars import install_avatars, pending_avatars
from hidden_shelf.scrape.transport import HttpResponse

URL = "https://pics.dmm.co.jp/mono/actjpgs/suzumori_remu.jpg"


def png(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 200, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def transport_for(pages):
    calls = []

    def call(request, timeout, limit):
        calls.append((request.url, request.headers.get("Referer"), limit))
        body = pages.get(request.url)
        if isinstance(body, Exception):
            raise body
        if body is None:
            return HttpResponse(404, {}, b"", request.url)
        return HttpResponse(200, {}, body, request.url)

    call.calls = calls
    return call


@pytest.fixture
def connection(tmp_root: Path):
    conn = db.connect(ShelfPaths(tmp_root))
    yield conn
    conn.close()


def test_install_avatars_from_r18_thumbs(connection, tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    remu = entities.ensure_entity(connection, "performer", "涼森れむ")
    entities.merge_metadata(connection, remu, {"avatar_url": URL, "avatar_source": "r18dev"})
    nobody = entities.ensure_entity(connection, "performer", "没头像的人")
    insecure = entities.ensure_entity(connection, "performer", "明文地址")
    entities.merge_metadata(connection, insecure, {"avatar_url": "http://x/a.jpg"})
    assert pending_avatars(connection) == [(remu, "涼森れむ", URL)]
    messages = []
    transport = transport_for({URL: png(900, 1200)})
    assert install_avatars(connection, paths, transport, progress=messages.append) == 1
    assert transport.calls == [(URL, "https://www.dmm.co.jp/", 2 * 1024 * 1024)]
    row = connection.execute("SELECT avatar_file FROM entity WHERE id=?", (remu,)).fetchone()
    assert row[0] == f"avatars/{remu}.jpg"
    with Image.open(paths.avatars / f"{remu}.jpg") as image:
        assert image.size == (384, 512) and image.mode == "RGB"
    assert messages == [f"[头像] 涼森れむ ← {URL}"]
    # 第二次不重下。
    assert install_avatars(connection, paths, transport) == 0
    assert len(transport.calls) == 1
    assert connection.execute("SELECT avatar_file FROM entity WHERE id=?", (nobody,)).fetchone()[0] is None


def test_install_avatars_handles_failures_without_raising(connection, tmp_root: Path):
    paths = ShelfPaths(tmp_root)
    gone = entities.ensure_entity(connection, "performer", "甲")
    entities.merge_metadata(connection, gone, {"avatar_url": "https://pics.dmm.co.jp/mono/actjpgs/gone.jpg"})
    flaky = entities.ensure_entity(connection, "performer", "乙")
    entities.merge_metadata(connection, flaky, {"avatar_url": "https://pics.dmm.co.jp/mono/actjpgs/flaky.jpg"})
    broken = entities.ensure_entity(connection, "performer", "丙")
    entities.merge_metadata(connection, broken, {"avatar_url": "https://pics.dmm.co.jp/mono/actjpgs/broken.jpg"})
    messages = []
    transport = transport_for({"https://pics.dmm.co.jp/mono/actjpgs/flaky.jpg": httpx.ConnectError("reset"),
                               "https://pics.dmm.co.jp/mono/actjpgs/broken.jpg": b"not an image"})
    from unittest.mock import patch
    with patch("hidden_shelf.scrape.transport.NETWORK_RETRY_DELAYS", ()):
        assert install_avatars(connection, paths, transport, progress=messages.append) == 0
    assert any("不存在" in note for note in messages)
    assert any("未取得" in note for note in messages)
    assert any("解不开" in note for note in messages)
    # 404 的地址从元数据里拿掉，不再排队；连接失败与坏图留着下趟再试。
    assert entities.metadata_of(connection, gone) == {"avatar_missing": "https://pics.dmm.co.jp/mono/actjpgs/gone.jpg"}
    assert {entity_id for entity_id, _, _ in pending_avatars(connection)} == {flaky, broken}
    assert pending_avatars(connection, limit=1) == [(flaky, "乙", "https://pics.dmm.co.jp/mono/actjpgs/flaky.jpg")]
    assert not (paths.avatars / f"{gone}.jpg").exists()
