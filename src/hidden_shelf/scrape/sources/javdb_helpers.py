"""javdb 页面的几个共用判据。

取自 peach `src/peach/javdb.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，AGPL-3.0-or-later）
的 `LOGIN`、`RECORD_KIND`、`clean`；peach 那个模块的其余部分（演员资料页、人物搜索）不移植。
"""
from __future__ import annotations

import html as html_lib
import re

#: 一部分页面要登录才给，回的是登入页而不是 401/403。搜索页与详情页都要认。
LOGIN = re.compile(r"<title>\s*登入\s*\|")

#: 同一位女优的无码那条记录，现名后面挂着 `(無碼)`。它是记录类型不是名字的一部分，留着会让
#: `木下ひまり(無碼)` 与 `木下ひまり` 变成两个人。
RECORD_KIND = re.compile(r"[(（](?:無碼|无码|有碼|有码|流出|破解|中文字幕)[)）]\s*$")

_TAG = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    """去标签、解实体、压空白。"""
    return re.sub(r"\s+", " ", html_lib.unescape(_TAG.sub(" ", text)).replace("\xa0", " ")).strip()
