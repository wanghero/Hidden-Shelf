# Hidden Shelf 计划 2：联网刮削 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在计划 1 的本地流水线里加一步「刮削」：按 peach 的来源链逐站问番号资料与封面，单来源就落库（用户定的「最宽松」口径），分歧按字段优先级链结算；原始响应落 `.shelf/sources/` 快照，7 天内不重问；403/429 按站冷却到下次运行；失败只记日志不中断，归位与出站照常。

**Architecture:** 规则模块照抄 peach（站点解析器契约、8 个自写解析器、路由表、分级表、身份核对、封面择优判据），跑法自写：`scrape/run.py` 一个薄编排层按「档」问链、`scrape/settle.py` 按链结算、`scrape/apply.py` 以 `auto:<来源>` 身份经 `field_owners` 落库。传输层自写（httpx + 按主机限速 + 按来源 Cookie + 冷却），不接 amane 子进程、不接本机浏览器。

**Tech Stack:** 计划 1 的栈 + `httpx`（HTTP/SOCKS 代理）+ `beautifulsoup4`（javdb、fc2、javarchive 解析）；`curl_cffi` 为可选依赖（`[project.optional-dependencies] fingerprint`），只给 AVBase 这种撞 Cloudflare 的站用，没装就走 httpx。

**Spec:** `docs/superpowers/specs/2026-10-28-hidden-shelf-design.md` §3（单来源资料最宽松）、§4.3 第 2 步、§4.6、§4.7、§6。

前置：计划 1 已完成（v0.1.15）。后续：计划 3「进度网页」。

## Global Constraints

- 计划 1 的全部约束继续有效（路径 POSIX、`.shelf/` 布局、`field_owners`、不删原始文件、版本号 +0.0.1、中文提交并 push）。本计划版本从 **0.2.0** 起，每个任务 +0.0.1。
- **只移植 peach 自写解析器的 8 个站**：`r18dev`、`dmm`、`1pondo`、`fc2`、`javarchive`、`avbase`、`javbus`、`javdb`。经 amane 桥的站（`prestige`、`faleno`、`dahlia`、`makers`、`mgstage`、`avsox`、`fc2club`、`freejavbt`、`airav`）和要本机浏览器过 Cloudflare 的站（`fc2cmadb`、`fc2ppvdb`、`javten`）**不接**；它们在路由表里不出现，不留占位。覆盖率影响见 spec §6（素人系少了 mgstage，FC2 链少了两个存档站）。
- 每个站只有一个归属，来源名在 `policy.SOURCE_SPECS` 登记一次，链、快照文件名、`field_owners` 的 `auto:<来源>`、实体关联的 `source` 都用同一个名字。
- **落库口径（spec §3、§4.7）**：一家来源给了就直接写，不要求两家互证，不进复核。一行里同一字段几家不一致时按 `policy.chain_rank` 取链首；跨次运行时，字段现值归属 `auto:<来源A>`、新来源 B 的层级（`policy.source_tier`）**严格更高**（数字更小）才覆盖，同级或更低不动（先到先得）。`auto:nfo`（本地 NFO）是层级 0，联网来源永远盖不过它；`user:*`、`review:*` 由 `field_owners` 挡住。
- **身份核对压在一切之上**：来源返回的番号与问的对不上（`identity.identifies_code`）整条记录不落库、不进快照 `result`（记成 `error.reason = "identity_mismatch"`，当「没有」对待）。
- **「没拿到」不缓存成「没有」**：只有 `not_found` 类（`FailureReason.NOT_FOUND / GONE / NO_USABLE_METADATA`）和身份错配写进快照并记 7 天；超时、5xx、网络、限流、拒绝访问一概不写快照。
- **冷却按站、按次运行**：403 首停 15 分钟、连续再撞翻倍到该站上限；429 按 `Retry-After`（没有就 15 分钟）。冷却记在 `.shelf/sources/_cooldown.json`，本趟后面的番号直接跳过这一站，下次运行到期才问。
- 主机间隔：默认 2 秒，javdb 3 秒（页面与图床同计）。整个进程一把限速器。
- 请求只发 HTTPS，重定向只跟 HTTPS，跨域不带 Cookie；页面大小有上限（各站 `SiteConfig.page_limit`）。User-Agent 用一份标准桌面 Chrome 串。
- 配置分两层：本盘 `.shelf/config.json` 加 `scrape: bool`（默认 true）；跨盘 `~/.hidden-shelf/config.json` 放代理三选一、各站 Cookie 与开关、路由覆盖。**凭据不进盘里的任何文件**，不进日志，不进快照。
- 封面：只在 asset 没有封面或封面归属是 `auto:frame` 时联网取；`auto:local` 的本地旧封面不被联网替换。JavDB 的转存图不当封面（只做证据，照 peach）。装上的封面归属 `auto:<来源>`，海报与九宫格仍由计划 1 的 `media` 步骤生成。
- 头像：只用 r18.dev `combined` 页给的 DMM 官方头像（`pics.dmm.co.jp/mono/actjpgs/`），落 `avatars/<entity_id>.jpg`；没有的站点显示首字圆标（计划 1 已做）。不抓艺人页。
- 刮削步骤**自己兜底**：任一番号、任一站失败只记日志计数；整步没网时报一条告警后流水线继续（归位会落 `_未知厂牌/`，出站照常）。
- 测试不发真实请求：传输层可注入（`Session.transport` 是一个 `(HttpRequest, timeout, limit) -> HttpResponse` 可调用），解析器测试只喂 `parse` 一张页面。

## Review Focus

1. **番号错配**：r18dev `dvd_id=ABW-358` 回的是别的 `content_id`、javbus 搜不到时给近似命中、avbase 给收录本作的合集——都必须整条拒收。→ Task 1、4、5。
2. **不覆盖用户与本地资料**：`overrides.json` 写过的标题、NFO 导入的厂牌，联网来源再给也写不进；`auto:frame` 封面会被联网封面换掉，`auto:local` 不会。→ Task 8、9。
3. **冷却生效**：一站回 403 后，本趟后面的番号对这一站零请求；写盘的冷却记录让下次运行在到期前照样跳过；通了一次就清记录。→ Task 2、10。
4. **失败不缓存**：模拟超时与 503，快照目录里不出现这一站的文件；模拟 404，出现 `error.reason = not_found` 且 7 天内不再请求；第 8 天重问。→ Task 2、10。
5. **断网也能跑完**：传输层全部抛连接错误时，`shelf run` 仍产出 `index.html`，退出码 0，日志里有「刮削未取得」计数。→ Task 10。
6. **合集封面串号**：`259LUXU-1475` 在 avbase 上的主图是 `118sng021` 的封套，`is_cross_product_cover` 要把它剔掉。→ Task 9。
7. **艺人实体不乱建**：`本庄美奈子 30歳 元カフェ店員` 剪成 `本庄美奈子`；`145cm色白お嬢様` 这类描述性称呼不建实体；r18dev 的 `涼森れむ` 与 javdb 的 `涼森れむ` 合成一个实体并挂两个外站 ID。→ Task 7、8。

---

## 文件结构

