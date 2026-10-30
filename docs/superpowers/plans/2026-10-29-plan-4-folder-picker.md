# Hidden Shelf 计划 4：盘根目录鼠标选择 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 进度网页的「盘根目录」不再只能手打路径：输入框旁加一个「浏览」按钮，弹出目录选择器，从本机的卷和用户目录开始用鼠标逐级点进子目录，选中后回填输入框。

**Architecture:** 浏览器出于安全不会把本机绝对路径交给网页（`<input webkitdirectory>` 只给相对名），所以列目录由后端做：新增 `GET /api/browse` 只列目录、只在本机同源下可用；前端在 `progress.js` 里加一个弹窗组件，面包屑 + 子目录列表 + 「上一级」「选择此目录」，纯逻辑（面包屑拆分、排序、路径拼接）进 `progress-core.js` 供 node 测。沿用现有的 `h()` 渲染、`api()` 请求、`t()` 字典、主题与 token。

**Tech Stack:** 现有：FastAPI + 原生 JS + ux-standard token。不加任何新依赖。

**Spec:** `docs/superpowers/specs/2026-10-28-hidden-shelf-design.md` §4.5（进度网页）。本计划是用户 2026-10-29 追加的小改动：「把盘根目录这个地方变成可以用鼠标操作的」，不改媒体目录模型（仍然一次运行一个盘根目录）。

## Global Constraints

- 继承计划 3 的全部约束：只监听 127.0.0.1；新接口同样要 `X-Shelf-Request: 1` 且 `Origin`/`Referer` 可信（复用 `app.py` 的 `_trusted_origin`，GET 也要），否则 403。
- 只列目录，不列文件；不读文件内容；不跟随越界：`path` 必须是绝对路径，`..` 段拒绝（400）；不存在 404；无权限 403；不是目录 400。
- 默认不显示点开头的隐藏目录；`show_hidden=1` 才显示。永远不显示 `.shelf`（它是产物不是媒体目录）；但要告诉前端该目录「已有藏片阁库」（`has_shelf`）。
- 每次响应最多 2000 条子目录，超出截断并返回 `truncated: true`。
- 前端 CSS 只用 `tokens.css` 变量（`tests/test_serve_app.py::test_progress_css_uses_only_tokens` 要继续过）；`i18n.js` 中英 key 一致（`test_i18n_dictionaries_have_same_keys`）；不加载外网资源。
- 弹窗按 `docs/ux-standard/SKILL.md` 第 215 行附近的规范：宽 640px（表单型），圆角 16px，内边距 28px，`--shadow-popover`，遮罩 `--overlay`；手机上改为底部抽屉；Esc 关闭；打开时焦点进弹窗，关闭后焦点回「浏览」按钮。
- 版本号：从 0.3.5 起每个任务 +0.0.1（`pyproject.toml`、`src/hidden_shelf/__init__.py`、`tests/test_smoke.py` 三处同改）。提交信息中文。

## Review Focus

1. **macOS 上 `/Volumes` 里有拔掉后残留的空目录或无权限目录**（TCC 限制的 `~/Desktop`、`~/Documents` 在未授权时 `PermissionError`）：接口返回 403 而不是 500，前端在该行显示「无权限」并可继续浏览别处。→ Task 1、Task 3。
2. **路径里有空格、中日文、`#`**（如 `/Volumes/我的盘/30、下载未整理`）：前端用 `encodeURIComponent` 放进查询串，后端原样取到，回填输入框后 `POST /api/run` 能跑。→ Task 1、Task 2、Task 3。
3. **目录里子目录数万个**（整块盘的根）：后端截断到 2000 条并告知，前端提示「只显示前 2000 个」；列表渲染不卡（用一次 `DocumentFragment` 追加）。→ Task 1、Task 3。
4. **运行进行中打开选择器**：允许浏览，但「选择此目录」在 `state.running` 时禁用并提示，避免改掉正在跑的盘根目录。→ Task 3。
5. **Windows**（未来可能）：根列表用盘符 `C:\`、`D:\`…，路径分隔符 `\`；本计划在 Linux/macOS 上测，Windows 分支只写代码、不测，但 `os.path` 与 `Path` 调用不能写死 `/`。→ Task 1。

---

## 文件结构

```
src/hidden_shelf/serve/
  browse.py                 新增：list_roots()、list_directory()、BrowseError
  app.py                    修改：GET /api/browse 路由；_trusted_origin 对该 GET 生效
  static/progress-core.js   修改：breadcrumbs()、joinPath()、sortEntries()
  static/progress.js        修改：浏览按钮、选择器弹窗、与输入框联动
  static/progress.css       修改：弹窗与列表样式
  static/i18n.js            修改：新增 key
