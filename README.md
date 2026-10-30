# Hidden Shelf（藏片阁）

![tests](https://github.com/wanghero/Hidden-Shelf/actions/workflows/test.yml/badge.svg)

本地番号片整理器：认番号、联网刮削、按 `厂牌/番号/` 归位，并在盘根目录生成纯静态站，插盘双击 `index.html` 即可浏览播放。

- 设计文档：`docs/superpowers/specs/2026-10-28-hidden-shelf-design.md`
- 实施计划 1（本地流水线）：`docs/superpowers/plans/2026-10-28-plan-1-local-pipeline.md`
- 实施计划 2（联网刮削）：`docs/superpowers/plans/2026-10-28-plan-2-online-scraping.md`
- 实施计划 3（进度网页）：`docs/superpowers/plans/2026-10-29-plan-3-progress-web.md`
- 实施计划 4（盘根目录鼠标选择）：`docs/superpowers/plans/2026-10-29-plan-4-folder-picker.md`
- 许可：AGPL-3.0-or-later。策略模块移植自 [peach-mitao/peach](https://github.com/peach-mitao/peach)，登记见 `docs/REUSE.md`。

```bash
uv sync
uv run pytest -v
uv run shelf run <盘根目录>              # 扫描 → 导入本地资料 → 联网刮削 → 归位 → 媒体 → 出站
uv run shelf run <盘根目录> --offline    # 不联网
uv run shelf config                     # 看全局配置在哪、代理模式、各站有没有 Cookie
uv run shelf serve                      # 进度网页：浏览器里选盘、点开始、看每步进度与日志
```

## 进度网页

`shelf serve` 在本机起一个只监听 `127.0.0.1` 的小网页（默认 `http://127.0.0.1:8031/`，端口被占就在 8000–8099 内往后找，`--port` 可指定，`--no-browser` 不自动打开浏览器）。页面上填盘根目录（最近用过的会出现在下拉里；也可以点输入框旁的「浏览」按钮，从用户目录和各个卷开始用鼠标逐级点进去选，已经整理过的目录带「已有库」标记）、选「认不出番号的视频搬到 未识别/」「本次不联网」「强制重刮」，点「开始」；六步各一行状态与进度，日志实时滚动，跑完有「打开成品」。同一时刻只跑一个；「停止」在当前步完成后生效。网页和命令行跑的是同一条流水线，输出一字不差。

## 联网刮削的全局配置

刮削用到的代理与各站 Cookie 放在 `~/.hidden-shelf/config.json`（环境变量 `HIDDEN_SHELF_HOME` 可改目录），第一次运行会写出默认值。
凭据只住在这里：不进盘里的任何文件、不进日志、不进快照。`shelf config` 也只说有没有，不打印值。

```json
{
  "network": { "mode": "environment", "proxy": "" },
  "sources": {
    "javdb":  { "enabled": true, "cookie": "_jdb_session=...; over18=1" },
    "javbus": { "enabled": true, "cookie": "existmag=all" },
    "avbase": { "enabled": false, "cookie": "" }
  },
  "routes": { "censored": ["r18dev", "dmm", "javdb"] }
}
```

- `network.mode`：`environment`（跟随 `HTTPS_PROXY` 等环境变量）、`direct`（忽略环境变量直连）、`proxy`（用 `network.proxy`，如 `http://127.0.0.1:7890` 或 `socks5h://127.0.0.1:1080`）。
- `sources.<站>.cookie`：浏览器里复制的一行 Cookie 请求头；只有 javdb（配额与登录墙）和 javbus（年龄门）需要。`enabled: false` 整站不问。
- `routes`：整条替换某类番号的来源链。内容类型 `censored | amateur | uncensored | fc2`，来源名 `r18dev dmm 1pondo fc2 javarchive avbase javbus javdb`。每站各是一档、逐家短路：有一家答了就停。

快照（`<番号>-<来源>.json`）与来源冷却（`_cooldown.json`）在 `<盘根>/.shelf/sources/`，7 天内不重问；403 首停 15 分钟连着翻倍，429 按站方说的时间。
