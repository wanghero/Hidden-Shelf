# Hidden Shelf 计划 3：进度网页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `shelf serve` 在本机起一个只监听 127.0.0.1 的小网页：选盘根目录（最近用过的下拉）、开关几个选项、点「开始」，页面上六步（扫描、导入、刮削、归位、媒体、出站）各一行状态与进度，实时日志经 SSE 推到浏览器，跑完给「打开成品」按钮。同一时刻只允许一个运行；网页和命令行跑的是同一个 `pipeline.run`，输出一致。

**Architecture:** 计划 1 的 `Progress` 回调协议再加两个可选方法（`failed`、`skipped`），`pipeline.run` 加一个只在步与步之间检查的取消回调；`serve/events.py` 把回调翻成带序号、带时间戳的事件并存进一个有上限的环形缓冲，`serve/runner.py` 用一个守护线程跑流水线、一把锁保证单运行；`serve/app.py` 是 FastAPI 应用（三个 JSON 接口 + 一个 SSE 流 + 静态页），前端是纯 HTML + 原生 JS（`progress-core.js` 纯逻辑 UMD 可用 node 测），外观按 `docs/ux-standard/SKILL.md`。不碰静态站、不碰刮削规则。

**Tech Stack:** 计划 1、2 的栈 + `fastapi`、`uvicorn`（进运行时依赖；测试用 `fastapi.testclient`，底层 httpx 已在）。前端沿用仓库内 `docs/ux-standard/` 的 `tokens.css` 与 `ripple.js`。

**Spec:** `docs/superpowers/specs/2026-10-28-hidden-shelf-design.md` §1 目标 4、§2（端口只监听 127.0.0.1、按 `~/.claude/ports.md` 分配）、§4.1（fastapi + uvicorn 只给进度网页；进度网页纯 HTML + 原生 JS，SSE 收日志）、§4.3（进度网页和命令行输出一致）、§4.5、§5（SSE 实现细节与日志格式留给建造者——本计划定）。

前置：计划 1（v0.1.15）、计划 2（v0.2.11）已完成。本计划版本从 **0.3.0** 起，每个任务 +0.0.1，到 **0.3.5**。

## Global Constraints

- 计划 1、2 的全部约束继续有效（路径 POSIX、`.shelf/` 布局、`field_owners`、不删原始文件、凭据不进盘、测试永不联网、版本号 +0.0.1、中文提交并 push）。
- **只监听 `127.0.0.1`**，不提供 `--host`。端口按 8000–8099 段：本机实施时先 `cat ~/.claude/ports.md` 选空闲口并写回；云端没有该文件，暂定 **8031** 作默认口，登记进 `CLAUDE.md`「端口约束」。默认口被占时在 8000–8099 内往后找第一个空闲口并打印实际地址；`--port` 可指定。
- **单运行**：进程内一把锁，运行中再点「开始」回 409 与一句说明；不做跨进程锁（命令行与网页同时跑同一盘不在本计划保护范围，写进已知风险）。
- **取消只在步与步之间生效**：当前步跑完才停（归位是事务、刮削每个番号后提交，中途打断没有半成品）。页面上写明「停止：当前步完成后不再继续」。不杀线程。
- **SSE 事件格式（本计划定）**：每条 `id: <seq>`、`event: <kind>`、`data: <一行 JSON>`；JSON 键固定 `{"seq", "ts", "run", "kind", "step", "level", "message", "stats"}`，没有的键为 `null`。`kind ∈ {run.start, step.start, step.progress, step.done, step.failed, step.skipped, run.done, run.cancelled}`。每 15 秒一行 `: ping` 注释保活。客户端带 `Last-Event-ID` 重连时从该序号之后补发；缓冲上限每次运行 5000 条，超出丢最早的 `step.progress`，`start/done/failed/skipped` 类永不丢。
- **日志格式与命令行一致**：`step.progress` 的 `message` 就是 `ConsoleProgress` 打印的那一行去掉 `[步名]` 前缀的正文；`.shelf/logs/run-<时间>.log` 照计划 1 写法不变。
- **同源防护**：所有 `POST` 接口要求请求头 `X-Shelf-Request: 1`，且 `Origin`（没有则 `Referer`）的主机是 `127.0.0.1` 或 `localhost`，否则 403——挡住别的网页对 localhost 的跨站请求（DNS 重绑定场景）。不做登录、不做 CORS。
- **路径只收目录**：`root` 必须是已存在的目录，否则 400 带中文原因；「打开成品」只对 `<root>/index.html` 存在的目录生效，用 `webbrowser.open(file:// URL)`，不调 `open`/`xdg-open` 子进程。
- 最近用过的盘根目录存 `~/.hidden-shelf/recent.json`（跟全局配置同目录，`HIDDEN_SHELF_HOME` 可改），最多 10 条，最新在前；只存路径，不存任何凭据。
- 前端外观按 `docs/ux-standard/SKILL.md`：只用 `tokens.css` 变量（`grep -nE "#[0-9a-fA-F]{3,6}\b|rgb\(" progress.css` 应无输出）、浅/深/系统主题、中英双语字典（两套 key 一致）、可点击元素 `data-ripple`、每个数据区块有加载/空/错误三态、长任务显示阶段 + 已用时间 + 停止按钮、375px 无横向滚动。字体用系统字体栈，页面不加载任何外网资源。
- 不改 `site/`（静态站）、不改 `scrape/` 的规则模块；`pipeline.py` 只加可选参数与两个回调，命令行行为不变。
- 测试：服务用 `fastapi.testclient.TestClient`；流水线用 monkeypatch 的假 `pipeline.run`（不依赖 ffmpeg、毫秒级），另有一条真跑的端到端用 `fake_video`（ffmpeg 缺则 skip）。前端纯逻辑 `node --test`。最后用 Playwright 无头 Chromium 对着真服务器过一遍手动清单。