```
Hidden-Shelf/
  pyproject.toml                       dependencies += httpx>=0.27, beautifulsoup4>=4.12；optional fingerprint = [curl_cffi]
  src/hidden_shelf/
    netconfig.py                       ~/.hidden-shelf/config.json：代理模式、各站 Cookie/开关、路由覆盖
    migrations/0002_scrape.sql         entity_alias 加 source/confidence；entity_external_ref；entity.avatar_file；asset.scraped_at/scrape_note
    kanji.py                           ← peach kanji.py（字形折叠，比名字用）
    scrape/
      __init__.py
      transport.py                     HttpRequest/HttpResponse、HttpxTransport、CurlTransport（可选）、HostLimiter、USER_AGENT、_fetch 分档
      access.py                        冷却记录、SourceTransport（按来源带 Cookie、算冷却、计预算）
      snapshots.py                     .shelf/sources/<番号>-<来源>.json 读写、新鲜度、「没有」记忆
      identity.py                      ← peach metadata.py 的 identifies_code / validate_provider_code
      names.py                         ← peach metadata_alias_resolve.py（stage_name、is_descriptive、is_planning_alias）+ metadata.py 的 split_former_name / normalized_performers
      routes.py                        ← peach metadata_routes.py（裁掉未接的站）
      policy.py                        ← peach metadata_policy.py（裁掉未接的站与历史来源）
      sources/
        __init__.py                    SITE_SOURCES 登记表
        base.py                        ← peach sources/base.py
        r18dev.py dmm.py onepondo.py   ← peach 同名模块
        fc2.py javarchive.py           ← peach 同名模块
        avbase.py javbus.py javdb.py   ← peach 同名模块（javdb 去掉磁链与评论）
        javdb_helpers.py               ← peach javdb.py 的 clean / LOGIN / RECORD_KIND
      settle.py                        一个番号几家记录 → 每字段一个胜出值（链结算、番号日期、javbus 兜底）
      apply.py                         胜出值 → asset 列（分级覆盖）与实体关联（performers/tags/studio/series + 外站 ID + 别名）
      covers.py                        ← peach jav_cover_fetch.py 的候选、CDN 变体、串号判据、Range 量尺寸、择优下载
      avatars.py                       r18.dev 官方头像 → avatars/<entity_id>.jpg
      run.py                           scrape_assets：该不该问 → 链 → 按档问 → 结算 → 落库 → 封面 → 头像；ScrapeResult
    entities.py                        扩展：find_by_external_ref、add_alias、resolve_performer（外站 ID > 规范名 > 唯一别名 > 字形折叠）
    pipeline.py                        步骤表加 scrape（import 之后、organize 之前）；scrape 失败不中断
    cli.py                             scrape 子命令；run 默认含 scrape；--offline、--sources、--routes
    site/build.py                      performers[].avatar 指向 .shelf/avatars/<id>.jpg（存在时）
  tests/
    fixtures/sources/                  各站样例页（从 peach 测试里的内联样例搬来；peach 没有的手写最小页）
    test_netconfig.py test_transport.py test_access.py test_snapshots.py test_identity.py test_names.py
    test_routes.py test_policy.py test_sources_official.py test_sources_community.py test_sources_fc2.py
    test_entities_scrape.py test_settle.py test_apply_scrape.py test_covers_online.py test_avatars.py
    test_scrape_run.py test_pipeline_scrape.py
```

---

### Task 0: 依赖、全局配置与传输层

**Files:**
- Modify: `pyproject.toml`（依赖、可选依赖、版本 0.2.0）
- Create: `src/hidden_shelf/netconfig.py`, `src/hidden_shelf/scrape/__init__.py`, `src/hidden_shelf/scrape/transport.py`
- Test: `tests/test_netconfig.py`, `tests/test_transport.py`
- Reference: `reference/peach/src/peach/peach_proxy.py`（三选一语义）、`http.py`（HttpRequest/HttpResponse、有界读取）、`scripting.py` 的 `HostLimiter`、`user_agent.py`、`jav_cover_fetch._fetch`（重试与分档）

**Interfaces:**
- `netconfig.GlobalConfig`（dataclass）：`network_mode: "environment"|"direct"|"proxy"`、`proxy: str`、`sources: dict[str, SourceSettings]`（`SourceSettings(enabled: bool = True, cookie: str = "")`）、`routes: dict[str, list[str]]`（整条覆盖）。`load(path=~/.hidden-shelf/config.json) -> GlobalConfig`（不存在写默认；坏 JSON 用默认不覆盖）、`save()`；`client_options() -> dict`（`{"trust_env": True}` / `{"trust_env": False}` / `{"trust_env": False, "proxy": url}`）；代理地址校验照 peach `validate`（http/https/socks5/socks5h + 端口，不带 query/fragment/空白）。路径可用环境变量 `HIDDEN_SHELF_HOME` 覆盖（测试用）。
- `transport.USER_AGENT`（标准桌面 Chrome 串）、`@dataclass HttpRequest(method, url, headers: dict, body: bytes|None)`、`@dataclass HttpResponse(status, headers: dict, body: bytes, url: str)`；`Transport = Callable[[HttpRequest, float, int], HttpResponse]`（超时秒、最大字节）。
- `HttpxTransport(client: httpx.Client)`：发请求、按 `max_bytes` 有界读取（超限抛 `PageTooLarge(ValueError)`）、不自动跟重定向；`close()`。
- `CurlTransport(impersonate="chrome")`：`curl_cffi` 装了才可用；接口同上。`available() -> bool`。
- `HostLimiter(intervals: dict[str, float], default: float = 2.0)`：`wait(host)` 按主机（点边界匹配）睡到下次可发时刻；线程安全。
- `PROBE_BYTES = 64 KiB`、`NETWORK_RETRY_DELAYS = (2, 4, 6, 8)`、`class Unavailable(RuntimeError)`、`class NotFound(Unavailable)`、`class DeadlineExceeded(RuntimeError)`；`fetch(transport, url, *, referer, limit, ranged=False, extra_headers=None, deadline=None, method="GET", body=None) -> bytes`：`TransportError` 按退避表重试；最终地址命中 `now_printing` 抛 `NotFound("来源给的是「准备中」占位图")`；404 抛 `NotFound("HTTP 404")`；非 200/206 抛 `Unavailable("HTTP <状态>")`。
- `follow_redirects(transport, request, timeout, limit, *, max_hops=6)`：只跟 HTTPS，跨域去掉 `Cookie`/`Authorization`，303 改 GET。

- [ ] **Step 1: 写失败测试**：`test_global_config_defaults_and_roundtrip`（`HIDDEN_SHELF_HOME` 指到 tmp；默认 environment；改 proxy 保存再读）、`test_proxy_validation`（`socks5h://127.0.0.1:1080` 合法；`http://x` 无端口、带空格、带 `?q` 非法）、`test_client_options_three_modes`、`test_host_limiter_spaces_requests`（用注入的 `clock`/`sleep` 断言两次同主机间隔 ≥ 2 秒，`javdb.com` 3 秒，不同主机不互等，`img.javdb.com` 按点边界算到 `javdb.com`）、`test_fetch_retries_transport_errors_then_raises`（假传输前 4 次抛 `httpx.TransportError`，第 5 次成功；5 次都抛则抛出）、`test_fetch_tiers`（404 → NotFound；503 → Unavailable("HTTP 503")；`now_printing` 跳转 → NotFound 占位）、`test_fetch_ranged_header`（`ranged=True` 带 `Range: bytes=0-65535`）、`test_redirect_rules`（https→http 拒绝；跨域去 Cookie；超过 6 跳抛）、`test_bounded_body`（超过 limit 抛 `PageTooLarge`）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。`uv add httpx beautifulsoup4`，`uv add --optional fingerprint curl_cffi`。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: 版本 0.2.0，Commit**：`feat: 联网刮削的全局配置与传输层`

