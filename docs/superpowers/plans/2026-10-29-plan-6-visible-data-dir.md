# Hidden Shelf 计划 6：资料目录改成普通可见目录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 盘根目录下的派生产物目录 `.shelf/` 改名为普通可见目录 **`HiddenShelf/`**——用户 2026-10-29 要求「不要放在隐藏文件夹里，正常文件即可，要考虑 Windows」。旧盘上的 `.shelf/` 自动改名迁移，用户什么都不用做。

**Architecture:** 目录名收口到一个常量 `paths.SHELF_DIR = "HiddenShelf"`，全仓库凡是写死 `".shelf"` 的地方都改引用常量（扫描跳过、空目录保护、目录选择器 `has_shelf`、静态站相对路径、文案）。`ShelfPaths.ensure()` 开头做一次迁移：`<盘根>/.shelf` 存在且 `<盘根>/HiddenShelf` 不存在 → `os.rename`；两者都在 → 报错让人处理，不猜。库里 `cover_file`/`poster_file`/`sheet_file` 本来就是相对资料目录的路径，不用改库；`index.html` 由下一次 `build` 重新生成。

**Tech Stack:** 现有。不加依赖。

**Spec:** 设计文档 §4.2 的布局改为 `HiddenShelf/`（本计划完成时在设计文档里加一行「2026-10-29 用户改为可见目录」，不重写全文）。

## Global Constraints

- 名字 **`HiddenShelf`**（我定的，用户只要求可见、正常、Windows 友好）：纯 ASCII、无前导点或下划线、不是 Windows 保留名、不含尾随点或空格，exFAT/NTFS/APFS 都合法；与厂牌目录撞名的概率可忽略；**不设置** Windows 隐藏属性，不写 `desktop.ini`。
- 目录名只出现在 `paths.SHELF_DIR` 一处，其它代码一律 `paths.shelf.name` 或 `SHELF_DIR`；完成后 `git grep -n '"\.shelf"\|\.shelf/' -- src` 只允许留在**迁移代码**与其注释里。
- 库里的相对路径约定不变：`asset.path` 相对盘根、`cover_file` 等相对资料目录；迁移不改库。
- 静态站从 `file://` 打开，相对路径 `HiddenShelf/site/...`、`HiddenShelf/covers/...`，前端 `encodeMediaPath` 逐段编码不变。
- 版本：接着 `main` 当前版本 +0.0.1（本计划写成时 `main` 是 v0.3.11，本计划两个任务 → 0.3.12、0.3.13；若计划 5 先做了，就接计划 5 的最后一个版本号）。`.gitignore` 的 `.shelf/` 改为 `HiddenShelf/`。
- 本计划要**先于计划 5 的 Task 5–7**（CI、README、CONTRIBUTING）完成，README 才会写对目录名。推荐顺序：计划 6 → 计划 5。

## Review Focus

1. **老盘迁移**：已经跑过的盘有 `.shelf/`，再跑一次（任何子命令、网页也一样）自动改名为 `HiddenShelf/`，日志里记一行，之后一切照旧；旧 `index.html` 在重建前指向 `.shelf/` 已失效——`ensure()` 迁移后把旧 `index.html` 删掉或让 `build` 必跑？**决定：不删，迁移后打一行提示「请重新出站」，`shelf run` 本来就会重建。** → Task 2 `test_ensure_migrates_legacy_dot_shelf`。
2. **两个目录都在**（用户手工复制过）：不合并、不猜，`ensure()` 抛 `RootNotWritable` 同类的清楚错误：「盘根目录同时有 .shelf/ 和 HiddenShelf/，请保留一个」，退出码 2 / 网页 400。→ Task 2 `test_ensure_refuses_both_dirs`。
3. **大小写不敏感的文件系统**（exFAT、默认 APFS、NTFS）：盘上已有 `hiddenshelf/`（大小写不同）时 `Path.exists()` 为真，视作同一目录，不另建。→ Task 1 不需要额外代码，`test_shelf_dir_name` 钉住常量即可；文档里提一句。
4. **扫描不能把资料目录当媒体**：`HiddenShelf/legacy/` 里有 NFO 和 jpg，`sheets/`、`covers/` 全是 jpg，扫描必须整目录跳过；目录选择器不列它、但 `has_shelf` 对它为真；空目录清理不碰它。→ Task 1 现有测试改名后必须全过，加 `test_scan_skips_visible_shelf_dir`。
5. **Windows 路径**：`HiddenShelf\covers\X.jpg` 在库里仍存 POSIX `covers/X.jpg`；`build.py` 拼的是 `HiddenShelf/covers/X.jpg`，浏览器在 Windows 上也按 `/` 解析。→ Task 1 `test_site_paths_use_forward_slashes`（用 `PureWindowsPath` 构造的路径也产出 `/`）。