## Review Focus

1. **断线重连不丢不重**：浏览器收到第 37 条后断开，带 `Last-Event-ID: 37` 重连，必须从第 38 条接着收，不重发前 37 条；运行已结束时重连也能把 `run.done` 补回来。→ Task 0、2。
2. **单运行**：运行中再 `POST /api/run` 回 409；跑完后再点能开新一轮，事件序号从 1 重新计、`run` 字段换新 id，旧订阅者收到 `run.done` 后流结束。→ Task 1、2。
3. **失败与跳过的状态正确**：`scrape` 失败（流水线不中断）页面上该步标「失败」其余照跑；`--offline` 时该步标「跳过」；`build` 失败时流水线停、后续步保持「等待」、`run.done` 带 `ok=false` 与失败步名。→ Task 0、1、3。
4. **取消**：运行中点「停止」，当前步跑完后不再开下一步，`run.cancelled` 到达，`run` 表里只有已跑的步；再次「开始」可用。→ Task 1、2。
5. **跨站请求挡住**：带 `Origin: https://evil.example` 的 `POST /api/run` 回 403；没有 `X-Shelf-Request` 头回 403；正常页面发出的请求（同源、带头）放行。→ Task 2。
6. **命令行一致**：同一块盘，`shelf run` 打印的每一行正文在网页日志里一字不差（除了前缀与时间戳）。→ Task 1、4。
7. **端口**：8031 被占时自动换口并打印；指定 `--port` 被占时报错退出码 2 不自动换。→ Task 4。

---

## 文件结构

```
Hidden-Shelf/
  pyproject.toml                       dependencies += fastapi>=0.115, uvicorn>=0.30；版本 0.3.0 起
  src/hidden_shelf/
    pipeline.py                        Progress 加 failed()/skipped()；run() 加 cancel 回调与 RunResult.cancelled
    serve/
      __init__.py
      events.py                        Event、RunLog（环形缓冲 + 订阅队列 + 按 seq 补发）、EventProgress(Progress)
      runner.py                        RunManager：单运行锁、守护线程、start/cancel/state、recent roots
      app.py                           create_app() → FastAPI：GET /、/api/state、POST /api/run、/api/cancel、/api/open、GET /api/events（SSE）、/static/*
      ports.py                         DEFAULT_PORT = 8031、PORT_RANGE = (8000, 8099)、pick_port()
      static/
        tokens.css ripple.js           ← docs/ux-standard/ 复制
        i18n.js                        进度网页自己的中英字典（与 site 的字典无关）
        progress-core.js               纯逻辑 UMD：事件归约成步状态、[i/total] 百分比、耗时格式、日志过滤
        progress.css                   只用 token 变量
        progress.js                    DOM：表单、步列表、日志、SSE 客户端（EventSource + 重连）、toast、主题/语言
      templates/progress.html.j2       一页；<head> 防闪烁主题脚本；引 static
    cli.py                             子命令 serve：--port、--no-browser
  tests/
    test_events.py test_runner.py test_serve_app.py test_cli_serve.py test_pipeline_cancel.py
    js/progress-core.test.mjs
```