---

### Task 1: 来源契约与番号身份核对

**Files:**
- Create: `src/hidden_shelf/scrape/sources/__init__.py`, `scrape/sources/base.py`, `scrape/identity.py`
- Test: `tests/test_identity.py`, `tests/test_sources_contract.py`
- Reference: `reference/peach/src/peach/sources/base.py`；`metadata.py` 的 `identifies_code`、`validate_provider_code`、`_release_writings`；断言来源 `reference/peach/tests/test_metadata_sources.py` 的 `ContractTests`、`FailureReasonTests`，`tests/test_resource_identification.py` 里 `identifies_code` 的用例

**Interfaces:**
- `identity.validate_provider_code(code) -> str`（Tokyo-Hot 小写，其余大写；不是番号形状抛 `ValueError`）、`identity.identifies_code(code, payload: dict) -> bool`（照 peach：`same_release_code` 并集宽松正则；三位数字前缀番号只比 `id`/`content_id`；mgstage 分支删掉——不接那站）。
- `base.FailureReason`（12 档照抄）、`REASON_KINDS`、`COOLDOWN_ACTIONS`（`blocked` / `rate_limited`）、`PERMANENT_REASONS`、`challenge_page(html) -> bool`、`DEFAULT_PAGE_LIMIT = 4 MiB`、`DEFAULT_INTERVAL = 2.0`。
- `SourceFailure(reason, message, *, status_code=0, detail="")`：属性 `kind`、`cooldown_action`、`held`。`http_failure(error: Unavailable) -> SourceFailure`。
- `@dataclass(frozen) SiteConfig(name, label, provider, base_url, domains, stage, interval=2.0, cookie=False, page_limit=...)`；`Page(url, body)`；`Session(transport, deadline=None)` 的 `get()` / `post()` 调 `transport.fetch`。
- `@dataclass(frozen) SiteRecord(source, provenance, code, source_url, title, performers, studio, label, series, director, release_date, runtime, tags, cover_urls, confidence, extra)`，`payload()` 投影（`id`、`maker`、`actresses`、`genres`、`cover_urls`……键名照 peach，快照存的就是它）。
- `SiteSource`：`DEFAULT`、`fetch(code, *, session) -> Page`、`parse(page, code) -> SiteRecord`、`holding(session)`（`Unavailable` → `SourceFailure`，`COOLDOWN_ACTIONS` 的细档交给 `session.transport.hold(source, action)`，有这个方法才记）、`query()`、`records()`。
- `sources.SITE_SOURCES: dict[str, type[SiteSource]]`（本任务先空，各站任务逐个登记）。

- [ ] **Step 1: 写失败测试**：`test_identifies_code`（搬 peach 用例：`118abw220` 认 `ABW-220`；`h_086iqqq00026` 认 `IQQQ-026`；`FC2-PPV-3701252` 与 `3701252`；`MAAN-545` 与 `300MAAN-545`；dl.getchu 那种 `item33938` 拒）、`test_validate_provider_code`（`n0646` 保持小写；`../x` 抛）、契约测试搬 `ContractTests`（`DemoSource` 喂页面不起传输；`query` 把 HTTP 分档翻成 reason；`parse_error` 不可重试；`payload()` 逐键）、`FailureReasonTests`（12 档各有 kind；只有验证页/封禁/地区/限流进冷却）、`test_holding_records_cooldown_once`（嵌套 `holding` 只记一次；传输没有 `hold` 就不记）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 移植**。`Session.get/post` 改调本项目 `transport.fetch`。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.2.1，Commit**：`feat: 移植站点解析器契约与番号身份核对`

---

### Task 2: 来源冷却、按来源传输与快照

**Files:**
- Create: `src/hidden_shelf/scrape/access.py`, `src/hidden_shelf/scrape/snapshots.py`
- Test: `tests/test_access.py`, `tests/test_snapshots.py`
- Reference: `reference/peach/src/peach/scraping_access.py` 的 `SOURCES`（只留 8 站）、`FIRST_BLOCKED_PAUSE`、`pause_source`、`SourceTransport`；`library_processing.py` 的 `_MissCache`、`_cached_evidence`、`_evidence_path`、`MISS_TTL_SECONDS`

**Interfaces:**
- `access.SOURCES`：8 站的 `label`、`domains`、`login`、`cookie`、`blocked_pause`（javdb 24h、javbus/avbase/javarchive 6h，其余不冷却 403 只报错）。`source_for(url) -> str | None`（按域名后缀）。
- `access.Cooldown(path: Path)`：`paused_until(source) -> float`、`pause(source, *, action: "blocked"|"rate_limited", retry_after: float | None = None)`（`blocked` 首停 900 秒、连续翻倍到上限；`rate_limited` 按 `retry_after` 或 900 秒）、`clear(source)`、`describe() -> dict`。文件 `.shelf/sources/_cooldown.json`，原子写。
- `access.SourceTransport(cooldown: Cooldown, config: GlobalConfig, *, limiter: HostLimiter, factory=None, max_requests=0, max_seconds=0)`：可调用 `(request, timeout, limit) -> HttpResponse`。按 `source_for` 选连接池（每站一个 httpx client，带该站 Cookie、代理按 `client_options`）、先 `limiter.wait(host)`、冷却中抛 `SourcePaused(RuntimeError)`、跟重定向、403 且该站有 `blocked_pause` → `pause(blocked)` 并抛 `SourcePaused`、429 → `pause(rate_limited)` 并抛、通了一次清记录；预算用完抛 `SourcePaused`。`hold(source, action)` 给 `SiteSource.holding` 用。`factory` 注入假传输（测试）。
- `snapshots.Snapshots(root: Path = paths.sources, *, ttl=7 天, now=time.time)`：`path(code_key, source)`；`load(code_key, source) -> dict | None`（新鲜且有 `result` 才回）；`fresh_miss(code_key, source) -> bool`；`save_result(code_key, source, payload)`；`save_miss(code_key, source, reason, message)`；文件形状 `{"fetched_at": iso, "source": name, "code": key, "result": payload}` 或 `{"...", "error": {"reason", "message"}}`；`forget(code_key)`。只有 `not_found` 类与 `identity_mismatch` 走 `save_miss`，调用方保证。

