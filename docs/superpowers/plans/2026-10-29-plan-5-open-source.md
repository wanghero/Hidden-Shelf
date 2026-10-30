# Hidden Shelf 计划 5：开源准备（预演、CI、面向外人的文档）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让陌生人敢把自己的盘交给这个程序：加 `--dry-run` 预演（列出要搬的文件、一个不动），加三平台 CI，把 README 改写成用户视角（中英两份），补 CONTRIBUTING、issue 模板、CHANGELOG 与免责声明，版本升到 0.4.0。公开仓库与打标签由用户本机手动做，不在本计划内。

**Architecture:** 预演复用 `organize/plan.py` 的 `build_plan`（计划与执行本来就共用一份判据），新增 `organize/apply.py::preview_organize` 只打印、只写 `HiddenShelf/logs/plan-<时间>.txt`，不备份、不改名、不记 `organize_batch`。`pipeline.run` 加 `dry_run` 参数：`organize` 步改调预演且不再 rescan，`media`、`build` 走现有的 `skipped` 分支（原因 `--dry-run`）。命令行与进度网页各加一个开关，和 `--offline` 并列。CI 用 GitHub Actions 跑现有测试（测试永不联网，天然适合）。文档不改代码行为。

**Tech Stack:** 现有：Python ≥ 3.12 + uv、FastAPI、原生 JS、ux-standard token；CI 用 GitHub Actions（`astral-sh/setup-uv`、`FedericoCarboni/setup-ffmpeg`、`actions/setup-node`）。不加运行时依赖。

**Spec:** `docs/superpowers/specs/2026-10-28-hidden-shelf-design.md` §4.3（流程）、§4.5（CLI/网页）、§6（风险）。本计划是用户 2026-10-29 决定开源后追加的；「预演」是设计文档没有、但面向外人必须有的功能（设计文档 §4.3 的「不确认直接归位」只对作者自己成立）。

## Global Constraints

- **先做计划 6**（`2026-10-29-plan-6-visible-data-dir.md`，资料目录 `.shelf/` 改为可见的 `HiddenShelf/`），再做本计划。本计划里的 `HiddenShelf/` 就是改名后的资料目录（原 `.shelf/`），代码里用 `paths.SHELF_DIR`。每个任务提交 +0.0.1（`pyproject.toml`、`src/hidden_shelf/__init__.py`、`tests/test_smoke.py` 三处同改），接着计划 6 的最后一个版本号往上数，最后一个任务升到 **0.4.0**。提交信息中文。
- 测试永不联网（`tests/conftest.py` 的 `isolated_home`）；CI 里也不许联网。
- 预演的承诺要能被测试钉住：**`HiddenShelf/` 之外一个字节都不改**（扫描、导入、刮削照常写 `HiddenShelf/`，这是算出计划的前提，文档里要如实写）。
- 文档里不出现作者本机的私有路径（`~/Claude-Code/...`、`~/.claude/...`、`/Volumes/Seagate-8T/...`）。截图已由本机准备好：`docs/images/wall.jpg`（海报墙）、`docs/images/progress.jpg`（进度网页）、`docs/images/picker.jpg`（目录选择器），都来自演示数据，直接引用，不要重新生成。
- 刮削来源在作者本机 2026-10-29 的真实冒烟结果（写进 README「来源」一节，不要编别的）：r18dev、javbus、javdb、fc2、javarchive 直连可用；dmm 对 `ABW-358` 回「没有这个番号」；avbase 回 403 进冷却（需要浏览器 Cookie）。
- `i18n.js` 两套 key 必须一致（`tests/test_serve_app.py::test_i18n_dictionaries_have_same_keys`）；`progress.css` 只用 token（`test_progress_css_uses_only_tokens`）。
- 不加载外网资源的约束不变；README 里的 CI 徽章是图片外链，只在 README 里，不进站点。

## Review Focus