tests/
  test_serve_browse.py      新增：browse.py 与 /api/browse
  js/progress-core.test.mjs 修改：新增纯逻辑用例
```

---

### Task 1: 后端目录列举（`serve/browse.py`）

**Files:**
- Create: `src/hidden_shelf/serve/browse.py`
- Test: `tests/test_serve_browse.py`

**Interfaces:**
- Produces：
  - `class BrowseError(Exception)`：属性 `status: int`（400/403/404）、`message: str`
  - `@dataclass(frozen=True) Entry(name: str, path: str, has_shelf: bool)`
  - `@dataclass(frozen=True) Listing(path: str, parent: str | None, entries: list[Entry], truncated: bool, has_shelf: bool, writable: bool)`
  - `list_roots(*, home: Path | None = None, volumes: Path | None = None) -> list[Entry]`：macOS：`home` + `/Volumes/*`（默认 `volumes=Path("/Volumes")`）；Linux：`home` + `/` + `/mnt/*` + `/media/<user>/*` 中存在的；Windows：`home` + 每个存在的盘符 `X:\`。`name` 用目录名（home 显示为 `~` 的实际名，如 `wanghero`），顺序：home 第一，其余按名排序。`has_shelf` = `(path/".shelf").is_dir()`。不存在或无权限的根跳过，不抛。
  - `list_directory(raw: str, *, show_hidden: bool = False, limit: int = 2000) -> Listing`：校验（非绝对 → 400 `"路径必须是绝对路径"`；含 `..` 段 → 400 `"路径不能包含 .."`；不存在 → 404 `"目录不存在"`；不是目录 → 400 `"不是目录"`；`PermissionError` → 403 `"没有读取权限"`）；用 `os.scandir`，只收 `entry.is_dir(follow_symlinks=False)` 为真的；名字以 `.` 开头且 `show_hidden=False` 的跳过；`.shelf` 永远跳过；`@eaDir`、`$RECYCLE.BIN`、`System Volume Information`、`.Spotlight-V100`、`.Trashes`、`.fseventsd` 永远跳过；单个子项 `stat` 失败跳过；按 `name.casefold()` 排序；超过 `limit` 截断。`parent` 是上一级的绝对路径，到根时 `None`。`writable = os.access(path, os.W_OK)`。
  - `MAX_ENTRIES = 2000`

- [ ] **Step 1: 写失败测试 `tests/test_serve_browse.py`**（用 `tmp_path` 建树：`disk/`、`disk/Prestige/`、`disk/.hidden/`、`disk/.shelf/`、`disk/@eaDir/`、`disk/file.txt`、`disk/中文 目录#1/`、`disk/Prestige/.shelf/`）：

```python
def test_list_directory_only_visible_dirs(tmp_path):
    listing = list_directory(str(tmp_path / "disk"))
    assert [e.name for e in listing.entries] == ["Prestige", "中文 目录#1"]
    assert listing.has_shelf is True and listing.parent == str(tmp_path)
    assert next(e for e in listing.entries if e.name == "Prestige").has_shelf is True

def test_show_hidden_includes_dot_dirs_but_never_shelf(tmp_path):
    names = [e.name for e in list_directory(str(tmp_path / "disk"), show_hidden=True).entries]
    assert ".hidden" in names and ".shelf" not in names and "@eaDir" not in names

@pytest.mark.parametrize("raw,status", [("relative/x", 400), ("/a/../b", 400)])
def test_rejects_bad_paths(raw, status): ...
def test_missing_is_404(tmp_path): ...
def test_file_is_400(tmp_path): ...
def test_permission_error_is_403(tmp_path, monkeypatch):  # monkeypatch os.scandir 抛 PermissionError
def test_truncates(tmp_path):  # 建 5 个子目录，limit=3 → 3 条且 truncated
def test_roots_macos_style(tmp_path):  # volumes=tmp_path/"Volumes" 下建两个卷，home=tmp_path/"home"：home 第一，卷按名排序；不存在的 volumes 目录不抛
```

- [ ] **Step 2: 运行** `uv run pytest tests/test_serve_browse.py -v`。Expected: FAIL（ImportError）。
- [ ] **Step 3: 实现 `browse.py`**。平台分支用 `sys.platform`；Windows 盘符用 `string.ascii_uppercase` 逐个 `Path(f"{letter}:\\").exists()`。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: 版本 0.3.6，Commit**：`feat: 目录列举后端`

---

### Task 2: `GET /api/browse` 路由

**Files:**
- Modify: `src/hidden_shelf/serve/app.py`
- Test: `tests/test_serve_browse.py`（追加）

**Interfaces:**
- Consumes: Task 1。
- Produces：`GET /api/browse?path=<绝对路径>&show_hidden=0|1`；`path` 为空或缺省 → `{"roots": [Entry...]}`；否则 → `Listing` 的 dict（`entries` 内每项 `{name, path, has_shelf}`）。`BrowseError` → 对应状态码 + `{"error": message}`。请求必须带 `X-Shelf-Request: 1` 且 `_trusted_origin`，否则 403（把 `_trusted_origin` 对「缺 `Origin` 和 `Referer`」的处理与现有 POST 保持一致）。响应 `Cache-Control: no-store`。

- [ ] **Step 1: 写失败测试**（用 `tests/test_serve_app.py` 里同样的 `TestClient` 构造方式）：`test_browse_roots`（无 path → 200 且 `roots` 非空）、`test_browse_lists_tmp_dir`（Review Focus 2：path 为 `tmp_path/"中文 目录#1"` 的父目录，查询串用 `urllib.parse.quote`，返回里 `entries[].name` 含它）、`test_browse_errors_map_status`（404/400/403）、`test_browse_requires_header_and_origin`（无头 → 403；`Origin: https://evil.example` → 403）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 在 `create_app` 里加路由**。
- [ ] **Step 4: 运行** `uv run pytest tests/test_serve_browse.py tests/test_serve_app.py -v`，PASS。
- [ ] **Step 5: 版本 0.3.7，Commit**：`feat: /api/browse 目录列举接口`

---

### Task 3: 前端目录选择器

**Files:**
- Modify: `src/hidden_shelf/serve/static/progress-core.js`, `progress.js`, `progress.css`, `i18n.js`
- Test: `tests/js/progress-core.test.mjs`（追加）；`tests/test_serve_app.py` 现有的 token 与 i18n 测试要继续过；手动清单

**Interfaces:**
- Consumes: Task 2 接口；现有 `h()`、`api()`、`t()`、`refs`、`state.running`、`writePref/readPref`。
- Produces（`progress-core.js` 新增，挂到返回对象）：
  - `breadcrumbs(path: string) -> [{name, path}]`：`"/Volumes/我的盘/30、下载"` → `[{name:"/",path:"/"},{name:"Volumes",path:"/Volumes"},{name:"我的盘",path:"/Volumes/我的盘"},{name:"30、下载",path:"/Volumes/我的盘/30、下载"}]`；Windows `"D:\\a\\b"` → `[{name:"D:\\",path:"D:\\"},{name:"a",path:"D:\\a"},{name:"b",path:"D:\\a\\b"}]`。
  - `sortEntries(entries) -> entries[]`：按 `name` 的 `localeCompare(undefined, {numeric: true, sensitivity: "base"})`。
  - `browseUrl(path: string|null, showHidden: boolean) -> string`：`"/api/browse?path=" + encodeURIComponent(path) + (showHidden ? "&show_hidden=1" : "")`，`path` 为空时不带 `path=`。
- 页面行为：
  - 盘根目录输入框右侧加一个图标按钮（文件夹图标，`aria-label` = `t('browse.open')`，title 同），放在输入框所在的 `.field` 内成一行（input 占满，按钮固定宽）。
  - 点击打开弹窗 `#browse-dialog`（`role="dialog"`、`aria-modal="true"`、`aria-labelledby` 指向标题）：标题「选择盘根目录」；顶部面包屑（每段可点，跳到该层）；主体左侧「位置」列（`roots`：用户目录与各卷，带盘图标；`has_shelf` 的显示一个小徽标「已有库」）、右侧子目录列表（每行：文件夹图标 + 名字 + `has_shelf` 徽标；单击选中高亮，双击或回车进入；列表空时空态「没有子目录」）；底部一行：「显示隐藏目录」开关、「上一级」按钮、`truncated` 时的提示文本、右侧「取消」「选择此目录」主按钮。「选择此目录」选的是**当前浏览到的目录**（面包屑最后一段），不是列表里高亮那条；想选子目录就先进去再点。
  - 初始位置：输入框当前值若非空且后端返回 200 就从它开始；否则从上次选择（`localStorage` key `browse.last`）；再否则显示 roots 并把主体定位到用户目录。
  - 加载中列表显示骨架或「加载中…」；403 显示该目录「没有读取权限」并保留面包屑可退回（Review Focus 1）；404 显示「目录不存在」。
  - 选择后：回填 `refs.root.value`，触发 `input` 事件让现有校验走一遍，写 `browse.last`，关闭弹窗，焦点回浏览按钮。`state.running` 为真时「选择此目录」禁用并 title 提示「运行中不能更换」（Review Focus 4）。
  - 键盘：Esc 关闭；列表项可 Tab 到达，回车进入，`ArrowUp/Down` 在列表内移动高亮。
  - 手机（≤ 640px）：弹窗变底部抽屉，位置列折叠成顶部横向胶囊。
  - i18n 新 key（中/英都要）：`browse.open`、`browse.title`、`browse.locations`、`browse.up`、`browse.choose`、`browse.cancel`、`browse.hidden`、`browse.empty`、`browse.loading`、`browse.truncated`（含 `{n}`）、`browse.has_shelf`、`browse.running`、`browse.error.403`、`browse.error.404`、`browse.error.generic`。

- [ ] **Step 1: 写失败测试 `tests/js/progress-core.test.mjs`**：`breadcrumbs` 的 POSIX 与 Windows 两例；`sortEntries` 数字感知（`["10","2","b","A"]` → `["2","10","A","b"]`）；`browseUrl` 对 `"/Volumes/我的盘/30、下载 #1"` 的编码（Review Focus 2）与空 path。
- [ ] **Step 2: 运行** `node --test "tests/js/**/*.test.mjs"`，FAIL。
- [ ] **Step 3: 实现 `progress-core.js` 三个函数**；运行，PASS。
- [ ] **Step 4: 实现 `progress.js`、`progress.css`、`i18n.js`**。列表渲染用 `DocumentFragment` 一次追加（Review Focus 3）。
- [ ] **Step 5: 自动检查**：`uv run pytest tests/test_serve_app.py -v`（token、i18n、index 引用三项继续过）；`grep -nE "#[0-9a-fA-F]{3,6}\b|rgb\(" src/hidden_shelf/serve/static/progress.css` 无输出。
- [ ] **Step 6: 手动清单**（`uv run shelf serve --no-browser` 后用 Playwright 无头 Chromium，脚本放 scratchpad 不进仓库；用 `tmp` 目录造 `卷/我的盘/30、下载 #1/` 并把 `list_roots` 的 `volumes` 用环境变量 `HIDDEN_SHELF_VOLUMES` 指过去——在 `browse.py` 里加这个只读的测试钩子）：
  1. 点浏览按钮弹窗打开，焦点在弹窗内，位置列有用户目录与卷。
  2. 双击进 `我的盘` → 面包屑三段；再进 `30、下载 #1`；点「选择此目录」→ 输入框值为完整路径且含 `#`，弹窗关闭，焦点回按钮。
  3. 点「开始」（勾「本次不联网」）→ 六步跑完，成品路径与输入一致。
  4. 再开弹窗：初始位置是刚才选的目录；点面包屑第一段回到根；「上一级」在根时禁用。
  5. 无权限目录（`chmod 000` 一个子目录）→ 该层显示「没有读取权限」，面包屑可退回。
  6. 「显示隐藏目录」打开后 `.hidden` 出现，`.shelf` 仍不出现；已有 `.shelf` 的目录显示「已有库」徽标。
  7. 2001 个子目录的目录 → 列表 2000 条 + 「只显示前 2000 个」提示，打开耗时 < 1 秒。
  8. 运行中打开弹窗 → 「选择此目录」禁用。
  9. Esc 关闭；375px 宽度下是底部抽屉且页面无横向滚动；深色主题下遮罩和弹窗颜色正确；中英切换后弹窗文案跟着变；控制台无报错。
- [ ] **Step 7: 版本 0.3.8，Commit**：`feat: 盘根目录鼠标选择弹窗`

---

### Task 4: 文档

**Files:**
- Modify: `CLAUDE.md`（架构节的 `serve/` 一段加 `browse.py` 与 `/api/browse`；命令节不变；当前阶段改为「计划 4 完成」）

- [ ] **Step 1: 改 CLAUDE.md**，把本计划的取舍写进去：只列目录不列文件；`.shelf` 永不显示；2000 条截断；GET 也要同源头；`HIDDEN_SHELF_VOLUMES` 只是测试钩子。
- [ ] **Step 2: 跑全部** `uv run pytest -q && node --test "tests/js/**/*.test.mjs"`，全过。
- [ ] **Step 3: 版本 0.3.9，Commit**：`docs: 计划 4 完成，更新架构说明`

---

## 自检记录

- 用户要求只有一条「盘根目录可以用鼠标操作」，本计划不扩成多媒体目录配置（用户 2026-10-29 明确「不改了」）。
- Review Focus 五条各有归属任务。`progress-core.js` 新函数名在 Task 3 的测试与实现里一致。