- [ ] **Step 1: 写失败测试**：`test_cooldown_blocked_doubles_to_cap`（900 → 1800 → … → 上限）、`test_cooldown_rate_limited_uses_retry_after`（`Retry-After: 120` 与 HTTP 日期两种）、`test_cooldown_persists_and_clears`（新建对象读回；通了清）、`test_source_transport_skips_paused_source`（冷却中直接抛 `SourcePaused`，假传输零调用）、`test_source_transport_403_pauses_javdb_not_r18dev`、`test_source_transport_sends_cookie_only_to_its_domains`（javdb 的 Cookie 不发给 jdbimgs 以外的域；跨域重定向去 Cookie）、`test_source_transport_respects_limiter`（注入 limiter 记录 `wait` 调用）、`test_snapshot_roundtrip_and_ttl`（7 天内 `load` 命中，第 8 天 None）、`test_snapshot_miss_memory`（`save_miss` 后 `fresh_miss` 真，过期假）、`test_snapshot_transient_never_written`（只提供 `save_miss` 一个写失败的入口，断言 `Unavailable` 类不会被调用方写——在 Task 10 覆盖，这里只测接口）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: REUSE.md 加行（`SOURCES`、冷却翻倍、快照 TTL 取自 peach），版本 0.2.2，Commit**：`feat: 来源冷却、按来源传输与原始快照`

---

### Task 3: 路由与分级策略

**Files:**
- Create: `src/hidden_shelf/scrape/routes.py`, `src/hidden_shelf/scrape/policy.py`
- Test: `tests/test_routes.py`, `tests/test_policy.py`
- Reference: `reference/peach/src/peach/metadata_routes.py`、`metadata_policy.py`；断言来源 `reference/peach/tests/test_metadata_routes.py`、`test_metadata_policy.py`

**Interfaces:**
- `policy.SOURCE_SPECS`：只登记 8 站（`r18dev: official_mirror`，`dmm/fc2/1pondo: official`，`avbase/javbus/javdb/javarchive: community`）；`LOCAL_NFO_SOURCE = "nfo"`（与计划 1 的 `auto:nfo` 对齐）；`PREFERRED_COMMUNITY_SOURCE = "javdb"`、`FALLBACK_SOURCES = ("javbus",)`；`CHAIN_*` 层级；`FIELD_SOURCE_PRIORITY = {}`（fc2cmadb 那行随站删掉）；`FIELD_SOURCE_ORDER` 各字段只留接了的站，顺序照 peach（`release_date` 里 r18dev 排在 fc2 之后、javdb 之前；`tags` 里 javdb 对有码提到链首）；`source_tier(source)`、`chain_rank(field, source, *, code=None)`、`field_rank`、`sort_candidates`、`preferred_tag_source(code)`、`blacklisted`；**新增** `owner_tier(owner: str) -> int`（`auto:nfo` → 0，`auto:<站>` → 该站层级，`auto:local`/`auto:frame` 只对 `cover_file` 有意义：`local` = 0、`frame` = 99，其余未知 → `CHAIN_UNKNOWN`）。
- `routes.CONTENT_TYPES`、`MGS_AMATEUR_PREFIXES`、`OTHER_SYSTEM_MARKS`、`classify(code, *hints)`（照抄）、`ROUTES`（裁剪后）：
  - `censored: ("r18dev", "dmm", "avbase", "javbus", "javdb")`
  - `amateur: ("avbase", "javbus", "javdb", "r18dev")`
  - `uncensored: ("1pondo", "avbase", "javbus", "javdb")`
  - `fc2: ("fc2", "javarchive", "javdb")`
  - `kmib / other / unknown: ()`，`unsure: ("avbase", "javbus", "javdb")`
- `OFFICIAL_STAGE = ("r18dev", "dmm", "1pondo", "fc2", "javarchive")`、`FC2_STAGE = ("fc2", "javarchive")`、`COMMUNITY_STAGE = ("avbase", "javbus", "javdb")`、`LIST_FIELD_DEPTH = 3`、`SCALAR_FIELDS`、`LIST_FIELDS`、`OFFICIAL_STAGE_NAMES = ("r18dev", "1pondo", "fc2")`；`parse_route_overrides`、`route`、`route_for_code(code, *hints, overrides=None)`（1pondo 要证据照 peach；`MAKER_EVIDENCE` 整段删掉）、`community_route`、`stages_for_code`、`stage_name`、`stages_for_chain`、`stage_members`、`official_route`、`required_scalars`、`settles(required, provided, *, wants_tags=False, then="")`。

- [ ] **Step 1: 写失败测试**：搬 peach `ClassifyTests`（形状分类；本机证据把 `LUXU-688` + `259LUXU-688.mp4` 判素人；国产标记判 other；读错号判 unsure）、`RouteTableTests` 按裁剪后的表改期望（有码不问 mgstage/prestige；素人不问 dmm；无码不问 r18dev；FC2 只问 fc2、javarchive、javdb；1pondo 只在证据指着一本道时在链上）、`StageTests`、`ShortCircuitTests`（`settles` 的几种情形）、`OverrideTests`（整条替换；未知来源名报错；空链合法）；policy：搬 `MetadataPolicyTests`（链上每站登记一次；有码标签 javdb 链首；nfo 层级 0；javbus 兜底；发行方排在 r18dev 前）+ `test_owner_tier`。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 移植并裁剪**。每条链后面的注释保留，并补一句「本项目不接 X，所以这里没有」。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.2.3，Commit**：`feat: 移植来源路由与字段分级策略`

---

### Task 4: 官方来源解析器（r18dev、dmm、1pondo）

**Files:**
- Create: `src/hidden_shelf/scrape/sources/r18dev.py`, `scrape/sources/dmm.py`, `scrape/sources/onepondo.py`
- Create: `tests/fixtures/sources/r18dev-detail.json`, `r18dev-combined.json`, `dmm-content.json`, `dmm-search.json`, `1pondo-detail.json`
- Test: `tests/test_sources_official.py`
- Reference: peach 同名模块；夹具与断言来源 `reference/peach/tests/test_metadata_r18dev.py`（`DETAIL`、`COMBINED`、`EXPECTED`）、`test_metadata_dmm.py`、`tests/test_metadata_sources.py` 里 1pondo 的样例

**Interfaces（与 peach 同名）:**
- `r18dev.R18DEV`、`R18DevSource`（`detail_url`、`combined_url`、`fetch`、`parse`、`japanese`、`query`）、`actresses(rows)`（含 `thumb_url` 官方头像地址）、`with_japanese`、`english_only`、`ACTRESS_IMAGE`。
- `dmm.DMM`、`DmmSource`（GraphQL：`guessed_cid` → `identified` → `search` 兜底，`DETAIL_ATTEMPTS = 2`）、`code_from_cid`、`code_parts`、`guessed_cid`、`matching_cids`、`release_date`（JST）。
- `onepondo.ONEPONDO`、`OnePondoSource`、`movie_id`、`names_this_studio`、`STUDIO = "一本道"`。
- 三站登记进 `SITE_SOURCES`。

