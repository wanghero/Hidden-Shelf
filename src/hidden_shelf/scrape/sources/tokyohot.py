"""Tokyo-Hot（my.tokyo-hot.com）官网的作品页。自写，不是从 peach 移植。

东京热是无码片商，编号形状独属一家（`n####`、`k####`、`red-###`，见 `rules.codes.tokyo_hot_code`），
目录站给的资料零碎，官网那一页才齐：标题、整段简介、出演者、プレイ内容标签、系列、配信開始日、收录时长，
外加一张 3762×2522 的封套（`/media/<编号>/jacket/…jpg`）。免登录、普通 UA 直接 200，没有 Cloudflare 验证
（2026-10-30 本机实测）。

作品页地址不是番号：新作是 `/product/n1700/`，老作品是站内数字编号 `/product/6325/`（n1161），
直接拿番号去开老作品是 404。所以一律先搜 `GET /product/?q=<番号>&lang=ja`，结果列表每项带
`(作品番号: n1161)`，取番号正好相等的那一项再开作品页；一部片两次请求。搜不到就是站上没有
（下架或根本不是这家的号），记「没有」。

简介在 `div.sentence`，段落用 `<br /><br />` 分开。老作品末尾挂着一段「餌食情報」（出演者的身高三围之类），
站方还把一串检索关键词黏在它最后一行后面，这两样都不是简介，从「餌食情報」起整段截掉；第一行常常是
标题原文重复一遍，也去掉。
"""
from __future__ import annotations

import html
import re
from urllib.parse import quote

from ...rules.codes import tokyo_hot_code
from .base import FailureReason, Page, Session, SiteConfig, SiteRecord, SiteSource, SourceFailure

#: 作品页、搜索页和图床（`my.cdn.tokyo-hot.com`）都在 tokyo-hot.com 底下。作品页实测 170～190 KB，上限留 2 MiB。
TOKYOHOT = SiteConfig(name="tokyohot", label="Tokyo-Hot", provider="tokyohot-html", base_url="https://my.tokyo-hot.com",
                      domains=("tokyo-hot.com",), stage="official", page_limit=2 * 1024 * 1024)
SEARCH_PATH = "/product/?q={query}&lang=ja"
#: 库里这家的厂牌写法（`studios.STUDIO_CANONICAL`）。
STUDIO = "Tokyo-Hot"

_RESULT = re.compile(r'<li class="detail">\s*<a href="(/product/[^"/]+/)"(.*?)</li>', re.S)
_RESULT_CODE = re.compile(r"作品番号[:：]\s*([A-Za-z0-9_-]+)")
_TITLE = re.compile(r'<div class="contents">\s*<h2>(.*?)</h2>', re.S)
_SENTENCE = re.compile(r'<div class="sentence">(.*?)</div>', re.S)
_INFO = re.compile(r'<dl class="info">(.*?)</dl>', re.S)
_ROW = re.compile(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", re.S)
_LINK = re.compile(r'<a href="([^"]*)"[^>]*>(.*?)</a>', re.S)
_JACKET = re.compile(r'href="(https://[^"]+/media/[^"]+/jacket/[^"]+\.jpe?g)"')
_LIST_IMAGE = re.compile(r'(https://[^"\s]+/media/[^"\s]+/list_image/[^"\s]+/820x462_default\.jpg)')
_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_PARAGRAPH_BREAK = "<br /><br />"
#: 简介里从这一行起不是剧情：出演者档案，后面还黏着站方的检索词。
_PROFILE_HEAD = "餌食情報"
_DATE = re.compile(r"(\d{4})/(\d{2})/(\d{2})")
_DURATION = re.compile(r"(\d{1,3}):(\d{2}):(\d{2})")


def product_code(code: str) -> str:
    """库里番号 → 官网认的写法（小写、补零）；不是这家的形状回空串。"""
    return tokyo_hot_code(code)


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).split())


def _links(fragment: str) -> list[tuple[str, str]]:
    return [(href, _text(label)) for href, label in _LINK.findall(fragment) if _text(label)]