---

### Task 0: 事件模型与进度协议扩展

**Files:**
- Modify: `pyproject.toml`（依赖 `fastapi`、`uvicorn`；版本 0.3.0）、`src/hidden_shelf/pipeline.py`
- Create: `src/hidden_shelf/serve/__init__.py`, `src/hidden_shelf/serve/events.py`
- Test: `tests/test_events.py`, `tests/test_pipeline_cancel.py`

**Interfaces:**
- `pipeline.Progress` 加 `failed(name: str, error: str) -> None` 与 `skipped(name: str, reason: str) -> None`，默认空实现；`run()` 在对应分支调用（`scrape` 软失败与硬失败都调 `failed`，`--offline`/`config.scrape=false` 调 `skipped`）。`ConsoleProgress` 的 `failed` 打印 `[步名] ✗ 失败：<error>`（替换现在的 `log("error", ...)`，输出文字不变），`skipped` 打印 `[步名] 跳过（<reason>）`。
- `pipeline.run(..., cancel: Callable[[], bool] | None = None)`：每步开始前检查 `cancel()`，为真则不再开后续步，`RunResult.cancelled = True`、`ok` 保持当前值；写日志一行「已取消：在 <下一步名> 之前停下」。`RunResult` 加 `cancelled: bool = False`。
- `events.Event`（frozen dataclass）：`seq: int, ts: str, run: str, kind: str, step: str | None, level: str | None, message: str | None, stats: dict | None`；`to_sse() -> str`（`id:`/`event:`/`data:` 三行 + 空行，`data` 是 `json.dumps(ensure_ascii=False)` 一行）。`KINDS = ("run.start", "step.start", "step.progress", "step.done", "step.failed", "step.skipped", "run.done", "run.cancelled")`；`KEEP_ALWAYS = KINDS - {"step.progress"}`。
- `events.RunLog(run_id: str, *, limit: int = 5000, clock=time.time)`：`append(kind, *, step=None, level=None, message=None, stats=None) -> Event`（序号从 1 起，线程安全）；`since(seq: int) -> list[Event]`；`subscribe() -> queue.Queue[Event | None]`（新事件推给每个订阅者，`close()` 时推 `None`）；`unsubscribe(q)`；`closed: bool`；超限淘汰只删 `step.progress`。
- `events.EventProgress(Progress)`：构造收 `RunLog`；`step(name)` → `step.start`；`advance(n, message)` → `step.progress`（`level="info"`）；`log(level, message)` → `step.progress`（带 `level`）；`done(stats)` → `step.done`（`stats`）；`failed(name, error)` → `step.failed`（`message=error`）；`skipped(name, reason)` → `step.skipped`。它记住当前步名填 `step`。

- [ ] **Step 1: 写失败测试**：`test_event_to_sse_shape`（三行格式、中文不转义、`None` 键为 `null`）、`test_runlog_sequence_and_since`（序号连续；`since(37)` 只给 38 起）、`test_runlog_eviction_keeps_milestones`（limit=10 塞 50 条 progress + 若干 start/done，淘汰后 start/done 全在、progress 只剩最新的）、`test_runlog_subscribe_and_close`（两个订阅者各收到全部新事件；`close()` 后各收到 `None`，再 `append` 抛 `RuntimeError`）、`test_event_progress_maps_callbacks`（依次 step/advance/log/done/failed/skipped，断言 kind、step、level、message、stats）、`test_pipeline_cancel_between_steps`（monkeypatch 各步函数为记录调用的假函数；`cancel` 在 `import` 完成后返回真 → 只跑 scan、import，`result.cancelled` 真、`ok` 真、`run` 表只有两行、日志含「已取消」）、`test_pipeline_calls_failed_and_skipped`（monkeypatch build 抛 → `failed("build", ...)` 被调；`offline=True` → `skipped("scrape", "--offline")`；`ConsoleProgress` 文字与计划 1 一致）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。`uv add fastapi uvicorn`。
- [ ] **Step 4: 运行**（含计划 1、2 全部测试：`ConsoleProgress` 文字不变，`tests/test_pipeline_cli.py` 照过），PASS。
- [ ] **Step 5: 版本 0.3.0，Commit**：`feat: 进度事件模型与流水线取消`