1. **从没扫过的盘上直接 `shelf run --dry-run`**：会创建 `HiddenShelf/`（库、日志、快照、封面），但盘上其它地方一个文件不动、一个目录不建、不删空目录。→ Task 2 `test_dry_run_touches_only_shelf_dir`。
2. **几万条计划**（整块盘）：终端只打前 200 行再提示「还有 N 条，完整清单见 `HiddenShelf/logs/plan-<时间>.txt`」，清单文件写全；进度网页不会被几万条 `step.progress` 拖死（`RunLog` 环形缓冲本来就淘汰 `step.progress`）。→ Task 1 `test_preview_caps_console_lines_but_writes_full_file`。
3. **预演之后真跑**：预演报 N 个要搬，接着真跑（同样参数）搬的就是这 N 个，不多不少；预演不留下任何让真跑行为变化的状态。→ Task 2 `test_dry_run_then_real_run_matches`。
4. **模板不合法时预演**：不抛、退出码 0，计划里每行都是 `跳过：模板不合法：…`，清单文件也写这条原因。→ Task 1 `test_preview_reports_bad_template`。
5. **Windows**：作者只在 macOS 验证过；CI 的 windows job 允许失败（`continue-on-error: true`），README 平台一节如实写「macOS 已验证，Linux 由 CI 验证，Windows 未验证」。CI 第一次在 GitHub 上跑的结果由本机看，云端不用等。→ Task 5、Task 6。

---

## 文件结构

```
src/hidden_shelf/
  organize/apply.py            修改：preview_organize()、_write_plan_file()
  pipeline.py                  修改：run(dry_run=)、RunResult.dry_run、_skip_reason()
  cli.py                       修改：--dry-run 开关与预演结束那一行
  serve/runner.py              修改：RunOptions.dry_run
  serve/static/progress.js     修改：「只预演」开关、结果文案
  serve/static/i18n.js         修改：form.dry_run、result.dry_run、toast.dry_run
  scrape/sources/javarchive.py 修改：标题反转义
tests/
  test_apply.py                新增预演测试
  test_pipeline_cli.py         新增 dry-run 端到端与命令行测试
  test_runner.py、test_serve_app.py、serve_fakes.py   dry_run 透传
  test_sources_community.py    javarchive 标题断言
.github/workflows/test.yml     新增 CI
.github/ISSUE_TEMPLATE/        新增 bug_report.md、source_broken.md
README.md、README.en.md、CONTRIBUTING.md、CHANGELOG.md   文档
CLAUDE.md                      「当前阶段」「命令」更新
```

---

### Task 1: 归位预演 `preview_organize`

**Files:**
- Modify: `src/hidden_shelf/organize/apply.py`
- Test: `tests/test_apply.py`

**Interfaces:**
- Consumes: `organize.plan.build_plan(connection, paths, config) -> Plan`（`Plan.rows[PlanRow(asset_id, current_path, target_path, action, reason)]`、`Plan.counts`、`Plan.reasons`）。
- Produces: `preview_organize(connection: sqlite3.Connection, paths: ShelfPaths, config: ShelfConfig, *, progress: Progress = lambda m: None) -> dict`，返回 `{"dry_run": True, "total": int, "move": int, "unchanged": int, "skip": int, "reasons": {原因: 数量}, "plan_file": "<相对 HiddenShelf/ 的路径，如 logs/plan-20261029-170000.txt>"}`。常量 `PREVIEW_CONSOLE_LIMIT = 200`。

- [ ] **Step 1: 写失败的测试**（加到 `tests/test_apply.py`，复用现有 `disk` 夹具）

```python
def _snapshot(root: Path) -> dict[str, int]:
    """盘上 .shelf 之外每个文件的大小；预演前后必须一模一样。"""
    return {str(p.relative_to(root)): p.stat().st_size
            for p in root.rglob("*") if p.is_file() and SHELF_DIR not in p.parts}


def test_preview_moves_nothing_and_writes_plan_file(disk):
    root, paths, connection = disk
    before = _snapshot(root)
    lines = []
    stats = preview_organize(connection, paths, ShelfConfig(), progress=lines.append)
    assert _snapshot(root) == before
    assert stats["dry_run"] is True and stats["move"] == 4 and stats["skip"] == 0
    assert not list(paths.backups.glob("shelf-*.db"))
    assert connection.execute("SELECT count(*) FROM organize_batch").fetchone()[0] == 0
    plan_file = paths.shelf / stats["plan_file"]
    text = plan_file.read_text(encoding="utf-8")
    assert "MOVE\ta/ABP-758.mp4\tPrestige/ABP-758/ABP-758.mp4" in text
    assert any("a/ABP-758.mp4 → Prestige/ABP-758/ABP-758.mp4" in line for line in lines)
    assert any(line.startswith("预演：4 个要搬") for line in lines)


def test_preview_reports_bad_template(disk):
    root, paths, connection = disk
    lines = []
    stats = preview_organize(connection, paths, ShelfConfig(dir_template="{nope"), progress=lines.append)
    assert stats["move"] == 0 and stats["skip"] >= 1
    assert any(reason.startswith("模板不合法") for reason in stats["reasons"])
    assert "SKIP\t" in (paths.shelf / stats["plan_file"]).read_text(encoding="utf-8")


def test_preview_caps_console_lines_but_writes_full_file(disk, monkeypatch):
    root, paths, connection = disk
    monkeypatch.setattr(apply_module, "PREVIEW_CONSOLE_LIMIT", 2)
    lines = []
    stats = preview_organize(connection, paths, ShelfConfig(), progress=lines.append)
    moves = [line for line in lines if " → " in line]
    assert len(moves) == 2
    assert any("还有 2 条" in line for line in lines)
    assert (paths.shelf / stats["plan_file"]).read_text(encoding="utf-8").count("MOVE\t") == 4
```

