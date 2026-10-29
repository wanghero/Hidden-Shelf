"""出演者栏的写法：剪出艺名，认出描述性称呼与企划名义，拆开「现名（旧名）」。

移植自 peach `src/peach/metadata_alias_resolve.py`（`is_descriptive`、`stage_name`、`is_planning_alias`）与
`src/peach/metadata.py`（`split_former_name`、`normalized_performers`），commit
4d5266d327a5971773409b44316e3926bd37c6ba，AGPL-3.0-or-later。改动：peach 把企划名义交人工复核队列，本项目没有
复核队列——剪得出艺名的用艺名、剪不出的整条丢掉，两种都记 warning；`canonicalize_entity_name` 换成
`entities.clean_person_name`，去重键用 `db.normalize_name`。

素人系与企划系的官方页把年龄、职业甚至整句宣传语写进出演者栏（`本庄美奈子 30歳 元カフェ店員`、
`超バドミントン部あかりちゃん 23歳 潮吹き部長`）。照抄会把整句变成实体名，所以要先剪；剪完仍认不出边界的
那些是**企划名义**——这部片给她起的称呼，不是这个人的主艺名。
"""
from __future__ import annotations

import re

from ..db import normalize_name
from ..entities import clean_person_name

#: 艺名到年龄标记为止，后面是介绍；`はな/19歳/…` 用斜杠分段，同理。
_PERFORMER_INTRO = re.compile(r"[\s　]*[（(]?\d+\s*歳.*$")
_PERFORMER_SEPARATOR = re.compile(r"[/／]")
#: 斜杠分段里单独成段的年龄。MGS 的 `300NTK` 把介绍写在最前：`…オフパコ！！/はな/20歳`，艺名是年龄前面那一段。
_AGE_SEGMENT = re.compile(r"\s*\d+\s*歳\s*")
#: 剪完仍带空白、分隔符或敬称的不是艺名，是企划文案（`超バドミントン部あかりちゃん`、`まゆみさん`）。
_NOT_A_STAGE_NAME = re.compile(r"[\s　/／]|ちゃん$|さん$")
#: 描述性称呼：身高、人数、外貌、身份与宣传语，不是谁的艺名。`OL` 区分大小写，免得撞上 `Ssol`、`Cola酱`。
_DESCRIPTIVE = re.compile(
    r"\d+\s*(?:cm|CM|㎝|センチ|名|人)|[!！]"
    r"|身長|長身|スレンダー|爆乳|巨乳|美乳|美脚|美尻|色白|パイパン|くびれ|クビレ"
    r"|女子|下級生|上級生|女優|グラドル|現役|看板娘|先生|少女|お嬢様|嬢$|美女|美人|ギャル|OL"
    r"|人妻|熟女|素人|店員|主婦|新人|の様な|のような|みたいな|働く|平凡|人気|伝説|抜群"
    r"|きれいな|綺麗な|可愛い|かわいい"
    r"|[A-Za-zＡ-Ｚ]カップ|変態|従事者|事務所|活躍|後輩|先輩|地元|大生|声優|究極|顔の|メンヘラ"
    r"|天真爛漫|^超美$|^牛逼$")
#: DMM 系来源把改过名的女优写成「现名（旧名）」：r18dev 给的是 `美谷朱音（美谷朱里）`。
_CURRENT_AND_FORMER = re.compile(r"(.+?)\s*[（(]([^（()）、，,/]+)[）)]")
_FORMER_PREFIX = re.compile(r"^\s*[旧元]\s*[・·]?\s*")
_JAPANESE = re.compile(r"[぀-ヿ一-鿿々]")


def is_descriptive(name: str) -> bool:
    """这个写法是描述性称呼，不是艺名。"""
    return bool(_DESCRIPTIVE.search(str(name or "")))


def stage_name(name: str) -> str | None:
    """出演者栏里的艺名；认不出艺名边界、或剪出来的是描述性称呼时返回 None。"""
    segments = _PERFORMER_SEPARATOR.split(str(name or ""))
    ages = [index for index, part in enumerate(segments) if _AGE_SEGMENT.fullmatch(part)]
    named = segments[ages[0] - 1] if ages and ages[0] > 0 else segments[0]
    trimmed = _PERFORMER_INTRO.sub("", named).strip()
    if not trimmed or _NOT_A_STAGE_NAME.search(trimmed) or is_descriptive(trimmed):
        return None
    return trimmed