---

### Task 1: 运行管理器

**Files:**
- Create: `src/hidden_shelf/serve/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- `runner.RunOptions`（dataclass）：`root: Path, move_unrecognized: bool = True, offline: bool = False, force_scrape: bool = False, steps: tuple[str, ...] = pipeline.STEPS`。`from_payload(data: dict) -> RunOptions`：校验 `root` 为已存在目录（否则 `ValueError("盘根目录不存在或不是目录：…")`），`steps` 子集校验，布尔字段强转。
- `runner.RunBusy(RuntimeError)`。
- `runner.RunManager(*, home: Path | None = None, run_pipeline=pipeline.run, clock=time.time)`：
  - `start(options) -> str`：拿锁，运行中抛 `RunBusy`；新建 `RunLog(run_id=<时间戳-短随机>)`；`append("run.start", stats={"root", "steps", "options"})`；守护线程里：读 `ShelfConfig.load(paths)` 再按 `options` 改 `move_unrecognized`，`ScrapeOptions(offline, force)`；调 `run_pipeline(root, config=..., steps=..., progress=EventProgress(log), scrape_options=..., cancel=self._cancelled)`；结束 `append("run.cancelled" if result.cancelled else "run.done", stats=asdict(result) 去掉 Path 转 str)`；`log.close()`；释放锁；异常（流水线自身抛，比如 `ValueError` 步名）记 `run.done` 带 `ok=false, error`，不让线程静默死掉。成功开始就把 `root` 写进 recent。
  - `cancel() -> bool`：运行中置取消标志、`append("step.progress", level="warning", message="收到停止请求：当前步完成后不再继续")`，返回真；没在跑返回假。
  - `state() -> dict`：`{"running": bool, "run": run_id | None, "root", "started_at", "steps": {名: {"status": waiting|running|done|failed|skipped, "stats", "error"}}, "cancel_requested", "result": 最后一次 run.done 的 stats}`——由 `RunLog` 的事件归约（后端也算一份，`/api/state` 刷新页面时直接用）。
  - `log_for(run_id) -> RunLog | None`：当前或最近一次。
  - `recent_roots() -> list[str]`、`remember_root(path)`：读写 `<home>/recent.json`，最多 10 条、去重、最新在前、原子写。
- 线程里不碰任何 FastAPI 对象；`RunLog` 是唯一共享状态。

- [ ] **Step 1: 写失败测试**（全部用假 `run_pipeline`：按步调用 `progress.step/advance/done`，可配置哪步 `failed`、是否睡一会、是否检查 `cancel`）：`test_start_runs_in_background_and_emits_lifecycle`（start 立刻返回 run_id；等线程结束后 `since(0)` 以 `run.start` 开头、`run.done` 结尾，`stats.ok` 真；`state()["running"]` 变假）、`test_second_start_while_running_is_busy`（假流水线阻塞在 `threading.Event` 上；第二次 `start` 抛 `RunBusy`；放行后能再 `start`，新 run_id 不同、序号从 1 起）、`test_cancel_flag_reaches_pipeline`（假流水线每步后查 `cancel()`；`cancel()` 返回真；最终事件是 `run.cancelled`）、`test_state_reduces_events`（scrape 失败、organize 跳过 → `steps.scrape.status == "failed"`、`steps.organize.status == "skipped"`、未跑的 `waiting`）、`test_pipeline_exception_is_reported_not_swallowed`（假流水线抛 `RuntimeError` → `run.done` 带 `ok=false`、`error` 文字；锁已释放）、`test_options_from_payload_validation`（不存在的目录 400 级 `ValueError`；`steps` 含未知名抛；布尔字段 `"false"` 字串不被当真——只认 JSON 布尔）、`test_recent_roots_roundtrip`（去重、最新在前、上限 10、`HIDDEN_SHELF_HOME` 隔离）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: 版本 0.3.1，Commit**：`feat: 进度网页的运行管理器`

---

### Task 2: FastAPI 应用与 SSE

**Files:**
- Create: `src/hidden_shelf/serve/app.py`
- Test: `tests/test_serve_app.py`
- Reference: Starlette `StreamingResponse` 做 SSE；`fastapi.testclient.TestClient` 的 `stream()` 读流

**Interfaces:**
- `app.create_app(manager: RunManager | None = None, *, static_dir=…, template_dir=…) -> FastAPI`。
- `GET /` → 渲染 `progress.html.j2`（注入版本号、默认语言 `zh`、静态文件路径 `/static/...`）。`GET /static/{path}` 只从 `serve/static/` 取，拒绝 `..`。
- `GET /api/state` → `manager.state()` + `{"version", "recent_roots", "steps_order": STEPS, "step_labels": STEP_LABELS}`。
- `POST /api/run`（JSON）→ 202 `{"run": id}`；运行中 409 `{"error": "已有一个运行在进行中，等它结束或先停止"}`；校验失败 400 `{"error": 原因}`。
- `POST /api/cancel` → 202 `{"cancelled": true}`；没在跑 409。
- `POST /api/open`（JSON `{"root"}`）→ `<root>/index.html` 存在：`webbrowser.open(Path(...).resolve().as_uri())`，200 `{"opened": "file:///…"}`；不存在 404 `{"error": "还没有成品，先跑一次"}`。`webbrowser.open` 可注入（`create_app(..., opener=...)`）。
- `GET /api/events?run=<id>` → `text/event-stream`：先按 `Last-Event-ID`（请求头，缺省 0）补发 `log.since(seq)`，再订阅队列实时转发；`RunLog.closed` 且补发完则发最后一条后结束流；队列 15 秒没新事件发 `: ping\n\n`；客户端断开时 `unsubscribe`。`run` 不是当前或最近一次 → 404。响应头 `Cache-Control: no-cache`、`X-Accel-Buffering: no`。
- 同源防护中间件：对 `POST` 检查 `X-Shelf-Request == "1"`，`Origin` 或 `Referer` 的 host ∈ {`127.0.0.1`, `localhost`}（含端口）；不满足 403 `{"error": "请求来源不被信任"}`。`GET` 不检查（SSE 与静态页）。

- [ ] **Step 1: 写失败测试**（`TestClient(create_app(RunManager(run_pipeline=假流水线)))`；POST 都带合法头 `{"X-Shelf-Request": "1", "Origin": "http://127.0.0.1:8031"}`）：`test_index_and_static`（200、含 `progress.js`、`/static/../pyproject.toml` 404）、`test_state_before_any_run`（`running=false`、六个步全 `waiting`、`recent_roots=[]`）、`test_run_then_events_stream_in_order`（POST 202 → `stream("GET", "/api/events?run=…")` 收到 `run.start … run.done`，`id:` 递增，`data` 可 `json.loads`、中文不转义）、`test_reconnect_with_last_event_id_resumes`（Review Focus 1：先收 3 条断开；带 `Last-Event-ID: 3` 再连，第一条 `id: 4`；运行结束后再带 `Last-Event-ID` 连能收到 `run.done` 然后流结束）、`test_busy_and_cancel`（运行中第二次 POST 409；`/api/cancel` 202 → 最终 `run.cancelled`；结束后 `/api/cancel` 409）、`test_bad_root_is_400`、`test_open_requires_index_html`（无 index 404；造一个 → 200 且注入的 opener 收到 `file://` URI）、`test_cross_site_post_is_rejected`（Review Focus 5：无头 403；`Origin: https://evil.example` 403；`Referer: http://localhost:8031/` 无 Origin 放行）、`test_unknown_run_is_404`。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。SSE 生成器用 `queue.get(timeout=15)` 轮询，`asyncio` 侧用 `run_in_threadpool` 包同步生成器或直接 `StreamingResponse(sync_iter)`（Starlette 会在线程池迭代同步生成器）。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: 版本 0.3.2，Commit**：`feat: 进度网页的 HTTP 接口与 SSE 流`

