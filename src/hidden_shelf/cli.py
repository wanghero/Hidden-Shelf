"""命令行：`shelf run|scan|import-local|scrape|organize|media|build <盘根目录>`，`shelf config [盘根目录]`。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, pipeline
from .config import ShelfConfig
from .paths import ShelfPaths

COMMANDS = {
    "run": ("全流程：扫描 → 导入本地资料 → 联网刮削 → 归位 → 媒体 → 出站", pipeline.STEPS),
    "scan": ("只扫描登记", ("scan",)),
    "import-local": ("只导入本地 NFO、封面与 overrides.json", ("import",)),
    "scrape": ("只联网刮削（资料、封面、头像）", ("scrape",)),
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
        sub.add_argument("--offline", action="store_true", help="本次跳过联网刮削")
        sub.add_argument("--force-scrape", action="store_true", help="忽略 7 天与「资料已齐」，全部重问")
        sub.add_argument("--sources", help="本次只问这几家，逗号分隔，如 r18dev,javdb")
        sub.add_argument("--routes", help="整条覆盖来源链，如 \"censored=r18dev,javdb;fc2=fc2\"")
        sub.add_argument("--verbose", "-v", action="store_true", help="打印更多日志")
    config_cmd = subparsers.add_parser("config", help="打印全局配置位置、代理模式、各站 Cookie 有无与冷却状态（不打印 Cookie 值）")
    config_cmd.add_argument("root", nargs="?", help="盘根目录（给出时一并打印该盘的来源冷却状态）")
    return parser


def _print_config(root: str | None) -> int:
    from .netconfig import GlobalConfig, config_path
    from .scrape.access import SOURCES, Cooldown

    config = GlobalConfig.load()
    summary = config.describe()
    print(f"全局配置：{config_path()}")
    print(f"网络：{summary['network']['mode']}" + ("（已保存代理地址）" if summary["network"]["proxy_saved"] else ""))
    print("来源：")
    for name, spec in SOURCES.items():
        item = summary["sources"].get(name, {"enabled": True, "cookie": False})
        state = "启用" if item["enabled"] else "停用"
        cookie = ("，Cookie：有" if item["cookie"] else "，Cookie：无") if spec.get("cookie") else ""
        print(f"  {name:<11}{spec['label']:<12}{state}{cookie}")
    if summary["routes"]:
        print("来源链覆盖：" + json.dumps(summary["routes"], ensure_ascii=False))
    if root:
        target = Path(root).expanduser()
        if not target.is_dir():
            print(f"盘根目录不存在或不是目录：{target}", file=sys.stderr)
            return 2
        cooling = Cooldown(ShelfPaths(target.resolve()).sources / "_cooldown.json").describe()
        if cooling:
            print("冷却中：" + "；".join(f"{name} 还剩 {state['remaining']} 秒（撞了 {state['blocks']} 次）"
                                     for name, state in cooling.items()))
        else:
            print("冷却中：无")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    if args.command == "config":
        return _print_config(args.root)
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
    try:
        options = _scrape_options(args)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    progress = pipeline.ConsoleProgress(verbose=args.verbose)
    _help, steps = COMMANDS[args.command]
    result = pipeline.run(root, config=config, steps=steps, progress=progress, scrape_options=options)
    if not result.ok:
        print(f"失败于 {pipeline.STEP_LABELS.get(result.failed_step, result.failed_step)}：{result.error}", file=sys.stderr)
        if result.log_path:
            print(f"日志：{result.log_path}", file=sys.stderr)
        return 1
    if result.index_html:
        print(f"成品：{result.index_html}")
    return 0


def _scrape_options(args) -> pipeline.ScrapeOptions:
    from .scrape.routes import parse_route_overrides
    from .scrape.sources import SITE_SOURCES

    only = None
    if args.sources:
        only = tuple(dict.fromkeys(part.strip() for part in str(args.sources).split(",") if part.strip()))
        unknown = [name for name in only if name not in SITE_SOURCES]
        if unknown:
            raise ValueError(f"未知来源：{'、'.join(unknown)}（可用：{'、'.join(SITE_SOURCES)}）")
    routes = {kind: list(chain) for kind, chain in parse_route_overrides(args.routes).items()} if args.routes else None
    return pipeline.ScrapeOptions(offline=args.offline, force=args.force_scrape, only_sources=only, routes=routes)


if __name__ == "__main__":
    sys.exit(main())
