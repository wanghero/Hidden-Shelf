"""查询侧的来源路由：一个番号属于哪种内容，因此问哪几家、什么顺序、何时停。

移植自 peach `src/peach/metadata_routes.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）。改动：

- 链上只放本项目接了的 8 站。经 amane 桥的片商站（prestige、faleno、dahlia、makers）、mgstage、
  avsox，以及要本机浏览器过 Cloudflare 的 fc2cmadb、fc2ppvdb、javten 都不接，不留占位；
  `MAKER_EVIDENCE` 与 `AMANE_*` 整段删掉。
- **综合索引三家不合成一档**（用户 2026-10-29 决定「有一家答了就停」）：avbase、javbus、javdb
  各算一档，与官方档一样逐家短路。peach 的 `COMMUNITY_STAGE`、`LIST_FIELD_DEPTH`、`community_route`
  服务于两家互证，本项目不互证，不移植。FC2 的两站同理各成一档。

本模块只管**问**：番号的内容类型、该类型的有序来源链、以及一站取到必填标量字段之后不再问下一站。
取回来的值怎么排序、怎么结算分歧，在 `policy`：javbus 在结算上是兜底，在查询上却排在 javdb 前面——
javdb 按出口 IP 计配额、主机间隔 3 秒，先问便宜的那两家不影响结算，只影响谁先撞上限流。

国产、欧美这些一家对应来源都没接的体系合成一类 `other`，链是空的；番号形状像有码、本机证据却对不上
它的写法时归 `unsure`，只问综合索引那几家。
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

from ..rules.codes import is_amateur_code, is_korean_mib_code, is_uncensored_code
from .policy import SOURCE_SPECS

#: 内容类型。`unknown` 是「番号认不出来」，不是一种内容；`other` 是认得出、但没接来源的体系
#: （国产、欧美）；`unsure` 是形状像有码、本机证据对不上的番号。
CONTENT_TYPES = ("censored", "amateur", "uncensored", "fc2", "kmib", "other", "unsure", "unknown")

#: MGStage 素人系的字母前缀。三位数字前缀那一批由 `is_amateur_code` 认，这三种没有数字前缀，
#: 形态上和厂牌番号一样，只能按前缀列出来。**`ABP` / `ABF` / `ABW` 不在此列**：那是 Prestige 的有码番号。
MGS_AMATEUR_PREFIXES = ("SIRO", "STP", "STN")
_MGS_AMATEUR = re.compile(r"^(?:" + "|".join(MGS_AMATEUR_PREFIXES) + r")-?\d+$", re.I)
#: 入库前没归一成 `FC2-PPV-…` 的短写法：`FC-43768`。
_FC2_SHORT = re.compile(r"^FC-\d{5,}$", re.I)
#: 番号拆成字母段与数字段，用来在本机证据里找它的写法。
_CODE_PARTS = re.compile(r"^([A-Z]+)-?0*(\d+)$")
#: 路径里出现就说明这是没接来源的体系。peach 2026-09-25 账本实测：`兔子先生TZ-105`、`网红…合集\MXGD3721.MP4`
#: 这类文件的番号形状和有码一模一样，按有码链问下去是每家各白问一遍。
OTHER_SYSTEM_MARKS = ("国产", "國產", "网红", "網紅", "兔子先生", "麻豆")
#: 欧美片站的文件名：番号前面挂着至少两个用连字符或下划线连起来的拉丁词
#: （`wankzvr-elena-koshka-GFE-180_180x180_3dh_LR.mp4`，站名加演员名）。
_WESTERN_SLUG = r"(?<![a-z])(?:[a-z]{2,}[-_]){2,}"

#: 每种内容类型问哪几家，从左到右。每条链后面的注释回答两件事：为什么是这个顺序，
#: 以及为什么某一家**不**在这条链上——后者才是省请求的地方。
ROUTES: dict[str, tuple[str, ...]] = {
    # 有码：r18.dev 一次请求给标题、厂牌、系列、发行日与演员；r18.dev 没有再问 DMM 自己的 GraphQL 目录
    # （它是 r18.dev 镜像的源头，当月新片与小厂 r18.dev 都是 404 而 DMM 有）；再落空才到三家综合索引。
    # AVBase 与 JavBus 各一次请求，javdb 两次且按出口 IP 计配额，所以 javdb 排最后。
    # 不进这条链：1pondo（无码片商，有码番号一律 404）、fc2（商品号体系不同）。
    # peach 还把片商官网（prestige/faleno/dahlia/makers，经 amane 桥）排在最前，本项目不接。
    "censored": ("r18dev", "dmm", "avbase", "javbus", "javdb"),
    # 素人：peach 先问 mgstage（MGS 素人系由 MGS 自己发行），本项目不接它，直接到综合索引。
    # r18.dev 垫在最后：peach 清点本机来源快照，素人号在 r18.dev 上一份都没有，排前面等于每部片先白等一次。
    # dmm 不进：DMM 的搜索对 `MIUM 1239`、`LUXU 1475` 零结果。
    "amateur": ("avbase", "javbus", "javdb", "r18dev"),
    # 无码：发行方自己那份作品 JSON 先问，但只在本机证据指着一本道时才问（见 `route_for_code`）——
    # 日期式番号不带片商，カリビアンコム 与一本道同形，问错一家答回来的是同一天发行的另一部片。
    # **不含 r18dev**：无码番号在 r18.dev 上没有。peach 的 avsox 经 amane 桥，本项目不接。
    "uncensored": ("1pondo", "avbase", "javbus", "javdb"),
    # FC2：发行方商品页 → 下架作品的转载站 JavArchive → javdb。peach 中间还有 fc2cmadb、fc2ppvdb、javten
    # 三个要本机浏览器过 Cloudflare 的存档站，本项目不接。
    # 不含 r18dev（peach 实测 85 条全空）、不含 AVBase 与 JavBus（对 FC2 番号一份都没给过）。
    "fc2": ("fc2", "javarchive", "javdb"),
    # 韩国 MIB 一家都不问：番号和日本番号同形，JAV 目录站按它去查返回的是别的作品。
    "kmib": (),
    # 国产、欧美：一家对应来源都没接，问日本目录站只会查空或撞上同号的日本片。
    "other": (),
    # 形状像有码、本机证据对不上写法的番号：只问综合索引，不问 r18.dev 与 DMM。
    "unsure": ("avbase", "javbus", "javdb"),
    "unknown": (),
}

#: 发行方与专站那一档。javarchive 按来源分级是 community，但在链上属于这一档：它只收 FC2，不是综合索引。
OFFICIAL_STAGE = ("r18dev", "dmm", "1pondo", "fc2", "javarchive")
#: 综合索引那几家。本项目里它们各是一档，逐家短路；列出来只为 `official_route` 等处分类。
COMMUNITY_SOURCES = ("avbase", "javbus", "javdb")
#: 缺标签的行在这几档之间多问一家，见 `settles`。dmm 不在这里：它与 r18.dev 是同一份目录，
#: r18.dev 答了标量却没给标签时再问 DMM 拿回的还是那一套 genre；它只在 r18.dev 落空时被问。
OFFICIAL_STAGE_NAMES = ("r18dev", "1pondo", "fc2")

#: 必填标量字段。一站把这几项（在这一行还缺的范围内）都给全了就不问下一站。
SCALAR_FIELDS = ("title", "performers", "studio", "release_date")
#: 列表字段。本项目不互证：这一行只缺列表字段时，第一站给出资料就停。
LIST_FIELDS = ("tags", "cover_url")


def classify(code: str | None, *hints: str | None) -> str:
    """这个番号属于哪种内容。`hints` 是本机证据（路径、文件名、库里厂牌）。

    只看番号形状与本机证据，不依赖任何抓取结果：一旦改成「先拿到元数据再判断」，
    没有元数据的番号就永远轮不到该问的那个来源。

    有码是兜底那一类，所以本机证据在这里再分三种（例子都是 peach 账本实测）：

    - 证据里写着带三位数字前缀的同一个号（`LUXU-688` 的文件是 `259LUXU-688.mp4`）是素人；
    - 路径带国产标记（`OTHER_SYSTEM_MARKS`）或文件名是欧美片站的写法（`_WESTERN_SLUG`）归 `other`；
    - 证据里有这个号的字母段、却找不到它的完整写法，是文件名被读错了号
      （`UWFr85dczsVeysGg.mp4` 读成 `UWFR-085`），归 `unsure`。证据里压根没有字母段的不算读错。
    """
    value = str(code or "").strip()
    if not value:
        return "unknown"
    if is_korean_mib_code(value):
        return "kmib"
    if value.upper().startswith("FC2") or _FC2_SHORT.match(value):
        return "fc2"
    if is_uncensored_code(value):
        return "uncensored"
    if is_amateur_code(value) or _MGS_AMATEUR.match(value.upper()):
        return "amateur"
    return _censored_or_other(value.upper(), [str(hint) for hint in hints if hint])


def _censored_or_other(value: str, hints: list[str]) -> str:
    """有码形状的番号按本机证据再分一次，判据见 `classify`。"""
    parts = _CODE_PARTS.match(value)
    if not parts or not hints:
        return "censored"
    letters, number = parts.group(1), str(int(parts.group(2)))
    text = "\n".join(hints)
    # 连字符是判据的一半：DMM 的 content_id 也是三位数字打头（`118lxvs00039`），那是 Prestige
    # 的有码号；MGS 素人号的写法总带着连字符。
    if re.search(rf"(?<![A-Z0-9])\d{{3}}{letters}-0*{number}(?!\d)", text, re.I):
        return "amateur"
    if any(mark in text for mark in OTHER_SYSTEM_MARKS):
        return "other"
    written = rf"(?<![A-Z]){letters}[-_ ]?0*{number}(?!\d)(?:[A-Z]{{0,3}})(?![A-Z])"
    if re.search(_WESTERN_SLUG + written, text, re.I):
        return "other"
    if re.search(written, text, re.I):
        return "censored"
    return "unsure" if re.search(rf"(?<![A-Z]){letters}", text, re.I) else "censored"


def parse_route_overrides(raw: str | Mapping[str, Sequence[str] | str] | None):
    """用户给的每类型覆盖。文本写法 `censored=r18dev,javdb;fc2=fc2`。

    来源名必须在 `SOURCE_SPECS` 里登记过，类型名必须是 `CONTENT_TYPES` 之一，不认识的直接报错
    而不是静默忽略。空链合法，意思是这类内容一家都不问。
    """
    if raw is None:
        return {}
    items: Iterable[tuple[str, Sequence[str] | str]]
    if isinstance(raw, str):
        items = [tuple(part.split("=", 1)) for part in raw.split(";") if part.strip()]  # type: ignore[misc]
    else:
        items = list(raw.items())
    overrides: dict[str, tuple[str, ...]] = {}
    for entry in items:
        if len(entry) != 2:
            raise ValueError("来源链覆盖要写成 `类型=来源,来源`")
        name, value = entry
        content = str(name).strip()
        if content not in CONTENT_TYPES:
            raise ValueError("未知内容类型：" + content)
        parts = value.split(",") if isinstance(value, str) else list(value)
        sources = tuple(dict.fromkeys(str(part).strip() for part in parts if str(part).strip()))
        unknown = [source for source in sources if source not in SOURCE_SPECS]
        if unknown:
            raise ValueError("未知来源：" + "、".join(unknown))
        overrides[content] = sources
    return overrides


def route(content_type: str, *, overrides: Mapping[str, Sequence[str]] | None = None):
    """这种内容的有序来源链。用户覆盖整条替换，不做逐项合并。"""
    if content_type not in ROUTES:
        raise ValueError("未知内容类型：" + str(content_type))
    resolved = parse_route_overrides(overrides)
    if content_type in resolved:
        return resolved[content_type]
    return ROUTES[content_type]


def route_for_code(code: str | None, *hints: str | None,
                   overrides: Mapping[str, Sequence[str]] | None = None):
    """这个番号的来源链，已按本机证据裁过。

    无码那条链上的 `1pondo` 要证据：日期式番号本身不带片商，只有路径、文件名或库里厂牌
    指着一本道时才问它，问不着的照旧落到综合索引。
    """
    chain = route(classify(code, *hints), overrides=overrides)
    if "1pondo" in chain:
        from .sources.onepondo import movie_id, names_this_studio
        if not (movie_id(str(code or "")) and names_this_studio(*hints)):
            chain = tuple(source for source in chain if source != "1pondo")
    return chain


def stage_name(source: str) -> str:
    """这个来源在采集里属于哪一档。本项目每站各是一档：逐家短路，有一家答了就停。"""
    return source


def stages_for_chain(chain: Sequence[str]):
    """任意一条有序来源链按档摊开，顺序同链。"""
    stages: list[str] = []
    for source in chain:
        name = stage_name(source)
        if name not in stages:
            stages.append(name)
    return tuple(stages)


def stages_for_code(code: str | None, *hints: str | None,
                    overrides: Mapping[str, Sequence[str]] | None = None):
    return stages_for_chain(route_for_code(code, *hints, overrides=overrides))


def stage_members(stage: str, chain: Sequence[str]):
    """这一档在链上对应哪几个来源名。"""
    return tuple(source for source in chain if stage_name(source) == stage)


def official_route(code: str | None, *hints: str | None,
                   overrides: Mapping[str, Sequence[str]] | None = None):
    """链上属于官方／发行方那一档的成员，顺序同链。"""
    chain = route_for_code(code, *hints, overrides=overrides)
    return tuple(source for source in chain if source in OFFICIAL_STAGE)


def required_scalars(missing: Iterable[str]):
    """这一行还缺、且属于必填标量的那些字段。空集合表示没有可短路的目标。"""
    wanted = set(str(field) for field in missing)
    return tuple(field for field in SCALAR_FIELDS if field in wanted)


def settles(required: Sequence[str], provided: Iterable[str], *,
            wants_tags: bool = False, then: str = "") -> bool:
    """这一档给的字段够不够停手。

    `required` 空时任何一档只要给出资料就停——这一行要的本来就不是标量字段。

    `wants_tags` 是这一行还缺标签，`then` 是链上下一档的档名。下一档仍是官方档
    （`OFFICIAL_STAGE_NAMES`）时再问它一次换一批标签；下一档是综合索引就照样停：
    javdb 按出口 IP 计配额，不为标签多问。
    """
    given = set(str(field) for field in provided)
    if wants_tags and "tags" not in given and then in OFFICIAL_STAGE_NAMES:
        return False
    if not required:
        return True
    return all(field in given for field in required)