---

### Task 3: 前端页面

**Files:**
- Create: `src/hidden_shelf/serve/templates/progress.html.j2`, `serve/static/progress-core.js`, `serve/static/progress.js`, `serve/static/progress.css`, `serve/static/i18n.js`；复制 `docs/ux-standard/tokens.css`、`ripple.js` 到 `serve/static/`
- Test: `tests/js/progress-core.test.mjs`；`tests/test_serve_app.py` 加 `test_i18n_dictionaries_have_same_keys`（照 `tests/test_site_build.py` 的做法）与 `test_progress_css_uses_only_tokens`
- Reference: `docs/ux-standard/SKILL.md`（布局骨架、状态与反馈、长任务规范）；`site/static/app.js` 的主题/语言切换与 toast 写法可借用（不 import，复制所需片段）

**页面（一页，左侧栏 + 内容区）：**
- 侧栏：品牌「藏片阁」；导航只有一项「运行」（当前项实心主色）；底部：主题三档菜单、「中 / EN」、版本号。
- 内容区标题「运行」，副标题显示服务地址与状态圆点（空闲 / 运行中 / 失败）。
- **表单卡**（≤ 640px）：盘根目录输入框 + `<datalist>` 最近用过的；三个开关：「认不出番号的视频搬到 未识别/」（默认开）、「本次不联网」、「强制重刮」；主按钮「开始」（运行中变为次级「停止」+ 说明「当前步完成后停下」，并显示已用时间）。
- **步骤卡**：六行，每行：状态圆点 + 文字（等待 / 运行中 / 完成 / 失败 / 跳过）、步名、已用时间、进度条（运行中无确定进度时显示条纹动画；`step.progress` 消息匹配 `^\[(\d+)/(\d+)\]` 时显示百分比）、最后一条消息（单行截断，`title` 全文）。完成的步显示 `stats` 里几项摘要（扫描：新增/消失；刮削：问了/落库/封面；归位：移动/跳过；出站：作品数）。
- **日志卡**：等宽字体，按步过滤的分段控件（全部 / 六步），`warning` 用 `--warning`、`error` 用 `--danger` 着色，新行自动滚到底（用户上滚时暂停自动滚动，出现「回到底部」浅色按钮），上限 5000 行。三态：加载骨架（页面刚开）、空（「还没有运行」+ 一句说明）、错误（SSE 断开超过 10 秒：「与服务断开」+ 重试按钮）。
- 结束：toast（成功 4 秒自动消失，失败不消失）；表单卡下出现「打开成品」浅色按钮（`POST /api/open`）；失败时步骤卡里失败步展开错误文字（「查看详情」折叠堆栈不做——后端只给一句）。
- `progress-core.js`（UMD，不碰 DOM）：`reduce(state, event) -> state`（步状态机；`run.start` 重置）、`percentOf(message) -> number | null`、`formatElapsed(ms, lang)`、`filterLog(events, step) -> events`、`summaryOf(step, stats, t) -> string`、`initialState(stepsOrder)`。
- `progress.js`：拉 `/api/state` 初始化（刷新页面能恢复正在跑的运行：按 `state.run` 连 SSE，`Last-Event-ID` 从 0 开始补发全部）；`EventSource` 断开自动重连（浏览器自带 + 我们带 `Last-Event-ID`）；主题与语言与站点一致（`localStorage` 键 `theme`、`lang`）；所有 `fetch` POST 带 `X-Shelf-Request: 1`。

