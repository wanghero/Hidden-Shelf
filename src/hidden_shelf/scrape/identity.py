"""番号身份核对：来源返回的是不是问的那部片。

移植自 peach `src/peach/metadata.py` 的 `validate_provider_code`、`identifies_code`
（commit 4d5266d327a5971773409b44316e3926bd37c6ba，AGPL-3.0-or-later）。
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..rules.codes import code_query_variants, normalise_code_key, same_release_code, tokyo_hot_code

#: 日期式那一支两种分隔符都放行：`_` 是一本道等片商的标识，不是可替换的写法。
#: 这里拦的是路径、URL 和任意文本，不是分隔符。
_SAFE_CODE = re.compile(
    r"^(?:FC2-PPV-\d{5,}|\d{3}[A-Z]{2,6}-\d{2,5}|[A-Z]{2,8}-\d{2,5}|\d{6}[-_]\d{2,4})$")

#: 番号在来源返回里的身份证据。`id`、`content_id` 和 `source_url` 至少有一处
#: 要认得出这个番号，否则拿到的是别的商品。
IDENTITY_FIELDS = ("id", "content_id", "source_url")

#: URL 里可能承载番号的片段。路径段与查询值都可能是它，`combined=ene009` 这种
#: 还要按 `=` 再切一层才拿得到右边那一半。
_URL_TOKEN = re.compile(r"[A-Za-z0-9_]+(?:-[A-Za-z0-9]+)*")


def validate_provider_code(code: str) -> str:
    """来源只接受规范化番号，不接受路径、URL 或任意文本。"""
    raw = str(code or "").strip()
    tokyo = tokyo_hot_code(raw)
    if tokyo:
        # Tokyo-Hot 的规范写法是小写，跟着别的番号转大写就等于拿一个来源不认的写法去查。
        return tokyo
    value = raw.upper()
    if not _SAFE_CODE.fullmatch(value):
        raise ValueError("来源只接受规范化番号，不接受路径、URL 或任意文本")
    return value


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _release_writings(payload: dict) -> list[str]:
    """payload 里所有可能是番号写法的片段，逐个交给 `same_release_code` 比。"""
    values = [str(payload.get(field) or "") for field in ("id", "content_id")]
    url = urlsplit(str(payload.get("source_url") or ""))
    blob = f"{url.path.replace('/', ' ')} {url.query.replace('&', ' ')}"
    for chunk in blob.split():
        values.extend(_URL_TOKEN.findall(chunk))
        if "=" in chunk:
            values.append(chunk.split("=", 1)[-1])
    return [value for value in values if value]


def identifies_code(code: str, payload: dict) -> bool:
    """来源返回的是不是这个番号本身。

    dl.getchu 对 `ABW-220` 和 `259LUXU-1475` 都返回同一件同人商品 `item33938`：站里没有
    这个番号时它不报「查无此片」，而是把不相干的商品当结果交出来。没有这道闸，那件商品的
    genre 会变成三个番号的官方标签。

    真实来源的写法要容得下：DMM 的 `118abw220` 带厂牌数字前缀，r18dev 的 `h_086iqqq00026`
    对 `IQQQ-026` 多补了零，`259LUXU-1475` 只在 URL 里出现。

    先问 `same_release_code`，它认得 FC2 的裸数字写法和登记过的前缀别名；下面那套正则不认，
    于是把 `FC2-PPV-3701252` 和来源返回的 `3701252` 判成两部作品。两条判据取并集：
    `same_release_code` 严格但不认厂牌数字前缀（`MAAN-545` 与 `300MAAN-545`），正则宽松但认得。
    """
    if any(same_release_code(code, writing) for writing in _release_writings(payload)):
        return True
    if re.match(r"^\d{3}[A-Z]", str(code or "").upper()):
        url = urlsplit(str(payload.get("source_url") or ""))
        product = re.fullmatch(r"/product/product_detail/([^/]+)/?", url.path)
        returned = str(payload.get("id") or payload.get("content_id") or "")
        if url.hostname in {"mgstage.com", "www.mgstage.com"} and product:
            product_code = product.group(1)
            return same_release_code(code, product_code) and (
                not returned or same_release_code(product_code, returned)
                or normalise_code_key(returned) in code_query_variants(product_code))
        return any(same_release_code(code, payload.get(field)) for field in ("id", "content_id"))
    blob = "|".join(_compact(payload.get(field)) for field in IDENTITY_FIELDS)
    if not blob.strip("|"):
        return False
    value = str(code or "").upper()
    matched = re.fullmatch(r"(?:\d{3,6})?([A-Z]{2,8})-?(\d{2,5})([A-Z]{0,2})", value)
    if matched:
        letters, digits = matched.group(1).lower(), matched.group(2).lstrip("0") or "0"
        suffix = matched.group(3).lower()
        return any(re.search(rf"(?<![a-z]){letters}[-_]?0*{digits}{suffix}(?![a-z0-9])",
                             str(payload.get(field) or "").lower()) is not None
                   for field in IDENTITY_FIELDS)
    return _compact(value) in blob