（测试文件顶部 `from hidden_shelf.paths import SHELF_DIR`。`disk` 夹具里 4 个视频：`a/ABP-758.mp4`、`b/259LUXU-1475-cd1.mp4`、`-cd2.mp4`、`c/deep/随手拍.mp4`，默认配置下 4 个都要搬——其中未识别那个搬去 `未识别/`。若实际数字不同，以 `build_plan` 的真实输出为准改断言，不改规则。）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_apply.py -k preview -v`
Expected: FAIL，`ImportError: cannot import name 'preview_organize'`

- [ ] **Step 3: 实现 `preview_organize` 与 `_write_plan_file(paths, plan) -> Path`**

清单文件：`paths.logs / f"plan-{时间戳}.txt"`（同名加 `-1`、`-2`，沿用 `apply_plan` 的写法），第一行 `# Hidden Shelf 归位预演 <ISO 时间>  要搬 N / 已就位 M / 跳过 K`，之后每行制表符分隔：`MOVE\t<现路径>\t<目标>` 或 `SKIP\t<现路径>\t<原因>`。终端输出顺序：`预演：N 个要搬，M 个已就位，K 个跳过`、每个跳过原因一行（沿用 `organize` 的 `  跳过原因 X：n`）、前 `PREVIEW_CONSOLE_LIMIT` 条 `[i/N] 现路径 → 目标`、超出时一行 `……还有 X 条，完整清单见 <相对盘根的 plan 文件路径>`、最后 `预演完成：没有动任何文件，清单：<路径>`。不调 `backup_database`、`apply_plan`、`remove_empty_dirs`，不写 `organize_batch`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_apply.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 版本 0.3.12，提交**

```bash
git add src/hidden_shelf/organize/apply.py tests/test_apply.py pyproject.toml src/hidden_shelf/__init__.py tests/test_smoke.py
git commit -m "feat: 归位预演 preview_organize，只列清单不动文件"
```

---

### Task 2: 流水线与命令行 `--dry-run`

**Files:**
- Modify: `src/hidden_shelf/pipeline.py`、`src/hidden_shelf/cli.py`
- Test: `tests/test_pipeline_cli.py`

**Interfaces:**
- Consumes: Task 1 的 `preview_organize`。
- Produces: `pipeline.run(root, *, config=None, steps=STEPS, progress=None, scrape_options=None, cancel=None, dry_run: bool = False) -> RunResult`；`RunResult.dry_run: bool = False`；`dry_run=True` 时 `organize` 步的 stats 就是 `preview_organize` 的返回值（不再 rescan，没有 `"rescan"` 键），`media`、`build` 记 `skipped`，原因字符串 `"--dry-run"`，`result.index_html` 保持 `None`。命令行所有流水线子命令加 `--dry-run`，帮助文案「只预演：列出要搬的文件与原因，不动盘上任何文件（仍会写 HiddenShelf/）」。

- [ ] **Step 1: 写失败的测试**（加到 `tests/test_pipeline_cli.py`，复用 `disk` 夹具）