- [ ] **Step 1: 写失败测试**：`progress-core.test.mjs`（`reduce`：start→running、done→done 带 stats、failed→failed、skipped→skipped、`run.start` 重置全部为 waiting、未知步忽略；`percentOf("[3/12] 九宫格 x")` → 25、无匹配 → null；`formatElapsed(65000, "zh")` → `1 分 5 秒`、`"en"` → `1m 5s`；`filterLog` 按步与「全部」；`summaryOf("scan", {"added": 3, "vanished": 1})` 含两个数）；Python 侧 `test_i18n_dictionaries_have_same_keys`、`test_progress_css_uses_only_tokens`（正则无命中）、`test_index_html_references_static_and_no_external_urls`（页面里没有 `http://`、`https://` 字串）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 运行** `uv run pytest -q && node --test "tests/js/**/*.test.mjs"`，PASS。
- [ ] **Step 5: 版本 0.3.3，Commit**：`feat: 进度网页前端`

---

### Task 4: 命令行 `shelf serve` 与端口选择

**Files:**
- Create: `src/hidden_shelf/serve/ports.py`
- Modify: `src/hidden_shelf/cli.py`、`CLAUDE.md`「端口约束」
- Test: `tests/test_cli_serve.py`

**Interfaces:**
- `ports.DEFAULT_PORT = 8031`、`ports.PORT_RANGE = (8000, 8099)`、`ports.is_free(port, host="127.0.0.1") -> bool`（`socket` 试绑）、`ports.pick_port(preferred: int | None) -> int`：给了 `preferred` 就只试它（被占抛 `PortInUse(RuntimeError)`）；没给从 `DEFAULT_PORT` 起在范围内找第一个空闲，都满抛 `PortInUse`。
- `cli`：子命令 `serve`（不收 `root`）：`--port <int>`、`--no-browser`、`--verbose`。流程：`pick_port` → 打印 `进度网页：http://127.0.0.1:<port>/`（被换口时多打一行「默认端口 8031 被占，改用 <port>」）→ 非 `--no-browser` 时 `webbrowser.open(url)` → `uvicorn.run(create_app(RunManager()), host="127.0.0.1", port=port, log_level="warning")`。`PortInUse` → 打印原因退出码 2。`uvicorn.run` 与 `webbrowser.open` 可 monkeypatch。
- 命令行 `run` 等子命令行为不变。