def is_planning_alias(name: str) -> bool:
    """这个写法是不是企划名义——这部片给她起的称呼，不是这个人的主艺名。

    两种形态。一种是把年龄职业写在名字后面（`桜井奈々 28歳 某企業広報担当`）；另一种是剪完仍认不出艺名边界的
    （`佐倉井さん`、`超バドミントン部あかりちゃん`）。判的是写法不是人。
    """
    return bool(_PERFORMER_INTRO.search(name)) or stage_name(name) is None


def split_former_name(name: str) -> tuple[str, str]:
    """(现名, 旧名)；不是这种写法时旧名为空串，现名就是原文。

    两边都得像日文艺名才拆：`Mana(23)` 括号里是年龄，`みく（素人）` 括号里是描述，整串照原样收。
    """
    matched = _CURRENT_AND_FORMER.fullmatch(str(name or "").strip())
    if matched is None:
        return name, ""
    current, former = matched.group(1).strip(), _FORMER_PREFIX.sub("", matched.group(2)).strip()
    for part in (current, former):
        if (len(part) < 2 or not _JAPANESE.search(part) or re.search(r"\d", part)
                or is_descriptive(part) or is_planning_alias(part)):
            return name, ""
    return current, former


def _settle_name(original: str, warnings: list[str]) -> str:
    """一个出演者栏的写法 → 落库的艺名；描述性称呼与剪不出艺名的企划名义回空串并记 warning。

    拉丁字母名（`Remu Suzumori`、`JULIA`）不经企划名义那套判据：`_NOT_A_STAGE_NAME` 会把带空格的罗马字名当文案。
    """
    cleaned = clean_person_name(original)
    if not cleaned:
        return ""
    if cleaned != " ".join(str(original).split()):
        warnings.append(f"来源演员名含重复片段，已规范化：{original} → {cleaned}")
    if _JAPANESE.search(cleaned) and is_planning_alias(cleaned):
        # 先剪再判：`本庄美奈子 30歳 元カフェ店員` 整串看是描述（`店員`），剪出的 `本庄美奈子` 不是。
        trimmed = stage_name(cleaned)
        if trimmed is None:
            what = "描述性称呼" if is_descriptive(cleaned) else "企划名义，认不出艺名"
            warnings.append(f"来源演员名是{what}，已跳过：{original}")
            return ""
        warnings.append(f"来源演员名含介绍，已剪成艺名：{original} → {trimmed}")
        return trimmed
    if is_descriptive(cleaned):
        warnings.append(f"来源演员名是描述性称呼，已跳过：{original}")
        return ""
    return cleaned


def normalized_performers(raw: object) -> tuple[list[dict], list[str]]:
    """来源记录的 `actresses` → 每人 `{name, external_id, thumb_url, aliases?, former_names?, profile_source?}` 与 warnings。

    同名（按 `normalize_name`）只留第一个；别名收旧名、来源给的 `aliases`、假名与罗马字，去掉与本名或彼此重复的。
    """
    performers: list[dict] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, (list, tuple)) else []:
        if isinstance(item, str):
            item = {"japanese_name": item}
        if not isinstance(item, dict):
            continue
        parts = [str(part).strip() for part in (item.get("last_name"), item.get("first_name")) if part]
        # 姓名分两格的写法：日文名直接相连（`三宮つばき`），罗马字名之间留空格。
        joiner = "" if all(_JAPANESE.search(part) for part in parts) else " "
        preferred = item.get("japanese_name") or joiner.join(parts)
        original = str(preferred or "").strip()
        current, former = split_former_name(original)
        name = _settle_name(current, warnings)
        key = normalize_name(name)
        if not name or key in seen:
            continue
        seen.add(key)
        aliases: list[str] = []
        for alias in (former, *(item.get("aliases") if isinstance(item.get("aliases"), list) else []),
                      item.get("name_kana"), item.get("name_romaji")):
            cleaned = clean_person_name(alias)
            if (cleaned and normalize_name(cleaned) != key
                    and normalize_name(cleaned) not in {normalize_name(value) for value in aliases}):
                aliases.append(cleaned)
        performer = {
            "name": name,
            # `dmm_id` 是 r18/DMM 那一路的写法；别的来源给的是同一件东西的通用写法，两个键在这里合成一个字段。
            "external_id": str(item.get("dmm_id") or item.get("external_id") or ""),
            "thumb_url": str(item.get("thumb_url") or ""),
        }
        if aliases:
            performer["aliases"] = aliases
        if former:
            # 现名在库里还没登记、旧名已经登记过时，落库挂到旧名那一位身上。
            performer["former_names"] = [clean_person_name(former)]
        if item.get("profile_source"):
            performer["profile_source"] = str(item["profile_source"])
        performers.append(performer)
    return performers, warnings
