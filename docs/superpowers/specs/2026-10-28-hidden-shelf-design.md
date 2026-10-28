# Hidden Shelf（藏片阁）设计文档

日期：2026-10-28 · 状态：草稿，待用户批准 · 参考项目：[peach-mitao/peach](https://github.com/peach-mitao/peach)（本机浅克隆在会话 scratchpad，正式开发时重新克隆到 `vendor/` 之外的参考目录）

## 1. 这是什么、为什么做

一台电脑或一块外接盘上散落着大量番号片（JAV）和以前刮削器留下的封面、海报、NFO。用户要的是：**跑一个程序，它把盘整理干净并在盘根目录生成一个纯静态网站；之后插上盘、双击 `index.html`，浏览器里出海报墙，点一部就播盘里的视频，换任何一台电脑插上都一样能看，不需要跑任何后台服务。**

peach 已经把「认番号 → 多站刮削 → 归位文件 → 浏览」做得很成熟，但它是常驻的动态 Web 应用（FastAPI + SQLite + React SPA 吃 JSON API），离了服务器什么都看不了。Hidden Shelf 的差别只有一条：**生成过程是动态的，产物是静态的，而且产物和数据库都住在盘里，盘是自包含的。**

### 目标

1. 整理：认番号、刮削、把视频按标准结构重命名归位；认不出的集中到「未识别」目录（可关）。
2. 产出：盘根目录一个 `index.html` + 一个站点目录，浏览器从 `file://` 打开即用，有海报墙、搜索筛选、详情页、艺人/厂牌/系列/标签页、直接播放。
3. 可重复跑：第二次跑只处理新增和变化，用户手改过的资料不会被覆盖；无需人工确认。
4. 有进度：本机小网页显示扫描、刮削、归位、出站四步的进度和日志；同时有命令行一条命令跑全程。

### 非目标（明确不做）

播放历史与观看统计、关注/追更、云下载、磁力、网盘/SMB/CloudDrive/PikPak、想要清单、人脸识别、LLM 候选、人工复核界面、多用户与登录、桌面打包（PyInstaller）、外部播放器集成（file:// 下做不到更多，只给复制路径）。

### 反目标（做到了功能也算失败）

- 把一个文件搬到错的地方，或者搬丢。
- 删掉用户任何原始文件（NFO、旧封面也不删，只搬走留底）。
- 浏览时需要启动任何服务、需要联网、需要特定电脑。
- 重跑一次就把用户手改的标题、演员覆盖掉。

## 2. 约束

- 媒体只在本机磁盘或外接盘，不考虑网络文件系统。
- 浏览产物从 `file://` 打开：Chrome/Safari 下脚本不能 `fetch` 本地 JSON，所以**数据必须打成 `<script src>` 能加载的 `.js` 文件**；视频、图片用相对路径；不能依赖任何 CDN。
- 浏览器播不了的容器/编码（MKV、WMV、AVI、RMVB、部分 HEVC 等）页面上要标出来，给「复制路径」。
- 刮削规则**完全按 peach**：番号识别、附属文件配对、内容类型判定、来源链顺序与停止条件、多源互证、字段优先级。不重新发明。
- peach 是 AGPL-3.0-or-later。从它移植代码，本项目也按 AGPL-3.0-or-later 发布，`LICENSE` 和 `docs/REUSE.md` 写明来源。仅自用时无额外义务。
- 遵守用户全局规则：中文交流、每次改代码更新版本号、Web 界面按 `ux-standard`、端口按 `~/.claude/ports.md` 分配（实施时选 8000–8099 段空闲口，只监听 127.0.0.1）。
- ffmpeg 用系统的（本机 `/usr/local/bin/ffmpeg`），找不到就报错并提示安装，不托管二进制。

## 3. 用户已经定下的事

| 事项 | 决定 |
|---|---|
| 媒体位置 | 本机或外接盘 |
| 整理规则 | 和 peach 完全一样：认番号、刮削、归位 |
| 浏览形态 | 插盘 → 双击 `index.html` → 海报墙 → 点播；换电脑照样能看 |
| 生成流程 | 扫描 → 不确认直接归位 → 显示操作进程 → 出站 |
| 未识别文件 | 一个开关「集中搬到『未识别』目录」，默认开；关则原地不动。两种情况站里都有「未识别」区 |
| 盘里的图片 | 都是以前刮削器留下的封面、海报（无独立写真内容） |
| 刮削器行为 | 完全按 peach（本地 NFO/封面优先于联网来源） |
| 草图 | 不需要看，由 Claude 定 |

## 4. 我定下的事（用户可推翻）

### 4.1 技术栈

- **Python ≥ 3.12，uv 管理**。理由：peach 的策略层（`catalog_rules`、`metadata_routes`、`metadata_policy`、`organize*`、`field_owners`、`library_nfo`、`sources/*`）是纯 Python，直接移植比翻译成别的语言可靠得多。peach 要求 3.14，我们用 3.12+ 以便本机 3.13 直接跑；移植时去掉 3.14 专有语法。
- 依赖尽量少：`httpx`（+ `curl_cffi` 给需要浏览器指纹的站）、`beautifulsoup4`、`pillow`、`jinja2`（出站模板）、`fastapi` + `uvicorn`（只给进度网页）。不要 APScheduler、grpc、pystray、sentry。
- SQLite 做工作库，**放在盘里** `.shelf/shelf.db`，随盘走。
- 前端产物：纯 HTML + CSS + 原生 JS，按 `ux-standard` 的 tokens（浅/深/系统主题、中英双语字典）；不用构建工具，模板用 jinja2 在出站时渲染。
- 进度网页：也是纯 HTML + 原生 JS，走 SSE 收日志。

### 4.2 盘上的布局

```
<盘根目录>/
  index.html                 ← 双击这个；实际是站点首页，引用 .shelf/site/ 下资源
  <厂牌>/<番号>/<番号>.mp4     ← 归位后的媒体（多碟 <番号>-cd1.mp4）
  未识别/<原相对路径>          ← 开关开时，认不出番号的视频搬到这里，保留原目录层级
  .shelf/
    shelf.db                 ← SQLite 工作库（真相）
    config.json              ← 本盘设置（未识别开关、代理、来源开关、模板）
    site/                    ← 出站产物：app.js、app.css、data/*.js、i18n
    covers/<番号>.jpg         ← 封面（来源图或本地旧封面）
    posters/<番号>.jpg        ← 竖版海报（封面右侧裁切或来源海报，按 peach 规则）
    sheets/<番号>.jpg         ← ffmpeg 九宫格
    avatars/<艺人id>.jpg      ← 艺人头像
    sources/<番号>-<来源>.json ← 原始快照缓存（少发请求、可续跑）
    legacy/<番号>/            ← 旧 NFO、多余图片原样搬来留底
    logs/run-<时间>.log       ← 每次运行日志
    backups/shelf-<时间>.db   ← 每次动文件前的库备份（保留最近 5 份）
```

- 目录名 `.shelf` 在 macOS Finder 默认隐藏，Windows 可见；用户要看可以 `⌘⇧.`。
- 媒体目录旁**不写** NFO、封面、缩略图，与 peach 一致。
- 归位模板默认 `{studio}/{code}/{code}[-cd{cd}]`，可在 `config.json` 改；模板语法、清洗、长度截断、路径逃逸防护照搬 peach 的 `organize_templates`。厂牌未知但番号已认出时落 `_未知厂牌/<番号>/`。
- 只做**同一卷内**移动（rename），绝不跨盘拷贝。

### 4.3 运行流程（一次 `run`）

四步串行，每步可单独跑，进度网页和命令行输出一致：

1. **扫描**：遍历根目录（跳过 `.shelf/`、`未识别/`、系统垃圾），按 peach 的扩展名集登记视频，按 `is_sidecar` 规则识别封面/海报/NFO 并配对到同目录主文件。只写观测字段（大小、mtime、last_seen）；消失的文件不删行，标 `vanished`。认番号用移植的 `release_code_from_filename`，先过用户自定义正则。
2. **刮削**：本地 NFO/封面先入库（`CHAIN_LOCAL_NFO`），再按 `metadata_routes` 的类型链逐站问，停止条件、互证、字段优先级照 peach。原始响应落 `sources/` 快照，新鲜就不再请求。失败只记日志不中断，不把「没拿到」缓存成「确认没有」。封面落 `covers/`，没有来源封面就用本地旧封面；都没有就从视频抽一帧当封面。
3. **归位**：按 `organize.build_plan → apply_plan` 三段式。顺序固定：**备份库 → 动文件 → 改库，改库失败就把文件名改回去**。计划里的 `skip` 原因沿用 peach 枚举（字段缺失、目标已存在、路径过长……）并进日志。未识别文件按开关处理；附属文件按 4.2 搬去 `covers/` 或 `legacy/`。空目录在归位后清掉（只删空目录）。
4. **出站**：ffmpeg 抽九宫格（源指纹不变就跳过）、生成艺人头像缩略图、渲染站点。

重跑规则：`field_owners` 照搬 peach，`user:*`、`review:*` 的字段自动写入一律不许改。用户手改的入口是 `.shelf/overrides.json`（番号 → 字段），运行时以 `user:manual` 身份合并进库；不做编辑界面。

### 4.4 静态站

- **形态：单页应用 + hash 路由**（`index.html#/work/ABP-968`），而不是每部片一个 HTML。理由：一万部片生成一万个页面又慢又碎，而搜索、筛选本来就要在浏览器里做；SPA 仍然是纯静态文件，`file://` 下没有任何障碍。
- 数据：`.shelf/site/data/works.js`、`performers.js`、`studios.js`、`series.js`、`tags.js`、`unrecognized.js`，每个是 `window.__shelf.works = [...]` 这种赋值。单文件超过约 5 MB 时按首字母或 id 段分片，首页只加载索引片。
- 页面：
  - 首页海报墙：封面、番号、标题、演员、时长、画质标（4K/1080p/720p）、有码/无码/素人、能否直接播放。顶部搜索（番号、标题、演员、厂牌，中日英都能搜），侧栏筛选（演员、厂牌、系列、年份、标签、类型、可播放），排序（发行日、入库日、时长、番号）。
  - 作品详情：大封面、全部资料、演员头像链接、九宫格、同演员/同系列/同厂牌的其他片，`<video controls>` 播放，多碟列出各碟。播不了的格式显示原因和「复制路径」按钮。
  - 艺人、厂牌、系列、标签：名册页（头像/Logo + 作品数）和各自的作品列表。
  - 未识别区：原文件名、当前路径、大小，可按名搜索。
  - 统计页：作品数、总时长、总大小、各类型占比（一页简单数字，不做图表交互）。
- 外观：`ux-standard`（Soft UI 卡片 + 波纹、靛蓝主色、Geist 字体回退到系统字体、浅/深/系统主题、中英双语、加载/空/错误三态）。字体不能联网加载，用系统字体栈。
- 浏览状态（主题、语言、上次筛选）存 `localStorage`，`file://` 下可用。

### 4.5 进度网页与命令行

- `shelf run <盘根目录>`：全流程。`shelf scan|scrape|organize|build <根>` 单步。`shelf serve` 启进度网页并自动打开浏览器。
- 进度网页：一页，顶部选根目录（最近用过的下拉）和「未识别搬走」开关，一个「开始」按钮，下面四步各一条进度条和实时日志（SSE），结束后「打开成品」按钮（`open <根>/index.html`）。同一时刻只允许一个运行。
- 配置：`.shelf/config.json` 存本盘的；代理地址、来源开关放 `~/.hidden-shelf/config.json`（跨盘共用）。代理语义照 peach「直连 / 自定义代理 / 跟随环境」三选一。

### 4.6 从 peach 移植什么、不移植什么

| 移植（基本照抄，改包名、去 3.14 语法、去网盘分支） | 不移植 |
|---|---|
| `catalog_rules.py`（番号、附属文件、垃圾文件、类型判定，连同误判证据注释） | `web_*` 23 个 handler、React 前端、BoardUI |
| `metadata_routes.py`、`metadata_policy.py`、`field_owners.py` | 任务系统、限流闸门、APScheduler |
| `organize.py`、`organize_templates.py` | SMB/CloudDrive/PikPak/浏览器取页 |
| `library_nfo.py`、`sources/` 下 peach 自写的解析器（javdb、javbus、dmm、r18dev、avbase、fc2 系、onepondo） | `metadata_amane.py` 桥和 amane 子进程（第一版不接；prestige/faleno/dahlia/mgstage/avsox 等经 amane 的来源缺位，影响面见 §6） |
| `frame_capture.py`、九宫格、封面取景、`artifact_rules.py` 指纹 | 时间线预览（第二版再考虑）、人脸识别、Gfriends 头像库 |
| `junk.py` | 关注、下载、想要、口味、统计、复核、诊断上报 |

移植的每个模块保留 peach 的测试用例（它的 `tests/` 里对应文件）作为回归基线。

## 5. 留给建造者决定的

- 包内目录划分、模块命名；移植时是否合并 peach 的平铺模块。
- SQLite 表结构（可从 peach `migrations/0000`、`0002`、`0029` 精简，去掉行为字段和网盘字段）。
- 进度网页的 SSE 实现细节、日志格式。
- `data/*.js` 的分片阈值与分片方式。
- 九宫格参数（帧数、宽度）、封面抽帧的时间点。
- 可播放性判定方式（ffprobe 读编码后按浏览器支持表判，还是只按扩展名）。
- 测试策略（至少：番号识别回归、归位计划生成、出站产物可从 `file://` 打开）。
- 版本号位置（建议 `pyproject.toml`，站点页脚显示）。

## 6. 已知风险与取舍

- **不接 amane 的影响**：peach 的 censored 链里 prestige/faleno/dahlia 片商站、素人链的 mgstage、无码链的 avsox 都走 amane。第一版这些番号只能靠 avbase/javbus/javdb/r18dev/dmm 补，覆盖率会低一些；第二版再决定是接 amane 还是自写这几站。
- **站点反爬**：javdb、javbus 会 403/429；照 peach 做冷却和快照，失败的留到下次跑。
- **HEVC**：Chrome 在 macOS 上能硬解 HEVC，Windows 要装扩展；页面按 `canPlayType` 运行时探测，不写死。
- **`.shelf` 在 Windows 可见**：接受。
- **大库**：一万部片的 `works.js` 约 3–5 MB，可接受；更大按分片。
- **许可**：AGPL 传染，接受。
