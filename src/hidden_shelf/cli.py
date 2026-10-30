"""命令行：`shelf run|scan|import-local|scrape|organize|media|build <盘根目录>`，`shelf config [盘根目录]`。"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

from . import __version__, pipeline
from .config import ShelfConfig
from .paths import (SHELF_DIR, RootNotWritable, ShelfLayoutConflict, ShelfPaths, check_layout, check_writable,
                    migrate_legacy_dir)

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
        sub.add_argument("--dry-run", action="store_true",
                         help=f"只预演：列出要搬的文件与原因，不动盘上任何文件（仍会写 {SHELF_DIR}/）")
        sub.add_argument("--force-scrape", action="store_true", help="忽略 7 天与「资料已齐」，全部重问")
        sub.add_argument("--sources", help="本次只问这几家，逗号分隔，如 r18dev,javdb")
        sub.add_argument("--routes", help="整条覆盖来源链，如 \"censored=r18dev,javdb;fc2=fc2\"")
        sub.add_argument("--verbose", "-v", action="store_true", help="打印更多日志")
    config_cmd = subparsers.add_parser("config", help="打印全局配置位置、代理模式、各站 Cookie 有无与冷却状态（不打印 Cookie 值）")
    config_cmd.add_argument("root", nargs="?", help="盘根目录（给出时一并打印该盘的来源冷却状态）")
    login_cmd = subparsers.add_parser("login", help="弹出浏览器登录来源站（javdb、javbus），把 Cookie 存进全局配置")
    login_cmd.add_argument("source", help="来源名：javdb 或 javbus")
    serve_cmd = subparsers.add_parser("serve", help="起进度网页（只监听 127.0.0.1，默认端口 8031）并打开浏览器")
    serve_cmd.add_argument("--port", type=int, help="指定端口；被占就报错退出，不自动换口")
    serve_cmd.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    serve_cmd.add_argument("--verbose", "-v", action="store_true", help="打印 uvicorn 的访问日志")
    return parser


def _serve(args) -> int:
    import webbrowser

    import uvicorn

    from .serve.app import create_app
    from .serve.ports import DEFAULT_PORT, HOST, PortInUse, pick_port
    from .serve.runner import RunManager

    try:
        port = pick_port(args.port)
    except PortInUse as error:
        print(str(error), file=sys.stderr)
        return 2
    url = f"http://{HOST}:{port}/"
    if args.port is None and port != DEFAULT_PORT:
        print(f"默认端口 {DEFAULT_PORT} 被占，改用 {port}")
    print(f"进度网页：{url}")
    print("按 Ctrl+C 停止")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - 没有桌面环境时打不开浏览器不算错
            pass
    uvicorn.run(create_app(RunManager()), host=HOST, port=port, log_level="info" if args.verbose else "warning")
    return 0


def _print_config(root: str | None) -> int:
    from .netconfig import GlobalConfig, config_path
    from .scrape.access import FINGERPRINT_SOURCES, SOURCES, Cooldown, fingerprint_available

    config = GlobalConfig.load()
    summary = config.describe()
    print(f"全局配置：{config_path()}")
    print(f"网络：{summary['network']['mode']}" + ("（已保存代理地址）" if summary["network"]["proxy_saved"] else ""))
    print("来源：")
    for name, spec in SOURCES.items():
        item = summary["sources"].get(name, {"enabled": True, "cookie": False})
        state = "启用" if item["enabled"] else "停用"
        cookie = ("，Cookie：有" if item["cookie"] else "，Cookie：无") if spec.get("cookie") else ""
        if name in FINGERPRINT_SOURCES:
            cookie += "，浏览器指纹：" + ("已装 curl_cffi" if fingerprint_available() else "未装 curl_cffi（uv sync --extra fingerprint）")
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


def _wait_for_enter(finish) -> None:
    """后台线程：用户在终端按回车也算「完成」。"""
    def read():
        try:
            sys.stdin.readline()
        except (OSError, ValueError):
            return
        finish.set()
    threading.Thread(target=read, daemon=True).start()


def _login(source: str) -> int:
    import threading as _threading

    from .netconfig import GlobalConfig, config_path
    from .scrape import login as login_module

    hint = login_module.availability()
    if hint:
        print(hint, file=sys.stderr)
        return 2
    config = GlobalConfig.load()
    finish = _threading.Event()
    _wait_for_enter(finish)
    try:
        result = login_module.capture_login(source, config=config, finish=finish,
                                            notify=lambda text: print(text.replace("点「完成」", "按回车")),
                                            launch=login_module.launch_browser)
    except login_module.LoginError as error:
        print(str(error), file=sys.stderr)
        return 2
    config.save()
    print(f"已保存 {result.cookies} 个 Cookie" + ("，浏览器 UA 已记录" if result.user_agent else "") + f"：{config_path()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    if args.command == "config":
        return _print_config(args.root)
    if args.command == "login":
        return _login(args.source)
    if args.command == "serve":
        return _serve(args)
    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"盘根目录不存在或不是目录：{root}", file=sys.stderr)
        return 2
    root = root.resolve()
    try:
        check_writable(root)
        check_layout(root)
        # 老盘迁移必须在读配置之前：读配置本身不建目录，但后面任何一步都可能建 HiddenShelf/。
        if migrate_legacy_dir(root):
            print(pipeline.MIGRATED_NOTE)
    except (RootNotWritable, ShelfLayoutConflict) as error:
        print(str(error), file=sys.stderr)
        return 2
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
    try:
        result = pipeline.run(root, config=config, steps=steps, progress=progress, scrape_options=options,
                              dry_run=args.dry_run)
    except (RootNotWritable, ShelfLayoutConflict) as error:
        # 前置检查之后、开跑之前盘变了（有人复制了目录、盘被改成只读）：说人话，不甩 traceback。
        print(str(error), file=sys.stderr)
        return 2
    if not result.ok:
        print(f"失败于 {pipeline.STEP_LABELS.get(result.failed_step, result.failed_step)}：{result.error}", file=sys.stderr)
        if result.log_path:
            print(f"日志：{result.log_path}", file=sys.stderr)
        return 1
    if result.dry_run:
        preview = result.steps.get("organize") or {}
        if preview.get("dry_run"):
            print(f"预演完成：{preview['move']} 个要搬，{preview['unchanged']} 个已就位，{preview['skip']} 个跳过；"
                  f"没有动任何文件，清单：{paths.shelf / preview['plan_file']}")
        else:
            print("预演完成：没有动任何文件")
        return 0
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
