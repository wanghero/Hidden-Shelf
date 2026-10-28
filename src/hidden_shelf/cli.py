"""命令行：`shelf run|scan|import-local|organize|media|build <盘根目录>`。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, pipeline
from .config import ShelfConfig
from .paths import ShelfPaths

COMMANDS = {
    "run": ("全流程：扫描 → 导入本地资料 → 归位 → 媒体 → 出站", pipeline.STEPS),
    "scan": ("只扫描登记", ("scan",)),
    "import-local": ("只导入本地 NFO、封面与 overrides.json", ("import",)),
    "organize": ("只归位（之后自动再扫描一次）", ("organize",)),
    "media": ("只做探测、九宫格与封面海报", ("media",)),
    "build": ("只出静态站", ("build",)),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shelf", description="Hidden Shelf（藏片阁）：本地番号片整理器")
    parser.add_argument("--version", action="version", version=f"shelf {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="命令")
    for name, (help_text, _steps) in COMMANDS.items():
        sub = subparsers.add_parser(name, help=help_text, description=help_text)
        sub.add_argument("root", help="盘根目录")
        sub.add_argument("--no-move-unrecognized", action="store_true", help="本次不把认不出番号的视频搬到 未识别/")
        sub.add_argument("--dir-template", help="本次使用的目录模板，如 {studio}/{code}")
        sub.add_argument("--file-template", help="本次使用的文件名模板，如 {code}[-cd{cd}]")
        sub.add_argument("--language", choices=("zh", "en"), help="站点默认语言")
        sub.add_argument("--verbose", "-v", action="store_true", help="打印更多日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"盘根目录不存在或不是目录：{root}", file=sys.stderr)
        return 2
    root = root.resolve()
    paths = ShelfPaths(root)
    config = ShelfConfig.load(paths)
    if args.no_move_unrecognized:
        config.move_unrecognized = False
    if args.dir_template is not None:
        config.dir_template = args.dir_template
    if args.file_template is not None:
        config.file_template = args.file_template
    if args.language:
        config.language = args.language
    progress = pipeline.ConsoleProgress(verbose=args.verbose)
    _help, steps = COMMANDS[args.command]
    result = pipeline.run(root, config=config, steps=steps, progress=progress)
    if not result.ok:
        print(f"失败于 {pipeline.STEP_LABELS.get(result.failed_step, result.failed_step)}：{result.error}", file=sys.stderr)
        if result.log_path:
            print(f"日志：{result.log_path}", file=sys.stderr)
        return 1
    if result.index_html:
        print(f"成品：{result.index_html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
