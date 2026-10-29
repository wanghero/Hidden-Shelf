# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目

- 名称：Hidden Shelf（中文名：藏片阁）。本地番号片整理器：认番号、刮削、按 `厂牌/番号/` 归位，并在盘根目录生成纯静态站，插盘双击 `index.html` 即可浏览播放。
- 参考项目：peach-mitao/peach（AGPL-3.0）。策略模块从它移植，编排层自写。本项目许可 AGPL-3.0-or-later，移植登记在 `docs/REUSE.md`。
- 与用户交流用中文，代码注释中文，标识符英文。

## 当前阶段（2026-10-29）

- 状态：**v0.2.11，计划 1「本地流水线」与计划 2「联网刮削」都已完成**（计划 2 Task 0–11 每个任务单独提交，版本 0.2.0 → 0.2.11）。全流程 `扫描 → 导入本地资料 → 联网刮削 → 归位 → 媒体 → 出站`；拔网线照样跑通，`scrape` 一步失败只记本步不拦后续。
- 设计文档（已批准）：`docs/superpowers/specs/2026-10-28-hidden-shelf-design.md`。所有决定以它为准。
- 实施计划 1：`docs/superpowers/plans/2026-10-28-plan-1-local-pipeline.md`（已完成）；实施计划 2：`docs/superpowers/plans/2026-10-28-plan-2-online-scraping.md`（已完成）。
- 实施计划 3「进度网页」：`docs/superpowers/plans/2026-10-29-plan-3-progress-web.md`（已写好，待批准后**从 Task 0 开始按任务顺序执行**，版本从 0.3.0 起到 0.3.5）。FastAPI + uvicorn 只监听 127.0.0.1（默认口 8031，8000–8099 段），`Progress` 协议翻成带序号的 SSE 事件，单运行、步间取消、同源防护；前端纯 HTML + 原生 JS 按 ux-standard。
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
uv run shelf scrape <盘根目录> --force-scrape --sources r18dev,javdb --routes "censored=r18dev,javdb"
uv run shelf config [<盘根目录>]          # 打印全局配置位置、代理模式、各站 Cookie 有无、该盘冷却状态（不打印 Cookie 值）
uv run shelf run <盘根目录> --no-move-unrecognized --dir-template "{studio}/{code}" --file-template "{code}[-cd{cd}]" --language en
uv run python scripts/smoke_sources.py ABW-358 --sources r18dev,dmm,avbase,javbus,javdb   # 真实来源冒烟（手动，需外网）
```

环境要求：Python ≥ 3.12、uv、系统 ffmpeg/ffprobe（macOS `brew install ffmpeg`，云端 Linux `apt-get install -y ffmpeg`）、node ≥ 20（只为跑前端测试）。

验证站点：用 Playwright 无头 Chromium 从 `file://` 打开生成的 `index.html`（云端预装在 `/opt/node-tools/node_modules/playwright`，用 `createRequire` 引入）。

## 架构（代码已落地，改动时保持同步）

