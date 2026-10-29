"""一本道（1pondo.tv）：Task 3 先放路由要用的两个纯函数，Task 4 填解析器。"""
from __future__ import annotations

import re

from ...rules.codes import is_uncensored_code

#: 站上的作品名写作 `112312_478`；库里同一部片可能写成 `112312-478`，那是压制组的文件名带进来的。
_DATED = re.compile(r"^(\d{6})[-_](\d{2,4})$")
#: 一本道自己在页面上标着「1pon」，作品目录、文件名与库里的 studio 都用得上这几个写法。
_OWN_MARKS = ("1pon", "一本道", "1pondo")


def movie_id(code: str) -> str:
    """库里番号 → 官网作品号。不是日期式番号的回空串。"""
    found = _DATED.match(str(code or "").strip())
    if not found or not is_uncensored_code(f"{found.group(1)}_{found.group(2)}"):
        return ""
    return f"{found.group(1)}_{found.group(2)}"


def names_this_studio(*evidence: str) -> bool:
    """这几段文字（路径、文件名、库里厂牌）里有没有说这部片是一本道的。"""
    text = " ".join(str(item or "") for item in evidence).lower()
    return any(mark.lower() in text for mark in _OWN_MARKS)
