"""归位用的路径模板：占位符取值、可选分组、文件名清洗与逃逸防护。

移植自 peach `src/peach/organize_templates.py`（commit 4d5266d327a5971773409b44316e3926bd37c6ba，
AGPL-3.0-or-later）。改动：`ntpath` → `posixpath`（库里路径是 POSIX 形态），但仍清洗
Windows 非法字符与保留名——盘可能插到 Windows 上；去掉 `mosaic` 占位符与界面示例；
`render` 只返回字符串，缺失的必填占位符另由 `missing_fields` 给出。

模板只有三种记号：字面量、`{占位符}`、`[可选分组]`。分组里的占位符只要有一个取不到值，
整段就不出现——`{code}[ {title}][ CD{cd}]` 在没有标题时给 `ABC-123`，而不是
`ABC-123  CD2` 这种带着两个空格的名字。

清洗与逃逸防护分两层，缺一层都会出事：

* **取值这一层**清除符号噪声，并将 Windows 保留字符（标题里的 `:` 与 `?`、演员名之间的 `/`）
  逐个替换，同时挡住 `CON`、`PRN` 这类保留名与结尾的点和空格。
* **模板本身这一层**才可能带来路径逃逸：`../..`、`C:\\`、`/etc`。取值那层的清洗挡不住它——
  那些字符是用户自己写在模板里的字面量。所以模板在保存和使用前都要过 `validate_template`。
"""
from __future__ import annotations

import posixpath
import re
import unicodedata
from dataclasses import dataclass

#: 模板认识的占位符，以及它的说明。
PLACEHOLDERS: dict[str, str] = {
    "code": "番号",
    "title": "标题",
    "studio": "厂牌",
    "series": "系列",
    "year": "发行年",
    "actors": "出演者",
    "cd": "分片号",
    "definition": "画质",
}

#: 单个路径组件的长度上限。Windows 的组件上限是 255 个字符，但长名字在资源管理器、
#: 压缩包和网盘客户端里到处挨截断，所以留一大截余量；超出的从中间截断而不是末尾——
#: 末尾往往是分片号和画质这些用来区分的部分。
MAX_COMPONENT = 120
#: 整条目标路径的长度上限。Windows 的 `MAX_PATH` 是 260；长路径要注册表开关配合，
#: 所以按最保守的那一档拦。
MAX_PATH = 240

#: Windows 不收的字符。POSIX 只禁 `/` 和 NUL，但盘可能插到 Windows 上，所以按 Windows
#: 这一套清洗，两个平台上结果一致。
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
#: 保留设备名。带扩展名也算：`CON.mp4` 在 Windows 上同样建不出来。
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL",
                       *(f"COM{n}" for n in range(1, 10)),
                       *(f"LPT{n}" for n in range(1, 10))})
_DRIVE = re.compile(r"^[A-Za-z]:")


class TemplateError(ValueError):
    """模板本身不合法。消息直接给用户看，所以写成一句中文。"""


@dataclass(frozen=True)
class _Token:
    kind: str          # "text" | "field" | "group"
    text: str = ""
    parts: tuple = ()


def clean_name_symbols(value: str) -> str:
    """清除装饰符号、替代字形与不可见噪声，保留文字、标点、单位及算术符号。"""
    parts: list[str] = []
    for char in value:
        category = unicodedata.category(char)
        point = ord(char)
        if category.startswith('C') or char in '\ufe0e\ufe0f\u20e3':
            continue
        if (category in {'So', 'Sm'} and point > 127 and char not in '×÷±−＋＝～°℃℉'
                and not 0x3300 <= point <= 0x33FF):
            parts.append(' ')
        elif category == 'Sk' and 0x1F3FB <= point <= 0x1F3FF:
            continue
        elif char in '※⁂⁎⁑⁕†‡＼﹨／':
            parts.append(' ')
        else:
            parts.append(char)
    text = ''.join(parts)
    return re.sub(r'\s+', ' ', text).strip() if text != value else value


def clean_filename(name: str) -> str:
    """只清理名称主干；扩展名和可辨认的名称保留，空名称不生成改名计划。"""
    stem, suffix = posixpath.splitext(name)
    cleaned = clean_name_symbols(stem)
    if cleaned != stem:
        cleaned = re.sub(r' +(?=\.[A-Za-z0-9]{2,4}(?:\.|$))', '', cleaned)
    cleaned = cleaned.rstrip('. ')
    if not any(char.isalnum() for char in cleaned):
        return name
    if cleaned.split('.', 1)[0].upper() in _RESERVED:
        cleaned = '_' + cleaned
    return cleaned + suffix


def sanitise_component(value: str) -> str:
    """把一个取值收敛成能当路径组件的样子。

    替换成 `_` 而不是删掉：`ABC-123：完整版` 删掉冒号会变成 `ABC-123完整版`，看不出
    该处有过分隔；`_` 一眼能看出这个位置上有个不能进文件名的符号。
    """
    text = _ILLEGAL.sub("_", clean_name_symbols(str(value or ""))).strip()
    # 结尾的点和空格在 Windows 上会被静默吃掉，于是「建出来的名字」和「要求的名字」
    # 不一致，下一轮整理又会认为这一行还没做完。
    text = text.rstrip(". ")
    if not text:
        return ""
    stem = text.split(".", 1)[0].upper()
    if stem in _RESERVED:
        text = "_" + text
    if len(text) > MAX_COMPONENT:
        head = MAX_COMPONENT - 21
        text = text[:head] + "…" + text[-20:]
    return text