- [ ] **Step 1: 写失败测试**：`test_pick_port_prefers_default_then_next_free`（用真 socket 占住 8031 → 返回 8032；指定 `--port` 被占抛）、`test_cli_serve_starts_uvicorn_on_loopback`（monkeypatch `uvicorn.run` 记参数、`webbrowser.open` 记 URL、`pick_port` 返回 8031 → host 是 `127.0.0.1`、URL 一致、退出码 0）、`test_cli_serve_no_browser`、`test_cli_serve_port_in_use_exit_2`（Review Focus 7）、`test_cli_serve_app_is_the_real_one`（传给 uvicorn 的 app 有 `/api/state` 路由）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。`CLAUDE.md`「端口约束」登记：`shelf serve` 默认 8031（8000–8099 段，只监听 127.0.0.1；本机实施时按 `~/.claude/ports.md` 调整并写回）。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: 版本 0.3.4，Commit**：`feat: shelf serve 子命令与端口选择`

---

### Task 5: 端到端验证与文档

**Files:**
- Modify: `CLAUDE.md`（当前阶段、命令、架构加进度网页一节）、`README.md`（`shelf serve` 用法）、`docs/REUSE.md`（核对：本计划无移植，加一行说明 `serve/` 全部自写）
- Test: `tests/test_serve_e2e.py`（真流水线 + `fake_video`，ffmpeg 缺则 skip）；手动清单用 Playwright 对着真服务器跑（脚本放 scratchpad，不进仓库）

**Interfaces:** 无新接口。