- [ ] **Step 1: 写失败测试**：r18dev——`test_parse_english_page`、`test_query_merges_japanese_page`（假传输按 URL 回 detail/combined，断言 `payload()` 与 peach `EXPECTED` 逐键相等，演员带 `thumb_url`）、`test_combined_for_another_work_counts_as_missing`、`test_identity_mismatch_is_parse_error`（`content_id` 对不上）、`test_404_is_not_found`；dmm——`test_guessed_cid_and_matching_cids`（`SSIS-057` → `ssis00057`；搜索结果里 `ssis00570` 排除、`48midv00012ai` 排原版后）、`test_fetch_tries_guess_then_search`（记录 POST 次数）、`test_release_date_to_jst`（`2021-05-06T15:00:00Z` → `2021-05-07`）、`test_parse_record`（厂牌日文名、genre、cover `largeUrl`）；1pondo——`test_movie_id_and_studio_evidence`、`test_parse_rejects_other_movie_id`、`test_parse_record`（时长秒→分、封面取 `ThumbUltra`）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 移植**。`Unavailable`/`NotFound` 改从 `scrape.transport` 导入；`identifies_code` 从 `scrape.identity`。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: REUSE.md 加三行，版本 0.2.4，Commit**：`feat: 移植 r18.dev、DMM 与一本道解析器`

---

### Task 5: 社区来源解析器（javdb、javbus、avbase）

**Files:**
- Create: `src/hidden_shelf/scrape/sources/javdb_helpers.py`, `scrape/sources/javdb.py`, `scrape/sources/javbus.py`, `scrape/sources/avbase.py`
- Create: `tests/fixtures/sources/javdb-search.html`, `javdb-detail.html`, `javdb-login.html`, `javbus-work.html`, `javbus-gate.html`, `avbase-works.html`, `avbase-challenge.html`
- Test: `tests/test_sources_community.py`
- Reference: peach 同名模块；`javdb.py` 的 `clean`、`LOGIN`、`RECORD_KIND`；断言来源 `tests/test_metadata_sources.py` 的 `JavDBResourceTests`（只搬标题/身份/类别三条）、`SiteCooldownTests`（AVBase 200 验证页）

**Interfaces（与 peach 同名）:**
- `javdb_helpers.clean(text)`、`LOGIN`、`RECORD_KIND`。
- `javdb.JAVDB`（interval 3.0，cookie True，域名含 `jdbstatic.com`、`jdbimgs.com`）、`JavDBSource`（`search_url`、`fetch`：搜索页按 `same_release_code` 取唯一 `/v/` 路径，多个抛 `PARSE_ERROR(identity_ambiguous)`；详情页 `?locale=zh`；登入页抛 `AUTH_REQUIRED`；`parse` 读 `番號/日期/片商/發行/系列/導演/演員/類別`，女优带 `external_id`，`origin-title` 优先）、`actresses`、`maker_writing`。**不移植** `resources`、`parse_magnets`、`parse_comment_links`、`merge_resources`。
- `javbus.JAVBUS`（cookie True）、`JavBusSource`（`/<番号>`；门页抛 `AUTH_REQUIRED`；`識別碼` 对不上抛 `NOT_FOUND`）。`SourceTransport` 给 javbus 加 `Accept-Language: zh-CN`（在 Task 2 的传输里按站名加）。
- `avbase.AVBASE`、`AVBaseSource`（`__NEXT_DATA__`；`own_products` 商品号认番号 > 标题相等；`PRODUCT_ORDER`；验证页抛 `CLOUDFLARE_CHALLENGE`）、`listing_date`、`own_products`。avbase 的 `_covers` 用 Task 9 的 `is_cross_product_cover`——本任务先 `from ..covers import is_cross_product_cover, THUMBNAIL`，所以 **Task 9 的 `covers.py` 中这两个纯函数提前到本任务创建**（文件先只含它们）。
- 三站登记进 `SITE_SOURCES`。

- [ ] **Step 1: 写失败测试**：javdb——`test_search_picks_the_card_matching_the_code`（两张卡 `ABW-358` 与 `ABW-3580` 只取前者）、`test_two_cards_same_code_is_ambiguous`、`test_login_page_is_auth_required`、`test_parse_panel_fields_and_female_actors_with_ids`、`test_origin_title_beats_display_title`、`test_maker_writing_prefers_japanese`；javbus——`test_gate_page_is_auth_required`、`test_near_miss_code_is_not_found`、`test_parse_fields_and_cover`；avbase——`test_parse_next_data_and_product_order`、`test_collection_product_is_not_this_work`（`259LUXU-1514` 的 `118sng013` 合集被剔）、`test_challenge_page_is_cloudflare_reason`、`test_no_work_is_not_found`。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 移植**。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.2.5，Commit**：`feat: 移植 javdb、JavBus 与 AVBase 解析器`

---

### Task 6: FC2 来源解析器（fc2、javarchive）

**Files:**
- Create: `src/hidden_shelf/scrape/sources/fc2.py`, `scrape/sources/javarchive.py`
- Create: `tests/fixtures/sources/fc2-article.html`, `fc2-gone.html`, `javarchive-search.html`, `javarchive-work.html`
- Test: `tests/test_sources_fc2.py`
- Reference: peach 同名模块；断言来源 `reference/peach/tests/test_metadata_fc2.py`

**Interfaces（与 peach 同名）:**
- `fc2.FC2`、`Fc2Source`、`video_id`、`canonical_code`、`runtime_minutes`、`storage_original`、`strip_code`、`fc2_record`、`STUDIO = "FC2-PPV"`。
- `javarchive.JAVARCHIVE`、`JavArchiveSource`（`search` → `links` → 每条 `records()`）、`links`。
- 两站登记进 `SITE_SOURCES`。

- [ ] **Step 1: 写失败测试**：`test_video_id_shapes`（`FC2-PPV-1234567`、`fc2ppv 1234567`、`FC-1234567`；带分段后缀认不出）、`test_fc2_parse_product_ld_json`（标题、卖家进 `label`、販売日、时长、原件封面地址、标签）、`test_fc2_gone_page_is_not_found`、`test_fc2_sku_mismatch_is_not_found`、`test_storage_original_unwraps_thumbnail_and_drops_no_image`、`test_javarchive_links_by_number_boundary`（`4137487` 不命中 `41374870`）、`test_javarchive_parse_rows_and_covers`（`_s.jpg` 预览排除；`--` 标签丢掉）、`test_javarchive_records_skip_404_entries`。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 移植**。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.2.6，Commit**：`feat: 移植 FC2 商品页与 JavArchive 解析器`

---

### Task 7: 实体层扩展与艺名清洗

**Files:**
- Create: `src/hidden_shelf/migrations/0002_scrape.sql`, `src/hidden_shelf/kanji.py`, `src/hidden_shelf/scrape/names.py`
- Modify: `src/hidden_shelf/entities.py`
- Test: `tests/test_entities_scrape.py`, `tests/test_names.py`
- Reference: `reference/peach/migrations/0002_canonical_entities.sql`、`0032_entity_external_ref_multi_id.sql`；`entities.py` 的 `resolve_entity`、`upsert_asset_entity`（外站 ID 优先）、`strip_zero_width`、`collapse_repeated_entity_name`；`kanji.py`；`metadata_alias_resolve.py`；`metadata.py` 的 `split_former_name`、`normalized_performers`；断言来源 `tests/test_performer_alias_followup.py`、`tests/test_metadata_r18dev.py` 的演员用例、`tests/test_performer_localization.py`（kanji 表）

