# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目

- 名称：Hidden Shelf（中文名：藏片阁）。本地番号片整理器：认番号、刮削、按 `厂牌/番号/` 归位，并在盘根目录生成纯静态站，插盘双击 `index.html` 即可浏览播放。
- 参考项目：peach-mitao/peach（AGPL-3.0）。策略模块从它移植，编排层自写。本项目许可 AGPL-3.0-or-later，移植登记在 `docs/REUSE.md`。
- 与用户交流用中文，代码注释中文，标识符英文。

## 当前阶段（2026-10-30）

- 状态：**v1.4.1（用户 2026-10-30 定版本从 1.4.x 起），计划 1「本地流水线」、计划 2「联网刮削」、计划 3「进度网页」、计划 4「盘根目录鼠标选择」、计划 5「开源准备」、计划 6「资料目录改为可见的 HiddenShelf/」、计划 7「老盘迁移要在写配置之前」全部完成**（七份计划每个任务单独提交；计划 5 先于计划 6 做了，所以计划 6 的版本接在 0.4.0 之后；0.4.3、0.4.4 是 CI 首跑修正）。全流程 `扫描 → 导入本地资料 → 联网刮削 → 归位 → 媒体 → 出站`，命令行 `shelf run` 与进度网页 `shelf serve` 跑同一个 `pipeline.run`，输出一致；拔网线照样跑通。预演语义：`dry_run=True` 时前三步照常（只写 `HiddenShelf/`），`organize` 走 `preview_organize` 只列清单（`HiddenShelf/logs/plan-<时间>.txt`）且不再 rescan，`media`、`build` 记 `skipped`（原因 `--dry-run`），`HiddenShelf/` 之外一个字节不动。
- 设计文档（已批准）：`docs/superpowers/specs/2026-10-28-hidden-shelf-design.md`。所有决定以它为准。
- 实施计划 1：`docs/superpowers/plans/2026-10-28-plan-1-local-pipeline.md`；计划 2：`docs/superpowers/plans/2026-10-28-plan-2-online-scraping.md`；计划 3：`docs/superpowers/plans/2026-10-29-plan-3-progress-web.md`；计划 4：`docs/superpowers/plans/2026-10-29-plan-4-folder-picker.md`；计划 5：`docs/superpowers/plans/2026-10-29-plan-5-open-source.md`；计划 6：`docs/superpowers/plans/2026-10-29-plan-6-visible-data-dir.md`；计划 7：`docs/superpowers/plans/2026-10-30-plan-7-migrate-before-config.md`；计划 8「在浏览器里登录来源站」：`docs/superpowers/plans/2026-10-30-plan-8-login.md`（本机会话直接实现，v0.4.15–0.4.17）；计划 9「未识别上墙、图片回写原目录、三语站点、标签三语」：`docs/superpowers/plans/2026-10-30-plan-9-wall-images-languages.md`（本机实现中，v1.4.0 起）。
- 面向外人的文档：`README.md`（中）、`README.en.md`（英）、`CONTRIBUTING.md`、`CHANGELOG.md`、`.github/ISSUE_TEMPLATE/`；CI `.github/workflows/test.yml` 三平台（Windows 允许失败）。公开仓库、打版本标签由用户本机做；CI 三平台已全绿过（macOS 用 Homebrew 装 ffmpeg，Windows 整套测试都过）。
- 资料目录（用户 2026-10-29 定）：盘根下的派生产物目录叫 **`HiddenShelf/`**，普通可见目录（纯 ASCII、无前导点、非 Windows 保留名；不设隐藏属性、不写 `desktop.ini`），名字只在 `paths.SHELF_DIR` 一处写死，别处一律引用。改名前（v0.4.0 及之前）叫 `.shelf/`（`paths.LEGACY_SHELF_DIR`）：`migrate_legacy_dir(root)` 把它同卷 `os.rename` 成 `HiddenShelf/`——**迁移在 `cli.py` 开跑前检查里做（`check_writable → check_layout → migrate_legacy_dir`），先于 `ShelfConfig.load`**；网页端 `runner._work` 先 `ensure()` 再 `load`；`ensure()` 开头和 `pipeline.run` 开头也各调一次当兜底。`ShelfConfig.load` 无副作用（文件不存在只回默认值），默认 `config.json` 由 `ensure()` 末尾写出，老盘自带的配置随目录改名原样带过去（计划 7 修的 v0.4.4 真实盘 bug：`load` 抢先建了 `HiddenShelf/`，迁移再看到两目录并存就拒绝）。`pipeline.run` 抛出的 `ShelfLayoutConflict`/`RootNotWritable` 命令行也包成退出码 2，不甩 traceback；日志记一行「已把 .shelf/ 改名为 HiddenShelf/，请重新出站」；两个目录都在抛 `ShelfLayoutConflict`（`check_layout`，命令行退出码 2、`POST /api/run` 400，不合并不猜）；库里 `cover_file` 等相对资料目录的路径不用改；目录选择器对旧 `.shelf/` 也标「已有库」且不列它。
- 用户 2026-10-30 直接要的小改（v0.4.6、v0.4.7）：无码片商的厂牌一律写成官网英文名（见 `studios.py` 的 `STUDIO_CANONICAL`）：カリビアンコム → Caribbeancom、カリビアンコムプレミアム → Caribbeancompr、一本道 → 1pondo、天然むすめ → 10musume、パコパコママ → Pacopacomama、ムラムラってくる素人 → Muramura、東京熱 → Tokyo-Hot、heyzo → HEYZO。老盘再跑一次 `shelf run` 会在导入步把 `asset.studio` 改掉（`user:*` 的不碰）并把目录从日文名搬到英文名。有码片商（Prestige、MGS……）各来源本来就给英文或原名，不在表里。**番号形状独属一家的，导入步直接补厂牌**（v0.4.9，`studios.studio_from_code` / `fill_studios_from_code`，`import` 步在 `canonicalize_existing` 之后跑）：Tokyo-Hot 的 `n####`／`k####`／`red-###`、HEYZO 的 `HEYZO-####`；归属 `auto:local`（层级 0，联网不覆盖），只填空的；日期式番号不猜。v0.4.12：`codes._LABEL_HEAD` 放行番号前的登记厂牌名（`Catwalk CWPBD-120 …`），别的英文词在前仍不认（`Morning ABP-123 talk` 的测试仍成立）；Catwalk 进 `_UNCENSORED_SITE` 与 `STUDIO_CANONICAL`。v0.4.14：javbus 解析器抓 `span.genre` 当 `tags`（无码页没有類別栏 → `None`）。v0.4.13：`scan.content_type_of(name, code, studio)` 第三参数是库里厂牌，`studios.is_uncensored_studio`（在 `STUDIO_CANONICAL` 里就是无码）让类型不随改名回落。v0.4.10：单站冷却（`SourcePaused`）只让那一家歇着，只有 `BudgetExhausted`（本趟次数/时间预算用完）才整趟停——之前上一趟留下的 avbase 冷却会让整趟刮削在第一个番号就停。
- 登录来源站（计划 8，用户 2026-10-30 要的「需要登录的，写程序含开关，让我登录」）：`scrape/login.py::capture_login(source, config=, finish=, notify=, launch=)` 弹有头 Chromium（Playwright，可选依赖 `uv sync --extra login` + `uv run playwright install chromium`），每半秒抓该站域名下的 Cookie 快照，用户关窗口或置 `finish` 就用最后一份；`GlobalConfig.set_login` 存 `cookie` + `user_agent`（`SourceSettings.user_agent`），传输层「有 Cookie 就带、有 UA 就用」；可登录站 `LOGIN_SOURCES = (javdb, javbus)`；**avbase 不靠登录靠指纹**（v0.4.17，`access.FINGERPRINT_SOURCES = {avbase}`：装了 `curl_cffi` 就 `_transport_for` 走 `CurlTransport`、不带用户 Cookie——2026-10-30 实测 httpx 403、curl_cffi 200、带 cf_clearance 反而 403；没装退回 httpx 照旧冷却，403 提示改成 `uv sync --extra fingerprint`；面板行 `needs_fingerprint` + 响应 `fingerprint_available`）。命令行 `shelf login <站>`；网页 `serve/sources.py::SourcePanel`（`list_sources(root)`、`set_enabled`、`start_login`/`finish_login` 守护线程、`clear_cooldown(root, name)`）接 `GET/POST /api/sources`、`POST /api/login`、`/api/login/finish`、`/api/cooldown/clear`（`GET /api/sources` 也在 `GUARDED_GET_PATHS`）；前端「来源与登录」卡在表单卡下方，登录进行中每 2 秒轮询。凭据不进响应、日志与事件。
- 下一步没有已批准的计划。候选：`shelf rollback <批次日志>` 命令行入口、跨进程运行锁（`HiddenShelf/run.lock`）、步内取消、接 amane 或自写 mgstage/prestige 来源（见设计文档 §6）。
- 计划 2 的真实来源冒烟（`scripts/smoke_sources.py`）在云端会话里**未做**（容器无出站外网），本机有网时按计划 2 Task 11 Step 2 的清单补跑。
- 与计划的已知出入（以 peach 原函数实跑结果为准，不改规则）：`part_marker("ABP-758-cd1.mp4")` 返回 `"1"` 而不是 `"cd1"`；自定义正则抓到的段仍会归一化（`MYLABEL001` → `MYLABEL-001`）；`-C`（中字版）会被 peach 的 `_PART_MARKER` 当成分卷 `c`。计划 2 的出入：javdb 快照不带 peach 的 `javdb_rule`；企划名义剪不出艺名的整条丢弃（没有复核队列）；带敬称的写法（`木村さん`）按企划名义丢弃。
- 参考克隆 `reference/peach`（`.gitignore` 排除，commit 见 `docs/REUSE.md`）；云端会话需要时重新 `git clone --depth 1 https://github.com/peach-mitao/peach.git reference/peach`。