def _parse(template: str) -> tuple[_Token, ...]:
    """把模板切成记号。`{{`、`}}`、`[[`、`]]` 是对应符号的字面量写法。"""
    tokens: list[_Token] = []
    buffer: list[str] = []
    stack: list[list[_Token]] = []
    target = tokens

    def flush() -> None:
        if buffer:
            target.append(_Token("text", "".join(buffer)))
            buffer.clear()

    index = 0
    while index < len(template):
        char = template[index]
        pair = template[index:index + 2]
        if pair in {"{{", "}}", "[[", "]]"}:
            buffer.append(char)
            index += 2
            continue
        if char == "{":
            end = template.find("}", index)
            if end < 0:
                raise TemplateError("占位符的 `{` 没有配对的 `}`")
            name = template[index + 1:end].strip()
            # peach 的旧模板用 `number` 指番号。
            if name == "number":
                name = "code"
            if name not in PLACEHOLDERS:
                raise TemplateError(
                    f"不认识的占位符 `{{{name}}}`；可用的是 "
                    + "、".join(f"{{{key}}}" for key in PLACEHOLDERS))
            flush()
            target.append(_Token("field", name))
            index = end + 1
            continue
        if char == "[":
            flush()
            stack.append(target)
            target = []
            index += 1
            continue
        if char == "]":
            if not stack:
                raise TemplateError("可选分组的 `]` 没有配对的 `[`")
            flush()
            group = _Token("group", parts=tuple(target))
            target = stack.pop()
            target.append(group)
            index += 1
            continue
        buffer.append(char)
        index += 1
    if stack:
        raise TemplateError("可选分组的 `[` 没有配对的 `]`")
    flush()
    return tuple(tokens)


def _render_tokens(tokens: tuple[_Token, ...], values: dict[str, str]) -> tuple[str, bool]:
    """返回渲染结果，以及这一段里的占位符是不是都有值。"""
    out: list[str] = []
    filled = True
    for token in tokens:
        if token.kind == "text":
            out.append(token.text)
        elif token.kind == "field":
            value = sanitise_component(values.get(token.text, ""))
            if not value:
                filled = False
            out.append(value)
        else:
            text, group_filled = _render_tokens(token.parts, values)
            # 分组里有占位符没取到值就整段省略。方括号本身永远不出现在结果里；
            # 要一对字面的方括号写 `[[` 和 `]]`。一个占位符都没有的分组等于一段
            # 普通字面量，照常输出，而不是一段永远不出现的字。
            if group_filled or not _fields_in(token.parts):
                out.append(text)
    return "".join(out), filled


def _fields_in(tokens: tuple[_Token, ...]) -> bool:
    return any(token.kind == "field" or (token.kind == "group" and _fields_in(token.parts))
               for token in tokens)


def template_fields(template: str) -> frozenset[str]:
    """模板用到的占位符名字。"""
    def walk(tokens: tuple[_Token, ...]) -> set[str]:
        found: set[str] = set()
        for token in tokens:
            if token.kind == "field":
                found.add(token.text)
            elif token.kind == "group":
                found |= walk(token.parts)
        return found
    return frozenset(walk(_parse(template)))


def required_fields(template: str) -> frozenset[str]:
    """不在可选分组里的占位符：取不到值这一行就没法归位，只能跳过。"""
    def walk(tokens: tuple[_Token, ...]) -> set[str]:
        return {token.text for token in tokens if token.kind == "field"}
    return frozenset(walk(_parse(template)))


def validate_template(template: str, *, directory: bool = False) -> str:
    """校验并返回规范化的模板；不合法抛 `TemplateError`。

    目录模板可以带 `/` 或 `\\` 分层，文件名模板不行——文件名里的分隔符意味着模板在
    悄悄多建一层目录，而用户以为自己只是在给文件取名。
    """
    text = str(template or "").strip()
    if not text:
        return ""
    if len(text) > 300:
        raise TemplateError("模板太长")
    _parse(text)  # 记号配对与占位符名字先过一遍
    if _DRIVE.match(text):
        raise TemplateError("模板不能带盘符；它只描述盘根目录下面的相对位置")
    normalised = text.replace("\\", "/")
    if normalised.startswith("/"):
        raise TemplateError("模板不能以分隔符开头；它只描述盘根目录下面的相对位置")
    if not directory and "/" in normalised:
        raise TemplateError("文件名模板不能带目录分隔符；分层写在目录模板里")
    for component in normalised.split("/"):
        stripped = component.strip()
        if stripped in {".", ".."}:
            raise TemplateError("模板不能包含 `.` 或 `..`")
        if directory and not stripped and normalised.strip("/") != "":
            raise TemplateError("目录模板里有空的一层")
    return normalised.strip("/") if directory else normalised


def missing_fields(template: str, values: dict[str, str]) -> frozenset[str]:
    """模板里取不到值的必填占位符。"""
    normalised = validate_template(template, directory=True)
    if not normalised:
        return frozenset()
    return frozenset(name for name in required_fields(normalised)
                     if not sanitise_component(values.get(name, "")))


def render(template: str, values: dict[str, str], *, directory: bool = False) -> str:
    """渲染模板，返回已清洗、已截断的路径片段（目录模板用 `/` 分层）。

    必填占位符缺值时结果里就少那一段；调用方用 `missing_fields` 判断要不要跳过这一行。
    """
    normalised = validate_template(template, directory=directory)
    if not normalised:
        return ""
    text, _filled = _render_tokens(_parse(normalised), values)
    components = [sanitise_component(part) for part in text.split("/")] if directory \
        else [sanitise_component(text)]
    return "/".join(part for part in components if part)