**Interfaces:**
- `0002_scrape.sql`：`entity_alias` 重建为 `(entity_id, alias, normalized, source TEXT NOT NULL DEFAULT 'scrape', confidence REAL DEFAULT 1, UNIQUE(entity_id, normalized, source))`；新表 `entity_external_ref(entity_id FK, provider, external_kind, external_id, metadata TEXT DEFAULT '{}', synced_at, PRIMARY KEY(provider, external_kind, external_id), UNIQUE(entity_id, provider, external_kind, external_id))`；`entity` 加 `avatar_file TEXT`、`metadata TEXT DEFAULT '{}'`；`asset` 加 `scraped_at TEXT`、`scrape_note TEXT`；`schema_version` 写 2。
- `kanji.JP_KANJI_TO_SIMPLIFIED`、`fold_glyphs`、`simplify_kanji`（照抄）。
- `names.stage_name(name) -> str | None`、`is_descriptive`、`is_planning_alias`、`split_former_name(name) -> (现名, 旧名)`、`normalized_performers(raw) -> (list[dict], warnings)`（每人 `{name, external_id, thumb_url, aliases?, former_names?, profile_source?}`；企划名义剪成艺名、剪不出的整条丢掉并记 warning——本项目没有复核队列）。`collapse_repeated_entity_name`、`strip_zero_width` 并入 `entities.py`。
- `entities.find_by_external_ref(connection, kind, provider, external_id) -> int | None`、`add_external_ref(connection, entity_id, provider, kind, external_id)`（同 id 已属别的实体时不改、返回 False）、`add_alias(connection, entity_id, alias, source, confidence=1.0)`、`resolve_performer(connection, name, *, provider=None, external_id=None, aliases=()) -> int`：外站 ID 命中 > 规范名精确 > 唯一别名 > `normalize_name(fold_glyphs(x))` 唯一命中 > 新建；新建后登记别名（假名、罗马字、旧名）与外站 ID。`resolve_named(connection, kind, name)` 给 studio/series/tag 用（规范名 > 唯一别名 > 新建）。`normalize_name` 改为先 `strip_zero_width` 再 NFKC/casefold（保持计划 1 测试通过）。

- [ ] **Step 1: 写失败测试**：`test_migration_0002`（`schema_version == 2`；旧库（先用 0001 建、插一条别名）升级后别名保留且 `source='scrape'`）、`test_fold_glyphs_and_simplify`（`涼森れむ` 含假名原样；`永瀬` → `永濑`；`野々宮蘭` → `野野宫兰`；`斎藤` 不变成 `齐藤`）、`test_stage_name_cases`（`本庄美奈子 30歳 元カフェ店員` → `本庄美奈子`；`…オフパコ！！/はな/20歳` → `はな`；`超バドミントン部あかりちゃん 23歳 潮吹き部長` → None）、`test_descriptive_names_are_dropped`（`145cm色白お嬢様`、`美女6名`、`牛逼`）、`test_split_former_name`（`美谷朱音（美谷朱里）` 拆；`Mana(23)` 不拆）、`test_normalized_performers_dedup_and_aliases`、`test_resolve_performer_by_external_ref_then_name_then_glyph`（先建 `涼森れむ` 挂 r18dev id；javdb 给同名不同 id → 同实体并多挂一个 ref；`永瀬みなも` 与 `永濑みなも` 合一；`釈愛麗絲` 两个 javdb id 都能挂上）、`test_external_id_owned_by_another_entity_is_not_stolen`。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 运行**（含计划 1 全部测试），PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.2.7，Commit**：`feat: 实体外站 ID、别名与艺名清洗`

---

### Task 8: 结算与落库

**Files:**
- Create: `src/hidden_shelf/scrape/settle.py`, `src/hidden_shelf/scrape/apply.py`
- Test: `tests/test_settle.py`, `tests/test_apply_scrape.py`
- Reference: `reference/peach/src/peach/metadata_policy.py` 的 `chain_rank`/`sort_candidates`；`metadata_auto_apply.py` 的 `_apply_performer_candidate`、`_preferred_candidate`、ADR-0034 决策三（日期式番号发行日只认番号那天）、ADR-0035 决策二（javbus 兜底）、ADR-0038 决策一（链结算；同一家给两个值不结算）

**Interfaces:**
- `settle.Candidate(field, value, source, confidence=1.0)`；`settle.extract(record: SiteRecord | dict) -> list[Candidate]`（`title original_title studio series release_date tags performers cover_urls`；`performers` 经 `names.normalized_performers`；空值不出候选；`release_date` 经日期规整）。
- `settle.settle(code, candidates) -> dict[str, Settled]`（`Settled(value, source, overruled: list[(value, source)])`）：每字段按 `chain_rank` 排；`release_date` 对日期式番号只认等于 `code_release_date(code)` 的候选；`FALLBACK_SOURCES` 的值在同字段还有别家时不参与；`blacklisted` 的剔掉；同一家给出两个不同标量值时跳过这家（照 ADR-0038）；`tags` 取胜出那一家的整组；`performers` 取胜出那一家的整组；`cover_urls` 不在这里结算（交 Task 9）。
- `apply.apply_settled(connection, asset_ids: list[int], code, settled, *, now) -> ApplyReport(written: dict[field, source], kept: dict[field, owner])`：标量列经 `write_owned_fields`，owner `auto:<source>`；写前比较 `policy.owner_tier(现归属)` 与 `source_tier(source)`：现值为空或现归属层级数字更大才写（`require_empty` 不用，自己判）；同番号多碟一起写。`performers`：先删该 asset 上 `source LIKE 'auto:%'` 且不属于胜出来源的 performer 关联？——**不删**：只增不删，关联 `source = auto:<source>`，`user` 的照旧在前；每人 `resolve_performer` 并登记外站 ID、别名；`thumb_url` 存进 `entity.metadata.avatar_url`（Task 9 的头像步骤读它）。`tags`：同上只增不删，`resolve_named("tag")`；`studio`/`series`：标量写入成功时同步建实体并 `link(role=studio|series, source=auto:<source>)`。写完 `asset.scraped_at = now`。
- `apply.should_scrape(row, *, force=False) -> tuple[bool, list[str]]`：有 `code_key`；`content_type ∉ {unrecognized}`；`routes.classify` 不是 `kmib/other/unknown`；`scrapes_as_jav(code, studio, creator=None)` 真；缺字段列表 = `title/performers/studio/release_date` 中为空或归属层级 > 官方档的字段 + `tags`（无关联时）+ `cover`（无封面或 `auto:frame`）；`force` 时全要；一项都不缺或 `scraped_at` 在 7 天内且不 force → 不问。

- [ ] **Step 1: 写失败测试**：`test_extract_candidates_from_record`、`test_settle_official_beats_community`（r18dev 标题胜 javdb）、`test_settle_javdb_beats_other_community`、`test_settle_javbus_only_when_alone`、`test_settle_dated_code_release_date_must_match_code`（`092415_001`：javdb 2016-06-16 剔、javbus 2015-09-24 取）、`test_settle_same_source_two_values_is_skipped`、`test_settle_censored_tags_prefer_javdb`、`test_apply_writes_scalars_with_auto_owner`、`test_apply_does_not_overwrite_user_or_nfo`（Review Focus 2）、`test_apply_higher_tier_replaces_lower`（先 javbus 写厂牌，再 r18dev 来 → 换；再 avbase 来 → 不换）、`test_apply_performers_create_entities_with_refs_and_keep_user_links`、`test_apply_shares_across_parts`、`test_should_scrape_rules`（无番号不问；kmib 不问；全齐且 7 天内不问；`force` 问；缺封面问）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: 版本 0.2.8，Commit**：`feat: 来源分级结算与落库`