## 命令

```bash
uv sync                                  # 装依赖
uv run pytest -v                         # 全部 Python 测试（约 560 个，依赖系统 ffmpeg，缺则部分 skip；测试永不联网）
uv run pytest tests/test_codes.py -k 名字  # 单个测试
node --test "tests/js/**/*.test.mjs"     # 前端纯逻辑测试（node 22 的 --test 要 glob，不接受目录）
uv run shelf run <盘根目录>               # 全流程：扫描 → 导入本地资料 → 联网刮削 → 归位 → 媒体 → 出站
uv run shelf scan|import-local|scrape|organize|media|build <盘根目录>   # 单步
uv run shelf run <盘根目录> --offline     # 本次跳过联网刮削
uv run shelf run <盘根目录> --images-in-work-dir   # 封面与九宫格复制到视频旁（--no-images-in-work-dir 收回）
uv run shelf run <盘根目录> --dry-run     # 预演：只列要搬的清单（HiddenShelf/logs/plan-*.txt），盘上 HiddenShelf/ 之外不动
uv run shelf scrape <盘根目录> --force-scrape --sources r18dev,javdb --routes "censored=r18dev,javdb"
uv run shelf config [<盘根目录>]          # 打印全局配置位置、代理模式、各站 Cookie 有无、该盘冷却状态（不打印 Cookie 值）
uv run shelf login javdb|javbus           # 弹浏览器登录来源站，Cookie 与 UA 存进 ~/.hidden-shelf/config.json（要 uv sync --extra login）
uv run shelf run <盘根目录> --no-move-unrecognized --dir-template "{studio}/{code}" --file-template "{code}[-cd{cd}]" --language en
uv run python scripts/smoke_sources.py ABW-358 --sources r18dev,dmm,avbase,javbus,javdb   # 真实来源冒烟（手动，需外网）
uv run shelf serve [--port 8031] [--no-browser]   # 进度网页：只监听 127.0.0.1，默认口 8031 被占就在 8000–8099 内往后找
scripts/restart-serve.sh [端口]            # 停掉旧的 shelf serve、等端口释放、后台重启并打开浏览器（日志 ~/.hidden-shelf/serve.log）
```