---

### Task 1: 常量化并改名 `HiddenShelf/`

**Files:**
- Modify: `src/hidden_shelf/paths.py`（加 `SHELF_DIR`，`shelf` 属性用它，模块与 `check_writable` 文案）、`scan.py:36`、`organize/apply.py:210,216`、`serve/browse.py:20,53`、`site/build.py:72,113,286`、`serve/static/i18n.js:28,124`、`.gitignore`
- Modify: 注释与文案里的 `.shelf/`（`local_import.py`、`organize/apply.py`、`scrape/access.py`、`scrape/run.py`、`scan.py` 的模块注释）改成 `HiddenShelf/`
- Test: `tests/test_paths_config.py`、`tests/test_scan.py`、`tests/test_site_build.py`，以及所有写了 `".shelf"` 的测试（约 34 处，改为 `SHELF_DIR` 或 `paths.shelf`）

**Interfaces:**
- Produces: `paths.SHELF_DIR: str = "HiddenShelf"`；`ShelfPaths.shelf == root / SHELF_DIR`；`browse.NEVER_SHOW` 含 `SHELF_DIR`，`has_shelf` 判 `(path / SHELF_DIR).is_dir()`；`site/build.py` 生成的相对路径前缀 `f"{SHELF_DIR}/"`，`site_dir=f"{SHELF_DIR}/site"`。

- [ ] **Step 1: 写失败的测试**

`tests/test_paths_config.py`：

```python
def test_shelf_dir_is_visible_ascii(tmp_path):
    from hidden_shelf.paths import SHELF_DIR, ShelfPaths
    assert SHELF_DIR == "HiddenShelf"
    assert not SHELF_DIR.startswith((".", "_")) and SHELF_DIR.isascii()
    assert SHELF_DIR.upper() not in {"CON", "PRN", "AUX", "NUL"} and not SHELF_DIR.endswith((".", " "))
    assert ShelfPaths(tmp_path).shelf == tmp_path / "HiddenShelf"
```

`tests/test_scan.py` 加 `test_scan_skips_visible_shelf_dir`：在 `HiddenShelf/legacy/X/X.nfo`、`HiddenShelf/covers/X.jpg`、`HiddenShelf/sheets/ABP-758.mp4`（故意放个 .mp4 名）下造文件，扫描后 `asset` 与 `sidecar` 表都没有以 `HiddenShelf/` 开头的路径。

