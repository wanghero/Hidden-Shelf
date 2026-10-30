"""来源分级与字段结算策略：取回来的值怎么分级、怎么排序、分歧听谁的。

移植自 peach `src/peach/metadata_policy.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）。改动：只登记本项目接了的 8 站，去掉历史来源与经 amane 桥的站；
`LOCAL_NFO_SOURCE` 改名 `nfo`（与计划 1 的 `auto:nfo` 对齐）；新增 `owner_tier`，把 `field_owners`
的归属串折成层级，供跨次运行的「高档覆盖低档」判断。

查询侧（一个番号问谁、什么顺序、何时停）在 `routes`；这里只管取回来的值怎么分级。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

POLICY_VERSION = "hidden-shelf-source-policy-v1"
FIELDS = ("title", "original_title", "performers", "studio", "series", "release_date", "tags")


@dataclass(frozen=True)
class SourceSpec:
    name: str
    kind: str

    @property
    def official(self) -> bool:
        return self.kind in {"official", "official_mirror"}


SOURCE_SPECS = {
    name: SourceSpec(name, kind) for name, kind in {
        # r18.dev 是 DMM 数字版目录的镜像，有码链排在最前的那一档。
        "r18dev": "official_mirror",
        # DMM 自己的 GraphQL 目录，有码链上 r18.dev 之后的兜底。
        "dmm": "official",
        # FC2 发行方自己的商品页。
        "fc2": "official",
        # 一本道的官网作品 JSON，发行方自己那一份。
        "1pondo": "official",
        # 几个存档站也没有的下架 FC2 的最后一档：转载站，标题由发布者写，封面是转存件。
        "javarchive": "community",
        # 自写解析器的社区站。
        "javdb": "community", "javbus": "community",
        # AVBase 汇总各店铺的商品条目。
        "avbase": "community",
    }.items()
}

#: 社区来源之间不一致时听这一家的。peach 用户 2026-09-16 逐条核对过：javdb 比 javbus 准。
PREFERRED_COMMUNITY_SOURCE = "javdb"

#: 兜底来源：同一个字段上还有别家可用时，它的取值不当证据。javbus 搜不到原番号会给近似命中。
FALLBACK_SOURCES = ("javbus",)

#: 视频旁边那份 NFO。它不是联网来源，所以不进 `SOURCE_SPECS`，但字段优先级链要给它排一个位置。
#: 计划 1 的 `local_import` 以 `auto:nfo` 身份写入，名字只能有一份。
LOCAL_NFO_SOURCE = "nfo"

#: 字段优先级链的层级，数字越小越先被采信。用户自己整理的 NFO 在最前，其次是发行方自己那页，
#: 再次是逐条核对过的 javdb，然后是其余社区站，最后是兜底。未登记的来源排在所有已知来源之后。
CHAIN_LOCAL_NFO, CHAIN_OFFICIAL, CHAIN_PREFERRED = 0, 1, 2
CHAIN_COMMUNITY, CHAIN_FALLBACK, CHAIN_UNKNOWN = 3, 4, 5

#: 稀疏例外：某个字段上把几家来源提到链首。peach 那行 fc2cmadb 随站一起没接，表先空着。
FIELD_SOURCE_PRIORITY: dict[str, tuple[str, ...]] = {}

#: 字段级黑名单，优先于一切：列进来的来源在这个字段上连候选都不算。
FIELD_SOURCE_BLACKLIST: dict[str, frozenset[str]] = {}

#: 每个字段上官方来源之间谁更接近这部片的发行方。顺序照 peach，只留接了的站。
#: `release_date`：r18dev 排在 fc2 之后、javdb 之前（它给的发行日与 DMM 同源，但有码链已有 dmm 在前）。
#: `tags`：dmm 的 genre 与 r18dev 是同一套词，r18dev 垫后；有码作品的标签另由 `preferred_tag_source` 提 javdb 到链首。
FIELD_SOURCE_ORDER = {
    "title": ("dmm", "r18dev", "1pondo", "fc2", "javdb", "avbase", "javbus", "javarchive"),
    "original_title": ("dmm", "r18dev", "1pondo", "fc2", "javdb", "avbase", "javbus", "javarchive"),
    "performers": ("dmm", "r18dev", "1pondo", "fc2", "javdb", "avbase", "javbus", "javarchive"),
    "studio": ("dmm", "r18dev", "1pondo", "fc2", "javdb", "avbase", "javbus", "javarchive"),
    "series": ("dmm", "r18dev", "1pondo", "fc2", "javdb", "avbase", "javbus", "javarchive"),
    "release_date": ("dmm", "1pondo", "fc2", "r18dev", "javdb", "avbase", "javbus", "javarchive"),
    "tags": ("dmm", "1pondo", "fc2", "r18dev", "javdb", "avbase", "javbus", "javarchive"),
}


def source_tier(source: str) -> int:
    """这家来源在字段优先级链上的层级。"""
    name = str(source or "").strip()
    if name == LOCAL_NFO_SOURCE:
        return CHAIN_LOCAL_NFO
    if name in FALLBACK_SOURCES:
        return CHAIN_FALLBACK
    spec = SOURCE_SPECS.get(name)
    if spec is None:
        return CHAIN_UNKNOWN
    if spec.official:
        return CHAIN_OFFICIAL
    if name == PREFERRED_COMMUNITY_SOURCE:
        return CHAIN_PREFERRED
    return CHAIN_COMMUNITY


def owner_tier(owner: str | None) -> int:
    """`field_owners` 的归属串折成层级：`auto:nfo` 与 `auto:local` 是 0，`auto:<站>` 按站，`auto:frame` 垫底。

    `user:*`、`review:*` 返回 -1：它们由 `field_owners` 挡住，这里给个永远赢的数只是让比较不出错。
    无主（空串）返回比任何来源都大的数：空格子谁都能填。
    """
    text = str(owner or "").strip()
    if not text:
        return CHAIN_UNKNOWN + 100
    kind, _, identifier = text.partition(":")
    if kind in {"user", "review"}:
        return -1
    if kind == "auto":
        if identifier in {LOCAL_NFO_SOURCE, "local"}:
            return CHAIN_LOCAL_NFO
        if identifier == "frame":
            return CHAIN_UNKNOWN + 50
        return source_tier(identifier)
    return CHAIN_UNKNOWN


def preferred_tag_source(code: str | None) -> str | None:
    """有码作品的内容标签采用 JavDB 社区类别（它比 DMM 那套泛化类别细），其余类型沿用来源链。"""
    from .routes import classify

    return PREFERRED_COMMUNITY_SOURCE if code and classify(code) == "censored" else None


def chain_rank(field: str, source: str, *, code: str | None = None) -> tuple[int, int, str]:
    """字段优先级链上的排序键，越小越先采信。层内用 `FIELD_SOURCE_ORDER` 再排一次；名字兜底保证确定。"""
    name = str(source or "").strip()
    if name == LOCAL_NFO_SOURCE:
        return (-2, 0, name)
    if field == "tags" and preferred_tag_source(code):
        if name == preferred_tag_source(code):
            return (-1, 0, name)
    priority = FIELD_SOURCE_PRIORITY.get(field, ())
    if name in priority:
        return (-1, priority.index(name), name)
    order = FIELD_SOURCE_ORDER.get(field, ())
    within = order.index(name) if name in order else len(order)
    return (source_tier(name), within, name)


def blacklisted(field: str, source: str) -> bool:
    """这个字段上这家来源是不是被判了不听。"""
    return str(source or "").strip() in FIELD_SOURCE_BLACKLIST.get(field, frozenset())


def field_rank(field: str, source: str, *, code: str | None = None) -> int:
    """这家来源在这个字段的顺序表里排第几，从 1 起；表里没有的排在末尾之后。"""
    order = FIELD_SOURCE_ORDER[field]
    if field == "tags" and preferred_tag_source(code) and source == LOCAL_NFO_SOURCE:
        return -1
    if field == "tags" and source == preferred_tag_source(code):
        return 0
    try:
        return order.index(source) + 1
    except ValueError:
        return len(order) + 1


def sort_candidates(field: str, candidates: Iterable[Mapping[str, object]], *,
                    code: str | None = None) -> list[dict]:
    """同一字段的候选按来源顺序表排，同位次按置信度，再按来源名兜底保证确定。"""
    if field not in FIELDS:
        raise ValueError("未知元数据字段：" + field)
    rows = [dict(candidate) for candidate in candidates]
    for row in rows:
        row["field_rank"] = field_rank(field, str(row.get("source") or ""), code=code)
    rows.sort(key=lambda row: (
        int(row["field_rank"]),
        -float(row.get("confidence") or 0),
        str(row.get("source") or ""),
    ))
    return rows
