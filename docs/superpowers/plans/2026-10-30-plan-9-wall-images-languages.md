# Hidden Shelf 计划 9：未识别上墙、图片回写原目录、三语站点、标签三语 Implementation Plan

> **For agentic workers:** 本计划由本机会话直接实现（用户 2026-10-30 定）。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户 2026-10-30 的五条要求：① 下个版本从 v1.4.x 起；② 未识别的视频也列进海报墙，艺人写成「素人」，厂牌与系列各加一个「未识别」；③ 加一个选项，把刮削后的封面与九宫格复制到作品自己的目录；④ 语言从「中 / EN」改成 CH / EN / JP 三选；⑤ 标签也按中 / 英 / 日显示。

**Architecture:** ② 在 `site/build.py::_view_model` 里把没番号的视频也做成作品条目（`id="u:<asset_id>"`、`kind="unrecognized"`、厂牌与系列用哨兵值 `__unrecognized__`、艺人用哨兵实体 id 0），前端按当前语言把哨兵显示成「未识别 / 素人」；原来的「未识别」表格页保留。③ 新配置 `images_in_work_dir`（默认关），媒体步末尾 `media/place.py::place_images` 把 `covers/<番号>.jpg`、`sheets/<碟>.jpg` 复制成 `<番号>-cover.jpg`、`<碟名>-sheet.jpg` 放到视频所在目录，并在 `sidecar` 表记 `status='placed'`，扫描不当它是待导入附属文件、归位时随视频进新目录（不进 legacy）、关掉选项时删掉这些副本（只删自己放的）。④ 站点与进度网页的字典各加 `ja`，语言按钮变成三档循环；`ShelfConfig.language` 允许 `ja`。⑤ `tags_i18n.py` 一张「日 / 中 / 英」对照表，出站时给每个标签带 `names: {zh, en, ja}`，前端按语言显示、搜索三种都匹配；表里没有的原样显示。

**Tech Stack:** 现有。

**Spec:** 设计文档 §4.2（布局）、§4.6（站点）。③ 是对「媒体目录旁不写任何附属文件」的用户明确例外：默认仍不写，开了选项才写，且只写自己能认出来的副本。

## Global Constraints

- 版本：Task 1 → **1.4.0**，之后每任务 +0.0.1。三处同改，提交信息中文，提交后 push。
- 站点仍从 `file://` 打开，数据只走 `<script src>`；前端只用 token。
- 三套字典（zh / en / ja）键必须一致（站点与进度网页各一份测试钉住）。

## Review Focus

1. **未识别条目上墙后不能把统计撑坏**：作品数仍按有番号的算；「未识别」厂牌只在有未识别视频时出现。→ `test_unrecognized_listed_on_wall`。
2. **回写的图片不被当成本地封面再导入、不被搬去 legacy**：开选项跑两遍，`sidecar` 里是 `placed`，`covers/` 不变；归位后副本跟到新目录。→ `test_placed_images_survive_rescan_and_organize`。
3. **关掉选项要收回副本**：只删 `placed` 记录指向的文件，用户自己的图片不动。→ `test_placed_images_removed_when_option_off`。
4. **三语字典同键**：站点与进度网页各一份。→ 扩展现有 `test_i18n_dictionaries_have_same_keys`。
5. **标签翻译查不到就原样**：出站 `names` 三个键都存在，未知标签三个键相同。→ `test_tag_names_in_three_languages`。

---

### Task 1: 未识别视频上墙（1.4.0）
- `site/build.py`：`_KINDS` 加 `unrecognized`；无番号的视频也进 `works`（哨兵见上）；`entities.studios/series` 含哨兵项，`entities.performers` 含 `{id: 0, name: "__amateur__"}`。
- `site/static/app.js`：`localizeData()` 在加载与切换语言时把哨兵换成 `t('placeholder.unrecognized')` / `t('placeholder.amateur')`；卡片与详情在没番号时用文件名当标题、番号位显示「未识别」。
- `i18n.js`：`kind.unrecognized`、`placeholder.unrecognized`、`placeholder.amateur`。
- 测试：`tests/test_site_build.py::test_unrecognized_listed_on_wall`。

### Task 2: 封面与九宫格回写原目录（1.4.1）
- `config.ShelfConfig.images_in_work_dir: bool = False`；命令行 `--images-in-work-dir`；网页开关 `images_in_work_dir`。
- `media/place.py::place_images(connection, paths, config, progress) -> PlaceResult(copied, removed)`；`pipeline` 媒体步末尾调用。
- `scan.py`：`_register_sidecar` 的 upsert 只动 `pending`（已如此）；陈旧清理只删 `pending`（已如此）。`organize/apply.py::_move_sidecars`：`placed` 的随视频进新目录并更新 `path`；回滚按日志改回。
- 测试：`tests/test_place.py` 三个用例（Review Focus 2、3 + 多碟共用封面）。

### Task 3: 站点与进度网页三语（1.4.2）
- `site/static/i18n.js`、`serve/static/i18n.js` 各加 `ja`；语言按钮三档循环 `zh → en → ja`，文案 `CH / EN / JP`；`<html lang>` 对应 `zh-CN / en / ja`；`ShelfConfig.language` 与 `--language` 允许 `ja`；模板按语言。
- 测试：同键测试扩到三套；`test_japanese_language_sets_lang`。

### Task 4: 标签三语（1.4.3）
- `tags_i18n.py`：`TAG_NAMES: tuple[tuple[ja, zh, en], ...]` 常见类别表；`tag_names(name) -> dict`。
- `site/build.py`：`entities.tags[].names`；前端 `tagName(id)` 按语言取，搜索匹配三种。
- 测试：`test_tag_names_in_three_languages`、JS 搜索测试。