```python
def _outside_shelf(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if SHELF_DIR not in p.parts}


def test_dry_run_touches_only_shelf_dir(disk):
    before = _outside_shelf(disk)
    result = pipeline.run(disk, dry_run=True, scrape_options=pipeline.ScrapeOptions(offline=True))
    assert result.ok and result.dry_run
    assert _outside_shelf(disk) == before
    assert not (disk / "index.html").exists() and result.index_html is None
    assert result.steps["organize"]["dry_run"] is True and result.steps["organize"]["move"] == 3
    assert "rescan" not in result.steps["organize"]
    assert result.steps["media"] == {"skipped": True, "reason": "--dry-run"}
    assert result.steps["build"] == {"skipped": True, "reason": "--dry-run"}
    with sqlite3.connect(disk / SHELF_DIR / "shelf.db") as connection:
        assert connection.execute("SELECT status FROM run WHERE step='media'").fetchone()[0] == "skipped"
        assert connection.execute("SELECT count(*) FROM organize_batch").fetchone()[0] == 0


def test_dry_run_then_real_run_matches(disk):
    preview = pipeline.run(disk, dry_run=True, scrape_options=pipeline.ScrapeOptions(offline=True))
    real = pipeline.run(disk, scrape_options=pipeline.ScrapeOptions(offline=True))
    assert real.ok and real.steps["organize"]["moved"] == preview.steps["organize"]["move"]
    assert (disk / "Prestige" / "ABP-758" / "ABP-758.mp4").is_file()


def test_cli_dry_run_prints_summary(disk, capsys):
    assert cli.main(["run", str(disk), "--dry-run", "--offline"]) == 0
    out = capsys.readouterr().out
    assert "预演完成" in out and "没有动任何文件" in out and "plan-" in out
    assert "成品：" not in out
    assert not (disk / "Prestige").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pipeline_cli.py -k dry_run -v`
Expected: FAIL，`TypeError: run() got an unexpected keyword argument 'dry_run'`

- [ ] **Step 3: 实现**

`pipeline.py`：把现在只给 `scrape` 用的跳过判断抽成 `_skip_reason(name, config, scrape_options, dry_run) -> str | None`（`scrape` 的两种原因不变；`dry_run` 且 `name in ("media", "build")` → `"--dry-run"`），循环里统一走 `skipped` 分支。`_execute` 加 `dry_run` 参数，`organize` 分支 `dry_run` 时返回 `preview_organize(...)` 且不 rescan。`RunResult` 加 `dry_run` 字段，`run` 开头赋值；日志文件第一行加 `（预演）`。`cli.py`：`--dry-run` 开关；结束时 `result.dry_run` 为真打印 `预演完成：{move} 个要搬，{unchanged} 个已就位，{skip} 个跳过；没有动任何文件，清单：{盘根/HiddenShelf/plan_file}`，不打印「成品」。

- [ ] **Step 4: 跑全部测试**

Run: `uv run pytest -q`
Expected: 全部 PASS（`test_serve_e2e.py` 钉的是 `ConsoleProgress` 与网页逐行一致，`skipped` 文案没变所以不受影响）

- [ ] **Step 5: 版本 0.3.13，提交**

```bash
git commit -am "feat: shelf run --dry-run 预演，只写 HiddenShelf/ 不动盘"
```

---

### Task 3: 进度网页「只预演」开关

**Files:**
- Modify: `src/hidden_shelf/serve/runner.py`、`serve/static/progress.js`、`serve/static/i18n.js`
- Test: `tests/test_runner.py`、`tests/test_serve_app.py`、`tests/serve_fakes.py`

**Interfaces:**
- Consumes: Task 2 的 `pipeline.run(dry_run=)`、`RunResult.dry_run`（`run.done` 事件的 `stats` 由 `_plain(result)` 生成，自动带上 `dry_run`）。
- Produces: `RunOptions.dry_run: bool = False`，`from_payload` 接受 JSON 键 `dry_run`（与 `offline` 同样校验），`to_dict` 带它；`RunManager` 调 `run_pipeline(..., dry_run=options.dry_run)`。前端新增开关 `toggle('dryRun', 'form.dry_run', ...)` 放在「本次不联网」之下，`POST /api/run` 带 `dry_run`。i18n 键：`form.dry_run` 中「只预演：列出要搬的文件，不动盘（仍会写 HiddenShelf/）」英 "Preview only: list the moves, touch nothing (still writes HiddenShelf/)"；`result.dry_run` 中「预演完成，没有动任何文件；清单在 HiddenShelf/logs/ 下」英 "Preview finished, nothing was moved; the list is under HiddenShelf/logs/"；`toast.dry_run` 中「预演完成」英 "Preview finished"；`page.dry_run` 中「上次预演完成」英 "Last preview finished"。

