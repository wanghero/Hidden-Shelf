# 更新日志

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## 0.4.16 - 2026-10-30

### 新增

- 进度网页新增「来源与登录」面板：每站一个开关（关掉整站不问）、登录状态、冷却状态；要登录或要过验证的站（JavDB、JavBus、AVBase）有「登录」按钮，点了在本机弹出浏览器窗口，登录完关窗口或点「我已登录完成」，Cookie 与浏览器 UA 自动存进全局配置；冷却中的站可以一键「清除冷却」。接口 `GET/POST /api/sources`、`POST /api/login`、`POST /api/login/finish`、`POST /api/cooldown/clear`（都要同源头）。

## 0.4.15 - 2026-10-30

### 新增

- `shelf login <站>`：弹出浏览器登录来源站（javdb、javbus、avbase），登录完关窗口或按回车，该站 Cookie 与浏览器 User-Agent 存进 `~/.hidden-shelf/config.json`，之后刮削带着它们请求。AVBase 的 Cloudflare 放行 Cookie 绑 UA，所以 UA 一起存。Playwright 是可选依赖：`uv sync --extra login` 再 `uv run playwright install chromium`，没装时命令行与网页都给出这两条命令。
- 传输层改成「配置里有这一站的 Cookie 就带」，不再只认登记了需要 Cookie 的站。

## 0.4.14 - 2026-10-30

### 新增

- JavBus 解析器抓類別栏当标签（有码作品页才有這一栏；JavBus 的无码区不标类别，那些页仍不给标签）。之前这一站只给标题、厂牌、演员等，只靠它刮到的有码片标签页是空的。

## 0.4.13 - 2026-10-30

### 修复

- 归位改名后文件名里没了发行站名（`Catwalk CWPBD-120 …` → `CWPBD-120.mp4`），重扫时内容类型会从「无码」回落成「有码」。现在库里的厂牌是登记过的无码片商就仍算无码。

## 0.4.12 - 2026-10-30

### 新增

- 转载站把厂牌名写在番号前面的文件名也能认（`Catwalk CWPBD-120 Miku Ohashi - ….mp4` → `CWPBD-120`）：登记过的无码厂牌名（Catwalk / Catwalk Poison、Caribbeancom、1pondo、10musume、Pacopacomama、Muramura、HEYZO、Tokyo Hot）可以站在番号前面；别的英文词站在前面仍按片名处理，不认。Catwalk 同时登记为无码发行站，厂牌 キャットウォーク 归一为 **Catwalk**。

## 0.4.11 - 2026-10-30

### 变更

- 归位时，作品自己的目录（目录名里就是这个番号，如 `Tokyo Hot n0610 乙音奈々/`、`_未知厂牌/n0610/`）里剩下的零散文件（截图、说明、没配上对的图片）跟着视频进新目录，名字不变；只带该目录顶层的普通文件，子目录、`.DS_Store` 之类系统垃圾、别的视频与已登记的附属文件不在此列，目标撞名另起名字绝不覆盖。预演清单里以 `EXTRA` 行列出，批次日志记 `extra`，回滚一并放回。已登记的 NFO、海报等附属文件仍按原规则进 `HiddenShelf/legacy/<番号>/`。

## 0.4.10 - 2026-10-30

### 修复

- 上一趟留下的单站冷却（如 avbase 403 后的 24 小时）会让整趟刮削在第一个番号就停下，别家来源一个都没问到。现在只有本趟请求次数或时间预算用完才整趟停；单站冷却只让那一家歇着，javbus、javdb 照问，后面的番号照跑。

## 0.4.9 - 2026-10-30

### 新增

- 番号形状独属一家片商的，导入步直接补上厂牌，不等联网刮削：Tokyo-Hot 的 `n####`／`k####`／`red-###` 与 HEYZO 的 `HEYZO-####`。归属记 `auto:local`，联网来源不覆盖，用户手写的照旧最高；已有厂牌的不动。老盘再跑一次 `shelf run` 会把 `_未知厂牌/n0610/` 搬到 `Tokyo-Hot/n0610/`。日期式番号（カリビアンコム、一本道、天然むすめ 同形）不猜。

