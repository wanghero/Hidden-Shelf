# 更新日志

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

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