---

### Task 9: 封面择优与官方头像

**Files:**
- Modify/Create: `src/hidden_shelf/scrape/covers.py`（Task 5 已放 `THUMBNAIL`、`is_cross_product_cover`）、Create `src/hidden_shelf/scrape/avatars.py`
- Test: `tests/test_covers_online.py`, `tests/test_avatars.py`
- Reference: `reference/peach/src/peach/jav_cover_fetch.py` 的 `Candidate`、`candidate_for`、`code_variants`、`cid_variants`、`dmm_cdn_images`、`official_image_candidates`、`content_id_images`、`is_cross_product_cover`、`_fc2_names_another_work`、`probe_size`、`_usable_candidates`、`_measure`、`_download_best`、`MIN_WIDTH`、`SMALL_MIN_WIDTH`、`PLACEHOLDER`；`sources/r18dev.py` 的 `ACTRESS_IMAGE`；断言来源 `tests/test_jav_covers.py` 的 `CodeShapeTests`、`ContentIdTests`、`CrossProductCoverTests`、`BestCoverTests`

**Interfaces:**
- `covers.Candidate(host, url, referer, kind)`、`PRODUCT_IMAGE/PREVIEW_IMAGE/COVER_IMAGE`、`candidate_for`、`code_variants`、`cid_variants`、`dmm_cdn_images`、`official_image_candidates`、`content_id_images`、`is_javdb_image`、`is_cross_product_cover`、`THUMBNAIL`、`MIN_WIDTH = 700`、`SMALL_MIN_WIDTH = 240`。
- `covers.candidates_from_records(code, records: list[(source, payload)]) -> list[Candidate]`：每份 `cover_urls`（javdb 的剔掉）+ r18dev/dmm 的 `content_id` 展开成 DMM CDN 高清/低清变体；去重、去缩略图、去串号。
- `covers.best_cover(transport, code, candidates, *, minimum_width=MIN_WIDTH, delay, deadline=None) -> (Candidate, (w, h), bytes)`：Range 量尺寸 → 够宽的按像素面积（同面积商品图优先）→ 整张下载 → 核实尺寸 → 动图跳过；全部太小时用 `SMALL_MIN_WIDTH` 再筛一次（素人系官方图只有 300 宽）；一张都不行抛 `NotFound`（来源的确定答复）或 `Unavailable`（有连接失败）。
- `covers.install_online_cover(connection, paths, asset_ids, code_key, data: bytes, source) -> str`：写 `covers/<code_key>.jpg`（经 Pillow 转 RGB JPEG q90）、`cover_file` 以 `auto:<source>` 写（现归属 `auto:frame` 或空才写；`auto:local` 不写）、顺手删旧海报指纹让 `media` 步重做海报。
- `avatars.install_avatars(connection, paths, transport, *, progress) -> int`：`entity.metadata.avatar_url` 非空且 `avatar_file` 为空的 performer，取图（`PROBE` 不做，直接下，上限 2 MiB）→ `avatars/<entity_id>.jpg`（Pillow 转正、RGB、最长边 512）→ 写 `avatar_file`；失败记日志不抛；一次运行最多 N 个（默认 200）。

- [ ] **Step 1: 写失败测试**：搬 `CodeShapeTests`（`278GYAN-017` → 两种写法）、`ContentIdTests`（`waaa415` → `waaa00415`）、`CrossProductCoverTests`（`259LUXU-1475` 对 `118sng021` 真；`YUJ-101` 对 `yuj00011` 真；`ABW-232` 对 `118abw00232` 假；FC2 图床文件名写着别的作品号真）、`test_candidates_from_records_expands_dmm_cdn_and_drops_javdb`、`test_best_cover_picks_largest_by_range_probe`（假传输：三张候选分别回 800×539、2184×1464、147×200 的 JPEG 头；断言只整张下载最大那张，Range 头带 `bytes=0-65535`）、`test_best_cover_falls_back_to_small_width`、`test_best_cover_rejects_placeholder_and_animated`、`test_install_online_cover_respects_owner`（Review Focus 2）、`test_install_avatars_from_r18_thumbs`（假传输回 PNG；落 `avatars/<id>.jpg`；第二次不重下）。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 移植与实现**。去掉 peach 的 Prestige API、MGS、DUGA、成功日志复用、`known_sizes` 升级模式、诊断计数（只留 `unanswered` 判断 `NotFound` 还是 `Unavailable`）。
- [ ] **Step 4: 运行**，PASS。
- [ ] **Step 5: REUSE.md 加行，版本 0.2.9，Commit**：`feat: 联网封面择优与官方头像`

---

### Task 10: 刮削编排、流水线与命令行

**Files:**
- Create: `src/hidden_shelf/scrape/run.py`
- Modify: `src/hidden_shelf/pipeline.py`, `src/hidden_shelf/cli.py`, `src/hidden_shelf/config.py`（`scrape: bool = True`）, `src/hidden_shelf/site/build.py`（头像）, `src/hidden_shelf/site/static/app.js`（名册与详情页用 `avatar`，已有分支）
- Test: `tests/test_scrape_run.py`, `tests/test_pipeline_scrape.py`
- Reference: `reference/peach/src/peach/library_processing.py` 的 `_query`（按档问、`settles` 短路、`_askable`、`_cached_evidence`、`_record_miss`）、`_cover_inputs`

**Interfaces:**
- `run.ScrapeResult(asked: int, settled: int, covers: int, avatars: int, skipped: int, missing: int, failed: int, paused: list[str])`。
- `run.scrape_assets(connection, paths, config: ShelfConfig, *, global_config: GlobalConfig | None = None, transport=None, progress=..., force=False, only_sources=None, now=time.time) -> ScrapeResult`：
  1. 建 `Cooldown`、`Snapshots`、`SourceTransport`（`transport` 可注入假传输）。
  2. 按 `code_key` 分组未消失视频；每组一次。`apply.should_scrape` 判要不要问、缺什么。
  3. 本机证据 `hints = (path, name, studio)`；`chain = routes.route_for_code(code, *hints, overrides=global_config.routes)`；去掉 `global_config.sources[x].enabled == False` 的站。
  4. 按 `stages_for_chain` 逐档：成员里剔掉 `snapshots.fresh_miss` 与冷却中的；先读新鲜快照，再问没快照的；每站 `SiteSource.records()`；`identifies_code` 核身份（解析器已核，这里再核 `payload`）；成功 `save_result`，`not_found` 类与错配 `save_miss`，其余只记日志；`SourcePaused` 记进 `paused` 并跳过该站；`settles(required, given, wants_tags, then)` 真则停。综合索引档整档问（最多 3 家）。
  5. `settle.extract` 全部记录 → `settle.settle` → `apply.apply_settled`。
  6. 缺封面时 `covers.candidates_from_records` → `best_cover` → `install_online_cover`；`NotFound` 记 `snapshots.save_miss(code, "cover", ...)` 7 天。
  7. 全部番号跑完后 `avatars.install_avatars`。
  8. 每个番号一行进度：`[刮削] ABP-758 ← r18dev,javdb · 标题/厂牌/演员 · 封面 2184×1464`。
  9. 任一番号抛异常：记 `failed`、写 `asset.scrape_note`，继续下一个。整步连第一个请求都连不上（`httpx.TransportError` 连续 3 个番号）→ 报「网络不可用，本趟跳过刮削」并提前返回，不抛。