验证进度网页：`shelf serve --no-browser` 跑在后台，Playwright 无头 Chromium 连 `http://127.0.0.1:<port>/`（脚本不进仓库，放 scratchpad）。验证目录选择器时用 `HIDDEN_SHELF_VOLUMES=<临时卷目录>` 起服务，让位置列出现造好的卷；容器里是 root，`chmod 000` 挡不住，「无权限」那一层用 Playwright 拦截 `/api/browse` 回 403（后端映射有单元测试）。

环境要求：Python ≥ 3.12、uv、系统 ffmpeg/ffprobe（macOS `brew install ffmpeg`，云端 Linux `apt-get install -y ffmpeg`）、node ≥ 20（只为跑前端测试）。

验证站点：用 Playwright 无头 Chromium 从 `file://` 打开生成的 `index.html`（云端预装在 `/opt/node-tools/node_modules/playwright`，用 `createRequire` 引入）。

## 架构（代码已落地，改动时保持同步）

- 包 `src/hidden_shelf/`：
  - `pipeline.py` 串六步 `scan → import → scrape → organize（后自动再 scan） → media → build`，每步写 `run` 表与 `HiddenShelf/logs/run-<时间>.log`；`scrape` 是唯一失败不中断后续的步；跳过判断集中在 `_skip_reason(name, config, scrape_options, dry_run)`（`config.scrape=false` 或 `--offline` 跳 `scrape`，`dry_run` 跳 `media`、`build`）。`run(..., dry_run=)` 与 `RunResult.dry_run`：预演时 `organize` 调 `organize/apply.py::preview_organize`（`PREVIEW_CONSOLE_LIMIT=200` 条之外只进清单文件），`build` 被跳过时 `index_html` 保持 `None`。`Progress` 回调协议（`step/advance/log/done/failed/skipped`），`ConsoleProgress` 是命令行实现，`serve.events.EventProgress` 是网页实现；`run(..., cancel=)` 只在步与步之间检查取消，`RunResult.cancelled`。`cli.py` 是 argparse 入口（`shelf`），`--dry-run` 结束打印预演汇总而不是「成品」。
  - 进度网页 `serve/`：`events.py`（`Event`、`RunLog` 环形缓冲 5000 条——`step.progress` 可淘汰、里程碑永不淘汰——订阅队列、按序号补发；`EventProgress`）、`runner.py`（`RunManager` 进程内单运行锁、守护线程跑 `pipeline.run`、`cancel()` 置标志、`reduce_state` 事件归约、`<home>/recent.json` 最近 10 个盘根；`RunOptions.dry_run` 由 `POST /api/run` 的 `dry_run` 透传，前端「只预演」开关、`result.dry_run`/`page.dry_run`/`summary.organize.dry_run` 文案）、`browse.py`（目录选择器后端：`list_roots` 用户目录 + 各卷/挂载点/盘符，`list_directory` 只列目录、不跟符号链接、不列文件；`BrowseError.status` 400/403/404）、`app.py`（FastAPI：`GET /`、`/static/*`、`/api/state`、`/api/browse`，`POST /api/run|cancel|open`，`GET /api/events` SSE；同源防护：POST **和 `GET /api/browse`** 要 `X-Shelf-Request: 1` + `Origin`/`Referer` 主机是 127.0.0.1/localhost，否则 403）、`ports.py`（默认 8031、8000–8099 段、指定口被占报错）、`static/`（`progress-core.js` 纯逻辑 UMD 可 node 测，含选择器的 `breadcrumbs/sortEntries/browseUrl`、`progress.js` DOM、EventSource 客户端与目录选择弹窗、`progress.css` 只用 token、开头有 `[hidden]{display:none!important}`（带 `display` 的类会盖过浏览器自带的 `[hidden]`）、`i18n.js` 自己的中英字典、`tokens.css`/`ripple.js` 来自 ux-standard）、`templates/progress.html.j2`。
  - 目录选择器的取舍：浏览器拿不到本机绝对路径，列目录全由后端做；`GET /api/browse?path=&show_hidden=0|1`，`path` 空回 `roots`，否则回 `{path, parent, entries[{name,path,has_shelf}], truncated, has_shelf, writable}`，响应 `no-store`；`..` 段拒绝、隐藏目录默认不显示、`HiddenShelf` 与系统目录（`@eaDir`、`$RECYCLE.BIN`、`System Volume Information`、`.Spotlight-V100`、`.Trashes`、`.fseventsd`）永不显示但 `has_shelf` 告诉前端「已有库」；单项 stat 失败跳过那一项；最多 2000 条，超出 `truncated`。前端「选择此目录」选的是当前浏览到的目录（面包屑最后一段），运行中禁用；起点是输入框的值 → `localStorage` 的 `browse.last` → 用户目录。`HIDDEN_SHELF_VOLUMES` 环境变量只是手动验证用的只读钩子（把 macOS 风格的卷目录指到别处），不是配置项。
  - SSE 格式：每条 `id: <seq>`、`event: <kind>`、`data: <一行 JSON>`，JSON 键 `seq, ts, run, kind, step, level, message, stats`；`kind ∈ run.start | step.start | step.progress | step.done | step.failed | step.skipped | run.done | run.cancelled`；15 秒没事件发 `: ping`；客户端带 `Last-Event-ID` 重连从该序号之后补。`step.progress` 的 `message` 就是 `ConsoleProgress` 那一行去掉 `[步名]` 前缀的正文（`tests/test_serve_e2e.py` 钉住两边逐行一致）。
  - `rules/`（移植自 peach）：`codes.py` 番号识别、`sidecars.py` 附属文件判定、`nfo.py` NFO 读取与配对。`field_owners.py` 字段归属。`organize/templates.py` 归位模板。`media/frames.py`、`media/fingerprint.py` 抽帧与指纹。`kanji.py` 日本字形→简体表。登记表 `docs/REUSE.md`。
  - 自写：`paths.py`（`ShelfPaths`，`HiddenShelf/` 布局）、`config.py`（`HiddenShelf/config.json`）、`studios.py`（厂牌规范写法表 `STUDIO_CANONICAL`，用户 2026-10-30 定无码片商一律官网英文名，カリビアンコム → **Caribbeancom**、一本道 → **1pondo** 等；`canonical_studio` 在 `settle.extract`、NFO 导入、`entities.ensure_entity/resolve_named` 三处生效，`canonicalize_existing` 在 `import` 步开头把老库的别名改掉并合并厂牌实体，`user:*`/`review:*` 的不碰；加一家片商只改这张表）、`netconfig.py`（`~/.hidden-shelf/config.json`）、`db.py` + `migrations/*.sql`（当前版本 2）、`scan.py`、`local_import.py` + `entities.py`、`organize/plan.py` + `organize/apply.py`、`media/process.py` + `sheets.py` + `covers.py` + `ffmpeg.py`、`site/build.py` + `playability.py`、`site/static/*`、`site/templates/index.html.j2`。
  - 刮削 `scrape/`：`transport.py`（有界读取、重定向规则、`HostLimiter`）、`access.py`（8 站登记 `SOURCES`、按站 `Cooldown`、`SourceTransport`：Cookie/限速/预算/403-429 冷却）、`snapshots.py`（原始快照与「没有」，7 天）、`identity.py`（`identifies_code`）、`routes.py`（番号形状 → 内容类型 → 来源链；**每站各是一档、逐家短路**）、`policy.py`（来源分级、字段顺序、`owner_tier`）、`names.py`（艺名清洗）、`settle.py`（结算）、`apply.py`（落库、`should_scrape`）、`covers.py`（候选拼法、量尺寸择优、落盘）、`avatars.py`（官方头像）、`run.py`（编排 `scrape_assets`）、`sources/`（契约 `base.py` + 8 站解析器：`r18dev`、`dmm`、`onepondo`、`fc2`、`javarchive`、`javdb`、`javbus`、`avbase`，全部登记在 `SITE_SOURCES`）。
