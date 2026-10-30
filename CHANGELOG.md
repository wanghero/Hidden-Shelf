# 更新日志

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## 0.4.0 - 2026-10-30

第一个面向外人的版本（计划 5「开源准备」）。

### 新增

- 归位预演：`shelf run <盘根目录> --dry-run` 与进度网页的「只预演」开关。列出每个要搬的文件与不搬的原因，完整清单写在 `.shelf/logs/plan-<时间>.txt`，盘上 `.shelf/` 之外一个字节不动；媒体与出站两步跳过。
- GitHub Actions CI：ubuntu / macos / windows 三平台跑全部 Python 与前端测试（Windows 允许失败，未验证）。
- README 改写成用户视角，新增英文版 `README.en.md`。
- `CONTRIBUTING.md`、issue 模板（程序出错、来源坏了）。

### 修复

- JavArchive 标题里发帖者留下的反斜杠转义（`みお\(19\)`）现在会还原。
- 进度网页：带 `display` 的类盖过了 `[hidden]`，预演之后「打开成品」按钮仍会显示。

### 历史

0.4.0 之前的变更见 git log 与 `docs/superpowers/plans/` 下的五份实施计划（本地流水线、联网刮削、进度网页、盘根目录鼠标选择、开源准备）。