def plot_from_sentence(fragment: str, title: str = "") -> str:
    """`div.sentence` 的 HTML → 分段简介。段间一个空行；「餌食情報」起截掉；开头重复的标题去掉。"""
    paragraphs: list[str] = []
    for chunk in fragment.split(_PARAGRAPH_BREAK):
        lines = [" ".join(html.unescape(_TAG.sub(" ", line)).split()) for line in _BR.split(chunk)]
        lines = [line for line in lines if line]
        if any(line.startswith(_PROFILE_HEAD) for line in lines):
            lines = lines[:next(i for i, line in enumerate(lines) if line.startswith(_PROFILE_HEAD))]
            paragraphs.append("\n".join(lines))
            break
        paragraphs.append("\n".join(lines))
    paragraphs = [item for item in paragraphs if item]
    if paragraphs and title:
        # 标题原文有时单独占第一行，有时和第一段黏在同一行开头
        head_lines = paragraphs[0].split("\n")
        if head_lines[0] == title:
            head_lines.pop(0)
        elif head_lines[0].startswith(title + " "):
            head_lines[0] = head_lines[0][len(title):].strip()
        paragraphs[0] = "\n".join(head_lines)
        paragraphs = [item for item in paragraphs if item]
    return "\n\n".join(paragraphs).strip()


class TokyoHotSource(SiteSource):
    DEFAULT = TOKYOHOT

    def search_url(self, code: str) -> str:
        found = product_code(code)
        # 官网自己写小写 `n1161`，搜索对大小写不敏感；库里的规范写法是大写（v1.4.11），搜索词按站上的写法
        return self.config.base_url + SEARCH_PATH.format(query=quote(found.lower())) if found else ""

    def _unrecognised(self) -> SourceFailure:
        return SourceFailure(FailureReason.NOT_FOUND, f"这个番号不是{self.config.label}的写法")

    def product_url(self, page: Page, code: str) -> str:
        """搜索结果里番号正好相等的那一项的作品页地址；没有回空串。"""
        wanted = product_code(code)
        for href, body in _RESULT.findall(page.text):
            found = _RESULT_CODE.search(_text(body))
            if found and tokyo_hot_code(found.group(1)) == wanted:
                return self.config.base_url + href + "?lang=ja"
        return ""

    def fetch(self, code: str, *, session: Session) -> Page:
        url = self.search_url(code)
        if not url:
            raise self._unrecognised()
        listing = session.get(url, config=self.config)
        target = self.product_url(listing, code)
        if not target:
            raise SourceFailure(FailureReason.NOT_FOUND, f"{self.config.label}站上没有这部片")
        return session.get(target, config=self.config, referer=url)

    def parse(self, page: Page, code: str) -> SiteRecord:
        wanted = product_code(code)
        if not wanted:
            raise self._unrecognised()
        text = page.text
        info = _INFO.search(text)
        title = _TITLE.search(text)
        if not info or not title:
            raise SourceFailure(FailureReason.PARSE_ERROR, f"{self.config.label}的作品页结构对不上")
        rows = {_text(name): body for name, body in _ROW.findall(info.group(1))}
        found_code = tokyo_hot_code(_text(rows.get("作品番号", "")))
        if found_code != wanted:
            raise SourceFailure(FailureReason.NOT_FOUND, f"{self.config.label}回的作品号对不上这个番号")
        performers = tuple({"japanese_name": name, "profile_source": self.config.name,
                            "external_id": href.strip("/").rsplit("/", 1)[-1]}
                           for href, name in _links(rows.get("出演者", "")) if "/cast/" in href)
        series = [name for _href, name in _links(rows.get("シリーズ", ""))]
        tags = tuple(dict.fromkeys(name for _href, name in _links(rows.get("プレイ内容", ""))))
        date = _DATE.search(_text(rows.get("配信開始日", "")))
        duration = _DURATION.search(_text(rows.get("収録時間", "")))
        runtime = None
        if duration:
            hours, minutes, seconds = (int(part) for part in duration.groups())
            runtime = round(hours * 60 + minutes + seconds / 60, 2)
        covers = [found.group(1) for found in _JACKET.finditer(text)]
        covers += [url for url in _LIST_IMAGE.findall(text) if url not in covers][:1]
        title_text = _text(title.group(1))
        sentence = _SENTENCE.search(text)
        return SiteRecord(
            source=self.config.name, provenance=self.config.provider, code=found_code, source_url=page.url,
            title=title_text, performers=performers, studio=STUDIO,
            label=_text(rows.get("レーベル", "")), series=series[0] if series else "",
            release_date="-".join(date.groups()) if date else "", runtime=runtime,
            tags=tags, cover_urls=tuple(dict.fromkeys(covers)),
            plot=plot_from_sentence(sentence.group(1), title_text) if sentence else "")