- 包 `src/hidden_shelf/`：
  - `pipeline.py` 串六步 `scan → import → scrape → organize（后自动再 scan） → media → build`，每步写 `run` 表与 `.shelf/logs/run-<时间>.log`；`scrape` 是唯一失败不中断后续的步，`config.scrape=false` 或 `--offline` 记 `skipped`。`Progress` 回调协议，`ConsoleProgress` 是命令行实现，计划 3 做 SSE 版。`cli.py` 是 argparse 入口（`shelf`）。
  - `rules/`（移植自 peach）：`codes.py` 番号识别、`sidecars.py` 附属文件判定、`nfo.py` NFO 读取与配对。`field_owners.py` 字段归属。`organize/templates.py` 归位模板。`media/frames.py`、`media/fingerprint.py` 抽帧与指纹。`kanji.py` 日本字形→简体表。登记表 `docs/REUSE.md`。
  - 自写：`paths.py`（`ShelfPaths`，`.shelf/` 布局）、`config.py`（`.shelf/config.json`）、`netconfig.py`（`~/.hidden-shelf/config.json`）、`db.py` + `migrations/*.sql`（当前版本 2）、`scan.py`、`local_import.py` + `entities.py`、`organize/plan.py` + `organize/apply.py`、`media/process.py` + `sheets.py` + `covers.py` + `ffmpeg.py`、`site/build.py` + `playability.py`、`site/static/*`、`site/templates/index.html.j2`。
  - 刮削 `scrape/`：`transport.py`（有界读取、重定向规则、`HostLimiter`）、`access.py`（8 站登记 `SOURCES`、按站 `Cooldown`、`SourceTransport`：Cookie/限速/预算/403-429 冷却）、`snapshots.py`（原始快照与「没有」，7 天）、`identity.py`（`identifies_code`）、`routes.py`（番号形状 → 内容类型 → 来源链；**每站各是一档、逐家短路**）、`policy.py`（来源分级、字段顺序、`owner_tier`）、`names.py`（艺名清洗）、`settle.py`（结算）、`apply.py`（落库、`should_scrape`）、`covers.py`（候选拼法、量尺寸择优、落盘）、`avatars.py`（官方头像）、`run.py`（编排 `scrape_assets`）、`sources/`（契约 `base.py` + 8 站解析器：`r18dev`、`dmm`、`onepondo`、`fc2`、`javarchive`、`javdb`、`javbus`、`avbase`，全部登记在 `SITE_SOURCES`）。
