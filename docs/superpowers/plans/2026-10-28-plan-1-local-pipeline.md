# Hidden Shelf 计划 1：本地流水线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不联网也能跑通「扫描 → 本地 NFO/封面导入 → 归位 → 出静态站」全流程的命令行版 Hidden Shelf，产物从 `file://` 打开即可浏览和播放。

**Architecture:** Python 包 `hidden_shelf`，策略模块从 peach 移植（番号识别、附属文件、NFO、字段归属、归位模板），编排层自写；SQLite 工作库和全部产物住在盘根目录的 `.shelf/` 下；静态站是「一个根 `index.html` + `.shelf/site/` 下的 app.js/app.css/data/*.js」的 hash 路由单页应用，数据以 `window.__shelf.*` 赋值的 JS 文件形式随站携带。

**Tech Stack:** Python ≥ 3.12 · uv · SQLite（stdlib）· Pillow · Jinja2 · 系统 ffmpeg/ffprobe · 前端纯 HTML/CSS/JS（`ux-standard` 的 `tokens.css` + `ripple.js`）· pytest · node 内建 `--test`（只测前端纯逻辑）

**Spec:** `docs/superpowers/specs/2026-10-28-hidden-shelf-design.md`

后续计划：计划 2「联网刮削」（来源链、分级、实体外站 ID、封面头像、代理与 Cookie），计划 3「进度网页」（FastAPI + SSE，端口按 `~/.claude/ports.md` 分配）。本计划不碰网络。

## Global Constraints

- Python `requires-python = ">=3.12"`；peach 要求 3.14，移植时去掉 3.14 专有语法。本机解释器 3.13.3。
- 运行时依赖只允许：`pillow`、`jinja2`。开发依赖：`pytest`。不要 click/typer（用 argparse）、不要 APScheduler、grpc、pystray、sentry、filelock。
- ffmpeg/ffprobe 用系统的（本机 `/usr/local/bin/ffmpeg`），找不到就报错提示安装，不托管二进制。
- 库里的 `asset.path` 是**相对盘根目录的 POSIX 形态**（`/` 分隔），不沿用 peach 的 Windows 形态和 `ntpath`。
- 媒体目录旁不写 NFO、封面、缩略图；派生产物全在 `.shelf/` 下（布局见 spec §4.2）。
- 绝不删用户的原始文件；旧 NFO 和多余图片只搬到 `.shelf/legacy/<番号>/`。只做同一卷内 `os.rename`，不跨盘拷贝。
- 归位固定顺序：备份库 → 动文件 → 改库；改库失败把文件改回去。
- `field_owners`：`user:*` 与 `review:*` 的字段，自动写入一律不许改。
- 静态站从 `file://` 打开：数据只能用 `<script src>` 加载的 `.js`，不能 `fetch`；视频和图片用相对路径；不加载任何外网资源（含字体）。
- 前端外观按 `~/.claude/skills/ux-standard/SKILL.md`：颜色、字号、间距只引用 `tokens.css` 变量；浅/深/系统主题；中英双语字典；加载/空/错误三态；可点击元素有波纹。字体栈用系统字体回退，不联网。
- 许可 AGPL-3.0-or-later；`docs/REUSE.md` 登记每个移植模块的 peach 源文件。
- 每个 git commit 用中文说明；每次改代码更新 `pyproject.toml` 的 `version`（本计划从 0.1.0 起，每个任务提交 +0.0.1）。
- 与用户交流用中文；代码注释中文；标识符英文。

## Review Focus

实施者在对应任务里为每条加测试（已在各任务步骤中标注「Review Focus」）：

1. **文件名含 `#`、`?`、`%`、空格、中日文**的视频：站点里 `<video src>` 必须仍能定位到文件（路径要 `encodeURI` 后分段处理 `#` 和 `?`）。→ Task 13。
2. **同一番号的多碟文件**（`ABP-758-cd1.mp4`、`ABP-758-CD2.mp4`、`ABP-758-A.mp4`）：归位后同目录、详情页列出全部碟，不能互相覆盖。→ Task 9、Task 12。
3. **目标路径已被另一个文件占着**（两份不同的 `ABP-758.mp4`）：第二份必须跳过并记 `目标已存在`，不能覆盖、不能丢。→ Task 10。
4. **第二次运行**：已归位的文件不再移动；用户在 `overrides.json` 改过的标题不被 NFO 重新导入覆盖；消失的文件在站点里不再显示但库里保留 `vanished=1`。→ Task 7、Task 10、Task 12。
5. **ffmpeg 不在或抽帧失败**（损坏文件、0 字节文件）：九宫格和封面抽帧失败只记日志，流水线继续，站点显示占位图，不中断。→ Task 11。

---

## 文件结构

```
Hidden-Shelf/
  pyproject.toml                      uv 项目；[project.scripts] shelf = "hidden_shelf.cli:main"
  LICENSE                             AGPL-3.0-or-later 全文
  docs/REUSE.md                       移植登记表：本项目文件 ← peach 源文件（含 commit）
  reference/peach/                    peach 浅克隆，.gitignore 排除，只读参考
  src/hidden_shelf/
    __init__.py                       __version__
    cli.py                            argparse：run / scan / import-local / organize / build；--no-move-unrecognized
    paths.py                          ShelfPaths：root → .shelf 下各目录；ensure()
    config.py                         ShelfConfig：读写 .shelf/config.json，默认值，code_patterns 编译
    db.py                             connect()、迁移（migrations/*.sql 顺序执行）、schema_version
    migrations/0001_init.sql          表结构（见 Task 5）
    field_owners.py                   ← peach field_owners.py
    rules/
      codes.py                        ← peach catalog_rules.py 番号部分（§Task 1 列出要留的函数）
      sidecars.py                     ← peach scan.py 的 medium_of / video_stems / is_sidecar / ARTWORK*
      nfo.py                          ← peach library_nfo.py（去 processing_traffic）
    scan.py                           遍历、登记、认番号、登记附属文件
    local_import.py                   NFO 与本地封面导入到库和 .shelf/covers
    organize/
      templates.py                    ← peach organize_templates.py（posixpath 版）
      plan.py                         build_plan：PlanRow、SKIP_* 常量
      apply.py                        apply_plan / rollback_batch / 备份库 / 附属文件搬迁 / 清空目录
    media/
      ffmpeg.py                       find_ffmpeg/find_ffprobe、probe()
      frames.py                       ← peach frame_capture.py（去 processing_control）
      fingerprint.py                  ← peach artifact_rules.py（去 upgrade_rules/fsutil）
      sheets.py                       九宫格
      covers.py                       封面安装、海报比例裁切、抽帧兜底
    site/
      build.py                        查询库 → 视图模型 → data/*.js → 渲染 index.html → 拷静态文件
      playability.py                  容器/编码 → play_hint
      templates/index.html.j2
      static/tokens.css               复制自 ~/.claude/skills/ux-standard/tokens.css
      static/ripple.js                复制自 ~/.claude/skills/ux-standard/ripple.js
      static/shelf-core.js            纯逻辑（搜索/筛选/排序/路径编码/可播放判定），UMD，node 可测
      static/app.js                   hash 路由与渲染
      static/app.css
      static/i18n.js                  中英字典
    pipeline.py                       run(root, config, progress) 串四步；Progress 回调协议
  tests/
    conftest.py                       fixtures：tmp_root（带 .shelf）、fake_video()（ffmpeg lavfi 生成 2 秒小视频）、db
    test_codes.py test_sidecars.py test_nfo.py test_field_owners.py test_paths_config.py test_db.py
    test_scan.py test_local_import.py test_templates.py test_plan.py test_apply.py
    test_media.py test_site_build.py test_pipeline_cli.py
    js/shelf-core.test.mjs            node --test
```

---

### Task 0: 脚手架与参考克隆

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `docs/REUSE.md`, `src/hidden_shelf/__init__.py`, `tests/conftest.py`, `tests/test_smoke.py`
- Modify: `.gitignore`（加 `reference/`、`.shelf/`、`*.db`）

**Interfaces:**
- Produces: 包 `hidden_shelf`，`hidden_shelf.__version__ == "0.1.0"`；fixture `tmp_root(tmp_path) -> Path`（空盘根目录）；fixture `fake_video(path: Path, seconds: float = 2.0, size: str = "320x240") -> Path`（用 `ffmpeg -f lavfi -i testsrc` 生成 h264/aac mp4，ffmpeg 不在则 `pytest.skip`）。

- [ ] **Step 1: 写 `pyproject.toml`**：`name = "hidden-shelf"`，`version = "0.1.0"`，`requires-python = ">=3.12"`，`dependencies = ["pillow>=11", "jinja2>=3.1"]`，`[dependency-groups] dev = ["pytest>=8"]`，`[project.scripts] shelf = "hidden_shelf.cli:main"`，`[build-system]` 用 hatchling，`[tool.pytest.ini_options] testpaths = ["tests"]`。`license = "AGPL-3.0-or-later"`。
- [ ] **Step 2: 克隆参考**：`git clone --depth 1 https://github.com/peach-mitao/peach.git reference/peach`，记下其 `git rev-parse HEAD` 写进 `docs/REUSE.md` 表头。`.gitignore` 加 `reference/`。
- [ ] **Step 3: 写 `LICENSE`**（AGPL-3.0-or-later 原文，可从 `reference/peach/LICENSE` 复制）和 `docs/REUSE.md`（表：本项目文件 | peach 源文件 | 改动摘要；先只写表头和 Task 0 行）。
- [ ] **Step 4: 写 `tests/conftest.py` 的两个 fixture 和 `tests/test_smoke.py`**：`test_version()` 断言 `hidden_shelf.__version__ == "0.1.0"`；`test_fake_video(fake_video, tmp_path)` 断言生成文件大小 > 0。
- [ ] **Step 5: 运行** `uv sync && uv run pytest -v`。Expected: 2 passed。
- [ ] **Step 6: Commit**：`chore: 脚手架、许可与 peach 参考克隆`

---

### Task 1: 番号识别规则移植（`rules/codes.py`）

**Files:**
- Create: `src/hidden_shelf/rules/__init__.py`, `src/hidden_shelf/rules/codes.py`
- Test: `tests/test_codes.py`
- Reference: `reference/peach/src/peach/catalog_rules.py`，断言来源 `reference/peach/tests/test_jav_code_domain.py`

**Interfaces:**
- Produces（签名与 peach 一致）：
  - `VIDEO_EXTENSIONS: frozenset[str]`
  - `release_code_from_filename(name: str | None, *, patterns: Iterable[re.Pattern] = ()) -> str | None`
  - `release_code_from_text(value: str | None) -> str | None`
  - `compile_code_patterns(raw) -> tuple[re.Pattern, ...]`（用户自定义正则，上限 `CODE_PATTERN_LIMIT = 20`、长度 `CODE_PATTERN_MAX_LENGTH = 200`）
  - `normalise_code_key(code) -> str`、`release_identity(code) -> str`、`same_release_code(a, b) -> bool`
  - `is_jav_code(code) -> bool`、`is_amateur_code`、`is_uncensored_code`、`is_korean_mib_code`、`scrapes_as_jav(code, studio=None, ...)`、`code_release_date(code) -> str | None`
  - `strip_promo_markers(name) -> str`、`is_repost_site_label(value) -> bool`、`jav_fallback_title(name, code) -> str`
  - `part_marker(name: str) -> str`（返回 `"cd1"`、`"a"`、`""` 这类分卷标记，照 peach）
  - `jav_edition_badges(name, code, ...)`（画质/字幕/无码版标，照 peach）
  - `VERSION_TAIL`、`REPOST_SITE_LABELS`、`CODE_BODY_STOPWORDS`
- 不移植：标签词表（`LENGTH_TAGS`…`RETIRED_TAGS`、`tag_cat`、`canonical_tag_name`）、`face_focus`、`dir_expr`/`solo_performer_clause`（SQL 片段）、`photo_set_title`、`fill_masked_title`、`duration_clusters`/`ordered_multipart_items`（留到计划 2 的版本聚类）。

- [ ] **Step 1: 写失败测试 `tests/test_codes.py`**。最少这些用例（期望值以在 `reference/peach` 里用 `uv run --python 3.14 python -c` 跑 peach 原函数的结果为准，写测试前先跑一遍核对）：

```python
import pytest
from hidden_shelf.rules.codes import (release_code_from_filename, normalise_code_key, is_jav_code,
    is_amateur_code, is_uncensored_code, scrapes_as_jav, part_marker, strip_promo_markers,
    compile_code_patterns, code_release_date)

@pytest.mark.parametrize("name,expected", [
    ("ABP-758.mp4", "ABP-758"),
    ("abp758.mp4", "ABP-758"),
    ("hhd800.com@ABP-758.mp4", "ABP-758"),
    ("[javdb.com]ABP-758-C.mp4", "ABP-758"),
    ("1080p ABP-758.mp4", "ABP-758"),
    ("259LUXU-1475.mp4", "259LUXU-1475"),
    ("092415_001.mp4", "092415_001"),
    ("092415-001.mp4", "092415-001"),
    ("HEYZO-1380.mp4", "HEYZO-1380"),
    ("FC2-PPV-1234567.mp4", "FC2-PPV-1234567"),
    ("VID_20241015_120000.mp4", None),
    ("IMG_1234.mp4", None),
    ("家庭录像.mp4", None),
])
def test_release_code_from_filename(name, expected):
    assert release_code_from_filename(name) == expected

def test_date_code_separator_is_identity():
    assert normalise_code_key("092415_001") != normalise_code_key("092415-001")

def test_part_markers():
    assert part_marker("ABP-758-cd1.mp4") == "cd1"
    assert part_marker("ABP-758-CD2.mp4") == "cd2"
    assert part_marker("ABP-758.mp4") == ""

def test_custom_pattern_first():
    patterns = compile_code_patterns([r"^(?P<code>MYLABEL\d{3})"])
    assert release_code_from_filename("MYLABEL001 whatever.mp4", patterns=patterns) == "MYLABEL001"

def test_creator_filename_not_scraped_as_jav():
    code = release_code_from_filename("sumwall95 masturbation_1.mp4")
    assert code == "SUMWALL-095"
    assert scrapes_as_jav(code, None, creator="sumwall95") is False

def test_code_kinds():
    assert is_amateur_code("259LUXU-1475")
    assert is_uncensored_code("092415_001")
    assert code_release_date("092415_001") == "2015-09-24"
```

另外把 `reference/peach/tests/test_jav_code_domain.py` 里直接调用上述函数、不依赖数据库和其他模块的断言整段搬过来（改 import），放在同一文件末尾。

- [ ] **Step 2: 运行** `uv run pytest tests/test_codes.py -v`。Expected: 全部 FAIL，`ModuleNotFoundError: hidden_shelf.rules`。
- [ ] **Step 3: 移植 `rules/codes.py`**：从 `catalog_rules.py` 复制番号相关的全部常量、私有正则、公开函数（连同每条规则上方的误判证据注释，一行都不要删）；删掉上面「不移植」列出的部分；`PureWindowsPath` 改成 `PurePosixPath`；去掉 3.14 专有语法。文件头注释写明来源与 commit。`VIDEO_EXTENSIONS`、`AUDIO_EXTENSIONS` 一并放这里。
- [ ] **Step 4: 运行** `uv run pytest tests/test_codes.py -v`。Expected: 全部 PASS。有期望值对不上时以 peach 原函数实跑结果改测试，不改规则。
- [ ] **Step 5: 在 `docs/REUSE.md` 加一行**，版本号 0.1.1，Commit：`feat: 移植 peach 番号识别规则`

---

### Task 2: 附属文件规则（`rules/sidecars.py`）

**Files:**
- Create: `src/hidden_shelf/rules/sidecars.py`
- Test: `tests/test_sidecars.py`
- Reference: `reference/peach/src/peach/scan.py` 第 52–75 行与 `medium_of` / `video_stems` / `is_sidecar`；断言来源 `reference/peach/tests/test_scan.py` 中与 `is_sidecar` 相关的用例

**Interfaces:**
- Produces：
  - `IMAGE_EXTENSIONS`、`ARCHIVE_EXTENSIONS`、`ARTWORK: frozenset[str]`（`poster`、`fanart`、`cover`、`thumb`、`landscape`、`banner`、`clearlogo` 等 peach 原集）、`ARTWORK_DIRS = {"extrafanart", "extrathumbs"}`
  - `medium_of(name: str) -> str`（`"video" | "image" | "audio" | "archive" | "nfo" | "subtitle" | "other"`；peach 没有 `nfo`/`subtitle` 档，这里加上，供导入和搬迁用）
  - `video_stems(names: Iterable[str]) -> frozenset[str]`
  - `is_sidecar(name: str, videos: frozenset[str], *, artwork_dir: bool = False) -> bool`（去掉 `path`/`library_roots` 参数：我们没有多根）
  - `sidecar_kind(name: str, videos: frozenset[str]) -> str | None`（新增：`"nfo" | "poster" | "fanart" | "cover" | "thumb" | "subtitle" | "other"`，`None` 表示不是附属文件；`ABP-758-poster.jpg` → `poster`，`ABP-758.nfo`、`movie.nfo` → `nfo`，`ABP-758.jpg`（与视频同名）→ `cover`，`ABP-758_4x4_thumb.jpg` → `thumb`，`ABP-758.srt` → `subtitle`）

- [ ] **Step 1: 写失败测试**：`test_medium_of`（`.mp4`→video，`.jpg`→image，`.nfo`→nfo，`.srt`→subtitle，`.iso`→video）、`test_is_sidecar_matches_video_stem`（同目录 videos={"ABP-758"}：`ABP-758-poster.jpg`、`ABP-758.nfo`、`ABP-758.mp4_thumbs.jpg` 为 True；`unrelated.jpg` 为 False；`artwork_dir=True` 时任何图都 True）、`test_sidecar_kind` 覆盖上面 Interfaces 列的每个例子。再搬 peach `test_scan.py` 里 `is_sidecar` 的断言。
- [ ] **Step 2: 运行** `uv run pytest tests/test_sidecars.py -v`。Expected: FAIL（ImportError）。
- [ ] **Step 3: 实现 `rules/sidecars.py`**，`is_sidecar` 逻辑照 peach（主名匹配、`_DERIVED_THUMB` 正则、`ARTWORK` 后缀、`ARTWORK_DIRS`），`sidecar_kind` 在其之上按后缀分类。
- [ ] **Step 4: 运行测试**。Expected: PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.1.2，Commit**：`feat: 移植附属文件判定规则`

---

### Task 3: NFO 读取（`rules/nfo.py`）

**Files:**
- Create: `src/hidden_shelf/rules/nfo.py`
- Test: `tests/test_nfo.py`
- Reference: `reference/peach/src/peach/library_nfo.py`；断言来源 `reference/peach/tests/test_metadata_library.py` 中 `read_nfo` / `SidecarIndex` 的用例

**Interfaces:**
- Consumes: Task 1 `release_code_from_filename`、`release_code_from_text`、`same_release_code`、`VIDEO_EXTENSIONS`
- Produces：
  - `class SidecarIndex(files: dict[str, Path])`：属性 `videos: list[Path]`、`nfos: list[Path]`；方法 `nfo_for(video: Path) -> Path | None`、`images_for(video: Path) -> list[Path]`（配对规则照 peach：同主名 > 番号同一 > 目录唯一 `movie.nfo`）
  - `directory_files(directory: Path) -> dict[str, Path]`
  - `read_nfo(path: Path) -> dict`：键固定为 `title original_title code studio series release_date year actors tags cover_url local_art plot`（没有的键不出现）；拒绝 DTD，读取上限 1 MiB + 1
  - `local_art(video: Path, payload: dict) -> Path | None`

- [ ] **Step 1: 写失败测试**：`test_read_nfo_basic`（临时写一个 Kodi 风格 `<movie>` NFO，含 `<title>`、`<num>ABP-758</num>`、`<studio>`、`<actor><name>甲</name></actor>` ×2、`<premiered>2019-05-10</premiered>`、`<thumb>https://x/cover.jpg</thumb>`；断言各键）、`test_read_nfo_rejects_dtd`（含 `<!DOCTYPE` 抛 `ValueError`）、`test_sidecar_index_pairs_by_stem_then_code`（目录里 `ABP-758.mp4`、`ABP-758.nfo`、`movie.nfo`、`ABP-758-poster.jpg`：`nfo_for` 取 `ABP-758.nfo`，`images_for` 含 poster）、`test_local_art_stays_inside_directory`（`local_art="../x.jpg"` → None）。
- [ ] **Step 2: 运行**，Expected FAIL。
- [ ] **Step 3: 移植 `rules/nfo.py`**：复制 peach 的 `SidecarIndex`、`read_nfo`、`local_art`、`directory_files`；删掉 `processing_traffic.record_media_read` 调用；`read_nfo` 的返回键按 Interfaces 固定（peach 原返回若键名不同，在这里统一改名）。
- [ ] **Step 4: 运行**，Expected PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.1.3，Commit**：`feat: 移植 NFO 读取与附属文件配对`

---

### Task 4: 字段归属（`field_owners.py`）

**Files:**
- Create: `src/hidden_shelf/field_owners.py`
- Test: `tests/test_field_owners.py`
- Reference: `reference/peach/src/peach/field_owners.py` 与 `reference/peach/tests/test_field_owners.py`

**Interfaces:**
- Produces（与 peach 同名）：`USER_MANUAL = "user:manual"`、`SCAN_FILENAME = "scan:filename"`、`review_owner(provider)`、`auto_owner(provider)`、`script_owner(name)`、`is_protected(owner) -> bool`（`user:*`、`review:*` 为 True）、`parse_owners(value) -> dict[str, str]`、`owner_of(value, field) -> str`、`@dataclass FieldWrite(field: str, value, owner: str, require_empty: bool = False)`、`write_owned_fields(connection, table: str, row_id: int, writes: Sequence[FieldWrite], *, owners_column: str = "field_owners", revision_column: str = "revision") -> dict[str, bool]`（返回每个字段是否真的写入；用逐字段 `CASE WHEN` 一条 UPDATE，受保护字段跳过，写入成功的字段把 owner 写进 JSON 列并 `revision + 1`）。
- 不移植：`check_revision`/`RevisionConflict`（没有并发编辑界面）。

- [ ] **Step 1: 写失败测试**（用内存 SQLite 建一张 `asset(id, title, studio, field_owners TEXT, revision INTEGER DEFAULT 0)`）：`test_auto_cannot_overwrite_user`（先以 `user:manual` 写 title，再以 `auto:nfo` 写，title 不变，返回 `{"title": False}`）、`test_auto_overwrites_auto`、`test_require_empty_only_fills_blank`、`test_is_protected`、`test_parse_owners_tolerates_garbage`（非 JSON → `{}`）。搬 peach `test_field_owners.py` 中不依赖账本夹具的断言。
- [ ] **Step 2: 运行**，Expected FAIL。
- [ ] **Step 3: 移植**，去掉 `expected_revision` 相关部分；表名、列名改成参数。
- [ ] **Step 4: 运行**，Expected PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.1.4，Commit**：`feat: 移植字段归属与受保护写入`

---

### Task 5: 盘上路径、配置与数据库

**Files:**
- Create: `src/hidden_shelf/paths.py`, `src/hidden_shelf/config.py`, `src/hidden_shelf/db.py`, `src/hidden_shelf/migrations/0001_init.sql`
- Test: `tests/test_paths_config.py`, `tests/test_db.py`

**Interfaces:**
- Produces：
  - `@dataclass(frozen=True) ShelfPaths(root: Path)`：属性 `shelf`（`root/.shelf`）、`db`（`shelf/shelf.db`）、`config`、`overrides`（`shelf/overrides.json`）、`site`、`site_data`（`site/data`）、`covers`、`posters`、`sheets`、`avatars`、`sources`、`legacy`、`logs`、`backups`、`unrecognized`（`root/未识别`）、`index_html`（`root/index.html`）；`ensure() -> None` 建全部目录；`relative(path: Path) -> str`（相对 root 的 POSIX 串，越界抛 `ValueError`）；`absolute(rel: str) -> Path`。
  - `@dataclass ShelfConfig`：`move_unrecognized: bool = True`、`dir_template: str = "{studio}/{code}"`、`file_template: str = "{code}[-cd{cd}]"`、`unknown_studio_dir: str = "_未知厂牌"`、`code_patterns: list[str] = []`、`language: str = "zh"`；`load(paths) -> ShelfConfig`（文件不存在用默认并写出）、`save(paths)`；`compiled_patterns()` 用 Task 1 的 `compile_code_patterns`。
  - `db.connect(paths: ShelfPaths) -> sqlite3.Connection`（`row_factory = sqlite3.Row`，`PRAGMA journal_mode=WAL; foreign_keys=ON`，自动跑迁移）、`db.migrate(connection)`、`db.schema_version(connection) -> int`。
  - 表（`0001_init.sql`）：
    - `asset(id PK, path TEXT UNIQUE, name, medium, size, mtime, first_seen, last_seen, vanished INT DEFAULT 0, code, code_key, part TEXT DEFAULT '', content_type, title, original_title, studio, series, release_date, plot, cover_file, poster_file, sheet_file, duration REAL, width INT, height INT, vcodec, acodec, container, play_hint, probed_at, field_owners TEXT DEFAULT '{}', revision INT DEFAULT 0)`；索引 `code_key`、`vanished`。
    - `sidecar(id PK, asset_id FK, path TEXT UNIQUE, kind, status TEXT DEFAULT 'pending', moved_to)`。
    - `entity(id PK, kind CHECK IN ('performer','studio','series','tag'), canonical_name, normalized_name, UNIQUE(kind, normalized_name))`、`entity_alias(entity_id FK, alias, normalized, UNIQUE(entity_id, normalized))`、`asset_entity(asset_id FK, entity_id FK, role, source, confidence REAL DEFAULT 1, PRIMARY KEY(asset_id, entity_id, role))`。
    - `run(id PK, started, finished, step, status, stats TEXT)`、`organize_batch(id PK, started, finished, log_path, status, moved INT, skipped INT)`、`schema_version(version INT)`。
  - `db.normalize_name(name: str) -> str`（NFC、casefold、去空白与全半角标点，供实体合并）。

- [ ] **Step 1: 写失败测试**：`test_paths_layout`（各属性相对 root 的位置与 spec §4.2 一致；`ensure()` 后目录存在）、`test_relative_rejects_outside`、`test_config_roundtrip_and_defaults`（无文件 → 默认值并落盘；改一项 save 再 load）、`test_connect_runs_migrations`（`schema_version == 1`，`asset`、`entity`、`asset_entity` 表存在）、`test_connect_is_idempotent`、`test_normalize_name`（`"Ａｂｃ 甲"` 与 `"abc甲"` 相同）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现三个模块与 SQL**。迁移按文件名排序逐个执行，执行后写 `schema_version`。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: 版本 0.1.5，Commit**：`feat: 盘上目录布局、配置与数据库迁移`

---

### Task 6: 扫描

**Files:**
- Create: `src/hidden_shelf/scan.py`
- Test: `tests/test_scan.py`
- Reference: `reference/peach/src/peach/scan.py` 的 `_walk`、`ingest_path`、`_UPSERT` 思路（不照抄：去掉 SMB、filelock、checkpoint、字幕、wants）

**Interfaces:**
- Consumes: Task 1 `release_code_from_filename`、`normalise_code_key`、`part_marker`；Task 2 `medium_of`、`video_stems`、`is_sidecar`、`sidecar_kind`；Task 4 `SCAN_FILENAME`、`write_owned_fields`；Task 5。
- Produces：
  - `@dataclass ScanResult(seen: int, added: int, updated: int, vanished: int, sidecars: int, unrecognized: int)`
  - `scan(connection, paths: ShelfPaths, config: ShelfConfig, *, progress: Callable[[str], None] = lambda m: None) -> ScanResult`
  - 行为：跳过 `.shelf/`、`未识别/`（但要把 `未识别/` 里的视频也登记，`content_type='unrecognized'`，便于站点列出）、`.DS_Store`、`._*`、`@eaDir`、`$RECYCLE.BIN`、`System Volume Information`；只登记 `medium in {video}` 的文件到 `asset`，附属文件登记到 `sidecar`（配对同目录主名）；`asset` 只写观测字段 `size mtime last_seen`（`first_seen` 首次）；番号写 `code`/`code_key`/`part`，owner `scan:filename`，用 `require_empty=True`（用户改过的番号不覆盖）；本次没见到的行 `vanished=1`，见到的 `vanished=0`；路径一律 `paths.relative()`。

- [ ] **Step 1: 写失败测试**（用 `tmp_root` 建目录树：`a/ABP-758.mp4`、`a/ABP-758-poster.jpg`、`a/ABP-758.nfo`、`b/259LUXU-1475-cd1.mp4`、`b/259LUXU-1475-cd2.mp4`、`c/随手拍.mp4`、`.shelf/x.mp4`，视频文件可以是 0 字节假文件）：`test_scan_registers_videos_and_codes`（3 个 asset，code 分别 `ABP-758`、`259LUXU-1475`×2，part `cd1`/`cd2`，`随手拍.mp4` code 为 NULL）、`test_scan_registers_sidecars`（2 条 sidecar，kind `poster`、`nfo`，`asset_id` 指向 ABP-758）、`test_scan_skips_shelf_dir`、`test_rescan_marks_vanished`（删 `c/随手拍.mp4` 再扫，该行 `vanished=1`，其余 0；再放回去扫，恢复 0）、`test_scan_keeps_user_code`（先以 `user:manual` 把某行 code 改成 `XYZ-001`，再扫不变）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现 `scan.py`**：`os.scandir` 递归（跟 peach 一样用显式栈，不用 `os.walk`，便于报进度），每个目录先算 `video_stems`，再分流视频/附属。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: 版本 0.1.6，Commit**：`feat: 扫描登记视频、附属文件与番号`

---

### Task 7: 本地 NFO 与封面导入

**Files:**
- Create: `src/hidden_shelf/local_import.py`
- Test: `tests/test_local_import.py`

**Interfaces:**
- Consumes: Task 3、Task 4、Task 5、Task 6 产出的 `asset`/`sidecar` 行。
- Produces：
  - `import_local(connection, paths, *, progress=...) -> ImportResult(nfo: int, covers: int, overrides: int)`
  - NFO：对每个 `status='pending'` 且 `kind='nfo'` 的 sidecar，`read_nfo` 后以 owner `auto:nfo` 写 `title original_title studio series release_date plot`（`code` 只在 asset 没有番号时写）；actors 建 `performer` 实体（按 `normalize_name` 合并）并写 `asset_entity(role='performer', source='nfo')`；tags 建 `tag` 实体；studio/series 同时建实体。写完 sidecar `status='imported'`。
  - 封面：`kind in ('cover','poster','fanart')` 的图片，按优先级 poster > cover > fanart 选一张复制到 `paths.covers / f"{code_key}.jpg"`（Pillow 打开后转 RGB 存 JPEG，质量 90；坏图跳过记日志），asset `cover_file` 写相对 `.shelf/` 的路径，owner `auto:local`；sidecar `status='imported'`。
  - `overrides.json`：格式 `{"<番号>": {"title": "...", "studio": "...", "performers": ["甲","乙"], "tags": [...]}}`；每次导入末尾读取，以 `USER_MANUAL` 写标量字段，`performers` 替换该 asset 的 `source='user'` 关联（先删旧 user 关联再写）。番号找不到的条目记日志跳过。
  - `apply_overrides(connection, paths) -> int` 单独可调。

- [ ] **Step 1: 写失败测试**：`test_import_nfo_fields_and_performers`（扫描后导入，断言 title/studio/release_date，`entity` 有两位 performer，`asset_entity` 两行，sidecar 状态 imported）、`test_import_cover_copies_to_shelf`（Pillow 生成一张 300×200 的 jpg 当 poster；导入后 `.shelf/covers/ABP-758.jpg` 存在，asset `cover_file` 非空）、`test_import_is_idempotent`（跑两次，entity 不重复）、`test_override_beats_nfo`（Review Focus 4：写 overrides 标题，导入后 title 为 override 值；再改 NFO 标题重新导入，仍为 override 值）、`test_bad_image_skipped`（把文本文件命名 `ABP-758-poster.jpg`，不抛异常）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。实体写入抽成 `entities.py` 里的 `ensure_entity(connection, kind, name) -> int` 与 `link(connection, asset_id, entity_id, role, source)`（新建 `src/hidden_shelf/entities.py`，计划 2 会扩展它）。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: 版本 0.1.7，Commit**：`feat: 导入本地 NFO、封面与用户覆盖`

---

### Task 8: 归位模板（`organize/templates.py`）

**Files:**
- Create: `src/hidden_shelf/organize/__init__.py`, `src/hidden_shelf/organize/templates.py`
- Test: `tests/test_templates.py`
- Reference: `reference/peach/src/peach/organize_templates.py` 与 `reference/peach/tests/test_organize.py` 中模板相关断言

**Interfaces:**
- Produces（与 peach 同名）：`TemplateError`、`MAX_COMPONENT = 120`、`MAX_PATH = 240`、`clean_filename(name) -> str`、`sanitise_component(value) -> str`、`template_fields(template) -> frozenset[str]`、`required_fields(template) -> frozenset[str]`、`validate_template(template, *, directory=False) -> str`、`render(template, values: dict[str, str], *, directory=False) -> str`（可选分组 `[...]` 内任一占位符缺值整段消失；返回已清洗、已截断的路径片段）、`PLACEHOLDERS = {"code","title","studio","series","year","actors","cd","definition"}`。
- 变化：`ntpath` 改 `posixpath`；仍然清洗 Windows 非法字符和保留名（盘可能插到 Windows 上）。

- [ ] **Step 1: 写失败测试**：`test_optional_group_drops_when_missing`（`"{code}[-cd{cd}]"` 无 cd → `ABP-758`，有 cd → `ABP-758-cd1`）、`test_illegal_chars_and_reserved_names`（title 含 `?:*` 被清掉；`CON` 变 `CON_`）、`test_validate_rejects_escape`（`"../{code}"`、`"/abs/{code}"`、`"{unknown}"` 抛 `TemplateError`）、`test_truncates_middle_not_tail`（超长 title 截中段保留番号）、`test_directory_template_allows_slash`（`"{studio}/{code}"` directory=True 合法，file 模板含 `/` 非法）。搬 peach 对应断言。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 移植**。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.1.8，Commit**：`feat: 移植归位路径模板`

---

### Task 9: 归位计划（`organize/plan.py`）

**Files:**
- Create: `src/hidden_shelf/organize/plan.py`
- Test: `tests/test_plan.py`
- Reference: `reference/peach/src/peach/organize.py` 的 `placeholder_values`、`_definition`、`build_plan`、`SKIP_*`

**Interfaces:**
- Consumes: Task 8；Task 5 的表；Task 1 `is_uncensored_release`、`part_marker`。
- Produces：
  - `SKIP_MISSING_FIELD = "字段缺失"`、`SKIP_TARGET_EXISTS = "目标已存在"`、`SKIP_TOO_LONG = "路径过长"`、`SKIP_VANISHED = "文件不在"`、`SKIP_UNRECOGNIZED_KEEP = "未识别-保持原地"`
  - `@dataclass PlanRow(asset_id: int, current_path: str, target_path: str, action: str, reason: str = "")`，`action in {"move", "skip"}`
  - `placeholder_values(row: sqlite3.Row, performers: list[str]) -> dict[str, str]`（`definition` 由 width/height 算 `4K/1080p/720p/SD`；`year` 取 release_date 前四位；`actors` 顶多 3 人以 `、` 连接；`cd` 取 `part`）
  - `build_plan(connection, paths, config, *, asset_ids=None) -> Plan(rows: list[PlanRow], counts: dict[str, int])`
  - 规则：有番号的 → `dir_template/file_template` 渲染，studio 缺则 `config.unknown_studio_dir/{code}`；无番号且 `config.move_unrecognized` → `未识别/<原相对路径>`；无番号且不搬 → skip `未识别-保持原地`；已在目标位置 → 只计 `counts["unchanged"]` 不进 rows；`vanished=1` → skip；同批内两行算出同一目标 → 第二行 skip `目标已存在`；目标在盘上已存在且不是自己 → skip `目标已存在`；扩展名保留原文件的（小写化）；渲染后总长超 `MAX_PATH` → skip `路径过长`。

- [ ] **Step 1: 写失败测试**：`test_plan_moves_to_studio_code_dir`（studio=`Prestige` → `Prestige/ABP-758/ABP-758.mp4`）、`test_plan_unknown_studio`（→ `_未知厂牌/ABP-758/ABP-758.mp4`）、`test_plan_multipart_same_dir`（Review Focus 2：cd1/cd2 → 同目录两个不同文件名）、`test_plan_unrecognized_toggle`（开关开 → `未识别/c/随手拍.mp4`；关 → skip）、`test_plan_duplicate_target_second_skips`（Review Focus 3）、`test_plan_unchanged_not_listed`、`test_plan_skips_vanished`。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: 版本 0.1.9，Commit**：`feat: 生成归位计划`

---

### Task 10: 归位执行与回滚（`organize/apply.py`）

**Files:**
- Create: `src/hidden_shelf/organize/apply.py`
- Test: `tests/test_apply.py`
- Reference: `reference/peach/src/peach/organize.py` 的 `_rename`、`_move_one`、`apply_plan`、`rollback_batch`

**Interfaces:**
- Consumes: Task 9 `Plan`/`PlanRow`；Task 5；Task 2 `sidecar_kind`。
- Produces：
  - `backup_database(paths) -> Path`（`sqlite3.Connection.backup` 到 `backups/shelf-<YYYYmmdd-HHMMSS>.db`，只保留最近 5 份）
  - `apply_plan(connection, paths, plan: Plan, *, progress=...) -> ApplyResult(moved: int, skipped: int, failed: int, batch_log: Path)`
  - 顺序：`backup_database` → 逐行：`os.makedirs(target.parent)` → 目标存在则改 skip `目标已存在` → `os.rename` → UPDATE `asset.path/name`（失败则 rename 回去并记 failed）→ 每行追加到 `logs/organize-<时间>.jsonl`（`{"asset_id","from","to","ok","error"}`）→ 该 asset 的 `sidecar` 行：`kind in (cover,poster,fanart)` 且已导入的 → 搬到 `legacy/<code_key>/`；`nfo` 与其他 → 同样搬到 `legacy/<code_key>/`；无番号的 sidecar 跟着视频去 `未识别/`。sidecar 更新 `status='moved'`、`moved_to`。
  - `remove_empty_dirs(root: Path, *, protect: set[Path]) -> int`：自底向上删空目录（只删空的；`.shelf`、`未识别`、root 本身不删；`.DS_Store` 单独存在的目录视为空，先删 `.DS_Store`）。
  - `rollback_batch(connection, paths, batch_log: Path) -> int`：按日志倒序 rename 回去并改库。
  - `organize(connection, paths, config, *, progress=...) -> ApplyResult`：`build_plan` + `apply_plan` + `remove_empty_dirs` + 写 `organize_batch` 行。

- [ ] **Step 1: 写失败测试**：`test_apply_moves_and_updates_db`、`test_apply_backup_created`、`test_apply_target_exists_not_overwritten`（Review Focus 3：预先在目标放一个不同内容文件，执行后两个文件都在，原文件未动）、`test_apply_sidecars_go_to_legacy`（poster、nfo 到 `.shelf/legacy/ABP-758/`，媒体目录里没剩图片）、`test_apply_unrecognized_moves_with_sidecars`、`test_apply_db_failure_renames_back`（monkeypatch 更新函数抛异常，文件仍在原位）、`test_remove_empty_dirs`、`test_rollback_restores`、`test_second_run_no_moves`（Review Focus 4：organize 两次，第二次 moved==0）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.1.10，Commit**：`feat: 归位执行、附属文件留底与回滚`

---

### Task 11: 媒体探测、九宫格与封面兜底

**Files:**
- Create: `src/hidden_shelf/media/__init__.py`, `media/ffmpeg.py`, `media/frames.py`, `media/fingerprint.py`, `media/sheets.py`, `media/covers.py`
- Test: `tests/test_media.py`
- Reference: `reference/peach/src/peach/frame_capture.py`、`artifact_rules.py`、`scripts/sheets.py`、`jav_poster_crop.py` 的 `ratio` 先验常量

**Interfaces:**
- Consumes: Task 5。
- Produces：
  - `ffmpeg.find_ffmpeg() -> str`、`find_ffprobe() -> str`（`shutil.which`，找不到抛 `FFmpegMissing(RuntimeError)`，消息含 `brew install ffmpeg`）；`probe(path) -> ProbeInfo(duration: float, width: int, height: int, vcodec: str, acodec: str, container: str)`（`ffprobe -v error -print_format json -show_streams -show_format`）。
  - `frames.capture_frame(ffmpeg, path, timestamp, destination, *, width=None) -> bool`、`capture_with_retry(...)`（照 peach：色彩元数据错误时加 `COLOR_OVERRIDE` 重试）、`tile_frames(ffmpeg, pattern, columns, rows, destination, ...)`。
  - `fingerprint.fingerprint(source: Path) -> dict`（size、mtime_ns、ino）、`current(artifact: Path, *, source) -> bool`、`remember(artifact, *, source)`（边车 `<artifact>.rule` JSON）。
  - `sheets.build_sheet(ffmpeg, video: Path, destination: Path, *, duration: float, columns=3, rows=3, frame_width=480) -> bool`（9 帧取 `duration * (i+0.5)/9`，跳过前 2 秒；每帧单独抽，失败的帧用黑图占位，最后 Pillow 拼图）。
  - `covers.poster_from_cover(cover: Path, destination: Path) -> bool`（宽高比在 `1.2–1.65` 之间视为 DVD 封套，裁右侧宽 = 高 × 0.704；否则整图等比缩放到 2:3 居中裁）、`covers.cover_from_frame(ffmpeg, video, destination, *, duration) -> bool`（取 `max(2, duration*0.2)` 秒那一帧）。
  - `media.process_assets(connection, paths, *, progress=...) -> MediaResult(probed, sheets, posters, frame_covers, failed)`：对未 probe 的 asset 写 duration/width/height/vcodec/acodec/container/play_hint（`play_hint` 由 Task 12 的 `playability` 算，这里先写 `""`，Task 12 补）；对有视频但无 `cover_file` 的抽帧作封面（owner `auto:frame`，优先级最低：之后导入的本地封面可覆盖，用 `require_empty`?—不，用 owner 比较：`auto:frame` 视作可被任何 `auto:*` 覆盖，实现时在 `local_import` 写封面前判断当前 owner 是否 `auto:frame`）；九宫格 `sheets/<code_key or asset_id>.jpg`，指纹未变则跳过；海报从 `cover_file` 生成到 `posters/`。失败只记日志、计数，不抛。

- [ ] **Step 1: 写失败测试**（全部依赖 `fake_video`，ffmpeg 不在则 skip）：`test_probe_reads_dimensions`（320×240、h264、aac、mp4，duration≈2）、`test_build_sheet_creates_3x3`（输出存在，宽 == 3×frame_width）、`test_fingerprint_skips_unchanged`（连跑两次第二次不重做：用 mtime 判）、`test_poster_crop_dvd_sleeve`（Pillow 造 800×538 的图 → 输出宽高比≈0.704）、`test_poster_crop_non_sleeve`（400×400 → 2:3）、`test_cover_from_frame`、`test_corrupt_file_does_not_raise`（Review Focus 5：0 字节 `.mp4` 过 `process_assets`，`failed==1`，不抛）、`test_missing_ffmpeg_message`（monkeypatch `shutil.which` → None，抛 `FFmpegMissing` 且消息含 `brew install ffmpeg`）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。移植 `frames.py`、`fingerprint.py` 时去掉 `processing_control.checkpoint`、`ffmpeg_options`、`upgrade_rules`、`fsutil`（原子写用 `tempfile` + `os.replace` 自己写一个 `atomic_write_text`，放 `hidden_shelf/fsutil.py`）。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.1.11，Commit**：`feat: 媒体探测、九宫格与封面海报生成`

---

### Task 12: 静态站数据与页面骨架（`site/build.py`）

**Files:**
- Create: `src/hidden_shelf/site/__init__.py`, `site/build.py`, `site/playability.py`, `site/templates/index.html.j2`, `site/static/tokens.css`（复制）, `site/static/ripple.js`（复制）, `site/static/i18n.js`, `site/static/app.css`（先只有骨架样式）
- Test: `tests/test_site_build.py`

**Interfaces:**
- Consumes: Task 5 表；Task 11 的探测字段。
- Produces：
  - `playability.play_hint(container: str, vcodec: str, acodec: str) -> str`：`"native"`（mp4/mov/m4v + h264 + aac/mp3/无音轨；webm + vp8/vp9/av1）、`"check"`（mp4 + hevc/av1；任何 + opus/ac3/flac）、`"unsupported"`（mkv/avi/wmv/rmvb/flv/ts/iso 或其他）。
  - `build.build_site(connection, paths, config, *, progress=...) -> BuildResult(works, performers, studios, series, tags, unrecognized)`
  - 产物：
    - `.shelf/site/data/works.js`：`window.__shelf=window.__shelf||{};window.__shelf.works=[...]`，每项 `{id, code, title, studio, series, date, year, performers:[entityId], tags:[entityId], duration, width, height, definition, kind ("censored"|"amateur"|"uncensored"|"fc2"|"other"), parts:[{id, path, name, size, container, vcodec, acodec, play_hint}], cover, poster, sheet, addedAt}`，同一 `code_key` 的多个 asset 合成一个 work，`parts` 按 `part` 排序；路径均为相对盘根目录的 POSIX 串（**不**预先 URL 编码，编码在前端做）。`vanished=1` 的 asset 不进站。
    - `data/entities.js`：`window.__shelf.entities={performers:[{id,name,avatar,count}],studios:[...],series:[...],tags:[...]}`
    - `data/unrecognized.js`：`[{id,path,name,size,duration,play_hint}]`
    - `data/meta.js`：`{version, builtAt, language, counts:{works,performers,...}, totalDuration, totalBytes}`
    - 单个 data 文件序列化后超过 5 MB 时按 `works` 分成 `works-1.js`、`works-2.js`…，`meta.js` 里 `dataFiles` 列出全部文件名，`index.html` 按它生成 `<script>`。
    - `<root>/index.html`：由 `index.html.j2` 渲染；`<script src=".shelf/site/data/...">` 顺序：tokens.css、app.css、i18n.js、data/*、shelf-core.js、ripple.js、app.js；`<title>藏片阁</title>`；`<noscript>` 提示。
    - `.shelf/site/` 下拷贝全部 static。
  - JSON 序列化用 `json.dumps(ensure_ascii=False, separators=(",",":"))`，并把 `</script` 转义为 `<\/script`。

- [ ] **Step 1: 写失败测试**：`test_play_hint_table`（参数化覆盖 Interfaces 的每档）、`test_build_writes_files`（扫描 + 导入后 build：`index.html`、`data/works.js`、`data/entities.js`、`data/meta.js`、`site/app.js` 存在）、`test_works_group_parts`（Review Focus 2：cd1/cd2 合成一个 work，parts 两项按序）、`test_vanished_excluded`（Review Focus 4）、`test_data_js_is_valid`（用正则取出 `=` 后的 JSON 文本 `json.loads` 成功；含 `</script>` 的标题被转义）、`test_split_when_large`（monkeypatch 阈值到 1 KB，生成 ≥2 个 works 文件且 meta.dataFiles 列全）、`test_index_references_all_data_files`。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。`app.js`、`shelf-core.js` 此任务先放最小占位（能加载不报错），Task 13 填。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: 版本 0.1.12，Commit**：`feat: 静态站数据文件与页面骨架`

---

### Task 13: 前端纯逻辑（`shelf-core.js`）

**Files:**
- Create: `src/hidden_shelf/site/static/shelf-core.js`
- Test: `tests/js/shelf-core.test.mjs`（`node --test`）

**Interfaces:**
- Produces（UMD：浏览器挂 `window.ShelfCore`，node `require`/`import` 可用）：
  - `encodeMediaPath(rel: string) -> string`：逐段 `encodeURIComponent` 后以 `/` 连接（保留 `/`，编码 `#`、`?`、`%`、空格、中日文）。
  - `searchWorks(works, query) -> works[]`：不区分大小写，匹配 code、title、studio、series、performers 名（传入已解析名）、tags；多词 AND；空串返回全部。
  - `filterWorks(works, filters) -> works[]`：`filters = {performers:[id], studios:[name], series:[name], years:[number|"none"], tags:[id], kinds:[kind], playable: null|true}`；同维度 OR，维度之间 AND。
  - `sortWorks(works, key, dir)`：`key in {"date","added","duration","code"}`，`dir in {"asc","desc"}`；空值排最后。
  - `facetCounts(works, dim)`：返回 `[{value, count}]` 按 count 降序。
  - `canPlay(part, canPlayType: (mime) => string) -> "yes"|"maybe"|"no"`：`native` → yes；`check` → 用 `canPlayType("video/mp4; codecs=\"hvc1\"")` 之类探测，`"probably"|"maybe"` → maybe，否则 no；`unsupported` → no。
  - `formatDuration(seconds)`（`1:23:45` / `12:34`）、`formatBytes(bytes)`。

- [ ] **Step 1: 写失败测试 `tests/js/shelf-core.test.mjs`**：`encodeMediaPath("厂牌/ABP-758/ABP-758 #1 50%.mp4")` 等于 `"%E5%8E%82%E7%89%8C/ABP-758/ABP-758%20%231%2050%25.mp4"`（Review Focus 1）；`searchWorks` 多词 AND 与大小写；`filterWorks` 的 OR/AND 组合与 `years:["none"]`；`sortWorks` 空值在最后；`canPlay` 三档；`formatDuration(3725)==="1:02:05"`。
- [ ] **Step 2: 运行** `node --test tests/js/`。Expected: FAIL（模块不存在或函数未定义）。
- [ ] **Step 3: 实现 `shelf-core.js`**（UMD 头：`(function(root, factory){ if (typeof module==="object"&&module.exports) module.exports=factory(); else root.ShelfCore=factory(); })(this, function(){ ... })`）。
- [ ] **Step 4: 运行**，PASS。在 `pyproject.toml` 不加 node 依赖；在 CLAUDE.md 命令节记 `node --test tests/js/`。
- [ ] **Step 5: 版本 0.1.13，Commit**：`feat: 前端搜索、筛选、排序与可播放判定`

---

### Task 14: 前端页面（`app.js`、`app.css`、`i18n.js`）

**Files:**
- Modify: `src/hidden_shelf/site/static/app.js`, `app.css`, `i18n.js`, `templates/index.html.j2`
- Test: 手动验证（下面步骤）；逻辑已在 Task 13 测过

**Interfaces:**
- Consumes: Task 12 的 `window.__shelf.*`；Task 13 `ShelfCore`；`tokens.css` 变量；`ripple.js` 的 `initRipple()`。
- Produces：hash 路由 `#/`（海报墙）、`#/work/<code_key>`、`#/performers`、`#/performer/<id>`、`#/studios`、`#/studio/<name>`、`#/series`、`#/series/<name>`、`#/tags`、`#/tag/<id>`、`#/unrecognized`、`#/stats`。

页面要求（照 spec §4.4）：
- 布局：左侧栏导航（`ux-standard` 的侧栏骨架）：首页、艺人、厂牌、系列、标签、未识别、统计；底部主题切换（浅/深/系统）和语言切换（中/英），存 `localStorage`。
- 海报墙：卡片 = 海报（`poster` 无则 `cover` 无则占位块）、番号、标题（两行截断）、演员（最多 3 人）、时长、画质标、类型标、可播放标（`maybe` 显示「可能」、`no` 显示「需外部播放器」）。顶部搜索框（防抖 150ms）、排序下拉；侧栏筛选面板：艺人、厂牌、系列、年份、标签、类型、仅可播放，每项带计数（`facetCounts`）。筛选状态写进 hash 查询参数（`#/?q=..&studio=..`），刷新保留。无结果显示空态文案。卡片按视口宽度自适应列数（grid `minmax(180px, 1fr)`）。列表超过 200 张时分页（每页 120，底部页码）。
- 详情页：左封面（`cover`），右资料表（番号、标题、原名、厂牌、系列、发行日、时长、分辨率、编码、类型、标签胶囊、演员头像链接）；中间 `<video controls preload="metadata">` + 碟片切换按钮（多碟）；`canPlay==="no"` 时不渲染 video，显示原因与「复制路径」按钮（`navigator.clipboard.writeText(绝对路径)`：绝对路径由 `location.href` 去掉 `index.html#...` 后解码拼接）；`maybe` 时渲染 video 并在上方给提示。下方九宫格图（点击放大为 overlay）。再下「同演员」「同系列」「同厂牌」各一行横向卡片（最多 12）。
- 名册页（艺人/厂牌/系列/标签）：头像或首字圆标 + 名字 + 作品数，搜索框过滤；点进去是带该筛选的海报墙。
- 未识别：表格（文件名、路径、大小、时长、可播放），点击行弹出同详情页的播放区。
- 统计：四张统计卡片（作品数、总时长、总大小、艺人数）+ 按类型、按年份的数字表。
- i18n：`i18n.js` 导出 `{zh: {...}, en: {...}}`，所有界面文案走 `t(key)`；缺键回退 zh。
- 错误态：`window.__shelf` 缺失或 data 文件加载失败（`<script onerror>`）时显示「站点数据不完整，请重新运行 shelf build」。
- 无障碍：侧栏与卡片可键盘到达；图片有 alt；对比度按 tokens。

- [ ] **Step 1: 按 `ux-standard` SKILL.md 第 0 节检查**：`tokens.css`、`ripple.js` 已在 Task 12 复制；`app.css` 只用变量，不出现裸色值（用 `grep -nE "#[0-9a-fA-F]{3,6}|rgb\(" app.css` 自查，Expected 无输出）。
- [ ] **Step 2: 写 `i18n.js`、`app.css`、`app.js`**，按上面要求。
- [ ] **Step 3: 造一个演示盘**：`uv run python -m hidden_shelf.cli run <tmp 盘>`（Task 15 之前可先用 `tests` 里同样的 fixture 脚本手工生成：3 部假视频 + 1 个未识别 + NFO），然后 `open <tmp 盘>/index.html`。
- [ ] **Step 4: 手动验证清单**（Chrome 与 Safari 各一遍；可用 claude-in-chrome 截图）：海报墙出图；搜索番号出现一张；筛选厂牌计数正确；点卡片进详情，`<video>` 能播放假视频；多碟切换可用；把一部的扩展名改成 `.mkv` 重 build 后显示「需外部播放器」+ 复制路径可用；主题切换与语言切换刷新后保留；`#/unrecognized` 列出那一条；控制台无报错。
- [ ] **Step 5: 版本 0.1.14，Commit**：`feat: 静态站页面：海报墙、详情、名册、未识别与统计`

---

### Task 15: 流水线与命令行

**Files:**
- Create: `src/hidden_shelf/pipeline.py`, `src/hidden_shelf/cli.py`
- Test: `tests/test_pipeline_cli.py`
- Modify: `CLAUDE.md`（命令、架构两节）、`~/Claude-Code/PROJECTS.md`（状态与技术栈）

**Interfaces:**
- Consumes: Task 6 `scan`、Task 7 `import_local`、Task 10 `organize`、Task 11 `process_assets`、Task 12 `build_site`。
- Produces：
  - `class Progress`：`step(name: str, total: int | None)`、`advance(n=1, message="")`、`log(level, message)`、`done(stats: dict)`；默认实现 `ConsoleProgress` 打印 `[扫描] 123/456 文件名`；计划 3 会实现 SSE 版本。
  - `pipeline.run(root: Path, *, config: ShelfConfig | None = None, steps: Sequence[str] = ("scan","import","organize","media","build"), progress: Progress = ConsoleProgress()) -> dict`：每步写 `run` 表一行；每步开始与结束写 `logs/run-<时间>.log`；任一步抛异常则记录、停止后续步、返回非零。`organize` 后要再 `scan` 一次（路径变了），这由 `run` 内部做，不暴露。
  - `cli.main(argv=None) -> int`：子命令 `run <root>`、`scan <root>`、`import-local <root>`、`organize <root>`、`media <root>`、`build <root>`；通用选项 `--no-move-unrecognized`（本次运行覆盖 config）、`--dir-template`、`--file-template`、`--verbose`。`run` 结束打印 `成品：<root>/index.html`。root 不存在或不是目录 → 退出码 2 并说明。

- [ ] **Step 1: 写失败测试**：`test_run_end_to_end`（fixture 盘：`a/ABP-758.mp4`（fake_video）+ NFO（studio Prestige）+ poster、`b/259LUXU-1475-cd1.mp4`、`c/随手拍.mp4`；`run` 后断言：`Prestige/ABP-758/ABP-758.mp4` 存在、`_未知厂牌/259LUXU-1475/259LUXU-1475-cd1.mp4` 存在、`未识别/c/随手拍.mp4` 存在、`a/` `b/` `c/` 已删、`.shelf/legacy/ABP-758/` 有 nfo 与 poster、`.shelf/sheets/ABP-758.jpg` 存在、`index.html` 存在、`data/works.js` 含 `"ABP-758"`）、`test_run_twice_is_stable`（第二次 moved==0，文件位置不变）、`test_cli_no_move_unrecognized`（加旗标后 `c/随手拍.mp4` 仍在原地）、`test_cli_bad_root_exit_2`。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现 `pipeline.py`、`cli.py`**。
- [ ] **Step 4: 运行全部** `uv run pytest -v && node --test tests/js/`。Expected: 全部 PASS。
- [ ] **Step 5: 更新 `CLAUDE.md`**：「命令」节写 `uv sync`、`uv run shelf run <盘根目录>`、`uv run pytest`、`uv run pytest tests/test_codes.py -k name`、`node --test tests/js/`；「架构」节写：策略模块移植自 peach（列表 + REUSE.md 指引）、数据流四步、`.shelf/` 布局指向 spec、静态站 `file://` 约束（数据必须是 `.js`）、归位事务顺序、`field_owners` 规则、版本号在 `pyproject.toml`。状态改 v0.1.15。更新 `PROJECTS.md` 该行（状态 🟢 v0.1.15、技术栈 `Python ≥3.12 · uv · SQLite · Pillow · Jinja2 · ffmpeg · 纯静态前端`）并 `node ~/Claude-Code/Artifacts/build-overview.mjs`。
- [ ] **Step 6: 版本 0.1.15，Commit**：`feat: 流水线与命令行入口；更新项目文档`

---

## 自检记录

- Spec 覆盖：§4.2 布局 → Task 5/10；§4.3 四步 → Task 6/7/10/11/12/15（联网刮削留计划 2，进度网页留计划 3，`junk.py` 垃圾文件判定留计划 2 一并做，因为它依赖番号与时长聚类）；§4.4 静态站 → Task 12/13/14；§4.5 命令行 → Task 15，网页留计划 3；§4.7 实体层最小版 → Task 7 `entities.py`；`overrides.json` → Task 7；许可与 REUSE → Task 0 与各移植任务。
- 类型一致：`ShelfPaths`、`ShelfConfig`、`Plan`/`PlanRow`、`Progress` 在各任务引用同名；`code_key` 作为文件名与 work 分组键贯穿 Task 6/10/11/12。
- Review Focus 五条各有对应测试（已标注）。