- [ ] **Step 1: 写失败的测试**

`tests/serve_fakes.py` 的 `run` 签名加 `dry_run=False`，`calls.append` 里记 `"dry_run": dry_run`。`tests/test_runner.py` 的 `test_options_from_payload_validation` 里加：`RunOptions.from_payload({"root": str(tmp_root), "dry_run": True}).dry_run is True`、`"dry_run": "yes"` 抛 `ValueError`。`tests/test_serve_app.py` 新增：

```python
def test_dry_run_option_reaches_pipeline(tmp_path: Path, tmp_root: Path):
    fake = fake_pipeline()
    client = make_client(tmp_path, fake)
    response = client.post("/api/run", json={"root": str(tmp_root), "dry_run": True}, headers=HEADERS)
    assert response.status_code == 202
    client.manager.wait(timeout=10)
    assert fake.calls[-1]["dry_run"] is True
    assert client.get("/api/state").json()["options"]["dry_run"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_runner.py tests/test_serve_app.py -v`
Expected: 新增断言 FAIL（`dry_run` 不是 `RunOptions` 字段）

- [ ] **Step 3: 实现后端与前端**

`runner.py` 按 Interfaces 改。`progress.js`：`refs.dryRunValue` 与其它开关同样保存/恢复；`start()` 的请求体加 `dry_run: refs.dryRun.checked`；结果区：`result.dry_run && result.ok` 时文案用 `t('result.dry_run')`，并且「打开成品」按钮不亮（`finishedOk` 已经要求 `build` 是 `done`，预演时是 `skipped`，确认即可）；toast 用 `toast.dry_run`；页头状态 `page.dry_run`。`i18n.js` 两套各加四个键。

- [ ] **Step 4: 跑 Python 测试与前端测试**

Run: `uv run pytest tests/test_runner.py tests/test_serve_app.py tests/test_serve_e2e.py -v && node --test "tests/js/**/*.test.mjs"`
Expected: 全部 PASS（含 `test_i18n_dictionaries_have_same_keys`）

- [ ] **Step 5: Playwright 手动验证**（脚本放 scratchpad，不进仓库）

`shelf serve --no-browser` 跑在后台，Playwright 打开页面，开「只预演」，对一个临时盘根开跑，等结束：步骤卡里「媒体」「出站」显示跳过且原因 `--dry-run`，结果区显示预演文案，「打开成品」按钮不可用，临时盘根上没有生成 `index.html`。

- [ ] **Step 6: 版本 0.3.14，提交**

```bash
git commit -am "feat: 进度网页加「只预演」开关"
```

---

### Task 4: javarchive 标题反转义

**Files:**
- Modify: `src/hidden_shelf/scrape/sources/javarchive.py`
- Test: `tests/test_sources_community.py`、必要时补 `tests/fixtures/sources/javarchive-work.html` 片段

**Interfaces:** 无新接口。

本机真实冒烟（2026-10-29）里 javarchive 对 `FC2-PPV-4364209` 给出的标题是 `みお(19\\)可愛い巨乳JDの初アナル貫通動画…`——括号前多了反斜杠，来源页面的 `<h1>` 或 URL slug 里是转义写法，`strip_code` 之后没有反转义。同一番号 fc2 官方给的是 `みお(19)可愛い巨乳JDの初アナル貫通動画`。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_sources_community.py` 的 javarchive 部分加 `test_javarchive_title_unescapes_backslashes`：把夹具里作品页的标题改成含 `\\)` 的写法（或新增一个最小 HTML 片段），断言解析出的 `title` 里没有 `\\`，且等于去掉反斜杠后的文本。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_sources_community.py -k javarchive -v`
Expected: 新测试 FAIL

- [ ] **Step 3: 实现**

在 `javarchive.py` 取标题处把 `\\(`、`\\)`、`\\[`、`\\]`、`\\\\` 这类反斜杠转义还原（只处理反斜杠后跟标点的情形，别动日文里的 `＼`），放在 `strip_code` 之前。

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_sources_community.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 版本 0.3.15，提交**

```bash
git commit -am "fix: javarchive 标题里的反斜杠转义还原"
```

---

### Task 5: GitHub Actions CI