- 刮削数据流：按 `code_key` 分组 → `apply.should_scrape` 判要不要问、缺什么（7 天内问过且不 `--force-scrape` 不问；无番号、未识别、韩国 MIB、其他体系不问）→ `routes.route_for_code(code, 路径, 文件名, 厂牌)` 得链（1pondo 要本机证据）→ 逐站：冷却中或快照记「没有」跳过，新鲜快照直接用，否则 `SiteSource.records()`，`identifies_code` 再核一次 → `not_found` 类与番号错配记快照「没有」，超时/5xx/网络/限流/拒绝不记 → `routes.settles` 判够了就停 → `settle.extract` + `settle.settle` → `apply.apply_settled` → 缺封面时 `covers.candidates_from_records → best_cover → install_online_cover`（`NotFound` 记快照 7 天）→ 全部番号跑完 `avatars.install_avatars`。连着 3 个番号一个请求都连不上 → 报「网络不可用」提前返回，不抛。
- 落库口径（设计文档 §4.7，用户定「最宽松」）：单来源直接写；多来源分歧按 `policy.chain_rank`（本地 NFO > 官方 dmm/r18dev/1pondo/fc2 > javdb > avbase/javarchive > javbus 兜底）结算；javbus 的值在同字段还有别家时不参与；同一家给两个不同标量值时这一家跳过；日期式番号的发行日只认番号那天；有码作品的标签偏向 javdb。跨次运行只有**严格更高档**的来源才覆盖（`source_tier < owner_tier`），`auto:nfo`/`auto:local` 是 0 档永不被联网覆盖，`user:*`/`review:*` 不碰；演员与标签只增不删。封面只顶掉空的或 `auto:frame`，`auto:local` 不动。
- 实体层：`entity_alias(source, confidence)`、`entity_external_ref(provider, external_kind, external_id)`、`entity.avatar_file/metadata`。`entities.resolve_performer`：外站 ID > 规范名 > 唯一别名 > 旧名 > 字形折叠（`kanji.fold_glyphs`）> 新建；外站 ID 已属别人不抢。`names.normalized_performers`：描述性称呼与剪不出艺名的企划名义丢弃并记 warning。
- 位置：快照与冷却在 `<盘根>/.shelf/sources/`（`<番号>-<来源>.json`、`_cooldown.json`）；头像在 `.shelf/avatars/<entity_id>.jpg`；联网封面在 `.shelf/covers/<番号>.jpg`。全局配置 `~/.hidden-shelf/config.json`（`HIDDEN_SHELF_HOME` 可改）：代理三选一、各站 Cookie 与开关、来源链覆盖——**凭据不进盘里的任何文件、不进日志、不进快照**，`shelf config` 与 `GlobalConfig.describe()` 只说有没有。
- 真相在盘里：SQLite `.shelf/shelf.db`，全部派生产物（封面、海报、九宫格、站点、日志、备份、旧附属文件留底、快照、头像）都在 `<盘根>/.shelf/` 下，媒体目录旁不写任何附属文件。布局见设计文档 §4.2。
- `asset.path` 是相对盘根目录的 POSIX 路径；`cover_file`/`poster_file`/`sheet_file` 相对 `.shelf/`。同番号多碟共用 `code_key`、封面与海报，九宫格每碟一张（`<番号>-cd<n>.jpg`）。
- 归位是事务：备份库（保留 5 份）→ `os.rename` → 改库，改库失败把文件改回去；JSONL 批次日志可 `rollback_batch`；附属文件搬到 `.shelf/legacy/<番号>/`，未识别视频的附属文件跟着进 `未识别/`。只做同卷 rename，绝不删原始文件，绝不覆盖已存在的目标。
- `field_owners`：每条记录有字段归属 JSON；`user:*`、`review:*` 的字段自动写入不许改；扫描写番号用 `scan:filename` + `require_empty`；联网来源写 `auto:<来源名>`。用户手改入口是 `.shelf/overrides.json`（`{"番号": {"title", "studio", "performers": [...], "tags": [...]}}`）。封面归属优先级：`auto:local`（本地旧封面）> 联网 `auto:<来源>` > `auto:frame`（抽帧兜底）。
- 静态站从 `file://` 打开：数据只能是 `<script src>` 加载的 `.js`（`window.__shelf.{meta,works,entities,unrecognized}`，`works` 超 5 MB 分片成 `works-N.js`，`meta.dataFiles` 列全），不能 `fetch`；视频、图片相对路径，**不预先 URL 编码**，前端 `encodeMediaPath` 逐段编码；不加载外网资源（出处链接 `works[].sources` 是 `target=_blank` 外链，不是资源加载）。`entities.performers[].avatar` 指向 `.shelf/avatars/<id>.jpg`。前端是 hash 路由单页（`app.js`），纯逻辑在 `shelf-core.js`（UMD，node 可测）。
- 前端外观按 `docs/ux-standard/SKILL.md`（`tokens.css` + `ripple.js` 复制到 `site/static/`），`app.css` 只用 token 变量（`grep -nE "#[0-9a-fA-F]{3,6}\b|rgb\(" app.css` 应无输出），浅/深/系统主题，中英双语（`i18n.js` 两套 key 必须一致）。
- 测试永不联网：`tests/conftest.py` 的 autouse `isolated_home` 把全局配置落到临时目录并停用 8 站；要联网行为的测试自己传 `GlobalConfig()` 与假传输（`tests/test_scrape_run.py` 的 `replay`）。

## 约定

- 每次改代码更新 `pyproject.toml` 的 `version`（每个任务提交 +0.0.1），同时改 `src/hidden_shelf/__init__.py` 与 `tests/test_smoke.py`。
- 版本、技术栈、状态有大变化时同步更新 `~/Claude-Code/PROJECTS.md`（仅本机有此文件，云端跳过）。
- 提交信息用中文。有 GitHub remote，提交后直接 push。

## 端口约束

- 本项目计划 1、2 不开端口。计划 3 的进度网页 `shelf serve` 暂定默认口 **8031**（8000–8099 段，只监听 127.0.0.1，被占时在段内往后找）；本机实施时先 `cat ~/.claude/ports.md`（仅本机），若 8031 已被别的项目登记就换一个空闲口，分配后写回 ports.md 并更新本节与 `serve/ports.py` 的 `DEFAULT_PORT`。
