# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目

- 名称：Hidden Shelf（中文名：藏片阁）。本地番号片整理器：认番号、刮削、按 `厂牌/番号/` 归位，并在盘根目录生成纯静态站，插盘双击 `index.html` 即可浏览播放。
- 参考项目：peach-mitao/peach（AGPL-3.0）。策略模块从它移植，编排层自写。本项目许可 AGPL-3.0-or-later，移植登记在 `docs/REUSE.md`。
- 与用户交流用中文，代码注释中文，标识符英文。

## 当前阶段（2026-10-28）

- 状态：**v0.1.15，计划 1「本地流水线」已完成**（Task 0–15 全部落地，每个任务单独提交）。不联网也能跑通「扫描 → 本地 NFO/封面导入 → 归位 → 媒体 → 出站」，产物从 `file://` 打开即可浏览播放。
- 设计文档（已批准）：`docs/superpowers/specs/2026-10-28-hidden-shelf-design.md`。所有决定以它为准。
- 实施计划 1：`docs/superpowers/plans/2026-10-28-plan-1-local-pipeline.md`（已完成）。下一步写计划 2（联网刮削：来源链、分级、实体外站 ID、封面头像、代理与 Cookie）和计划 3（进度网页：FastAPI + SSE）。
- 与计划的已知出入（以 peach 原函数实跑结果为准，不改规则）：`part_marker("ABP-758-cd1.mp4")` 返回 `"1"` 而不是 `"cd1"`；自定义正则抓到的段仍会归一化（`MYLABEL001` → `MYLABEL-001`）；`-C`（中字版）会被 peach 的 `_PART_MARKER` 当成分卷 `c`。
- 参考克隆 `reference/peach`（`.gitignore` 排除，commit 见 `docs/REUSE.md`）；云端会话需要时重新 `git clone --depth 1 https://github.com/peach-mitao/peach.git reference/peach`。

## 命令

```bash
uv sync                                  # 装依赖
uv run pytest -v                         # 全部 Python 测试（约 300 个，依赖系统 ffmpeg，缺则部分 skip）
uv run pytest tests/test_codes.py -k 名字  # 单个测试
node --test "tests/js/**/*.test.mjs"     # 前端纯逻辑测试（node 22 的 --test 要 glob，不接受目录）
uv run shelf run <盘根目录>               # 全流程：扫描 → 导入本地资料 → 归位 → 媒体 → 出站
uv run shelf scan|import-local|organize|media|build <盘根目录>   # 单步
uv run shelf run <盘根目录> --no-move-unrecognized --dir-template "{studio}/{code}" --file-template "{code}[-cd{cd}]" --language en
```

环境要求：Python ≥ 3.12、uv、系统 ffmpeg/ffprobe（macOS `brew install ffmpeg`，云端 Linux `apt-get install -y ffmpeg`）、node ≥ 20（只为跑前端测试）。

验证站点：用 Playwright 无头 Chromium 从 `file://` 打开生成的 `index.html`（云端预装在 `/opt/node-tools/node_modules/playwright`，用 `createRequire` 引入）。

## 架构（代码已落地，改动时保持同步）

- 包 `src/hidden_shelf/`：
  - `pipeline.py` 串五步 `scan → import → organize（后自动再 scan） → media → build`，每步写 `run` 表与 `.shelf/logs/run-<时间>.log`；`Progress` 回调协议，`ConsoleProgress` 是命令行实现，计划 3 做 SSE 版。`cli.py` 是 argparse 入口（`shelf`）。
  - `rules/`（移植自 peach）：`codes.py` 番号识别、`sidecars.py` 附属文件判定、`nfo.py` NFO 读取与配对。`field_owners.py` 字段归属。`organize/templates.py` 归位模板。`media/frames.py`、`media/fingerprint.py` 抽帧与指纹。登记表 `docs/REUSE.md`。
  - 自写：`paths.py`（`ShelfPaths`，`.shelf/` 布局）、`config.py`（`.shelf/config.json`）、`db.py` + `migrations/*.sql`、`scan.py`、`local_import.py` + `entities.py`、`organize/plan.py` + `organize/apply.py`、`media/process.py` + `sheets.py` + `covers.py` + `ffmpeg.py`、`site/build.py` + `playability.py`、`site/static/*`、`site/templates/index.html.j2`。
- 真相在盘里：SQLite `.shelf/shelf.db`，全部派生产物（封面、海报、九宫格、站点、日志、备份、旧附属文件留底）都在 `<盘根>/.shelf/` 下，媒体目录旁不写任何附属文件。布局见设计文档 §4.2。
- `asset.path` 是相对盘根目录的 POSIX 路径；`cover_file`/`poster_file`/`sheet_file` 相对 `.shelf/`。同番号多碟共用 `code_key`、封面与海报，九宫格每碟一张（`<番号>-cd<n>.jpg`）。
- 归位是事务：备份库（保留 5 份）→ `os.rename` → 改库，改库失败把文件改回去；JSONL 批次日志可 `rollback_batch`；附属文件搬到 `.shelf/legacy/<番号>/`，未识别视频的附属文件跟着进 `未识别/`。只做同卷 rename，绝不删原始文件，绝不覆盖已存在的目标。
- `field_owners`：每条记录有字段归属 JSON；`user:*`、`review:*` 的字段自动写入不许改；扫描写番号用 `scan:filename` + `require_empty`。用户手改入口是 `.shelf/overrides.json`（`{"番号": {"title", "studio", "performers": [...], "tags": [...]}}`）。封面归属优先级：`auto:local`（本地旧封面）覆盖 `auto:frame`（抽帧兜底）。
- 静态站从 `file://` 打开：数据只能是 `<script src>` 加载的 `.js`（`window.__shelf.{meta,works,entities,unrecognized}`，`works` 超 5 MB 分片成 `works-N.js`，`meta.dataFiles` 列全），不能 `fetch`；视频、图片相对路径，**不预先 URL 编码**，前端 `encodeMediaPath` 逐段编码；不加载外网资源。前端是 hash 路由单页（`app.js`），纯逻辑在 `shelf-core.js`（UMD，node 可测）。
- 前端外观按 `docs/ux-standard/SKILL.md`（`tokens.css` + `ripple.js` 复制到 `site/static/`），`app.css` 只用 token 变量（`grep -nE "#[0-9a-fA-F]{3,6}\b|rgb\(" app.css` 应无输出），浅/深/系统主题，中英双语（`i18n.js` 两套 key 必须一致）。

## 约定

- 每次改代码更新 `pyproject.toml` 的 `version`（每个任务提交 +0.0.1），同时改 `src/hidden_shelf/__init__.py` 与 `tests/test_smoke.py`。
- 版本、技术栈、状态有大变化时同步更新 `~/Claude-Code/PROJECTS.md`（仅本机有此文件，云端跳过）。
- 提交信息用中文。有 GitHub remote，提交后直接 push。

## 端口约束

- 本项目计划 1 不开端口。计划 3 的进度网页需要端口时先 `cat ~/.claude/ports.md`（仅本机），按 8000–8099 段选空闲口，只监听 127.0.0.1，分配后写回 ports.md 并在本节登记。