**Files:**
- Create: `.github/workflows/test.yml`
- Modify: `README.md`（只加一行徽章占位，正文 Task 6 再写）

**Interfaces:** 无。

- [ ] **Step 1: 写 workflow**

```yaml
name: tests
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    continue-on-error: ${{ matrix.os == 'windows-latest' }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - uses: FedericoCarboni/setup-ffmpeg@v3
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: uv sync --frozen
      - run: uv run pytest -q
      - run: node --test "tests/js/**/*.test.mjs"
```

Windows job 允许失败的原因写在文件顶部注释里：作者没有 Windows 机器，先看 CI 的结果再决定修什么。

- [ ] **Step 2: 本地验证能解析**

Run: `uv run python -c "import yaml, sys; yaml.safe_load(open('.github/workflows/test.yml'))"`（`pyyaml` 不在依赖里就用 `node -e` 读一遍文件确认存在即可；有 `actionlint` 就跑 `actionlint`）
Expected: 无报错

- [ ] **Step 3: 版本 0.3.16，提交**

```bash
git add .github/workflows/test.yml
git commit -m "ci: GitHub Actions 三平台跑 pytest 与前端测试"
```

---

### Task 6: README 改写（中文）与 README.en.md

**Files:**
- Modify: `README.md`
- Create: `README.en.md`
- 引用：`docs/images/wall.jpg`、`docs/images/progress.jpg`、`docs/images/picker.jpg`（已存在）

**Interfaces:** 无。

- [ ] **Step 1: 改写 `README.md`**，按这个结构，总长不超过 250 行：

1. 标题 + 一句话（现有那句）+ CI 徽章 `![tests](https://github.com/wanghero/Hidden-Shelf/actions/workflows/test.yml/badge.svg)` + `[English](README.en.md)`。
2. 三张截图（海报墙、进度网页、目录选择器），说明是演示数据。
3. **它会对你的盘做什么**：六步各一句；然后「安全承诺」清单——只做同卷改名、绝不删除、绝不覆盖已存在的目标、归位前自动备份数据库（保留 5 份）、每批搬运有 JSONL 日志可回滚、所有派生产物只在 `HiddenShelf/` 下、媒体目录旁不写任何文件、`--dry-run` 先看清单再动手。
4. **安装**：前置 Python ≥ 3.12 与 ffmpeg（macOS `brew install ffmpeg`，Debian/Ubuntu `apt install ffmpeg`，Windows 从 ffmpeg.org 下载并加进 PATH）；两种装法：`uv tool install git+https://github.com/wanghero/Hidden-Shelf` 或 `pipx install git+https://github.com/wanghero/Hidden-Shelf`；开发者用 `git clone` + `uv sync`。
5. **三步上手**：`shelf run <盘根目录> --dry-run` 看清单 → `shelf run <盘根目录>` → 双击盘根的 `index.html`。每步一两句说会看到什么。
6. **进度网页**：现有段落压缩到 6 行以内，加「只预演」开关。
7. **联网刮削**：现有「全局配置」一节原样保留；新增「来源」表：8 站 × 列「内容类型 / 需要 Cookie / 2026-10-29 本机冒烟」，数据用 Global Constraints 里给的结果。
8. **盘上的布局**：`<盘根>/index.html`、`厂牌/番号/番号[-cdN].ext`、`未识别/`、`HiddenShelf/{shelf.db,config.json,overrides.json,site,covers,posters,sheets,avatars,sources,legacy,logs,backups}` 各一句。手改入口 `overrides.json` 的 JSON 例子。
9. **常见问题**：换台电脑能看吗（能，相对路径）；文件名不是番号怎么办（进 `未识别/`，或关掉开关原地不动）；以前刮削器留下的 NFO 和封面（导入后搬到 `HiddenShelf/legacy/<番号>/`）；搬错了怎么回滚（`HiddenShelf/logs/organize-*.jsonl`，目前要在 Python 里调 `rollback_batch`，命令行入口还没有——如实写）；javdb 要登录（Cookie 配置）；跑一半断网（刮削失败不拦后续步）。
10. **平台**：macOS 已验证；Linux 由 CI 验证；Windows 未验证（CI 允许失败），欢迎反馈。
11. **免责声明**：18+ 工具；只抓公开元数据与封面，不下载视频；不内置任何站点凭据；Cookie 与各站条款由用户自己负责；对数据丢失不承担责任（尽管程序设计上不删不覆盖，备份仍是你自己的事）。
12. **许可与致谢**：AGPL-3.0-or-later，含义一句（改了拿去做网络服务也得开源）；策略模块移植自 peach，登记在 `docs/REUSE.md`；界面规范 `docs/ux-standard/`。
13. **设计历史**：设计文档与五份计划的链接列表（现在 README 开头那段挪到这里）。

