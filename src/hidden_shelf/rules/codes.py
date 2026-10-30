"""番号识别规则：什么是番号、什么是分卷、噪声怎么剥。

移植自 peach `src/peach/catalog_rules.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）。只保留番号相关的常量、正则与函数，连同每条规则上方的误判证据注释；
不移植标签词表、人脸取景、SQL 片段、图集标题、标题补码与分卷聚类。
`PurePosixPath` 改为 `PurePosixPath`：本项目的路径一律是相对盘根目录的 POSIX 形态。

不碰数据库、不碰 HTTP、不依赖任何别的模块，是最底下那层纯策略。
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache
from pathlib import PurePosixPath


VIDEO_EXTENSIONS = frozenset({
    '.mp4', '.m4v', '.mkv', '.avi', '.wmv', '.mov', '.ts', '.flv', '.rmvb', '.mpg',
    '.m2ts', '.strm', '.iso',
})
AUDIO_EXTENSIONS = frozenset({'.mp3', '.flac', '.wav', '.m4a', '.ogg', '.opus'})
_EXTRA_SUFFIXES = {
    '-behindthescenes': 'behindthescenes', '-deleted': 'deleted', '-deletedscene': 'deleted',
    '-featurette': 'featurette', '-interview': 'interview', '-scene': 'scene',
    '-clip': 'clip', '-short': 'short', '-extra': 'other', '-other': 'other',
    **{separator + kind: kind for kind in ('trailer', 'sample') for separator in ('-', '.', '_', ' ')},
}
_EXTRA_DIRECTORIES = {
    'trailers': 'trailer', 'behind the scenes': 'behindthescenes', 'deleted scenes': 'deleted',
    'interviews': 'interview', 'scenes': 'scene', 'samples': 'sample', 'sample': 'sample',
    'shorts': 'short', 'featurettes': 'featurette', 'clips': 'clip',
    'extras': 'other', 'extra': 'other', 'other': 'other', 'specials': 'other',
    'backdrops': 'themevideo', 'theme-music': 'themeaudio',
}


@lru_cache(maxsize=8192)
def _extra_directory(directory: str, library_roots: tuple[str, ...], audio: bool) -> str | None:
    parent = PurePosixPath(directory)
    roots = [PurePosixPath(root) for root in library_roots if root]
    containing = [root for root in roots if parent.is_relative_to(root)]
    parts = (parent.relative_to(max(containing, key=lambda root: len(root.parts))).parts
             if containing else parent.parts)
    kinds = (_EXTRA_DIRECTORIES.get(part.casefold()) for part in reversed(parts))
    return next((kind for kind in kinds if kind is not None and (kind == 'themeaudio') == audio), None)


def local_extra_type(name: str | None, path: str | None = None, *,
                     library_roots: tuple[str, ...] = ()) -> str | None:
    """显式文件标记或库根以下的附属目录；判定只读名字和路径。"""
    filename = PurePosixPath(name or path or '').name
    suffix = PurePosixPath(filename).suffix.casefold()
    video, audio = suffix in VIDEO_EXTENSIONS, suffix in AUDIO_EXTENSIONS
    if not (video or audio):
        return None
    stem = filename[:-len(suffix)].casefold().rstrip('0123456789')
    if video:
        if stem in ('trailer', 'sample'):
            return stem
        tagged = next((kind for token, kind in _EXTRA_SUFFIXES.items() if stem.endswith(token)), None)
        if tagged:
            return tagged
    if audio and stem == 'theme':
        return 'themeaudio'
    return _extra_directory(str(PurePosixPath(path).parent), tuple(library_roots), audio) if path else None


def is_local_extra(name: str | None, path: str | None = None, *,
                   library_roots: tuple[str, ...] = ()) -> bool:
    """是否为本地预告片、花絮或主题媒体。"""
    return local_extra_type(name, path, library_roots=library_roots) is not None

_CODE_STUDIO = re.compile(r"^[A-Z]{2,8}-\d{2,5}(?:[A-Z]{1,2})?$")
_CODE_AMATEUR = re.compile(r"^\d{3}[A-Z]{2,8}-\d{2,5}(?:[A-Z]{1,2})?$")
#: 素人系无码番号 `MMDDYY-NNN` / `MMDDYY_NNN`。**分隔符是片商标识，属于身份的一部分**：
#: 一本道、パコパコママ、カリビアンコムPR 用 `_`，カリビアンコム 用 `-`，同一天同一序号
#: 是两部不同影片。JavDB 自己也分开保存——搜 `092415-001` 首位返回的是一本道的
#: `092415_001`，`092416-001`、`092015-001` 才是加勒比那几部。
#: 所以归一化只统一大小写，绝不把 `_` 转写成 `-`，查询也不生成另一种分隔符的变体：
#: 用错分隔符搜到的是别的片。
#: 日期式番号的六位是 `MMDDYY`，月日必须成立。
_MMDDYY = r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{2}"
_CODE_DATE = re.compile(rf"^{_MMDDYY}[-_]\d{{2,4}}$")
#: ムゲンエンターテインメント 的无码系列 KIRARI：序号前带一个 `S`，`MKD-S` 是 DVD 版、
#: `MKBD-S` 是 Blu-ray 版。javbus 上 `MKBD-S118`／`MKD-S118`／`MKBD-S89`／`MKD-S89`
#: 四页都认这个写法、都给封面（2026-09-25 实测）。通用的「字母-S数字」不放开：
#: 没有实证的形态放进来，素材编号和文件计数都会被当成番号。
_KIRARI_BODY = r"MKB?D-S\d{2,4}"
_KIRARI_CODE = re.compile(rf"^{_KIRARI_BODY}$", re.I)

#: Tokyo-Hot 的编号没有厂牌字母段：`n1234`／`k1234` 是本编，`red-123` 是 Red Hot 支线。
#: 规范写法取小写，不跟着别的番号大写——javbus 的作品页地址就是 `/n1234`，NeoAVDC
#: （MIT，`src/main/number/parseNumber.ts` 的
#: `TOKYOHOT_NUM_RE`）同样输出小写 `n####`。
_TOKYO_HOT_BODY = re.compile(r"^(?:([nk])(\d{3,5})|red[-_]?(\d{2,4}))$", re.I)
#: Tokyo-Hot 站名。编号本身没有字母段，只靠形态会把 `no0037_01`、`part 18` 一起认走，
#: 所以站名出现时才允许在名字中段搜编号。
_TOKYO_HOT_SITE_TOKEN = r"tokyo[-_. ]?hot"
_TOKYO_HOT_SITE = re.compile(rf"(?i)(?<![a-z0-9]){_TOKYO_HOT_SITE_TOKEN}(?![a-z0-9])")
#: 站名写在编号前面的番号写法（`TOKYO-HOT-N0762`），账本里按目录名落的 `code` 是这个形状。
_TOKYO_HOT_SITE_PREFIX = re.compile(rf"(?i)^{_TOKYO_HOT_SITE_TOKEN}[-_. ]*")
#: 名字开头就是编号的写法（`n1025_rena_yamamoto_ss_n_fhd.wmv`）。本编固定四位，
#: 放宽到三位就会把 `no0037`、`k12` 这类一起收进来。
_TOKYO_HOT_HEAD = re.compile(r"^(?:[nk]\d{4}|red[-_]\d{3})(?![0-9])", re.I)
_TOKYO_HOT_INLINE = re.compile(
    r"(?<![a-z0-9])((?:[nk]\d{3,5}|red[-_]?\d{2,4}))(?![a-z0-9])", re.I)

#: 字母段 → 搜索扩展前缀。这里只生成查询词，不断言两种编号属于同一发行。
#:
#: 这张表按账本里实测出现过的字母段登记，不凭记忆扩展。补前缀会改变发给来源的查询，
#: 猜错就是拿别人的番号去查——这正是 2026-09-02 那批误匹配的成因。新增一行之前先在
#: 账本里确认该字母段只属于这一个发行方（`\d{3}[A-Z]+` 分组后看数字前缀是否唯一）。
MAKER_NUMBER_PREFIX = {
    "ARA": "261", "ENE": "550", "FKOS": "762", "GANA": "200", "GYAN": "278",
    "HHH": "451", "INST": "413", "JAC": "390", "JNT": "390", "KAI": "308",
    "KBI": "336", "LUXU": "259", "MAAN": "300", "MFC": "435", "MIUM": "300",
    "MLA": "476", "NTK": "300", "NTR": "348", "ORETD": "230", "OTIM": "393",
    "SIMM": "345", "SUKE": "428",
}
#: 日期式番号被抹掉分隔符后剩下的纯数字串，片商无从判断。月日与 `_CODE_DATE` 同一把尺。
_DATED_COMPACT = re.compile(rf"^{_MMDDYY}\d{{2,4}}$")
_CODE_MAKER_PREFIXED = re.compile(r"^(\d{3})([A-Z]{2,8})-(\d{2,5})$")
#: 数字前缀单独保留；`h_` 是 DMM content_id 的 label 标记。
_RELEASE_ID = re.compile(r"^(\d{1,4})?([A-Z]{2,8})0*(\d{1,5})([A-Z]{0,2})$")
# 仅登记已核验的写法关系；查询扩展表不是身份等价表。
#
# MGStage 前缀那 9 行 2026-09-25 逐组核过：MGStage 商品页与 r18dev 快照的标题、时长、
# 出演一致，封面同图，avbase 把两家店的条目归为同一作品，账本里每个字母段只挂一个厂牌。
# 同一轮判出的反例 `348NTR`／`451HHH`／`550ENE` 与 DMM 裸编号是不同厂牌的不同作品，不登记。
_RELEASE_PREFIX_ALIASES = {
    ("259", "LUXU"), ("7", "BAZX"), ("49", "HA"),
    ("230", "ORETD"), ("278", "GYAN"), ("336", "KBI"), ("345", "SIMM"), ("413", "INST"),
    ("428", "SUKE"), ("435", "MFC"), ("476", "MLA"), ("762", "FKOS"),
}
_DMM_LABEL_PREFIX = re.compile(r"^H_(?=\d)")
_MEDIA_EXTENSION = re.compile(
    r"\.(?:mp4|mkv|avi|wmv|mov|m4v|webm|ts|m2ts|mts|mpg|mpeg|flv|rm|rmvb|iso|strm)$",
    re.I,
)
_PROMO_DOMAIN = re.compile(
    r"(?:www\.)?[a-z0-9][a-z0-9-]{1,30}\."
    r"(?:com|net|la|xyz|cc|me|top|vip|club|info|org|tv|app|co|pw|gg|cn)",
    re.I,
)
_BRACKETED_PROMO_DOMAIN = re.compile(
    r"[\[【(（]\s*" + _PROMO_DOMAIN.pattern + r"\s*[\]】)）]", re.I,
)
_EDITION_TAIL = re.compile(
    r"(?:[-_.\s]+(?:c|ch|sub|uc|u|uncen(?:sored)?|uncensored|中字|中文字幕|无码|无码破解|破解))+$",
    re.I,
)

#: 转载站与搬运渠道的域名标签（不含 TLD）。
#:
#: 这份名单拦的是一次具体误判，不是识别广告。域名剥掉 `.com` 之后就是「字母+数字」，
#: 和番号同形，于是 `normalise_code_key("HHD800")` 会补出连字符变成 `HHD-800`，
#: 一个水印域名在作品页、在 `JAV_ASSET_PREDICATE`、在 `clean_names` 的重命名提案里
#: 全都成了番号。实例 asset 31048：
#:
#:     B:\番号\_未知厂牌\HHD800\hhd800.com@ABW-132.mp4\ABW-132.mp4
#:
#: 真番号 ABW-132 就在文件名里，`code` 却是 `HHD800`。
#:
#: 形态本身分不开——真番号 `IPX219C`、`MEYD911`、`476MLA-179` 同样是字母紧贴数字，
#: 所以只能靠名单。这里每一条都有本机 ledger 的路径实证（`<label>.<tld>` 或
#: `<label>@` 水印链），`bei88` 是唯一例外：它只以 `bei88@sis001@…` 的搬运链出现，
#: 形态与 `www.98t.la@` 同类，但路径里没有 TLD。新增条目前先用
#: `scripts/audit_domain_codes.py` 在真实 ledger 上取路径证据，并确认它不撞真番号。
REPOST_SITE_LABELS = frozenset({
    "18my", "22sht", "7mmtv", "7sht", "91home", "98t", "aavv333", "bbsxv",
    "bei88", "big2048", "fuckbe", "gc2048", "hhd800", "hjd2048", "huachishe",
    "javday", "javme", "jitumi", "kfa11", "kfa33", "madoubt", "mtfdz",
    "nyap2p", "ses23", "supjav", "thz", "thzu", "u3c3", "yy2048",
})

#: 画质标记落在番号前面，剥掉才露出番号主体（`HD-abp-758` → `abp-758`）。
_QUALITY_HEAD = re.compile(r"^(?:hd|fhd|sd|uhd|4k|2160p?|1080p?|720p?)[-_. ]+", re.I)
#: 版本标记：`-C`/`-CH` 是中文字幕版，`-UC` 是无码流出，画质词也可能落在词尾。
#: token 单独列成一份，字幕 sidecar 配对要剥掉同一批后缀（`subtitles.py`）；各写一份
#: 的话，哪天多认一个版次标记，字幕就配不上那一批文件。
VERSION_TAIL_TOKENS = ("ch", "sub", "uc", "fhd", "4k", "hd", "c", "u")
VERSION_TAIL = re.compile(r"[-_. ]?(?:" + "|".join(VERSION_TAIL_TOKENS) + r")$", re.I)
#: 一本道、加勒比是「日期+序号」体系，没有字母番号主体。分隔符进捕获组，原样带出去。
_DATE_CODE = re.compile(rf"(?<!\d)({_MMDDYY})([-_])(\d{{2,4}})(?!\d)")
#: UUID 首段长得像番号（`DCE7230C-730E-…` 会被拆成 `DCE`+`7230`），按整串形态排除。
_UUID_LIKE = re.compile(
    r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}", re.I)
#: 媒体、串流入口和图片共用番号提取；视频容器沿用展示层的后缀判据。
_ASSET_EXTENSION = re.compile(
    rf"(?:{_MEDIA_EXTENSION.pattern}|\.(?:jpg|jpeg|png|webp|gif|bmp)$)", re.I)
#: 文件名尾部的分卷、画质和重复计数；剥掉才能和目录名对齐。
_FILE_NOISE = re.compile(
    r"(?:[-_. ]?(?:1080p?|720p?|2160p?|4k|fhd|hd|uc|sub|ch|c|u)"
    r"|[-_. ]\d{1,2}|\(\d{1,2}\)|[a-z])+$", re.I)
#: 剥掉 `_FILE_NOISE` 之后的主干还像一个完整番号：有分隔符，或序号至少三位。
_STANDS_ALONE = re.compile(r"[-_ ]|\d{3}")
#: 番号主体：可选的三位素人前缀 + 字母厂牌 + 序号。
_CODE_BODY = re.compile(r"^(?:\d{3})?[A-Za-z]{2,8}[-_. ]?\d{2,5}$")

#: 论坛导出的完整 URL 包装只解开一层，内部沿用文件名与用户规则。
_FORUM_URL_WRAPPER = re.compile(r"^\[url\](.+)\[(?:\||/)url\]$", re.I)
_REMUX_CODE_TAIL = re.compile(r"\(([A-Za-z]{2,8}-\d{2,5})\)\[BD[ ._-]Remux\]$", re.I)
_INLINE_STUDIO_CODE = re.compile(
    rf"(?<![A-Za-z0-9])(?:(?:\d{{3}})?[A-Za-z]{{2,8}}-\d{{2,5}}|{_KIRARI_BODY})(?![A-Za-z0-9])", re.I)

#: DMM 自己交付的文件名：四位发行日（`0112` 是 1 月 12 日）顶在番号前面，编码写在后面。
#: 四位是判据的关键——素人系的前缀恰好三位（`259LUXU-1007`），放宽到「若干位数字」
#: 就会把它的厂牌段吃掉。编码词也逐个列出，不写成「任意后缀」：那等于允许番号后面
#: 跟任何东西，`ABP-123-鈴村あいり` 这种把演员名写在后面的名字会被当成同一形状。
_DMM_DELIVERY = re.compile(
    r"^\d{4}([A-Za-z]{2,8}\d{2,5})[-_](?:h264|h265|hhb|mhb|dmb|dm|hq|sd|hd|mhbw|dmbw)$", re.I)
#: HEYZO 官方文件名把站名写在最前面，番号散在中间：`heyzo_hd_1031_full`。中间那截是
#: 画质档（`hd`／`lt`／`sd`），不是番号的一部分。站名必须出现——只按「下划线里夹一串
#: 数字」认的话，创作者目录里的 `Banbi_20歳の…_1080` 同样满足。
_HEYZO_FILENAME = re.compile(r"(?i)(?<![A-Z0-9])heyzo[-_ ]*(?:hd|lt|sd|fhd)?[-_ ]*(\d{3,5})(?![0-9])")

#: 只说明「这是什么文件」的词，形态与番号主体一模一样，但没有一个是厂牌代号。
#
#: 画质词和转载站标识不重复登记在这里：前者归 `_QUALITY_HEAD`，后者归
#: `REPOST_SITE_LABELS`，三份名单各管一类噪声，`release_code_from_text` 依次过一遍。
#: 新增条目需核对误判证据；创作者昵称也可能撞上这个形态，不逐个加入停用名单。
CODE_BODY_STOPWORDS = frozenset({"IMG", "NO", "PART", "VID", "VIDEO"})
#: 停用词落在名字开头时，后面跟的数字串同样不是番号：`VID_20241015_071039_730.mp4` 里的
#: `071039_730` 月日都成立，光靠日期形状拦不住，只有「这是一段手机录像」能。
#: 后视断言挡住 `NOAH-101`、`VIDEOMAN-12` 这类以停用词起头的真厂牌代号。
#: 排序固定成「长的在前、同长按字母」：`frozenset` 的遍历顺序随进程变，
#: 编出来的正则每次都不一样，比对与排错就没有稳定的东西可看。
_STOPWORD_HEAD = re.compile(
    r"^(?:" + "|".join(sorted(CODE_BODY_STOPWORDS, key=lambda word: (-len(word), word)))
    + r")(?![A-Za-z])", re.I)

#: 西片按「厂牌／系列 + 发行日」命名，没有番号：`DorcelClub.24.12.02.Christy.White.XXX.1080p`、
#: `LIFESELECOTR.20.10.03.Shinaryen.My.Hot.Girlfriend`。年份两位四位都有，月日必须成立。
#:
#: 只在 token 开头认，不在 token 中间搜：账本里的
#: `E078. Redhead.Sucking.Big.Cock.And.Hard.Sex.2019.10.15` 中间搜会得到系列名 `Sex`，
#: 而这一批的真系列写在方括号里。NeoAVDC（MIT，同上）的 `WESTERN_RE` 在 token 内任意
#: 位置匹配且只认两位年份，这里收紧成 token 开头并同时认四位年份。
_WESTERN_DATE = re.compile(
    r"^([A-Za-z][A-Za-z0-9]{1,23})\.(\d{4}|\d{2})\."
    r"(0[1-9]|1[0-2])\.(0[1-9]|[12]\d|3[01])(?![0-9])")
#: 分词只按空白与各类括号切，句点留给日期本身。
_WESTERN_TOKEN_SEP = re.compile(r"[\s_@\[\]【】()（）]+")
#: FC2 商品号。`FC-2052614` 是合集包常见的短写法（`B:\MVP\FC2-Selected collection-2`
#: 下 97 个文件是这种写法），`FC` 与数字之间必须有分隔符：连写的 `FC2052614`
#: 分不清是哪一种，仍按 `FC2` 连写读。
_FC2_ID = re.compile(r"^(?:FC2(?:[-_. ]?PPV)?[-_. ]?|FC[-_])(\d{5,})$", re.I)

#: 能证明「这是一次公开发行」的实体类型。`tag` 不在其中：口味标签谁都能挂，
#: 挂上了不代表这条记录对应某个发行物。
RELEASE_EVIDENCE_KINDS = frozenset({"performer", "studio", "series"})

#: 韩国 MIB 的番号前缀（用户 2026-09-04 指定）。这些是韩国内容，不是 JAV，拿它们去查
#: javbus／javdatabase 这类 JAV 目录站，取回的一定是**别的作品**。
#:
#: 形状上它们和厂牌番号毫无区别，所以 `is_jav_code` 认得它们，`is_jav_asset` 也只要求
#: 「有发行证据」——而那份证据恰恰是刮削自己写进去的，跑一轮就自我坐实了。2026-09-02 实测
#: `B:\MVP\MIB\` 下 68 次匹配有 58 次返回的番号根本不是查询的番号，整目录的厂牌、系列、
#: 标题与厂牌可能因此被误判，不能作为已确认的发行证据。
#: `_identity_mismatch` 只拦得住来源自报了番号的那部分，剩下的照样落进候选队列。
#:
#: 所以判据前移到刮削入口：这些番号一开始就不该被拿去问 JAV 来源。
#:
#: 前缀是 MIB 演员名的缩写，不是厂牌代号——`AR` 是 Ari、`JH` 是 Juhee、`SA` 是 Suah，
#: 一个演员一个前缀，所以表会随片源增加而变长，不要指望它收敛。2026-09-04 实测账本里
#: 两字母前缀番号共 24 种 75 条，其中 21 种全部位于 `B:\MVP\MIB\` 下、目录外零条。
#:
#: **不要退化成「两字母前缀就不是 JAV」这条形状判据。** 同一批实测里的三个例外正是反例：
#: `BF-366` 在 `B:\番号\BeFree\` 下，BeFree 是真实 JAV 厂牌；`TZ-105` 的 `TZ` 来自转载站
#: 水印 `[ThZu.Cc]`，压根不是番号（`is_repost_site_label` 那条路管它）；`FC-437689` 是 FC2
#: 的变体写法。按形状一刀切会把 BeFree 的真作品一起拦掉。
#: 三字母前缀同属这套命名。2026-09-09 复查 `B:\MVP\MIB\` 下 120 条资产，这 15 种
#: 三字母前缀共 40 条，目录外同样零条。
#:
#: 其余前缀取自官网 k-mib.com 的自有作品目录（2026-09-10 快照 368 部，合作厂牌的
#: JS、STRC、SFL 等不在此列）。它们在账本里 MIB 目录外同样零条。
KOREAN_MIB_PREFIXES = frozenset({
    "WX", "AR", "JH", "CA", "IY", "JA", "MY", "SH", "HA", "MH", "DB", "JI",
    "ES", "SR", "SY", "CD", "YH", "UY", "NN", "SA", "JE", "YR",
    "CHU", "ENS", "ERI", "HAL", "HNL", "MIJ", "MIN", "SAR", "SEY", "SIA",
    "SOY", "SRN", "SUY", "SYN", "YUJ",
    "CY", "DK", "JM", "JW", "RA", "RI", "SJ", "UB", "YL",
    "AIN", "GUL", "HRI", "JIE", "KJI", "MGL", "MOI", "MOR", "SEI", "SEO",
    "XIA", "YEL", "YJI", "YNS", "YWN",
    "MOSA", "MOSY", "NOAH", "SJSK",
})
_KOREAN_MIB_CODE = re.compile(r"^([A-Z]{2,4})-\d+$")
#: MIB 文件名常带站名方括号（`[K-MIB]NOAH-101(NOAH)(1)`）或用 `_` 分隔（`YUJ_103 片名`）。
#: `_titled_release_code` 只看第一段、只认 `-`，第一段又是 `K-MIB`，两种都接不住，
#: 所以 MIB 前缀单独开这条路，前缀之外的仍走通用规则。
_KOREAN_MIB_FILENAME = re.compile(
    r"^(?:\[K-?MIB\]\s*)?([A-Za-z]{2,4})[-_](\d{3,4})(?=$|[\s(\[._-])", re.I)
#: 带片名的文件名里，番号是一段连续的半角字母数字，中间只夹 `-`、`_`、`.`。
#: 中日文、空白、括号和 `+` 都是边界：`CAWD-987いいなり`、`GVH-520【中文字幕】`
#: 切出来就是番号本身。
_TITLE_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
_QUALITY_TOKEN = re.compile(r"^(?:hd|fhd|sd|uhd|4k|2160p?|1080p?|720p?)$", re.I)
#: 片名前的番号必须用 `-` 把厂牌和序号隔开。连写（`Nanshu969`、`LOOKS199`）和下划线
#: （`photo_83439`、`@yszl_0107`）在片名里多半是创作者账号或相机编号，不是番号。
#: 序号至少三位：两位的（`ShinoAoi-15`、`miru-10`）是创作者的分集号；后面紧跟月日的
#: （`TG-2025-01-27`）是日期。只取词元开头这一段，紧跟的版次和分卷（`-C`、`-CD1`、
#: `_part1`）不影响番号。
#: 转载站爱把厂牌名写在番号前面（`Catwalk CWPBD-120 Miku Ohashi - …`）。只放行登记过的无码厂牌名：
#: 别的英文词站在番号前面多半是片名（`Morning ABP-123 talk`），peach 的「只看第一段」仍然成立。
_LABEL_HEAD = re.compile(
    r"(?i)^(?:catwalk(?:[ _-]?poison)?|carib(?:bean(?:com)?(?:pr)?)?|1pon(?:do)?|10mu(?:sume)?|heyzo|"
    r"pacopacomama|paco|muramura|tokyo[-_. ]?hot)[ _-]+")
_HYPHENATED_CODE = re.compile(
    rf"^(?:{_KIRARI_BODY}(?![0-9])|(?:\d{{3}})?[A-Z]{{2,8}}-\d{{3,5}}(?![0-9]|-\d{{2}}-\d))",
    re.I,
)
#: 用户番号识别规则的上限。每条规则要对库里每个文件名跑一遍，条数和长度都设个顶。
CODE_PATTERN_LIMIT = 20
CODE_PATTERN_MAX_LENGTH = 200
#: `(?<name>`（不是 `(?<=`、`(?<!` 这两种后视断言）换成 Python 的 `(?P<name>`。
_PCRE_NAMED_GROUP = re.compile(r"\(\?<(?![=!])")
#: 名字中段的 FC2 商品号：`FC2` 前面不能紧贴字母数字，商品号后面不能再接数字。
_FC2_IN_TITLE = re.compile(r"(?i)(?<![A-Z0-9])FC2[-_ ]*(?:PPV[-_ ]*)?(\d{5,8})(?!\d)")

_PART_MARKER = re.compile(
    r"(?:^|[^a-z0-9]|(?<=\d)(?=[a-h]\.|(?:part|pt|cd|disc|disk|dvd|vol)))"
    r"(?:part|pt|cd|disc|disk|dvd|vol|fhd)?[-_ ]?(0|0?[1-9]|[1-9]\d|[a-h])"
    r"(?=\.[a-z0-9]{2,4}$)",
    re.I,
)
_CIRCLED_PART = re.compile(r"[-_ ]([①-⑳])[^.]*\.[a-z0-9]{2,4}$", re.I)


def compact_label(value: str | None) -> str:
    """把一串标识压成「无分隔符、序号不补零」的比较形。

    `BEI88`、`BEI-088`、`bei88` 说的是同一个东西，但 `normalise_code_key` 会把前两个
    都写成 `BEI-088`。不抹掉补零，名单就只拦得住其中一种写法——而界面显示的、
    SQL 谓词里比的、脚本重命名用的恰好是补过零的那一种。
    """
    text = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    shape = re.fullmatch(r"([a-z]+)(\d+)", text)
    return f"{shape.group(1)}{int(shape.group(2))}" if shape else text


def is_repost_site_label(value: str | None) -> bool:
    """True 表示这串字符是转载站／搬运渠道的水印标识，不是番号。

    两条判据：整串就是一个域名（`hhd800.com` 原样落进 `code` 的情况），或者压成
    比较形后命中 `REPOST_SITE_LABELS`（域名被剥掉 TLD、只剩标签的情况）。
    """
    text = str(value or "").strip()
    if not text:
        return False
    if _PROMO_DOMAIN.fullmatch(text):
        return True
    return compact_label(text) in REPOST_SITE_LABELS


def tokyo_hot_code(value: str | None) -> str:
    """Tokyo-Hot 编号的规范写法；不是这一形态返回空串。

    补零到发行方自己的位数（本编四位、Red Hot 三位），大小写一律折成小写。
    形态判据与小写这一点的出处见 `_TOKYO_HOT_BODY`。

    站名写在编号前面的一并认（`TOKYO-HOT-N0762`）：账本里按目录名落的 `code` 就是这个
    写法，站名不剥掉的话它既不成番号形态，也进不了封面缓存键。
    """
    shape = _TOKYO_HOT_BODY.match(_TOKYO_HOT_SITE_PREFIX.sub("", str(value or "").strip()))
    if not shape:
        return ""
    if shape.group(3):
        return f"red-{int(shape.group(3)):03d}"
    return f"{shape.group(1).lower()}{int(shape.group(2)):04d}"


def is_code_body_stopword(value: str | None) -> bool:
    """True 表示这段文字的字母只是文件类型标记，不能当番号主体（见 `CODE_BODY_STOPWORDS`）。"""
    return re.sub(r"[^A-Za-z]", "", str(value or "")).upper() in CODE_BODY_STOPWORDS


def western_release_identity(value: str | None) -> str:
    """西片的「厂牌／系列 + 发行日」身份；不是这一形态返回空串。

    返回 `DORCELCLUB.2024-12-02` 这样的写法。它不是番号，也不会和番号撞上——番号里
    没有句点，也没有四位年份。两位年份按 70 分界展开（`69` → 2069，`70` → 1970）：
    这个语料里的西片全是 2010 年之后的，分界点取在哪都不影响现有条目，写死一个是为了
    同一个文件名永远给出同一个身份。

    同一场景在不同发布组手里会写成 `Vixen.26.05.07` 和 `Vixen.2026.05.07`，收敛成一个
    身份才能判重；这也是它进 `release_identity` 的理由。
    """
    stem = _ASSET_EXTENSION.sub("", str(value or "").strip())
    for token in _WESTERN_TOKEN_SEP.split(stem):
        shape = _WESTERN_DATE.match(token)
        if not shape:
            continue
        series, year, month, day = shape.groups()
        if len(year) == 2:
            year = f"20{year}" if int(year) < 70 else f"19{year}"
        return f"{series.upper()}.{year}-{month}-{day}"
    return ""


def normalise_code_key(code: str | None) -> str:
    """Normalize a release code into the stable cover-cache key.

    日期式番号（`_CODE_DATE`）例外：分隔符是片商标识，归一化原样保留，
    `092415_001` 与 `092415-001` 各算一个键、各存一张封面。
    Tokyo-Hot 同样例外，它的规范写法是小写（见 `_TOKYO_HOT_BODY`）。
    """
    raw = (code or "").upper().strip()
    tokyo = tokyo_hot_code(raw)
    if tokyo:
        return tokyo
    if _CODE_DATE.match(raw):
        return raw
    value = raw.replace("_", "-").replace(" ", "-").strip()
    if not value:
        return ""
    if is_repost_site_label(value):
        # 水印域名原样返回：给它补出连字符就等于凭空造了一个番号，
        # 而作品页显示的 `display_code` 正是这个返回值。
        return value
    if value.startswith("FC2"):
        digits = re.search(r"(\d{5,})", value)
        return f"FC2-PPV-{digits.group(1)}" if digits else value
    short_fc2 = _FC2_ID.match(value)
    if short_fc2:
        return f"FC2-PPV-{short_fc2.group(1)}"
    shape = re.fullmatch(r"(\d{3})?([A-Z]+)-?(\d+)([A-Z]{0,2})", value)
    if not shape:
        return value
    return f"{shape.group(1) or ''}{shape.group(2)}-{int(shape.group(3)):03d}{shape.group(4)}"


def is_jav_code(code: str | None) -> bool:
    """Recognize only code shapes whose original value keeps its separator.

    停用词在这里也要拦。提取器不再产出 `VIDEO-2022` 这样的值，但账本里存着 58 条
    （2026-09-12 只读盘点：`VIDEO-2022` 34 条、`VIDEO-2025` 3 条、`IMG-nnnn` 21 条），
    而 `JAV_ASSET_PREDICATE` 是通过 SQLite 自定义函数直接调本函数判的。
    """
    value = (code or "").upper().strip()
    if not value or is_repost_site_label(value) or is_code_body_stopword(value):
        return False
    if value.startswith(("MKBD-", "MKD-")):
        return bool(_KIRARI_CODE.fullmatch(value))
    if value.startswith("FC2"):
        return bool(re.search(r"\d{5,}", value))
    return bool(
        _CODE_STUDIO.match(value)
        or _CODE_AMATEUR.match(value)
        or _CODE_DATE.match(value)
        or _KIRARI_CODE.match(value)
        or tokyo_hot_code(value)
    )


def is_korean_mib_code(code: str | None) -> bool:
    """True 表示这个番号属于韩国 MIB，不适用 JAV 规则。

    只认 `<字母>-<数字>` 这一种写法下的前缀。素人系的三位数字前缀（`300MIUM-1239`）
    和 FC2 都不在此列：它们的字母段虽然可能撞上，但发行体系本来就不是 MIB。
    """
    value = normalise_code_key(code)
    shape = _KOREAN_MIB_CODE.match(value)
    return bool(shape and shape.group(1) in KOREAN_MIB_PREFIXES)


def code_query_variants(code: str | None) -> tuple[str, ...]:
    """按可用程度排序的查询写法，第一个永远是账本的规范写法。

    同一发行方在账本里两种写法都有——`259LUXU-1004` 和 `LUXU-688`、`336KBI-010`
    和 `KBI-019`，共 6 个字母段 13 个裸写法。来源站点通常只索引一种，拿另一种查会
    落空。所以先查规范写法，落空再换另一种写法。

    去前缀仅生成搜索词；补前缀只对 `MAKER_NUMBER_PREFIX` 登记过的字母段做。
    消费者必须按原始编号另行核验返回作品，不能用扩展查询词代替发行身份。

    日期式番号只回它自己：换一种分隔符搜到的是别的片商的另一部片，不是同一发行的
    另一种写法（见 `_CODE_DATE`）。
    """
    primary = normalise_code_key(code)
    if not primary:
        return ()
    if primary.startswith("FC2"):
        return (primary,)
    prefixed = _CODE_MAKER_PREFIXED.fullmatch(primary)
    if prefixed:
        return (primary, f"{prefixed.group(2)}-{prefixed.group(3)}")
    bare = _CODE_STUDIO.match(primary)
    if bare:
        letters = primary.split("-", 1)[0]
        prefix = MAKER_NUMBER_PREFIX.get(letters)
        if prefix:
            return (primary, f"{prefix}{primary}")
    return (primary,)


def release_identity(code: str | None) -> str:
    """把番号或来源返回的 id 收敛成可比对的作品身份。

    数字前缀保留作品身份，只有登记过的等价写法和显式 DMM h_ 标记可归一。
    搜索变体不证明发行相同：390JAC-040 配信与 JAC-040 DVD 合集分别保留。

    认不出形态的值原样返回，只和自己相等：`20211103_JENNIFERMENDEZ` 这种关键词
    搜索结果不该和任何番号算成同一部。
    """
    raw = _DMM_LABEL_PREFIX.sub("", str(code or "").upper().strip())
    tokyo = tokyo_hot_code(raw)
    if tokyo:
        return tokyo
    if _CODE_DATE.match(raw):
        # 日期式番号带着分隔符进身份：抹掉它就等于断言一本道的 `092415_001` 和
        # 加勒比的 `092415-001` 是同一部（见 `_CODE_DATE`）。
        return raw
    western = western_release_identity(raw)
    if western:
        # 西片不走番号体系，但同一场景的两种年份写法要收敛成一个身份。
        return western
    value = re.sub(r"[\s._\-]+", "", raw)
    if not value:
        return ""
    if value.startswith("FC2"):
        # 分隔符已经抹掉，取数字要从 `FC2` 之后开始：否则 `FC2-1812235` 会被读成
        # 一段 `21812235`，和 `FC2-PPV-1812235` 算成两部不同的作品。
        digits = re.search(r"(\d{5,})", value[3:])
        return f"FC2-{int(digits.group(1))}" if digits else value
    if _DATED_COMPACT.fullmatch(value):
        # 来源只给一串数字时分隔符无从得知，原样留着数字，别替它挑一个片商。
        # 与带分隔符那一侧的比对交给 `same_release_code`。
        return value
    shape = _RELEASE_ID.fullmatch(value)
    if shape:
        prefix, letters, number, suffix = shape.groups()
        prefix = prefix or ""
        # HA 的这一组重制写法已有来源等价证据，其余尾字母均保留。
        if (prefix, letters, suffix) == ("49", "HA", "R"):
            suffix = ""
        if (prefix, letters) in _RELEASE_PREFIX_ALIASES or str(code or "").upper().strip().startswith("H_"):
            prefix = ""
        return f"{prefix}{letters}-{int(number)}{suffix}"
    return value


def same_release_code(left: str | None, right: str | None) -> bool:
    """两个写法是否指同一部作品。空值不算相等——没有证据不是证据。"""
    first, second = release_identity(left), release_identity(right)
    if not first or not second:
        return False
    if first == second:
        return True
    # 日期式番号的紧凑写法（`040221001`）没带分隔符，认不出片商，两种分隔符都算命中：
    # 缺一个字符不构成「这是另一部片」的证据，拒掉只会把对的元数据一起丢了。
    compact = next((value for value in (first, second)
                    if _DATED_COMPACT.fullmatch(value)), "")
    if compact:
        dated = first if second == compact else second
        if (_CODE_DATE.match(dated)
                and re.sub(r"[-_]", "", dated) == compact):
            return True
    # FC2 的来源 id 是裸数字（`FC2-PPV-1812235` → `1812235`）。裸数字自己不是番号
    # 形态，所以这条不放进 `release_identity`：只有另一侧确实是 FC2 才按数字比。
    fc2 = next((value for value in (first, second) if value.startswith("FC2-")), "")
    other = first if second == fc2 else second
    return bool(fc2) and other.isdigit() and fc2 == f"FC2-{int(other)}"


def is_amateur_code(code: str | None) -> bool:
    """三位数字前缀的素人系番号：`259LUXU-1475`、`300MIUM-1239`。

    这类番号由 MGS 发行，不进 DMM 数字版目录，也查不到 r18.dev 与 Prestige
    官方 API。判定只看形状：一旦改成「先拿到元数据再判断」，没有元数据的番号
    就永远轮不到该问的那个来源。
    """
    return bool(_CODE_AMATEUR.match((code or "").upper().strip()))


def code_letter_stem(code: str | None) -> str:
    """番号的字母段，用来和 DMM `content_id` 对照：`ABW-232` -> `abw`。"""
    value = normalise_code_key(code)
    if not value or value.startswith("FC2"):
        return ""
    return re.sub(r"[^A-Z]", "", value.split("-", 1)[0]).lower()


#: 日本的产地码。取值集合与标签在 `regions.py`，这里只认这一个：本函数要回答的是
#: 「是不是日本发行物」，而 `regions` 反过来要用本模块的番号判据，写成 import 就成环。
JAPAN_REGION = "jp"


def is_jav_asset(code: str | None, studio: str | None = None,
                 release_date: str | None = None,
                 entity_kinds: tuple[str, ...] | list[str] = (),
                 region: str | None = None) -> bool:
    """Require release evidence in addition to a code-shaped string.

    Creator clips such as ``JI-103`` can look exactly like a studio code. They
    stay in ordinary browsing until a studio, performer, series, or release
    date ties them to a published JAV release. FC2 IDs are an explicit release
    system and do not need those projections.

    `region` 是已经判定的产地，判过且不是日本就一概不是 JAV——韩国 MIB 与国产厂牌的
    番号和日本番号同形，发行证据那几条它们全都满足，只有产地分得开。未判定（空串）
    维持原有口径：这一列绝大多数行还是空的，拿「没判过」当「不是日本」会把整个 JAV
    页清空。
    """
    if str(region or "").strip() not in ("", JAPAN_REGION):
        return False
    # 历史 ledger 里有 PBD390、IPVR00296 这类缺连字符但带片商／出演者证据的真发行物。
    # 裸 `RAIKUN325` 仍不能单凭形态升级；只有规范化后像番号且同时有发行证据才接受。
    normalized = normalise_code_key(code)
    if not is_jav_code(code) and not is_jav_code(normalized):
        return False
    value = normalized.upper().strip()
    if value.startswith("FC2"):
        return True
    return bool(
        str(studio or "").strip()
        or str(release_date or "").strip()
        or RELEASE_EVIDENCE_KINDS.intersection(entity_kinds)
    )


#: 发行体系自己的写法，形态本身就是发行证据：FC2 商品号（`FC-437689` 这种变体先经
#: `normalise_code_key` 归成 `FC2-PPV-…`）、
#: 素人平台的三位数字前缀（`300MIUM-698`）、MGStage 素人系（`STP-26232`、`SIRO-3508`）、
#: 日期式番号（`071213-625`）。创作者的文件名撞不出这几种形状，所以它们一概放行。
_RELEASE_SYSTEM_SHAPE = re.compile(r"^(FC2|\d{3}[A-Z]+-|ST[PN]-|SIRO-|\d{6}[-_])")


def scrapes_as_jav(code: str | None, studio: str | None = None,
                   creator: str | None = None, release_date: str | None = None,
                   entity_kinds: tuple[str, ...] | list[str] = (),
                   region: str | None = None) -> bool:
    """这个番号该不该拿去问 JAV 来源。

    和 `is_jav_asset` 的分工：那个判「这条记录算不算一部 JAV 发行物」，要求发行证据
    已经落在账本里，用来决定浏览时归到哪一类。刮削入口不能用它——那份证据本来就是
    刮回来的，没刮过就没证据，拿它当门会把每一部还没刮过的新片一起关在外面。

    这里只拦一种：**创作者作品的文件名被读成了番号**。`sumwall95 masturbation_1.mp4`
    出 `SUMWALL-095`、`aerith 2412a.mp4` 出 `AERITH-2412`（角色名加年月），形态上和厂牌
    番号毫无区别。判据是「归在某个创作者名下、没有厂牌也没有其他发行证据、写法又不属于
    任何发行体系」。2026-09-22 只读盘点：账本 2851 部有番号的资产里这样的 126 部，
    105 部是 `oscarkim123` 的 cosplay、19 部是 `sunwall` 的剪辑，每轮采集都拿去问一遍
    javdb；同一盘点里被放行的真番号零误伤。
    """
    if str(region or "").strip() not in ("", JAPAN_REGION):
        return False
    if not str(creator or "").strip():
        return True
    if (str(studio or "").strip() or str(release_date or "").strip()
            or RELEASE_EVIDENCE_KINDS.intersection(entity_kinds)):
        return True
    return bool(_RELEASE_SYSTEM_SHAPE.match(normalise_code_key(code).upper()))


def release_code_from_product(value: str | None) -> str | None:
    """明确的商品番号保留尾字母；文件名中的字幕、画质标记仍由文本解析器处理。"""
    raw = _ASSET_EXTENSION.sub("", str(value or "").strip())
    if re.fullmatch(r"(?:\d{3})?[A-Za-z]{2,8}[-_]?\d{2,5}[A-Za-z]{1,2}", raw):
        code = normalise_code_key(raw)
        return code if is_jav_code(code) else None
    return release_code_from_text(raw)


def release_code_from_text(value: str | None) -> str | None:
    """从一段文字（目录名或文件名主干）里解析出规范番号；解析不出返回 None。

    和 `normalise_code_key` 的分工：那个只归一化「已经确认是番号」的字符串，这个负责
    判断一段文字里到底有没有番号。归一化仍然交给它，不在这里重写一遍——番号既是身份
    判定也是封面缓存键，两份实现漂移会让同一部片解析出两个键。

    `HHD800` 这类转载站标签一律返回 None：它形态上完全符合「字母+数字」，只有名单能
    把它和 `MEYD911` 分开。

    噪声分三层，顺序固定：先按名单认出整串就是水印的情况，再摘掉头尾的推广域名
    （`www.98t.la@ABW-358-U`、`[xxx.cc]ABC-123`、`ABP-762-fuckbe.com`），最后剥画质
    前缀与版次后缀。域名这一层交给 `strip_promo_markers`，番号提取和目录判重共用它，
    否则同一个 `[98t.tv][98t.tv]` 会在两处各剥一半。

    西片是「厂牌／系列 + 发行日」，不产出番号：它没有番号可给，而剥掉尾部噪声后日期会
    散架，从剩下的半截里一定能抠出一个不存在的番号来。
    """
    text = str(value or "").strip()
    if not text or _UUID_LIKE.search(text):
        return None
    text = _ASSET_EXTENSION.sub("", text)
    if is_repost_site_label(text) or western_release_identity(text):
        return None
    text = strip_promo_markers(text)
    fc2 = _FC2_ID.match(text)
    if fc2:
        return normalise_code_key(f"FC2-PPV-{fc2.group(1)}")
    tokyo = _tokyo_hot_from_text(text)
    if tokyo:
        return tokyo
    if _STOPWORD_HEAD.match(text):
        return None
    date = _DATE_CODE.search(text)
    if date:
        return f"{date.group(1)}{date.group(2)}{date.group(3)}"
    body = VERSION_TAIL.sub("", _QUALITY_HEAD.sub("", text))
    canonical = normalise_code_key(body)
    if not (_CODE_BODY.fullmatch(body) or _KIRARI_CODE.fullmatch(canonical)) or is_code_body_stopword(body):
        return None
    return canonical if is_jav_code(canonical) else None


def _tokyo_hot_from_text(text: str) -> str:
    """Tokyo-Hot 编号只在两个位置上认：名字开头，或站名已经写在名字里。"""
    head = _TOKYO_HOT_HEAD.match(text)
    if head:
        return tokyo_hot_code(head.group(0))
    if _TOKYO_HOT_SITE.search(text):
        inline = _TOKYO_HOT_INLINE.search(text)
        if inline:
            return tokyo_hot_code(inline.group(1))
    return ""


def compile_code_patterns(raw) -> tuple[re.Pattern, ...]:
    """把用户写的番号识别规则编译成正则；写错的规则抛 `ValueError`，消息给用户看。

    每条规则是一个对完整文件名做搜索的正则。番号取命名组 `code`，没有就取第一个
    括号，再没有就取整段匹配。`(?<code>…)` 是多数在线正则工具的写法，Python 写作
    `(?P<code>…)`，两种都收。
    """
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError("番号识别规则要写成一组正则表达式")
    rules = [str(rule).strip() for rule in raw if str(rule or "").strip()]
    if len(rules) > CODE_PATTERN_LIMIT:
        raise ValueError(f"番号识别规则最多 {CODE_PATTERN_LIMIT} 条")
    compiled = []
    for index, rule in enumerate(rules, 1):
        if len(rule) > CODE_PATTERN_MAX_LENGTH:
            raise ValueError(f"第 {index} 条规则超过 {CODE_PATTERN_MAX_LENGTH} 个字符")
        try:
            compiled.append(re.compile(_PCRE_NAMED_GROUP.sub("(?P<", rule), re.I))
        except re.error as error:
            raise ValueError(f"第 {index} 条规则不是有效的正则表达式：{error}") from None
    return tuple(compiled)


def _code_from_patterns(name: str, patterns: Iterable[re.Pattern]) -> str | None:
    """按用户规则取番号；取出来的那段仍要是番号的样子，否则交给下一条规则。"""
    for pattern in patterns:
        match = pattern.search(name)
        if not match:
            continue
        captured = (match.group("code") if "code" in pattern.groupindex
                    else match.group(1) if pattern.groups else match.group(0))
        code = release_code_from_text(captured)
        if code:
            return code
    return None


def release_code_from_filename(name: str | None, *, patterns: Iterable[re.Pattern] = ()) -> str | None:
    r"""文件名带分卷、画质和重复计数，剥掉噪声后再解析。

    `patterns` 是用户在设置里写的番号识别规则（`compile_code_patterns`），先于内置
    规则试。

    剥完噪声剩下的主干要自己站得住：带分隔符，或序号至少三位。论坛合集包
    `[mtfdz.club]WX17.3` 摘掉域名、再把 `.3` 当分卷剥掉，只剩 `WX17`，补零才凑成
    `WX-017`；真番号的分卷（`abp762-1`、`ABW-358-2`）剥完仍是完整番号。
    """
    patterns = tuple(patterns)
    custom = _code_from_patterns(str(name or "").strip(), patterns)
    if custom:
        return custom
    stem = _ASSET_EXTENSION.sub("", str(name or "").strip())
    wrapper = _FORUM_URL_WRAPPER.fullmatch(stem)
    if wrapper:
        name = wrapper.group(1)
        custom = _code_from_patterns(name, patterns)
        if custom:
            return custom
        stem = _ASSET_EXTENSION.sub("", name)
    if western_release_identity(stem):
        return None
    cleaned = strip_promo_markers(stem)
    remux = _REMUX_CODE_TAIL.search(cleaned)
    if remux:
        codes = {normalise_code_key(code) for code in _INLINE_STUDIO_CODE.findall(cleaned)}
        candidate = normalise_code_key(remux.group(1))
        return candidate if codes == {candidate} and is_jav_code(candidate) else None
    partless = _ASSET_EXTENSION.sub("", _PART_MARKER.sub("", str(name or "").strip()))
    stripped = _FILE_NOISE.sub("", strip_promo_markers(partless))
    # 明确卷标摘掉后先核对番号主体，两位序号也属于完整番号。
    code = release_code_from_text(stem) or (
        release_code_from_text(partless) if _STANDS_ALONE.search(partless) else None) or (
        release_code_from_text(stripped) if _STANDS_ALONE.search(stripped) else None)
    if code:
        return code
    delivery = _DMM_DELIVERY.match(stem)
    if delivery:
        return normalise_code_key(delivery.group(1))
    heyzo = _HEYZO_FILENAME.search(stem)
    if heyzo:
        return normalise_code_key(f"HEYZO-{heyzo.group(1)}")
    mib = _KOREAN_MIB_FILENAME.match(stem)
    if mib and mib.group(1).upper() in KOREAN_MIB_PREFIXES:
        return normalise_code_key(f"{mib.group(1)}-{mib.group(2)}")
    return _titled_release_code(stem)


def _titled_release_code(stem: str) -> str | None:
    """「番号 + 片名」：番号是名字里第一段半角字母数字，后面跟片名、女优或说明。

    `FC2` 商品号自带站名，写在名字哪里都认。其余番号只看第一段：再往后就是片名，
    片名里的 `Rena n1042 clip`、`Part 18` 不是番号。中日文（`【中文字幕】`、女优名）
    不成段，画质词跳过去接着看。
    """
    fc2 = _FC2_IN_TITLE.search(stem)
    if fc2:
        return normalise_code_key(f"FC2-PPV-{fc2.group(1)}")
    for token in _TITLE_TOKEN.findall(_LABEL_HEAD.sub("", strip_promo_markers(stem).strip())):
        if _QUALITY_TOKEN.match(token):
            continue
        head = _HYPHENATED_CODE.match(token)
        return release_code_from_text(head.group(0)) if head else None
    return None


def _jav_code_pattern(code: str | None) -> str:
    """Return one regex fragment matching compact and separated forms of a canonical code."""
    canonical = normalise_code_key(code)
    if _KIRARI_CODE.fullmatch(canonical):
        letters, serial = canonical.split('-', 1)
        return rf"{re.escape(letters)}[-_ ]{re.escape(serial)}"
    fc2 = re.fullmatch(r"FC2-PPV-(\d+)", canonical)
    if fc2:
        return rf"FC2(?:[-_ ]?PPV)?[-_ ]*0*{re.escape(fc2.group(1))}"
    amateur = re.fullmatch(r"(\d{3})?([A-Z]+)-(\d+)([A-Z]{0,2})", canonical)
    if amateur:
        prefix, letters, digits, suffix = amateur.groups()
        return (
            rf"{re.escape(prefix or '')}{re.escape(letters)}"
            rf"[-_ ]*0*{re.escape(str(int(digits)))}{re.escape(suffix)}"
        )
    tokyo = _TOKYO_HOT_BODY.fullmatch(canonical)
    if tokyo:
        # 文件名里补零位数会漂移（`n646`／`n0646`），两种都放行。
        if tokyo.group(3):
            return rf"red[-_ ]*0*{int(tokyo.group(3))}"
        return rf"{tokyo.group(1)}0*{int(tokyo.group(2))}"
    dated = re.fullmatch(r"(\d{6})[-_](\d{2,4})", canonical)
    if dated:
        # 匹配文件名时两种分隔符都放行：身份认分隔符，野生文件名的写法却会漂移
        # （账本里同一部一本道既有 `1pon-092415-001-fhd1`，也有 `1pondo-092415_001-FHD`）。
        return rf"{re.escape(dated.group(1))}[-_ ]*{re.escape(dated.group(2))}"
    return ""


#: 无码片商自己的编号法：Caribbeancom／1Pondo／10musume／Pacopacomama 走日期式
#: （形状与分隔符含义见 `_CODE_DATE`，同一份实现），HEYZO 用 `HEYZO-1380`，
#: Tokyo-Hot 用 `n1234`（见 `_TOKYO_HOT_BODY`），KIRARI 用 `MKBD-S`／`MKD-S`。
UNCENSORED_CODE_SHAPES = (
    _CODE_DATE,
    _KIRARI_CODE,
    re.compile(r"^HEYZO-\d{2,5}$", re.I),
    _TOKYO_HOT_BODY,
)
#: 文件名里的发行站标记。番号形状认不出来时，这是另一条本机就能核验的证据。
_UNCENSORED_SITE = re.compile(
    r"(?i)(?<![A-Z0-9])(?:"
    r"carib(?:bean(?:com)?(?:pr)?)?|1pon(?:do)?|10mu(?:sume)?|heyzo|"
    r"pacopacomama|paco|muramura|catwalk(?:[ _-]?poison)?|" + _TOKYO_HOT_SITE_TOKEN +
    r")(?![A-Z0-9])"
)
#: 版次标记有时和番号粘在一起，中间没有分隔符：`PPPD-937CH.mp4`、`MIDV-751CH.mp4`。
#: 只认带分隔符的写法，这些文件既拿不到「中字」徽章，番号本身还会被当标题显示。
_GLUED_EDITION = r"(?:CH|C|SUB|UC|U)"


def is_uncensored_code(code: str | None) -> bool:
    value = str(code or "").strip()
    return any(shape.fullmatch(value) for shape in UNCENSORED_CODE_SHAPES)


def code_release_date(code: str | None) -> str | None:
    """日期式番号自己写着发行日：`092415_001` 是 2015-09-24。别的形状返回 None。

    这几家片商按发行日编号，番号比任何转录站都可靠：javdb 给 `092415_001` 的是
    2016-06-16，那是转售商的上架日。
    """
    value = str(code or "").strip()
    if not _CODE_DATE.fullmatch(value):
        return None
    return f"20{value[4:6]}-{value[0:2]}-{value[2:4]}"


def is_uncensored_release(name: str | None, code: str | None) -> bool:
    """番号形状或文件名里的发行站，两者有一个成立就是无码片商的片。

    这两条都是本机可核验的证据，不依赖抓取结果——`040221-001` 这类番号在
    r18.dev 永远 404，等元数据到齐再判，徽章就永远不会出现。
    """
    return is_uncensored_code(code) or bool(_UNCENSORED_SITE.search(str(name or "")))


def jav_edition_badges(name: str | None, code: str | None,
                       tags: tuple[str, ...] | list[str] = ()) -> list[str]:
    """Project filename/tag evidence into compact edition badges beside the code."""
    text = _MEDIA_EXTENSION.sub("", str(name or ""))
    tag_set = {str(tag).strip().casefold() for tag in tags if str(tag).strip()}
    code_pattern = _jav_code_pattern(code)
    after_code = (
        re.search(
            rf"(?:^|[^A-Z0-9]){code_pattern}((?:{_GLUED_EDITION})?(?:[^A-Z0-9].*)?)$",
            text, re.I,
        )
        if code_pattern else None
    )
    suffix = after_code.group(1) if after_code and after_code.group(1) else ""
    cracked = (
        bool(re.search(r"无码\s*破解|無碼\s*破解|AI\s*去码|"
                       r"(?:^|[-_.\s\[])破解(?:$|[-_.\s\]])", text, re.I))
        or "ai去码" in tag_set or "无码破解" in tag_set
    )
    uncensored = (
        cracked
        or "无码" in tag_set
        # 无码片商的片本身就是无码，不需要文件名里另有 `-U`／`Uncen` 标记。
        or is_uncensored_release(name, code)
        # `un` 和 `u`／`uc` 是同一个意思。此前它没进这张表，`ABF-158-UN.mp4`
        # 既拿不到徽章，`UN` 又被当标题显示；现在标题判空了，不认它就等于把
        # 这条信息整个丢掉。
        or bool(re.search(r"(?:^|[-_.\s\[])"
                          r"(?:uc|un|u|uncen(?:sored)?|uncensored|无码|無碼)"
                          r"(?:$|[-_.\s\]])", suffix, re.I))
    )
    subtitled = (
        bool({"中文字幕", "内嵌字幕", "外挂字幕", "中字"}.intersection(tag_set))
        or bool(re.search(r"(?:^|[-_.\s\[])(?:c|ch|sub|中字|中文字幕)"
                          r"(?:$|[-_.\s\]])", suffix, re.I))
    )
    badges = []
    if subtitled:
        badges.append("中字")
    if cracked:
        badges.append("无码破解")
    elif uncensored:
        badges.append("无码")
    return badges


#: 头尾的裸域名不允许标签里带连字符：`ABP-762-fuckbe.com` 整串都符合「标签+.com」，
#: 按通用形态删前缀会把番号一起吃掉，只剩 `mp4`。带方括号那种由括号定界，不受此限。
_BARE_PROMO = r"(?:www\.)?[a-z0-9]{2,31}\.(?:com|net|la|xyz|cc|me|top|vip|club|info|org|tv|app|co|pw|gg|cn)"
_PROMO_PREFIX = re.compile(
    r"^(?:[\[【(（]\s*(?:" + _PROMO_DOMAIN.pattern + r")\s*[\]】)）]|(?:"
    + _BARE_PROMO + r"))[-_@.\s]*", re.I)
_PROMO_SUFFIX = re.compile(
    r"[-_@.\s]*(?:[\[【(（]\s*(?:" + _PROMO_DOMAIN.pattern + r")\s*[\]】)）]|(?:"
    + _BARE_PROMO + r"))$", re.I)


def strip_promo_markers(name: str | None) -> str:
    """摘掉名字**头尾**的推广域名标记，其余部分一个字都不动。

    只认头尾，不认名字中间。删任意位置的带括号域名会把
    `Hazel Moore - [FootFetishDaily.com] - Hardcore` 里的厂牌一起删掉——欧美片的
    `[Vixen.com]`、`[StraplessDildo.com]` 是厂牌名，不是广告，删掉是丢真信息。
    真正的广告标记全在头或尾：`[44x.me]tre-080`、`MattieDoll - pornhub.com`。

    同样刻意不做的事：不压缩多余空格、不合并空括号。做了的话，
    `(12P+5V_1.28G) [12P-5V-1.28GB]` 会变成 `(12P+5V_1.28G12P-5V-1.28GB]`，
    没有广告的 `狗链  兔尾` 也跟着被改。

    头尾各剥到不动为止，`[98t.tv][98t.tv]ABW-251` 这种叠了两层的才能剥干净。
    """
    original = str(name or "")
    text = original
    while True:
        stripped = _PROMO_SUFFIX.sub("", _PROMO_PREFIX.sub("", text, count=1), count=1)
        if stripped == text:
            break
        text = stripped
    if text == original:
        # 没摘掉任何广告就原样返回：末尾那次 strip 会把 `@9ririsuamano` 这种
        # 本来就带前缀符号的账号名改掉，而它不是广告。
        return original
    return text.strip(" ._-—@")


def promo_free_key(name: str | None) -> str:
    r"""摘广告后再抹掉大小写与分隔符，用来判断两个目录名是不是同一个名字。

    实测的冗余层是 `TRE-080\[44x.me]tre-080`：大小写不同、还挂着广告前缀，
    直接比字符串会漏掉。分隔符也一起抹掉，`TRE080` 与 `TRE-080` 才算同名。
    """
    return re.sub(r"[\s._\-—]+", "", strip_promo_markers(name)).casefold()


#: 无码片的文件名基本由「发行站 + 番号 + 画质/分卷」拼成，一个真标题词都没有：
#: `040221-001-carib-1080p.mp4`、`071213-625-1pon-whole1_hd.avi`、
#: `heyzo_hd_1380_full.mp4`。剥掉番号剩下的是发行残渣，不是标题——界面上却当
#: 标题显示成「040221-001 carib-1080p」。这些站名和画质标记是有限集合，日文
#: 标题里不会出现，可以按词剥。
_RELEASE_NOISE = re.compile(
    r"(?i)(?<![A-Z0-9])(?:"
    r"carib(?:bean(?:com)?(?:pr)?)?|1pon(?:do)?|10mu(?:sume)?|heyzo|"
    r"pacopacomama|paco|muramura|" + _TOKYO_HOT_SITE_TOKEN + r"|xxx[-_]?av|"
    r"\d{3,4}p|[0-9]?[fu]?hd\d*|sd|4k|2k|whole\d*|part\d*|full|lt|ch\d*"
    r")(?![A-Z0-9])"
)
#: 剥完之后判断剩下的还算不算标题：既没有中日文，也没有一个长度 ≥4 的字母词，
#: 那就是番号数字和零碎标记，不是名字。`Minah My new companion…` 留得住，
#: `1pon-092415-001-fhd2 (new)` 剥到只剩 `new` 就该判空。
_TITLE_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_TITLE_WORD = re.compile(r"[A-Za-z]{4,}")


def _is_release_residue(text: str) -> bool:
    return not (_TITLE_CJK.search(text) or _TITLE_WORD.search(text))


def jav_fallback_title(name: str | None, code: str | None) -> str:
    """Clean a filename-derived JAV title without changing the stored filename."""
    text = _MEDIA_EXTENSION.sub("", str(name or "").strip())
    text = _BRACKETED_PROMO_DOMAIN.sub(" ", text)
    text = _PROMO_DOMAIN.sub(" ", text)
    code_pattern = _jav_code_pattern(code)
    if code_pattern:
        repeated = re.compile(
            rf"^[\s._\-—]*(?:{code_pattern})(?:[-_.]?{_GLUED_EDITION})?(?=$|[\s._\-—\[])", re.I)
        while repeated.search(text):
            text = repeated.sub("", text, count=1)
        # 番号不总在开头：`1pon-092415-001-fhd1_(new).mp4` 把发行站放在了前面。
        # 只认前缀，整个番号就会留在「标题」里显示出来。
        text = re.sub(rf"(?<![A-Z0-9])(?:{code_pattern})(?:[-_.]?{_GLUED_EDITION})?(?![A-Z0-9])",
                      " ", text, flags=re.I)
    text = _EDITION_TAIL.sub("", text)
    text = _RELEASE_NOISE.sub(" ", text)
    text = re.sub(r"[\[\]【】()（）]+", " ", text)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_—")
    return "" if _is_release_residue(text) else text


def jav_display_metadata(name: str | None, code: str | None,
                         tags: tuple[str, ...] | list[str] = ()) -> dict[str, object]:
    """Safe display projection; raw name/code remain untouched for file operations."""
    return {
        "display_code": normalise_code_key(code),
        "display_title": jav_fallback_title(name, code),
        "edition_badges": jav_edition_badges(name, code, tags),
    }


def part_marker(name: str) -> str:
    """Return a trailing multipart marker, if present."""
    match = _PART_MARKER.search(name or "")
    if match:
        return match.group(1).lower()
    circled = _CIRCLED_PART.search(name or "")
    return str(ord(circled.group(1)) - ord("①") + 1) if circled else ""