- 刮削数据流：按 `code_key` 分组 → `apply.should_scrape` 判要不要问、缺什么（7 天内问过且不 `--force-scrape` 不问；无番号、未识别、韩国 MIB、其他体系不问）→ `routes.route_for_code(code, 路径, 文件名, 厂牌)` 得链（1pondo 要本机证据）→ 逐站：冷却中或快照记「没有」跳过，新鲜快照直接用，否则 `SiteSource.records()`，`identifies_code` 再核一次 → `not_found` 类与番号错配记快照「没有」，超时/5xx/网络/限流/拒绝不记 → `routes.settles` 判够了就停 → `settle.extract` + `settle.settle` → `apply.apply_settled` → 缺封面时 `covers.candidates_from_records → best_cover → install_online_cover`（`NotFound` 记快照 7 天）→ 全部番号跑完 `avatars.install_avatars`。连着 3 个番号一个请求都连不上 → 报「网络不可用」提前返回，不抛。
- 落库口径（设计文档 §4.7，用户定「最宽松」）：单来源直接写；多来源分歧按 `policy.chain_rank`（本地 NFO > 官方 dmm/r18dev/1pondo/fc2 > javdb > avbase/javarchive > javbus 兜底）结算；javbus 的值在同字段还有别家时不参与；同一家给两个不同标量值时这一家跳过；日期式番号的发行日只认番号那天；有码作品的标签偏向 javdb。跨次运行只有**严格更高档**的来源才覆盖（`source_tier < owner_tier`），`auto:nfo`/`auto:local` 是 0 档永不被联网覆盖，`user:*`/`review:*` 不碰；演员与标签只增不删。封面只顶掉空的或 `auto:frame`，`auto:local` 不动。
- 实体层：`entity_alias(source, confidence)`、`entity_external_ref(provider, external_kind, external_id)`、`entity.avatar_file/metadata`。`entities.resolve_performer`：外站 ID > 规范名 > 唯一别名 > 旧名 > 字形折叠（`kanji.fold_glyphs`）> 新建；外站 ID 已属别人不抢。`names.normalized_performers`：描述性称呼与剪不出艺名的企划名义丢弃并记 warning。
- 位置：快照与冷却在 `<盘根>/HiddenShelf/sources/`（`<番号>-<来源>.json`、`_cooldown.json`）；头像在 `HiddenShelf/avatars/<entity_id>.jpg`；联网封面在 `HiddenShelf/covers/<番号>.jpg`。全局配置 `~/.hidden-shelf/config.json`（`HIDDEN_SHELF_HOME` 可改）：代理三选一、各站 Cookie 与开关、来源链覆盖——**凭据不进盘里的任何文件、不进日志、不进快照**，`shelf config` 与 `GlobalConfig.describe()` 只说有没有。
- 真相在盘里：SQLite `HiddenShelf/shelf.db`，全部派生产物（封面、海报、九宫格、站点、日志、备份、旧附属文件留底、快照、头像）都在 `<盘根>/HiddenShelf/` 下，媒体目录旁不写任何附属文件。布局见设计文档 §4.2。
- `asset.path` 是相对盘根目录的 POSIX 路径；`cover_file`/`poster_file`/`sheet_file` 相对 `HiddenShelf/`。同番号多碟共用 `code_key`、封面与海报，九宫格每碟一张（`<番号>-cd<n>.jpg`）。
- **图片副本回写视频目录**（v1.4.1，选项 `ShelfConfig.images_in_work_dir` 默认关；`media/place.py::place_images` 在媒体步 `process_assets` 之后跑，stats 里 `placed`）：`<番号>-cover.jpg`、`<视频主名>-sheet.jpg`，`sidecar` 表 `status='placed'` 认领——扫描的 upsert 与陈旧清理只动 `pending` 所以不会被当成本地封面导入；归位 `_move_sidecars` 把 `placed` 随视频进新目录并改 `path`（日志 `placed: true`，回滚改回 path）；选项关时删副本并删记录；同名文件是用户的（`pending`）不覆盖；没番号的不放。网页 `RunOptions.images_in_work_dir` 为 None 按盘上配置、给了就写进 `config.json`。
- 归位是事务：备份库（保留 5 份）→ `os.rename` → 改库，改库失败把文件改回去；JSONL 批次日志可 `rollback_batch`；附属文件搬到 `HiddenShelf/legacy/<番号>/`，未识别视频的附属文件跟着进 `未识别/`。 **作品自己的目录里剩下的零散文件跟着视频进新目录**（v0.4.11，用户定；`apply._is_own_dir`：目录名用 `release_code_from_text` 认出的番号与视频相同、且不是盘根；`extra_files_for` 只取顶层普通文件，排除视频、`sidecar` 表登记过的、`_JUNK_NAMES`/`._*`，不进子目录；撞名 `_free_name`；批次日志 `kind=extra` 无库行，回滚只改名；预演清单 `EXTRA\t文件\t目标目录/`，`preview_organize` 返回 `extras` 计数）。只做同卷 rename，绝不删原始文件，绝不覆盖已存在的目标。
- `field_owners`：每条记录有字段归属 JSON；`user:*`、`review:*` 的字段自动写入不许改；扫描写番号用 `scan:filename` + `require_empty`；联网来源写 `auto:<来源名>`。用户手改入口是 `HiddenShelf/overrides.json`（`{"番号": {"title", "studio", "performers": [...], "tags": [...]}}`）。封面归属优先级：`auto:local`（本地旧封面）> 联网 `auto:<来源>` > `auto:frame`（抽帧兜底）。
- 静态站从 `file://` 打开：数据只能是 `<script src>` 加载的 `.js`（`window.__shelf.{meta,works,entities,unrecognized}`，`works` 超 5 MB 分片成 `works-N.js`，`meta.dataFiles` 列全），不能 `fetch`；视频、图片相对路径，**不预先 URL 编码**，前端 `encodeMediaPath` 逐段编码；不加载外网资源（出处链接 `works[].sources` 是 `target=_blank` 外链，不是资源加载）。`entities.performers[].avatar` 指向 `HiddenShelf/avatars/<id>.jpg`。前端是 hash 路由单页（`app.js`），纯逻辑在 `shelf-core.js`（UMD，node 可测）。海报墙（用户 2026-10-30 定）：图集在左、筛选栏在右（`.wall-layout` 两列，手机上筛选用 `order:-1` 回到上面）；**未识别视频也上墙**（v1.4.0）：`build._view_model` 给没番号的视频各做一张卡（`id="u:<asset_id>"`、`kind="unrecognized"`、`unrecognized: true`），厂牌与系列是哨兵 `__unrecognized__`、艺人是哨兵实体 id 0 名 `__amateur__`；前端 `localizeData()` 在 `applyLang()` 里按语言换成「未识别 / 素人」；`BuildResult.works` 与 `meta.counts.works` 只算有番号的。卡片用**横版官方封面** `works[].cover`（`.cover-wrap` 按 800×538），竖版 `poster` 只在没有封面时兜底，`poster_file` 照常生成。
- 盘不可写（macOS 只读挂载的 NTFS 盘最常见）：`paths.check_writable` 在 `shelf run` 与 `POST /api/run` 开跑前先 `os.access`，写不了退出码 2 / 400，消息说明原因与怎么办（装 NTFS 驱动或改 exFAT/APFS、查写保护与权限）；`ShelfPaths.ensure` 把 `EROFS/EACCES/EPERM` 包成 `RootNotWritable` 同一句话。进度网页对第一步之前失败的运行显示「流水线没能开始：…」；目录选择器在 `writable=false` 的目录提示「此目录不可写」。
- 前端外观按 `docs/ux-standard/SKILL.md`（`tokens.css` + `ripple.js` 复制到 `site/static/`），`app.css` 只用 token 变量（`grep -nE "#[0-9a-fA-F]{3,6}\b|rgb\(" app.css` 应无输出），浅/深/系统主题，中英双语（`i18n.js` 两套 key 必须一致）。
- 测试永不联网：`tests/conftest.py` 的 autouse `isolated_home` 把全局配置落到临时目录并停用 8 站；要联网行为的测试自己传 `GlobalConfig()` 与假传输（`tests/test_scrape_run.py` 的 `replay`）。进度网页的测试用 `fastapi.testclient` 与 `tests/serve_fakes.py` 的假流水线；`TestClient` 提前关 SSE 流要等生成器下一次 yield，所以测试里 `ping_seconds` 设得很短。
- 进度网页的取舍：进程内单运行，不做跨进程锁（网页与命令行同时跑同一盘不保护）；取消粒度是「步」；只有 `media` 等带 `[i/total]` 前缀的消息给得出百分比，其余步运行中显示条纹；无桌面环境 `webbrowser.open` 静默失败，`--no-browser` 可绕过。

## 约定

- 每次改代码更新 `pyproject.toml` 的 `version`（每个任务提交 +0.0.1），同时改 `src/hidden_shelf/__init__.py` 与 `tests/test_smoke.py`。
- 本机专用的规则（项目索引、端口登记表）放在 `CLAUDE.local.md`，不进仓库。
- 提交信息用中文。有 GitHub remote，提交后直接 push。

## 端口约束

- 进度网页 `shelf serve` 默认口 **8031**（`serve/ports.py` 的 `DEFAULT_PORT`；8000–8099 段，只监听 127.0.0.1，被占时在段内往后找，`--port` 指定的口被占则退出码 2）。其余命令不开端口。