- [ ] **Step 1: 写失败测试** `test_serve_runs_a_real_disk_and_matches_cli_output`（Review Focus 6：同一块演示盘先 `cli.main(["run", root, "--offline"])` 用 `capsys` 收集每行正文（去 `[步名] ` 前缀与 `== 步名 ==` 行）；再起 `TestClient` 跑 `/api/run`（`offline=true`）收齐 SSE 的 `step.progress`/`step.done` 消息；两边消除时间戳与路径后逐行相等；`run.done.stats.ok` 真、`index.html` 存在；`/api/open` 200）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现与修正**（多半是 `ConsoleProgress` 与 `EventProgress` 的文字对齐）。
- [ ] **Step 4: 手动清单**（云端用 Playwright 无头 Chromium 连 `http://127.0.0.1:<port>/`，`shelf serve --no-browser` 在后台跑；本机用真浏览器）：
  - 页面打开有六行「等待」，日志区是空态文案；最近目录下拉为空。
  - 填演示盘路径、勾「本次不联网」、点「开始」：按钮变「停止」并计时；六行依次变「运行中」→「完成」，`刮削` 行为「跳过」；日志实时滚动，媒体步出现百分比；结束 toast，出现「打开成品」，点它（无头下断言 opener 被调或 200）。
  - 刷新页面：状态与日志恢复（`/api/state` + `Last-Event-ID: 0` 补发）。
  - 再点「开始」立刻再点「停止」：当前步完成后停下，`run.cancelled` toast，步骤行其余保持「等待」。
  - 填不存在的目录：字段下方红字，不发请求失败 toast 乱飞。
  - 深色主题、英文、375px 宽：无横向滚动、侧栏变抽屉、控制台无报错；`progress.css` 无裸色值。
  - 第二个终端 `curl -X POST http://127.0.0.1:<port>/api/run -H 'Origin: https://evil.example' -H 'X-Shelf-Request: 1' -d '{}'` → 403。
- [ ] **Step 5: 更新文档**：`CLAUDE.md`「当前阶段」改 v0.3.5、计划 3 完成；「命令」加 `uv run shelf serve [--port 8031] [--no-browser]`；「架构」加 `serve/` 一节（事件模型、SSE 格式、单运行、取消语义、同源防护、recent.json 位置）；`README.md` 加「进度网页」一小节。
- [ ] **Step 6: 版本 0.3.5，Commit**：`feat: 进度网页端到端验证；更新项目文档`

---

## 已知风险与取舍

- **跨进程不互斥**：网页在跑的同时命令行对同一盘 `shelf run`，两边都会碰 `.shelf/shelf.db`（WAL 下多半是一边等锁或报 `database is locked`）。本计划只在服务进程内保证单运行；要跨进程互斥得加 `.shelf/run.lock`，留给后续。
- **取消粒度是「步」**：媒体步在大盘上可能跑几十分钟，点「停止」要等它跑完。要步内取消得把 `cancel` 传进 `process_assets` 与 `scrape_assets` 的循环里，本计划不做，页面上把语义写清。
- **进度条多数是不确定进度**：只有 `scan`（无）、`media`（有 `[i/total]`）、`scrape`（无每条计数）给得出百分比；其余只显示运行中条纹与已用时间。要真百分比得改各步先数总量再报，本计划不改规则模块。
- **`webbrowser.open` 在无桌面环境**（SSH、容器）会静默失败或打印警告，`--no-browser` 可绕过；不算错误。
- **uvicorn 的访问日志**关掉（`log_level="warning"`），SSE 每 15 秒的 ping 不进日志；流水线自己的日志照旧写 `.shelf/logs/`。

## 自检记录

- Spec 覆盖：§1 目标 4「本机小网页显示进度和日志；命令行一条命令跑全程」→ Task 2/3/4；§2 端口只监听 127.0.0.1、8000–8099 → Task 4 与 Global Constraints；§4.1「fastapi + uvicorn 只给进度网页；纯 HTML + 原生 JS；SSE」→ Task 0/2/3；§4.3「进度网页和命令行输出一致」→ Review Focus 6 与 Task 5 的端到端；§4.5 的页面要素（根目录下拉、未识别开关、开始、每步进度条与实时日志、打开成品、同一时刻一个运行）→ Task 1/2/3；§5 留给建造者的 SSE 细节与日志格式 → Global Constraints 里定死。
- 与计划 1、2 的接口：`Progress` 只加默认空实现的方法，`ConsoleProgress` 输出文字不变（Task 0 的回归测试钉住）；`pipeline.run` 新参数可选、默认行为不变；`ScrapeOptions` 复用；不改 `site/`、`scrape/`、`organize/`、`media/`。
- Review Focus 七条各有对应测试（已标注任务）。
- ux-standard 自查清单（SKILL.md §10）在 Task 3 Step 4 与 Task 5 Step 4 逐项过。
