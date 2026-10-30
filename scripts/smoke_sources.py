"""对一个番号逐站真实 `query`，打印 `payload()` 摘要与失败分档。手动跑，不进测试。

    uv run python scripts/smoke_sources.py ABW-358 --sources r18dev,dmm,avbase,javbus,javdb
    uv run python scripts/smoke_sources.py 112312_478 --sources 1pondo
    uv run python scripts/smoke_sources.py FC2-PPV-4364209            # 按内容类型的默认链

每站一行：`r18dev  ok  涼森れむ流 / Prestige / 2023-05-26 / 1 人 / 封面 1 张`
或 `javdb  auth_required  javdb 要求登录`。代理与 Cookie 读 `~/.hidden-shelf/config.json`（`HIDDEN_SHELF_HOME`
可改位置）；冷却记录写到临时目录，不碰任何盘。
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

import httpx

from hidden_shelf.netconfig import GlobalConfig, config_path
from hidden_shelf.scrape import routes
from hidden_shelf.scrape.access import Cooldown, SourcePaused, SourceTransport
from hidden_shelf.scrape.sources import SITE_SOURCES, Session, SourceFailure
from hidden_shelf.scrape.transport import DeadlineExceeded


def summary(payload: dict) -> str:
    people = payload.get("actresses") or []
    covers = payload.get("cover_urls") or []
    return " / ".join([
        str(payload.get("title") or "（无标题）")[:40],
        str(payload.get("maker") or "（无厂牌）"),
        str(payload.get("release_date") or "（无日期）"),
        f"{len(people)} 人",
        f"封面 {len(covers)} 张",
        f"标签 {len(payload.get('genres') or [])} 个" if payload.get("genres") is not None else "无标签栏",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("code", help="番号，如 ABW-358、112312_478、FC2-PPV-4364209")
    parser.add_argument("--sources", help="逗号分隔的来源名；缺省按内容类型的默认链（1pondo 要路径证据，可用 --hint 给）")
    parser.add_argument("--hint", default="", help="本机证据（路径或厂牌），决定无码番号问不问 1pondo")
    parser.add_argument("--timeout", type=float, default=120.0, help="整趟预算（秒）")
    args = parser.parse_args(argv)

    config = GlobalConfig.load()
    print(f"全局配置：{config_path()}（网络 {config.network_mode}）")
    if args.sources:
        names = [part.strip() for part in args.sources.split(",") if part.strip()]
    else:
        names = list(routes.route_for_code(args.code, args.hint, overrides=config.routes))
        print(f"内容类型 {routes.classify(args.code, args.hint)}，默认链：{','.join(names) or '（不问任何来源）'}")
    unknown = [name for name in names if name not in SITE_SOURCES]
    if unknown:
        print(f"未知来源：{'、'.join(unknown)}；可用：{'、'.join(SITE_SOURCES)}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as scratch:
        transport = SourceTransport(Cooldown(Path(scratch) / "_cooldown.json"), config, max_seconds=args.timeout)
        session = Session(transport)
        failures = 0
        try:
            for name in names:
                if not config.enabled(name):
                    print(f"{name:<11}disabled      全局配置里停用")
                    continue
                started = time.monotonic()
                try:
                    records = SITE_SOURCES[name]().records(args.code, session=session)
                except SourceFailure as failure:
                    failures += 1
                    print(f"{name:<11}{failure.reason.value:<14}{failure.message}"
                          + (f"（HTTP {failure.status_code}）" if failure.status_code else ""))
                    continue
                except SourcePaused as error:
                    failures += 1
                    print(f"{name:<11}paused        {error}")
                    continue
                except httpx.TransportError as error:
                    failures += 1
                    print(f"{name:<11}network       {type(error).__name__}: {error}")
                    continue
                except DeadlineExceeded:
                    print(f"{name:<11}deadline      整趟预算 {args.timeout:.0f} 秒用完")
                    break
                elapsed = time.monotonic() - started
                for record in records:
                    print(f"{name:<11}ok            {summary(record.payload())}  [{elapsed:.1f}s] {record.source_url}")
        finally:
            transport.close()
        if transport.cooldown.describe():
            print("本趟触发的冷却（只记在临时目录）：", transport.cooldown.describe())
    return 1 if failures and failures == len(names) else 0


if __name__ == "__main__":
    sys.exit(main())
