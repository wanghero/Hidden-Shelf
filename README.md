# Hidden Shelf（藏片阁）

本地番号片整理器：认番号、联网刮削、按 `厂牌/番号/` 归位，并在盘根目录生成纯静态站，插盘双击 `index.html` 即可浏览播放。

![tests](https://github.com/wanghero/Hidden-Shelf/actions/workflows/test.yml/badge.svg) · [English](README.en.md)

| 海报墙 | 进度网页 | 目录选择器 |
|---|---|---|
| ![海报墙](docs/images/wall.jpg) | ![进度网页](docs/images/progress.jpg) | ![目录选择器](docs/images/picker.jpg) |

截图里都是演示数据。

## 它会对你的盘做什么

一次 `shelf run` 走六步：

1. **扫描**：登记盘上每个视频与它旁边的附属文件（NFO、封面、字幕），认出文件名里的番号。
2. **导入本地资料**：读以前刮削器留下的 NFO 与封面，以及你手写的 `HiddenShelf/overrides.json`。
3. **联网刮削**：缺资料的番号去各站问标题、厂牌、演员、标签、发行日、封面与头像；断网就跳过，不拦后面。
4. **归位**：按 `厂牌/番号/番号[-cdN].ext` 改名归位；认不出番号的视频集中到 `未识别/`。
5. **媒体**：探测时长与分辨率，抽帧做九宫格，没有封面的用抽帧兜底，裁出竖版海报。
6. **出站**：在盘根目录写 `index.html`，离线可开的海报墙，按演员、厂牌、标签筛选，点开直接播放。

**安全承诺**（都有测试钉住）：

- 只做同一卷内的改名，**绝不删除**任何原始文件，**绝不覆盖**已经存在的目标。
- 归位前自动备份数据库（保留最近 5 份）。
- 每批搬运写一份 JSONL 日志（`HiddenShelf/logs/organize-*.jsonl`），可以回滚。
- 所有派生产物（库、封面、海报、九宫格、站点数据、日志、备份）只在 `HiddenShelf/` 下；**媒体目录旁不写任何文件**。
- `--dry-run` 先看清单再动手：列出每个要搬的文件与不搬的原因，一个文件不动。

## 安装

前置：Python ≥ 3.12，以及系统 ffmpeg/ffprobe（「媒体」步要用，找不到会停在那一步并提示怎么装）。

- macOS：`brew install ffmpeg`
- Debian/Ubuntu：`sudo apt install ffmpeg`
- Windows：从 [ffmpeg.org](https://ffmpeg.org/download.html) 下载，把 `bin/` 加进 PATH

装命令行工具（二选一）：

```bash
uv tool install git+https://github.com/wanghero/Hidden-Shelf
pipx install git+https://github.com/wanghero/Hidden-Shelf
```

开发者：

```bash
git clone https://github.com/wanghero/Hidden-Shelf && cd Hidden-Shelf
uv sync
uv run shelf --version
```

## 三步上手

```bash
shelf run <盘根目录> --dry-run   # 1. 预演：只列清单
shelf run <盘根目录>             # 2. 真跑
open <盘根目录>/index.html       # 3. 看成品（Windows 双击 index.html）
```

1. **预演**：终端打出「预演：N 个要搬，M 个已就位，K 个跳过」，每个要搬的文件一行 `现路径 → 目标`，超过 200 条的完整清单在 `HiddenShelf/logs/plan-<时间>.txt`。预演会扫描、导入本地资料、联网刮削（这是算出计划的前提，都只写 `HiddenShelf/`），盘上其它地方一个文件不动。
2. **真跑**：同样的参数，搬的就是预演列出的那些。每步打一行完成摘要，结束打「成品：…/index.html」。
3. **看成品**：双击盘根目录的 `index.html`。换台电脑插上盘也能看，路径全是相对的。

## 进度网页

不想用终端就 `shelf serve`：在本机起一个只监听 `127.0.0.1` 的网页（默认 `http://127.0.0.1:8031/`，端口被占就在 8000–8099 内往后找，`--port` 可指定，`--no-browser` 不自动打开浏览器）。填盘根目录（或点旁边的「浏览」按钮用鼠标选，整理过的目录带「已有库」标记），四个开关：「认不出番号的视频搬到 未识别/」「本次不联网」「只预演」「强制重刮」，点「开始」。六步各一行状态与进度，日志实时滚动，跑完有「打开成品」；「停止」在当前步完成后生效。网页和命令行跑的是同一条流水线，输出一字不差。

## 联网刮削

### 全局配置

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

快照（`<番号>-<来源>.json`）与来源冷却（`_cooldown.json`）在 `<盘根>/HiddenShelf/sources/`，7 天内不重问；403 首停 15 分钟连着翻倍，429 按站方说的时间。

### 来源

| 来源 | 内容类型 | 需要 Cookie | 2026-10-29 本机冒烟 |
|---|---|---|---|
| r18dev | 有码 | 否 | 直连可用 |
| dmm | 有码 | 否 | 对 `ABW-358` 回「没有这个番号」 |
| 1pondo | 无码（一本道） | 否 | 未测 |
| fc2 | FC2 | 否 | 直连可用 |
| javarchive | FC2（下架转载） | 否 | 直连可用 |
| javdb | 有码、素人、无码、FC2 | 是 | 直连可用 |
| javbus | 有码、素人、无码 | 是（年龄门） | 直连可用 |
| avbase | 有码、素人、无码 | 否（但要过 Cloudflare） | 回 403 进冷却，需要浏览器 Cookie |

默认链：有码 `r18dev → dmm → avbase → javbus → javdb`；素人 `avbase → javbus → javdb → r18dev`；无码 `1pondo → avbase → javbus → javdb`；FC2 `fc2 → javarchive → javdb`。多来源分歧时本地 NFO 最高，其次官方站，社区站兜底；你在 `overrides.json` 里写的永远不被覆盖。

## 盘上的布局

```
<盘根>/
  index.html                       成品，双击打开
  厂牌/番号/番号[-cdN].ext           归位后的视频（模板可改）
  未识别/…                          认不出番号的视频，保留原目录层级
  HiddenShelf/
    shelf.db                       SQLite 库，真相在这里
    config.json                    这块盘的设置：模板、是否搬未识别、站点语言、是否联网
    overrides.json                 你手改的字段，优先级最高
    site/                          站点数据（works.js 等）
    covers/  posters/  sheets/     封面、竖版海报、九宫格
    avatars/                       演员头像
    sources/                       刮削快照与冷却
    legacy/<番号>/                  旧 NFO 与封面留底
    logs/                          run-*.log、organize-*.jsonl、plan-*.txt
    backups/                       归位前的库备份（5 份）
```

手改入口 `HiddenShelf/overrides.json`，下次 `shelf run` 自动合并：

```json
{
  "ABP-758": { "title": "改过的标题", "studio": "Prestige", "performers": ["铃村あいり"], "tags": ["单体作品"] }
}
```

## 常见问题

- **换台电脑能看吗？** 能。站点里全是相对路径，盘插哪台机器都一样。
- **文件名不是番号怎么办？** 默认搬到 `未识别/`（保留原目录层级），站点里单独列出；`--no-move-unrecognized` 可以让它们原地不动。
- **以前刮削器留下的 NFO 和封面？** 先导入，再搬到 `HiddenShelf/legacy/<番号>/` 留底，媒体目录旁不再留附属文件。
- **作品文件夹里还有截图、说明之类的零散文件？** 文件夹名里带着这个番号的，算作品自己的文件夹，里面顶层的零散文件跟着视频一起进新目录，名字不变；子目录不动。预演清单里以 `EXTRA` 行列出。
- **搬错了怎么回滚？** 每批有 `HiddenShelf/logs/organize-<时间>.jsonl`。目前要在 Python 里调 `hidden_shelf.organize.apply.rollback_batch(connection, paths, 日志路径)`，命令行入口还没有。
- **javdb 要登录？** 浏览器登录后把 Cookie 请求头贴进全局配置的 `sources.javdb.cookie`。
- **跑一半断网？** 刮削失败只记本步，归位、媒体、出站照常；下次有网再跑一遍补资料。
- **以前版本留下的 `.shelf/`？** 0.4.2 起资料目录改名为可见的 `HiddenShelf/`，再跑一次任何命令会自动改名，不用手动搬；两个目录都在时会拒绝运行并提示保留一个。
- **盘是只读的（macOS 插 NTFS 盘最常见）？** 开跑前会直接告诉你原因与怎么办：装 NTFS 驱动或改 exFAT/APFS。

## 平台

- macOS：已验证（作者日常使用）。
- Linux：由 CI 验证。
- Windows：**未验证**。CI 允许这一路失败，欢迎反馈。

## 免责声明

- 这是面向成年人（18+）内容的整理工具。
- 只抓公开的元数据与封面，不下载视频。
- 不内置任何站点凭据；Cookie 与各站的使用条款由你自己负责。
- 程序设计上不删、不覆盖、归位前备份，但**备份仍是你自己的事**，对数据丢失不承担责任。

## 许可与致谢

- 许可 **AGPL-3.0-or-later**：可以改、可以商用，但改过的版本拿去提供网络服务也必须开源。
- 策略模块移植自 [peach-mitao/peach](https://github.com/peach-mitao/peach)（AGPL-3.0），逐文件登记在 `docs/REUSE.md`。
- 界面规范来自 `docs/ux-standard/`。

## 设计历史

- 设计文档：`docs/superpowers/specs/2026-10-28-hidden-shelf-design.md`
- 计划 1（本地流水线）：`docs/superpowers/plans/2026-10-28-plan-1-local-pipeline.md`
- 计划 2（联网刮削）：`docs/superpowers/plans/2026-10-28-plan-2-online-scraping.md`
- 计划 3（进度网页）：`docs/superpowers/plans/2026-10-29-plan-3-progress-web.md`
- 计划 4（盘根目录鼠标选择）：`docs/superpowers/plans/2026-10-29-plan-4-folder-picker.md`
- 计划 5（开源准备）：`docs/superpowers/plans/2026-10-29-plan-5-open-source.md`
