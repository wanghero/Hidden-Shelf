"""JavArchive：下架 FC2 的最后一档。

移植自 peach `src/peach/sources/javarchive.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）。改动：`NotFound` 从 `scrape.transport` 导入。

作品地址是 `/926949-FC2-PPV-4137487-<标题>-pn.html`：开头那串是站内文章号，商品号夹在标题里，地址拼不出来，
只能先问 `/search?q=<番号>` 再取作品页。搜索结果那一条只有标题和一张缩略图，作品页才有标签、发行日、时长和
真正的封面位，所以这一跳省不得。封面转存在 `javstore.net` 上，两个域算同一个来源；免登录可读，不带 Cookie。

同一个商品常有好几条：不同转存者各发一次，文章号、番号写法、标题和图都各存各的，先后没有质量含义。第一条
的图未必还在，所以 `records()` 每一条都取、各交一份记录。
"""
from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from ..transport import NotFound
from .base import FailureReason, Page, Session, SiteConfig, SiteRecord, SiteSource, SourceFailure
from .fc2 import (PAGE_LIMIT, canonical_code, fc2_record, runtime_minutes, strip_code, text_of, unrecognised,
                  video_id)

#: 转载站，标题由发布者写，封面是转存件，按社区来源登记。主机间隔用默认的 2 秒。
JAVARCHIVE = SiteConfig(name="javarchive", label="JavArchive", provider="javarchive-page",
                        base_url="https://javarchive.com", domains=("javarchive.com", "javstore.net"),
                        stage="community", page_limit=PAGE_LIMIT)
SEARCH_PATH = "/search?q={code}"

#: 站内作品地址的形状。搜索页的结果、侧栏的本周热门和归档菜单用的是同一种。
_LINK = re.compile(r'href="(/\d+-[^"]+\.html)"')
#: 作品页上封面的两个位置：`div.fisrst_sc` 里那张排前，schema.org 的 `image` 排后。认位置不认文件名——
#: 转存者的命名没有统一：`4137487pl.jpg`、`FC2PPV-4030617.jpg`、`FC2PPV835964-2.jpg` 都有。
_COVER_SLOTS = ("div.fisrst_sc img[src]", 'img[itemprop="image"][src]')
#: 多帧拼成的长条预览，正文里叫 `Preview(ビデオのサムネイル)`，不是封面。
_PREVIEW = re.compile(r"_s\.(?:jpe?g|png)$", re.I)
#: 正文那块资料：`标签：A｜B｜C`、`日期：2023/11/21`、`时长：50:03`，每项后面跟一个 `<br>`。
#: 只在 `div.news` 里搜：head 的 `<meta name="description">` 里有同样的字样，值被站方截断。
_ROWS = {
    "genres": re.compile(r"标签\s*[:：]\s*([^<]*)"),
    "release_date": re.compile(r"日期\s*[:：]\s*(\d{4})/(\d{2})/(\d{2})"),
    "runtime": re.compile(r"时长\s*[:：]\s*([\d:]+)"),
}


def _number(wanted: str) -> re.Pattern:
    """按数字边界认商品号：`4137487` 不能命中 `41374870`，站上两个号真的都有。"""
    return re.compile(rf"(?<!\d){re.escape(wanted)}(?!\d)")


def links(html: str | bytes, code: str) -> list[str]:
    """搜索结果里这个商品号的每一条站内地址，按站上的先后；没有回空表。"""
    wanted = video_id(code)
    if not wanted:
        return []
    text = html.decode("utf-8", "replace") if isinstance(html, bytes) else str(html)
    boundary = _number(wanted)
    return list(dict.fromkeys(href for href in _LINK.findall(text)
                              if boundary.search(urllib.parse.unquote(href))))


def _rows(soup: BeautifulSoup) -> dict:
    """正文那块资料：标签、发行日、时长。哪一样没填就回这一样的空值。只在 `div.news` 里搜。"""
    block = soup.select_one("div.news")
    if block is None:
        return {"genres": [], "release_date": "", "runtime": ""}
    text = str(block)
    tags = _ROWS["genres"].search(text)
    sold = _ROWS["release_date"].search(text)
    runtime = _ROWS["runtime"].search(text)
    # 站上用全角竖线分隔；转存者留空时那一行写成 `--`，当成一个标签就入了库。
    names = [name.strip() for name in re.split(r"[｜|]", tags.group(1))] if tags else []
    return {
        "genres": list(dict.fromkeys(name for name in names if name and name != "--")),
        "release_date": "-".join(sold.groups()) if sold else "",
        "runtime": runtime.group(1) if runtime else "",
    }


class JavArchiveSource(SiteSource):
    DEFAULT = JAVARCHIVE

    def search_url(self, code: str) -> str:
        """这个番号在 JavArchive 上的搜索地址；认不出商品号时回空串。"""
        found = video_id(code)
        return (self.config.base_url + SEARCH_PATH.format(code=urllib.parse.quote(canonical_code(found)))
                if found else "")

    def work_url(self, link: str) -> str:
        """站内地址 → 作品页。地址里的标题有的已编码、有的是原字，拼之前统一编一遍。"""
        return self.config.base_url + urllib.parse.quote(link, safe="/%")

    def search(self, code: str, *, session: Session) -> list[str]:
        url = self.search_url(code)
        if not url:
            raise unrecognised()
        return links(session.get(url, config=self.config).body, code)

    def _missing(self) -> SourceFailure:
        return SourceFailure(FailureReason.NOT_FOUND, f"{self.config.label} 上没有这个商品")

    def fetch(self, code: str, *, session: Session) -> Page:
        """搜索结果里排第一的那条作品页。要每一条的用 `records()`。"""
        found = self.search(code, session=session)
        if not found:
            raise self._missing()
        return session.get(self.work_url(found[0]), config=self.config)

    def parse(self, page: Page, code: str) -> SiteRecord:
        """作品页 → 记录；对不上番号归 `not_found`。

        标题以站内 `<h1>` 为准，开头那截番号剥掉。`<h1>` 里认不出这个商品号就当没有这一页。封面两个图位都收，
        去重后 `div.fisrst_sc` 那张排前；`_s.jpg` 结尾的排除掉，那是多帧长条拼图。
        """
        wanted = video_id(code)
        if not wanted:
            raise unrecognised()
        soup = BeautifulSoup(page.text, "html.parser")
        heading = soup.select_one("h1")
        title = text_of(heading)
        if not title or not _number(wanted).search(title):
            raise self._missing()
        link = heading.select_one("a[href]")
        covers = []
        for slot in _COVER_SLOTS:
            for picture in soup.select(slot):
                url = str(picture.get("src") or "").strip()
                if url and not _PREVIEW.search(url) and url not in covers:
                    covers.append(url)
        rows = _rows(soup)
        return fc2_record(
            self.config, wanted, urllib.parse.urljoin(self.config.base_url, link["href"]) if link else "",
            title=strip_code(title, wanted), release_date=rows["release_date"],
            runtime=runtime_minutes(rows["runtime"]), tags=rows["genres"], cover_urls=covers)

    def records(self, code: str, *, session: Session) -> list[SiteRecord]:
        """搜索命中的每一条作品页各交一份记录。某一条 404 或对不上就跳过，一条都没有归 `not_found`。"""
        found = []
        with self.holding(session):
            for link in self.search(code, session=session):
                try:
                    found.append(self.parse(session.get(self.work_url(link), config=self.config), code))
                except NotFound:
                    continue
                except SourceFailure as failure:
                    if failure.kind != "not_found":
                        raise
        if not found:
            raise self._missing()
        return found
