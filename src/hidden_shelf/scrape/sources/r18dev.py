"""r18.dev 的作品 JSON：DMM 数字版目录的镜像，有码与素人来源链的第一档。

移植自 peach `src/peach/sources/r18dev.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）。改动：`Unavailable` 从 `scrape.transport` 导入，`identifies_code` 从 `scrape.identity`；
去掉封面层另一条路的说明（本项目封面取自同一份记录的 `cover_urls`）。

`dvd_id=<番号>` 那一页只给英文，标题和系列多是机翻，演员只有罗马字。日文在 `combined=<content_id>`
那一页：`title_ja`、`series_name_ja`、演员 `name_kanji`，取到后写进 `translations`，标题、系列、演员与
genre 都换成日文那份。厂牌不取日文——厂牌实体用品牌名（`Prestige`、`MOODYZ`），换成 `プレステージ`
会另起一个实体。

标题、系列和演员只认日文那一侧：日文那一页取不到，或那一侧空着，这几样就留空，不拿英文页的写法
顶上。留空的字段由来源链接着问下一家；发行日、厂牌、封面和 genre 两边一样可用，照旧交出。

genre 取 `categories[].name_ja`，也就是 DMM 自己那套词。英文是 r18 在它上面再译一层，词根会丢。
"""
from __future__ import annotations

import json
from dataclasses import replace
from urllib.parse import quote

import httpx

from ..identity import identifies_code
from ..transport import Unavailable
from .base import FailureReason, Page, Session, SiteConfig, SiteRecord, SiteSource, SourceFailure

#: 主机间隔用默认的 2 秒，不带 Cookie。两页实测都在几十 KB，2 MiB 是改版余量。
R18DEV = SiteConfig(name="r18dev", label="r18.dev", provider="r18-json", base_url="https://r18.dev",
                    domains=("r18.dev",), stage="official_mirror", page_limit=2 * 1024 * 1024)
DETAIL_PATH = "/videos/vod/movies/detail/-/dvd_id={code}/json"
COMBINED_PATH = "/videos/vod/movies/detail/-/combined={content_id}/json"
#: 女优头像：combined 页的 `actresses[].image_url` 只是文件名，图在 DMM 的头像目录下。
ACTRESS_IMAGE = "https://pics.dmm.co.jp/mono/actjpgs/{filename}"


def actresses(rows) -> list[dict]:
    """combined 页的演员：日文名、假名、罗马字、DMM id 与官方头像地址。

    `japanese_name` 只取 `name_kanji`，那是 DMM 登记的艺名（`RARA`、`JULIA` 这类本来就写拉丁字母的
    也在这一栏）。没有它的只剩 r18 拼的罗马字，名字留空，由 `with_japanese` 剔掉。
    """
    found = []
    for row in rows or []:
        image = str(row.get("image_url") or "").strip()
        thumb_url = (ACTRESS_IMAGE.format(filename=quote(image, safe=""))
                     if image and "/" not in image and "\\" not in image else "")
        found.append({
            "japanese_name": row.get("name_kanji") or "",
            "name_kana": row.get("name_kana") or "",
            "name_romaji": row.get("name_romaji") or "",
            "dmm_id": row.get("id") or "",
            "thumb_url": thumb_url,
            "profile_source": "r18dev",
        })
    return found


def english_only(record: SiteRecord) -> SiteRecord:
    """日文那一页没拿到时交出的记录：标题、系列与演员留空，其余照旧。"""
    return replace(record, title="", series="", performers=())


def with_japanese(record: SiteRecord, combined: object) -> SiteRecord:
    """把 combined 页的日文写法并进记录；那一页不是这部片的，按没拿到处理。"""
    content_id = str(record.extra.get("content_id") or "")
    if not isinstance(combined, dict) or combined.get("content_id") != content_id:
        return english_only(record)
    directors = [row.get("name_kanji") for row in combined.get("directors") or [] if row.get("name_kanji")]
    title = " ".join(str(combined.get("title_ja") or "").split())
    series = " ".join(str(combined.get("series_name_ja") or "").split())
    translations = [dict(language="ja", title=title, series=series,
                         label=combined.get("label_name_ja") or "",
                         director=directors[0] if directors else "")]
    performers = tuple(row for row in actresses(combined.get("actresses")) if row["japanese_name"])
    japanese = [row.get("name_ja") or row.get("name_en") or "" for row in combined.get("categories") or []]
    return replace(
        record, title=title, series=series, performers=performers,
        tags=tuple(name for name in japanese if name) if any(japanese) else record.tags,
        extra={**record.extra, "translations": translations, "combined": combined})


class R18DevSource(SiteSource):
    DEFAULT = R18DEV

    def detail_url(self, code: str) -> str:
        return self.config.base_url + DETAIL_PATH.format(code=quote(code))

    def combined_url(self, content_id: str) -> str:
        return self.config.base_url + COMBINED_PATH.format(content_id=quote(content_id))

    def fetch(self, code: str, *, session: Session) -> Page:
        return session.get(self.detail_url(code), config=self.config)

    def parse(self, page: Page, code: str) -> SiteRecord:
        try:
            raw = json.loads(page.body)
        except ValueError:
            raise SourceFailure(FailureReason.PARSE_ERROR, "r18.dev 返回的不是作品 JSON") from None
        if not isinstance(raw, dict):
            raise SourceFailure(FailureReason.PARSE_ERROR, "r18.dev 返回的不是作品 JSON")
        if not identifies_code(code, {"content_id": raw.get("content_id")}):
            raise SourceFailure(FailureReason.PARSE_ERROR, "来源返回的番号不匹配", detail="identity_mismatch")
        name = lambda key: (raw.get(key) or {}).get("name", "")
        jacket = (raw.get("images") or {}).get("jacket_image")
        return SiteRecord(
            source=self.config.name, provenance=self.config.provider, code=code, source_url=page.url,
            title=raw.get("title") or "",
            performers=tuple({"japanese_name": row.get("name", "")} for row in raw.get("actresses", [])),
            studio=name("maker"), label=name("label"), series=name("series"),
            director=raw.get("director") or "", release_date=raw.get("release_date") or "",
            runtime=raw.get("runtime_minutes"),
            tags=tuple(row.get("name", "") for row in raw.get("categories", [])),
            cover_urls=(jacket,) if jacket else (),
            extra={"content_id": raw.get("content_id"), "raw": raw})

    def japanese(self, record: SiteRecord, *, session: Session) -> SiteRecord:
        """补上 combined 页的日文写法。那一页取不到、不是 JSON 或连接失败时交 `english_only`。"""
        content_id = str(record.extra.get("content_id") or "")
        if not content_id:
            return english_only(record)
        try:
            combined = json.loads(session.get(self.combined_url(content_id), config=self.config).body)
        except (Unavailable, ValueError, httpx.TransportError):
            return english_only(record)
        return with_japanese(record, combined)

    def query(self, code: str, *, session: Session) -> SiteRecord:
        return self.japanese(super().query(code, session=session), session=session)