- `pipeline.STEPS = ("scan", "import", "scrape", "organize", "media", "build")`；`scrape` 一步在 `config.scrape` 为假或 `--offline` 时记 `skipped` 跳过；`run` 把 `scrape` 的异常当本步失败但**不中断**后续步（唯一的例外步）。
- `cli`：子命令 `scrape <root>`；`run` 默认含 scrape；通用选项 `--offline`（本次跳过刮削）、`--force-scrape`（忽略 7 天与「全齐」）、`--sources r18dev,javdb`（本次只问这几家）、`--routes "censored=r18dev,javdb"`（整条覆盖）；`shelf config`（打印 `~/.hidden-shelf/config.json` 路径与当前代理模式、各站是否有 Cookie、冷却状态；不打印 Cookie 值）。
- `site/build.py`：`entities.performers[].avatar = ".shelf/avatars/<id>.jpg"`（文件存在时），`works[].sources = [{source, url}]`（快照里的 `source_url`，前端详情页可列出处链接——`<a target=_blank>`，是外链不是资源加载）。

- [ ] **Step 1: 写失败测试**（全部用假传输：一个 `dict[url -> body | Exception]` 的回放器，按 Task 4–6 的夹具拼）：`test_scrape_end_to_end_censored`（`ABP-758`：r18dev 两页 + javdb 两页；断言标题/厂牌/发行日/演员/标签落库、归属 `auto:r18dev`/`auto:javdb`、封面从 DMM CDN 高清变体装上、快照两份、`scraped_at` 写了、进度行）、`test_short_circuit_stops_after_official_stage`（r18dev 给全必填 → 不问 dmm，但综合索引档仍问（标签与图源）——按 spec §4.7「综合索引档整档问」；若 `tags` 已由 r18dev 给出且缺的只有封面，综合索引档仍问以取图源）、`test_snapshot_is_reused_within_7_days`（第二次 `scrape_assets` 零请求）、`test_not_found_is_remembered_and_transient_is_not`（Review Focus 4）、`test_403_pauses_site_for_the_run`（Review Focus 3：javdb 第一个番号 403，第二个番号对 javdb 零请求，`_cooldown.json` 有记录，`paused == ["javdb"]`）、`test_identity_mismatch_rejected`（Review Focus 1：r18dev 回别的 `content_id`）、`test_user_and_nfo_fields_survive`（Review Focus 2）、`test_offline_network_down_does_not_raise`（Review Focus 5）、`test_disabled_source_is_skipped`、`test_only_sources_option`、`test_pipeline_includes_scrape_and_continues_on_failure`（monkeypatch `scrape_assets` 抛 → run 仍 ok，`run` 表 scrape 行 `failed`，index.html 存在）、`test_cli_offline_flag`、`test_cli_config_prints_without_cookie_values`、`test_site_build_performer_avatar_and_sources`。
- [ ] **Step 2: 运行**，FAIL。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 运行全部** `uv run pytest -v && node --test "tests/js/**/*.test.mjs"`，PASS。
- [ ] **Step 5: 版本 0.2.10，Commit**：`feat: 刮削编排接入流水线与命令行`

---

### Task 11: 真实来源冒烟脚本与文档

**Files:**
- Create: `scripts/smoke_sources.py`（手动跑：对一个番号逐站 `query`，打印 `payload()` 摘要与失败分档；不进测试）
- Modify: `CLAUDE.md`（当前阶段、命令、架构加刮削一节）、`docs/REUSE.md`（核对每行）、`README.md`（配置 `~/.hidden-shelf/config.json` 示例）、`~/Claude-Code/PROJECTS.md`（仅本机）
- Test: 无新增自动测试；手动验证清单如下

- [ ] **Step 1: 写 `scripts/smoke_sources.py`**：`uv run python scripts/smoke_sources.py ABW-358 --sources r18dev,dmm,avbase,javbus,javdb`，每站一行：`r18dev  ok  涼森れむ流 / Prestige / 2023-05-26 / 1 人 / 封面 1 张` 或 `javdb  auth_required  javdb 要求登录`。
- [ ] **Step 2: 本机手动验证**（云端无外网则跳过并在提交说明里写明）：`ABW-358`（有码）、`259LUXU-1475`（素人，预期只有综合索引有）、`092415_001`（无码，无证据时不问 1pondo）、`FC2-PPV-1234567`（FC2）各跑一次；再在演示盘上 `shelf run`，确认 `index.html` 详情页有演员头像与出处链接；拔网线 `shelf run` 仍成功。
- [ ] **Step 3: 更新文档**。`CLAUDE.md`「当前阶段」改 v0.2.11、计划 2 完成、下一步计划 3；「命令」加 `shelf scrape`、`--offline`、`shelf config`；「架构」加：刮削数据流（链 → 档 → 快照 → 结算 → 落库 → 封面 → 头像）、落库口径（单来源直接写、链结算、分级覆盖、不碰 `auto:nfo`/`user:*`）、快照与冷却位置、全局配置位置与「凭据不进盘」。
- [ ] **Step 4: 版本 0.2.11，Commit**：`feat: 来源冒烟脚本；更新项目文档`

---

## 自检记录

- Spec 覆盖：§3「单来源最宽松」→ Task 8 的 `settle`/`apply`（不互证、不复核、分级覆盖）；§4.3 第 2 步（本地 NFO 优先、按类型链逐站问、快照、失败不中断、封面链、抽帧兜底）→ Task 2/3/9/10，抽帧兜底沿用计划 1 `media`；§4.6 移植清单 → Task 1/3/4/5/6/7/9（`sources/` 8 站、`metadata_routes`、`metadata_policy`、实体层、`kanji`、`metadata_alias_resolve`、封面判据），不移植项按表落实（amane、浏览器取页、复核、磁链）；§4.7 的「规则照抄、跑法自写」「艺人以实体 ID 为准」「头像只用 r18.dev」「封面取 payload 地址、本地旧封面优先」「Cookie 每站一条」「curl_cffi 只给需要指纹的站」→ Task 0/7/9/10；§4.5 配置分两层 → Task 0；§6 的 amane 缺位与反爬冷却 → Task 2/3 注释与 Review Focus 3。
- 类型一致：`SiteRecord.payload()` 的键即快照 `result` 的键即 `settle.extract` 读的键；来源名贯穿 `SOURCE_SPECS`、`SITE_SOURCES`、`access.SOURCES`、`auto:<来源>`、`asset_entity.source`、快照文件名（Task 3 加一条一致性测试，照 peach `ConfigConsistencyTests`）。
- Review Focus 七条各有对应测试（已标注）。
- 与计划 1 的接口：`field_owners.write_owned_fields` 不改；`entities.ensure_entity/link/unlink/names_for` 保留并由新函数包住；`media.process_assets` 对联网封面照常生成海报（指纹变化触发）；`site/build.py` 只加字段不改结构。
