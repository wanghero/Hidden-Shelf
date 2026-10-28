# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目

- 名称：Hidden Shelf（中文名：藏片阁）。本地番号片整理器：认番号、刮削、按 `厂牌/番号/` 归位，并在盘根目录生成纯静态站，插盘双击 `index.html` 即可浏览播放。
- 参考项目：peach-mitao/peach（AGPL-3.0）。策略模块从它移植，编排层自写。本项目许可 AGPL-3.0-or-later，移植登记在 `docs/REUSE.md`。
- 与用户交流用中文，代码注释中文，标识符英文。

## 当前阶段（2026-10-28）

- 设计文档（已批准）：`docs/superpowers/specs/2026-10-28-hidden-shelf-design.md`。所有决定以它为准。
- 实施计划 1「本地流水线」：`docs/superpowers/plans/2026-10-28-plan-1-local-pipeline.md`。**从 Task 0 开始按任务顺序执行**，每个任务 TDD、单独提交。计划 2（联网刮削）和计划 3（进度网页）在计划 1 完成后再写。
- 代码还没有开始写。仓库里目前只有文档。

## 命令

计划 1 的 Task 0 建好脚手架后用这些（之前不可用）：

```bash
uv sync                                  # 装依赖
uv run pytest -v                         # 全部 Python 测试
uv run pytest tests/test_codes.py -k 名字  # 单个测试
node --test tests/js/                    # 前端纯逻辑测试
uv run shelf run <盘根目录>               # 全流程：扫描 → 导入本地资料 → 归位 → 媒体 → 出站
```

环境要求：Python ≥ 3.12、uv、系统 ffmpeg/ffprobe（macOS `brew install ffmpeg`，云端 Linux `apt-get install -y ffmpeg`）、node ≥ 20（只为跑前端测试）。

## 架构（按设计文档，代码落地后保持同步）

- 四步流水线 `scan → import_local → organize → media → build`，见 `pipeline.py`；每步可单独由 `cli.py` 调用。
- 真相在盘里：SQLite `.shelf/shelf.db`，全部派生产物（封面、海报、九宫格、站点、日志、备份、旧附属文件留底）都在 `<盘根>/.shelf/` 下，媒体目录旁不写任何附属文件。布局见设计文档 §4.2。
- `asset.path` 是相对盘根目录的 POSIX 路径。
- 归位是事务：备份库 → 动文件 → 改库，改库失败把文件改回去；只做同卷 `rename`，绝不删原始文件。
- `field_owners`：每条记录有字段归属 JSON；`user:*`、`review:*` 的字段自动写入不许改。用户手改入口是 `.shelf/overrides.json`。
- 静态站从 `file://` 打开：数据只能是 `<script src>` 加载的 `.js`（`window.__shelf.*`），不能 `fetch`；视频、图片相对路径；不加载外网资源。前端是 hash 路由单页，纯逻辑在 `shelf-core.js`（UMD，node 可测）。
- 前端外观按 `docs/ux-standard/SKILL.md`（`tokens.css` + `ripple.js` 在同目录），只用 token 变量，浅/深主题，中英双语。

## 约定

- 每次改代码更新 `pyproject.toml` 的 `version`（每个任务提交 +0.0.1）。
- 版本、技术栈、状态有大变化时同步更新 `~/Claude-Code/PROJECTS.md`（仅本机有此文件，云端跳过）。
- 提交信息用中文。有 GitHub remote，提交后直接 push。

## 端口约束

- 本项目计划 1 不开端口。计划 3 的进度网页需要端口时先 `cat ~/.claude/ports.md`（仅本机），按 8000–8099 段选空闲口，只监听 127.0.0.1，分配后写回 ports.md 并在本节登记。
