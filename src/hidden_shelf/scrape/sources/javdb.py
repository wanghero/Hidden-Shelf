"""javdb 的作品页。

移植自 peach `src/peach/sources/javdb.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）。只搬作品资料那一半：`resources`、`parse_magnets`、`parse_comment_links`、
`merge_resources` 不移植（本项目不做资源链接）；`extra` 里也不带 peach 的 `javdb_rule`。

搜索页 `/search?q=<番号>&f=all` 的结果卡片带番号，只在对应唯一来源 ID 时进详情页；详情页 `?locale=zh`
下面板字段是 `番號`、`日期`、`片商`、`發行`、`系列`、`導演`、`演員`，演员里女优带 `actor-female`，
类别保留链接里的原词。它按出口 IP 计配额，限速与封禁的处理在 `access`，这里只管取页与解析。几家的值常有
出入：ABW-358 在 javdb 上发行日期是 MGS 的 5/23、标题带 MGS 附注、演员里有男优，各字段按 `policy` 结算。
有隐藏 `origin-title` 时用作原标题，`current-title` 单独保存为显示标题；两者不互相改写。

一部分页面要登录才给，回的是登入页而不是 401/403（`javdb_helpers.LOGIN`），搜索页与详情页都要认。
"""
from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from ...rules.codes import same_release_code
from .base import FailureReason, Page, Session, SiteConfig, SiteRecord, SiteSource, SourceFailure
from .javdb_helpers import LOGIN, clean

#: 主机间隔 3 秒（每分钟 20 页）。参照面：每分钟 40～50 页会招来 3～7 天的封 IP。页面与图分别落在
#: `javdb.com` 与 `jdbstatic.com` 两个主机上，间隔要一起管。
JAVDB = SiteConfig(name="javdb", label="javdb", provider="javdb-page",
                   base_url="https://javdb.com", domains=("javdb.com", "jdbstatic.com", "jdbimgs.com"),
                   stage="community", interval=3.0, cookie=True)

_BOX = re.compile(r'<a href="(/v/[A-Za-z0-9]+)" class="box" title="[^"]*">.*?<strong>([^<]+)</strong>', re.S)
_PANEL = re.compile(r'<div class="panel-block[^"]*">\s*<strong>([^<:：]+)[:：]</strong>\s*(?:&nbsp;)?\s*'
                    r'<span class="value">(.*?)</span>', re.S)
#: 详情页那张封面。认标签、再从标签里取 `src`，不把属性挨着写死：站上 `class` 与 `src` 的先后两种写法都
#: 出现过，中间还可能夹着 `width`、`height` 与 `fetchpriority`。
_COVER = re.compile(r'<img\b[^>]*\bclass="video-cover"[^>]*>')
_IMG_SRC = re.compile(r'\bsrc="(https://[^"]+)"')
_ACTRESS = re.compile(r'<a\s([^>]*)>([^<]+)</a>')
#: 演員一栏里每个人名都挂着自己的资料页，那串 id 取名字时顺手带出来。
_ACTOR_HREF = re.compile(r'href="/actors/([A-Za-z0-9]+)"')
_JAPANESE = re.compile(r"[぀-ヿ一-鿿]")


def actresses(value: str) -> list[dict]:
    """演員一栏里的女优：名字，以及她在 javdb 的演员 id。

    男优挂的是同样的 `/actors/` 链接，靠 `actor-female` 分开。href 与 class 在标签里的先后不固定，所以先取
    整段属性再判，不假设它们的次序。
    """
    found = []
    for attributes, name in _ACTRESS.findall(value):
        if "actor-female" not in attributes:
            continue
        actor = _ACTOR_HREF.search(attributes)
        found.append({"japanese_name": clean(name), "profile_source": "javdb",
                      "external_id": actor.group(1) if actor else ""})
    return found


def maker_writing(value: str) -> str:
    """片商一栏并列英文与日文（`PRESTIGE,プレステージ`），取日文那一种。"""
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return next((part for part in parts if _JAPANESE.search(part)), parts[0] if parts else "")


class JavDBSource(SiteSource):
    DEFAULT = JAVDB

    def search_url(self, code: str) -> str:
        return f"{self.config.base_url}/search?q={urllib.parse.quote(code)}&f=all"

    def _page(self, url: str, *, session: Session) -> Page:
        page = session.get(url, config=self.config)
        if LOGIN.search(page.text):
            raise SourceFailure(FailureReason.AUTH_REQUIRED, "javdb 要求登录")
        return page

    def fetch(self, code: str, *, session: Session) -> Page:
        search = self._page(self.search_url(code), session=session)
        paths = list(dict.fromkeys(path for path, shown in _BOX.findall(search.text)
                                   if same_release_code(code, clean(shown))))
        if not paths:
            raise SourceFailure(FailureReason.NOT_FOUND, "javdb 没有这个番号")
        if len(paths) > 1:
            raise SourceFailure(FailureReason.PARSE_ERROR, "javdb 同番号对应多个作品，请核对来源身份：" + "、".join(paths),
                                detail="identity_ambiguous")
        path = paths[0]
        detail = self._page(self.config.base_url + path + "?locale=zh", session=session)
        # `source_url` 记不带界面语言参数的详情页地址。
        return Page(self.config.base_url + path, detail.body)

    def parse(self, page: Page, code: str) -> SiteRecord:
        text = page.text
        panel = {clean(label): value for label, value in _PANEL.findall(text)}
        shown = clean(panel.get("番號", "")).replace(" ", "")
        if not same_release_code(code, shown):
            raise SourceFailure(FailureReason.PARSE_ERROR, "javdb 详情页的番号与搜索结果不一致", detail="identity_mismatch")
        runtime = re.search(r"\d+", clean(panel.get("時長", "")))
        soup = BeautifulSoup(text, "html.parser")
        title = soup.select_one("strong.current-title")
        original = soup.select_one(".origin-title")
        display_title = clean(title.get_text(" ", strip=True)) if title else ""
        origin_title = clean(original.get_text(" ", strip=True)) if original else ""
        tag = _COVER.search(text)
        cover = _IMG_SRC.search(tag.group(0)) if tag else None
        genres = tuple(dict.fromkeys(
            clean(link.get_text(" ", strip=True))
            for link in BeautifulSoup(panel.get("類別", ""), "html.parser").find_all("a")
            if clean(link.get_text(" ", strip=True))))
        return SiteRecord(
            source=self.config.name, provenance=self.config.provider, code=shown, source_url=page.url,
            title=origin_title or display_title,
            performers=tuple(actresses(panel.get("演員", ""))),
            studio=maker_writing(clean(panel.get("片商", ""))), label=clean(panel.get("發行", "")),
            series=clean(panel.get("系列", "")), director=clean(panel.get("導演", "")),
            release_date=clean(panel.get("日期", "")), runtime=int(runtime.group()) if runtime else None,
            tags=genres,
            cover_urls=(cover.group(1),) if cover else (),
            extra={"origin_title": origin_title, "display_title": display_title,
                   "source_id": urllib.parse.urlsplit(page.url).path.rsplit("/", 1)[-1]})