- [ ] **Step 2: 写 `README.en.md`**，同样 13 节、同样的截图与表格，英文 sentence case，不逐字直译但信息一致。

- [ ] **Step 3: 检查**

Run: `grep -nE '~/Claude-Code|~/\.claude|/Volumes/Seagate|wanghero/[^H]' README.md README.en.md`
Expected: 无输出（仓库 URL `wanghero/Hidden-Shelf` 允许）。再 `uv run pytest tests/test_smoke.py -q` 过。

- [ ] **Step 4: 版本 0.3.17，提交**

```bash
git add README.md README.en.md
git commit -m "docs: README 改写成用户视角，加英文版"
```

---

### Task 7: CONTRIBUTING、issue 模板、CHANGELOG、0.4.0

**Files:**
- Create: `CONTRIBUTING.md`、`CHANGELOG.md`、`.github/ISSUE_TEMPLATE/bug_report.md`、`.github/ISSUE_TEMPLATE/source_broken.md`、`.github/ISSUE_TEMPLATE/config.yml`
- Modify: `CLAUDE.md`、`pyproject.toml`、`src/hidden_shelf/__init__.py`、`tests/test_smoke.py`

**Interfaces:** 无。

- [ ] **Step 1: `CONTRIBUTING.md`**（中文，末尾附英文摘要 10 行以内）：开发环境（`uv sync`、ffmpeg、node ≥ 20）；三条测试命令；**测试永不联网**与 `isolated_home`；提交规则（中文提交信息、每次改代码版本 +0.0.1 三处同改）；来源坏了怎么报（跑 `scripts/smoke_sources.py <番号> --sources <站>`，把输出贴进 issue）；新增来源要登记 `SITE_SOURCES` 并加契约测试 `tests/test_sources_contract.py`；移植 peach 代码要登记 `docs/REUSE.md`；界面改动遵守 `docs/ux-standard/SKILL.md`。

- [ ] **Step 2: issue 模板**：`bug_report.md`（版本 `shelf --version`、系统、命令或网页操作、期望/实际、`HiddenShelf/logs/run-*.log` 相关片段、是否 `--dry-run` 也能复现）；`source_broken.md`（来源名、番号、`smoke_sources.py` 输出、是否配了 Cookie——提醒**不要贴 Cookie 值**）；`config.yml` 关掉空白 issue。

- [ ] **Step 3: `CHANGELOG.md`**：Keep a Changelog 格式，一条 `## 0.4.0 - 2026-10-29`：新增（预演 `--dry-run` 与网页开关、CI、中英 README、CONTRIBUTING、issue 模板）、修复（javarchive 标题转义）、以及一句「0.4.0 之前的历史见 git log 与 `docs/superpowers/plans/`」。

- [ ] **Step 4: `CLAUDE.md`**：「当前阶段」改成 v0.4.0、计划 5 完成、预演语义一句（`dry_run` 时 organize 走 `preview_organize`，media/build skipped）；「命令」加 `uv run shelf run <盘根目录> --dry-run`；「架构」`pipeline.py` 一条加 `_skip_reason` 与 `RunResult.dry_run`；「下一步」候选加「`shelf rollback <批次日志>` 命令行入口」。

- [ ] **Step 5: 版本 0.4.0，跑全部测试，提交**

Run: `uv run pytest -q && node --test "tests/js/**/*.test.mjs"`
Expected: 全部 PASS

```bash
git add CONTRIBUTING.md CHANGELOG.md .github/ISSUE_TEMPLATE CLAUDE.md pyproject.toml src/hidden_shelf/__init__.py tests/test_smoke.py
git commit -m "docs: 开源准备——CONTRIBUTING、issue 模板、CHANGELOG，版本 0.4.0"
```

本机随后要做的（不在云端）：看 Actions 首次运行结果、打 `v0.4.0` 标签、开 GitHub Release、把仓库设为公开、更新 `~/Claude-Code/PROJECTS.md`。