`tests/test_site_build.py` 加 `test_site_paths_use_forward_slashes`：出站后 `works.js` 里所有 `cover`/`poster`/`sheet`/`video` 路径以 `HiddenShelf/` 或媒体相对路径开头、不含反斜杠；`index.html` 引用 `HiddenShelf/site/`。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_paths_config.py tests/test_scan.py tests/test_site_build.py -k "shelf_dir or visible_shelf or forward_slashes" -v`
Expected: FAIL（`ImportError: SHELF_DIR` 等）

- [ ] **Step 3: 实现**

按 Interfaces 改；全仓库测试里的 `".shelf"` 改引用常量。`check_writable` 文案「要在盘根目录写 HiddenShelf/ 和 index.html」。`i18n.js` 两处 `form.root.help` 改成 `HiddenShelf/`。`.gitignore` 改 `HiddenShelf/`。

- [ ] **Step 4: 全量测试与残留检查**

Run: `uv run pytest -q && node --test "tests/js/**/*.test.mjs" && git grep -n '"\.shelf"\|\.shelf/' -- src tests`
Expected: 测试全过；grep 无输出（Task 2 之前迁移代码还没写，所以此时应当一处都不剩）

- [ ] **Step 5: 版本 +0.0.1，提交**

```bash
git commit -am "feat: 资料目录 .shelf/ 改为可见的 HiddenShelf/，目录名收口到 SHELF_DIR"
```

---

### Task 2: 老盘自动迁移

**Files:**
- Modify: `src/hidden_shelf/paths.py`（`ShelfPaths.ensure()` 开头调 `migrate_legacy_dir(root) -> bool`，常量 `LEGACY_SHELF_DIR = ".shelf"`）、`pipeline.py`（迁移发生时写日志与 `progress.log("info", ...)`）、`serve/browse.py`（`has_shelf` 对旧 `.shelf/` 也为真，让选择器照样标「已有库」）、`serve/browse.py` 的 `NEVER_SHOW` 保留 `.shelf`
- Test: `tests/test_paths_config.py`、`tests/test_serve_browse.py`

**Interfaces:**
- Produces: `paths.migrate_legacy_dir(root: Path) -> bool`（改名了返回 True；没有旧目录返回 False；两者都在抛 `ShelfLayoutConflict(RuntimeError)`，消息「盘根目录同时有 .shelf/ 和 HiddenShelf/，请保留一个再运行」）；`ShelfPaths.ensure()` 先调它。`cli.py` 把 `ShelfLayoutConflict` 当作与 `RootNotWritable` 同类：打印消息，退出码 2；`POST /api/run` 回 400 同一句。

- [ ] **Step 1: 写失败的测试**

```python
def test_ensure_migrates_legacy_dot_shelf(tmp_path):
    (tmp_path / ".shelf" / "covers").mkdir(parents=True)
    (tmp_path / ".shelf" / "shelf.db").write_bytes(b"db")
    paths = ShelfPaths(tmp_path)
    paths.ensure()
    assert not (tmp_path / ".shelf").exists()
    assert (tmp_path / "HiddenShelf" / "shelf.db").read_bytes() == b"db"
    assert (tmp_path / "HiddenShelf" / "covers").is_dir()


def test_ensure_refuses_both_dirs(tmp_path):
    (tmp_path / ".shelf").mkdir()
    (tmp_path / "HiddenShelf").mkdir()
    with pytest.raises(ShelfLayoutConflict, match="同时有"):
        ShelfPaths(tmp_path).ensure()


def test_cli_both_dirs_exit_2(tmp_path, capsys):
    (tmp_path / ".shelf").mkdir(); (tmp_path / "HiddenShelf").mkdir()
    assert cli.main(["scan", str(tmp_path)]) == 2
    assert "同时有" in capsys.readouterr().err
```

`tests/test_serve_browse.py` 加：目录里只有旧 `.shelf/` 时 `list_directory` 的 `has_shelf` 为真且 `.shelf` 不出现在 `entries`。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_paths_config.py tests/test_serve_browse.py tests/test_pipeline_cli.py -k "legacy or both_dirs" -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`migrate_legacy_dir` 只做同卷 `os.rename`，失败（`OSError`）包成 `RootNotWritable` 同样的话术。迁移成功时 `pipeline.run` 的日志第一行后面加 `已把 .shelf/ 改名为 HiddenShelf/，请重新出站（shelf run 会自动做）`。

- [ ] **Step 4: 全量测试**

Run: `uv run pytest -q`
Expected: 全部 PASS

- [ ] **Step 5: 文档同步**：`CLAUDE.md`「架构」里所有 `.shelf/` → `HiddenShelf/`，加一句迁移规则；设计文档 §4.2 加一行注记；`README.md` 现有文字里的 `.shelf/` → `HiddenShelf/`（计划 5 Task 6 会整体重写，这里只替换）。

- [ ] **Step 6: 版本 +0.0.1，提交**

```bash
git commit -am "feat: 老盘的 .shelf/ 自动改名为 HiddenShelf/，两者并存时拒绝运行"
```

完成后在本机：对已经整理过的真实盘再跑一次 `shelf run <盘根目录> --offline`，确认 `.shelf/` 变成 `HiddenShelf/`、双击 `index.html` 封面照常显示。