## 0.4.7 - 2026-10-30

### 变更

- 无码片商的厂牌全部统一成官网英文名：一本道 → 1pondo、天然むすめ → 10musume、パコパコママ → Pacopacomama、ムラムラってくる素人 → Muramura、東京熱 → Tokyo-Hot、heyzo → HEYZO（0.4.6 已改 Caribbeancom）。老库在下一次 `shelf run` 的导入步自动改名，归位把 `一本道/` 等目录搬到英文名下。

## 0.4.6 - 2026-10-30

### 变更

- 厂牌 カリビアンコム 一律写成英文 **Caribbeancom**（`Carib`、`caribbeancom` 等写法同样归一；カリビアンコムプレミアム → Caribbeancompr）：刮削结算、NFO 导入、厂牌实体三处生效；已经刮过的老库在下一次 `shelf run` 的导入步自动改名并合并实体，归位会把 `カリビアンコム/` 搬到 `Caribbeancom/`。`overrides.json` 里用户自己写的字不动。

## 0.4.5 - 2026-10-30

### 修复

- 老盘（只有 `.shelf/`）第一次用 0.4.2–0.4.4 跑会失败：读配置时抢先建出了 `HiddenShelf/config.json`，迁移再看到两个目录并存就拒绝，而且是裸 traceback。现在迁移在开跑前检查里、读配置之前做；`ShelfConfig.load` 不再写盘，默认配置由建目录那一步写出；老盘自带的配置原样带过去。
- 命令行：开跑后才发现两目录并存或盘只读，也按退出码 2 打一句人话，不再甩 traceback。
- CI（0.4.3、0.4.4）：macOS 改用 Homebrew 装 ffmpeg；一个目录列举测试按平台拼绝对路径，Windows 整套测试通过。

## 0.4.2 - 2026-10-30

资料目录改成普通可见目录（计划 6）。

### 变更

- 盘根下的资料目录从隐藏的 `.shelf/` 改名为可见的 **`HiddenShelf/`**（纯 ASCII、Windows 合法；不设隐藏属性）。目录名只在 `paths.SHELF_DIR` 一处写死。
- 老盘自动迁移：任何子命令或进度网页开跑时，发现旧 `.shelf/` 就原地改名为 `HiddenShelf/`，日志记一行；库里的相对路径不用改，`index.html` 由下一次出站重写。
- 两个目录都在（手工复制过）时拒绝运行：命令行退出码 2、网页 400，提示保留一个。

## 0.4.0 - 2026-10-30

第一个面向外人的版本（计划 5「开源准备」）。当时资料目录还叫 `.shelf/`，下文按 0.4.2 之后的名字写。

### 新增

- 归位预演：`shelf run <盘根目录> --dry-run` 与进度网页的「只预演」开关。列出每个要搬的文件与不搬的原因，完整清单写在 `HiddenShelf/logs/plan-<时间>.txt`，盘上 `HiddenShelf/` 之外一个字节不动；媒体与出站两步跳过。
- GitHub Actions CI：ubuntu / macos / windows 三平台跑全部 Python 与前端测试（Windows 允许失败，未验证）。
- README 改写成用户视角，新增英文版 `README.en.md`。
- `CONTRIBUTING.md`、issue 模板（程序出错、来源坏了）。

### 修复

- JavArchive 标题里发帖者留下的反斜杠转义（`みお\(19\)`）现在会还原。
- 进度网页：带 `display` 的类盖过了 `[hidden]`，预演之后「打开成品」按钮仍会显示。

### 历史

0.4.0 之前的变更见 git log 与 `docs/superpowers/plans/` 下的五份实施计划（本地流水线、联网刮削、进度网页、盘根目录鼠标选择、开源准备）。
