"""本盘设置 `HiddenShelf/config.json`：未识别开关、归位模板、自定义番号规则、站点语言。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields

from .paths import ShelfPaths
from .rules.codes import compile_code_patterns


@dataclass
class ShelfConfig:
    #: 认不出番号的视频是否集中搬到 `未识别/`（保留原目录层级）。
    move_unrecognized: bool = True
    #: 归位目录模板（相对盘根）。厂牌缺失时落 `unknown_studio_dir/{code}`。
    dir_template: str = "{studio}/{code}"
    #: 归位文件名模板（不含扩展名）。
    file_template: str = "{code}[-cd{cd}]"
    unknown_studio_dir: str = "_未知厂牌"
    #: 用户自定义番号识别正则，先于内置规则试。
    code_patterns: list[str] = field(default_factory=list)
    #: 站点默认语言：`zh` | `en`。
    language: str = "zh"
    #: 是否联网刮削（计划 2）。关掉就只走本地流水线。
    scrape: bool = True
    #: 把封面与九宫格复制一份到视频所在目录（`<番号>-cover.jpg`、`<主名>-sheet.jpg`；计划 9）。默认不放。
    images_in_work_dir: bool = False

    @classmethod
    def load(cls, paths: ShelfPaths) -> "ShelfConfig":
        """读配置，没有副作用：文件不存在只回默认值（默认文件由 `ShelfPaths.ensure()` 写出，那时老盘的
        `.shelf/` 已经迁移完，不会在这里抢先建出 `HiddenShelf/`）。坏 JSON 用默认值但不覆盖文件。"""
        if not paths.config.is_file():
            return cls()
        try:
            raw = json.loads(paths.config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        config = cls()
        for item in fields(cls):
            if item.name not in raw:
                continue
            value = raw[item.name]
            if item.type in ("bool", bool):
                setattr(config, item.name, bool(value))
            elif item.type in ("str", str):
                setattr(config, item.name, str(value))
            elif item.name == "code_patterns":
                if isinstance(value, list):
                    config.code_patterns = [str(rule) for rule in value if str(rule or "").strip()]
        return config

    def save(self, paths: ShelfPaths) -> None:
        paths.shelf.mkdir(parents=True, exist_ok=True)
        paths.config.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")

    def compiled_patterns(self) -> tuple[re.Pattern, ...]:
        """编译好的自定义番号规则；写错的规则抛 `ValueError`。"""
        return compile_code_patterns(self.code_patterns)
