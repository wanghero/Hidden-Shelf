# 移植登记

本项目的策略模块从 [peach-mitao/peach](https://github.com/peach-mitao/peach)（AGPL-3.0-or-later）移植，编排层自写。
参考克隆：`reference/peach`（`.gitignore` 排除），commit `4d5266d327a5971773409b44316e3926bd37c6ba`（2026-10-28 浅克隆）。

| 本项目文件 | peach 源文件 | 改动摘要 |
|---|---|---|
| `LICENSE` | `LICENSE` | 原文复制（AGPL-3.0） |
| `src/hidden_shelf/rules/codes.py` | `src/peach/catalog_rules.py` | 只保留番号规则（常量、正则、函数及误判证据注释）；去掉标签词表、`face_focus`、SQL 片段、`photo_set_title`、`fill_masked_title`、分卷聚类；`PureWindowsPath` → `PurePosixPath` |
| `tests/test_codes.py`（后半） | `tests/test_jav_code_domain.py` | 搬入不依赖账本与其他模块的断言，改 import |
| `src/hidden_shelf/rules/sidecars.py` | `src/peach/scan.py`（`ARTWORK*`、`_DERIVED_THUMB`、`medium_of`、`video_stems`、`is_sidecar`） | 加 `nfo`/`subtitle` 档与 `sidecar_kind`；去掉多根参数；同名图片与字幕也算附属 |
| `tests/test_sidecars.py`（后半） | `tests/test_scan.py` | 搬入 `is_sidecar`、`medium_of` 相关断言 |
| `src/hidden_shelf/rules/nfo.py` | `src/peach/library_nfo.py` | 去 SMB 与 `processing_traffic`；`read_nfo` 返回固定键字典；`for_video` 拆成 `nfo_for`/`images_for` |
| `tests/test_nfo.py`（后半） | `tests/test_metadata_library.py` | 搬入 `read_nfo`/`sidecars`/`local_art` 断言 |
| `src/hidden_shelf/field_owners.py` | `src/peach/field_owners.py` | 去乐观并发；表名/列名参数化；每字段各自归属（`FieldWrite`），返回 `{字段: 是否写入}` |
| `tests/test_field_owners.py`（后半） | `tests/test_field_owners.py` | 搬入不依赖账本夹具的断言 |
| `src/hidden_shelf/organize/templates.py` | `src/peach/organize_templates.py` | `ntpath` → `posixpath`；去 `mosaic` 占位符与界面示例；`render` 返回字符串，缺失字段由 `missing_fields` 给出 |
| `tests/test_templates.py`（后半） | `tests/test_organize.py`（模板部分） | 搬入渲染表、清洗与逃逸断言 |
| `src/hidden_shelf/organize/plan.py`、`organize/apply.py` | `src/peach/organize.py`（`placeholder_values`、`_definition`、`build_plan`、`_move_one`、`apply_plan`、`rollback_batch`、`SKIP_*`） | 按单盘根与 POSIX 相对路径重写；JSONL 批次日志；附属文件搬 `legacy/` 或随未识别视频 |
| `src/hidden_shelf/media/frames.py` | `src/peach/frame_capture.py` | 去 `processing_control`、`ffmpeg_options`、SMB、硬解与诊断上报 |
| `src/hidden_shelf/media/fingerprint.py` | `src/peach/artifact_rules.py` | 去 `upgrade_rules` 与资源类来源；边车 `.rule` 存 JSON |
| `src/hidden_shelf/media/covers.py`（海报比例常量） | `src/peach/jav_poster_crop.py`（`SLEEVE_RATIO_*`、`PANEL_ASPECT`） | 只取 `ratio` 先验，不做 OpenCV 折痕检测 |
| `src/hidden_shelf/fsutil.py` | `src/peach/fsutil.py` | 去 Windows 占用重试与权限位 |
| `src/hidden_shelf/scrape/transport.py` | `src/peach/http.py`（`HttpRequest`/`HttpResponse`、有界读取）、`scripting.HostLimiter`、`user_agent.py`、`jav_cover_fetch._fetch`、`scraping_access.SourceTransport`（重定向规则） | 去内网判据、浏览器传输、流量计费；`curl_cffi` 改为可选 |
| `src/hidden_shelf/netconfig.py` | `src/peach/peach_proxy.py`（三选一语义与地址校验） | 改为一个 JSON 文件；加各站 Cookie/开关与路由覆盖 |
| `src/hidden_shelf/scrape/sources/base.py` | `src/peach/sources/base.py` | `Session` 改调本项目 `transport.fetch`；去 `provider_error`；加 `MISS_REASONS`、`is_miss`、`retryable` |
| `src/hidden_shelf/scrape/identity.py` | `src/peach/metadata.py`（`validate_provider_code`、`identifies_code`） | 照抄（含 mgstage URL 分支，纯函数无害） |
| `tests/test_identity.py`、`tests/test_sources_contract.py` | `tests/test_metadata.py`（`SourceIdentityTests`）、`tests/test_metadata_sources.py`（`ContractTests`、`FailureReasonTests`） | 改 pytest 风格 |
| `src/hidden_shelf/scrape/access.py` | `src/peach/scraping_access.py`（`SOURCES`、`FIRST_BLOCKED_PAUSE`、`pause_source`、`cookie_jar`、`SourceTransport`） | 只留 8 站；冷却记录合成一个 JSON；去浏览器传输、凭据库、流量计费与 `via` |
| `src/hidden_shelf/scrape/snapshots.py` | `src/peach/library_processing.py`（`_evidence_path`、`_cached_evidence`、`_MissCache`、`MISS_TTL_SECONDS`） | 结果与「没有」合写一个快照文件；去 `joined` 接入时刻 |
| `tests/test_access.py`（后半） | `tests/test_metadata_sources.py`（`SiteCooldownTests`） | 改 pytest 风格 |
| `src/hidden_shelf/scrape/routes.py` | `src/peach/metadata_routes.py` | 只留 8 站；每站各成一档（综合索引三家逐家短路，用户决定）；去 amane 桥与未接站 |
| `src/hidden_shelf/scrape/policy.py` | `src/peach/metadata_policy.py` | 只登记 8 站；`LOCAL_NFO_SOURCE` 改 `nfo`；新增 `owner_tier` 把 `field_owners` 归属折成层级 |
| `tests/test_routes.py`、`tests/test_policy.py` | `tests/test_metadata_routes.py`、`tests/test_metadata_policy.py` | 改 pytest 风格，期望按裁剪后的表改 |
| `src/hidden_shelf/scrape/sources/r18dev.py` | `src/peach/sources/r18dev.py` | `Unavailable`、`identifies_code` 改从本项目模块导入；去封面层另一条路的说明 |
| `src/hidden_shelf/scrape/sources/dmm.py` | `src/peach/sources/dmm.py` | 导入改本项目模块；GraphQL 操作名改 `Shelf*`；去 ADR 引用 |
| `src/hidden_shelf/scrape/sources/onepondo.py` | `src/peach/sources/onepondo.py` | 导入改本项目模块 |
| `tests/test_sources_official.py`、`tests/fixtures/sources/*.json` | `tests/test_metadata_r18dev.py`、`test_metadata_dmm.py`、`test_metadata_1pondo.py` | 改 pytest 风格；夹具从测试常量落成 JSON 文件；去 `LibraryMetadataProvider` 那一层 |
| `src/hidden_shelf/scrape/covers.py`（`THUMBNAIL`、`is_cross_product_cover`） | `src/peach/jav_cover_fetch.py`（同名两项及其私有正则） | 照抄；下载与择优在计划 2 Task 9 另加 |
| `src/hidden_shelf/scrape/sources/javdb_helpers.py` | `src/peach/javdb.py`（`LOGIN`、`RECORD_KIND`、`clean`） | 只取这三项 |
| `src/hidden_shelf/scrape/sources/javdb.py` | `src/peach/sources/javdb.py` | 不搬 `resources`、`parse_magnets`、`parse_comment_links`、`merge_resources`；`extra` 去 `javdb_rule` |
| `src/hidden_shelf/scrape/sources/javbus.py` | `src/peach/sources/javbus.py` | 导入改本项目模块；措辞「采集设置」→「全局配置」 |
| `src/hidden_shelf/scrape/sources/avbase.py` | `src/peach/sources/avbase.py` | 导入改本项目模块 |
| `tests/test_sources_community.py`、`tests/test_scrape_covers.py`、`tests/fixtures/sources/*.html` | `tests/test_community_catalog.py`（解析部分）、`tests/test_metadata_sources.py`（`JavDBResourceTests` 三条、`SiteCooldownTests` AVBase 一条）、`tests/test_jav_covers.py`（`CrossProductCoverTests`） | 改 pytest 风格；页面常量落成 HTML 夹具 |
| `src/hidden_shelf/scrape/sources/fc2.py` | `src/peach/sources/fc2.py` | 去 fc2cmadb/FC2PPV-DB/JAVten 的说明，FC2 链只剩 fc2 → javarchive → javdb |
| `src/hidden_shelf/scrape/sources/javarchive.py` | `src/peach/sources/javarchive.py` | `NotFound` 改从本项目模块导入 |
| `tests/test_sources_fc2.py`、`tests/fixtures/sources/fc2-*.html`、`javarchive-*.html` | `tests/test_metadata_fc2.py`（`Fc2CodeTests`、`Fc2ShopPageTests`、`JavArchiveTests`） | 改 pytest 风格；页面落成 HTML 夹具，变体用字节替换 |
| `src/hidden_shelf/migrations/0002_scrape.sql` | `migrations/0002_canonical_entities.sql`、`0032_entity_external_ref_multi_id.sql`（表结构） | 列名缩短（`metadata`、`synced_at`）；`entity_alias` 重建加 `source`/`confidence` |
| `src/hidden_shelf/kanji.py` | `src/peach/kanji.py` | 照抄 |
| `src/hidden_shelf/scrape/names.py` | `src/peach/metadata_alias_resolve.py`（`is_descriptive`、`stage_name`、`is_planning_alias`）、`src/peach/metadata.py`（`split_former_name`、`normalized_performers`） | 企划名义剪得出用艺名、剪不出整条丢弃并记 warning（无复核队列）；拉丁字母名不经企划名义判据 |
| `src/hidden_shelf/entities.py`（`strip_zero_width`、`collapse_repeated_entity_name`、`resolve_performer` 的解析顺序） | `src/peach/entities.py`（同名两项、`upsert_asset_entity`、`resolve_entity`） | 去 creator、合并重定向与扁平投影；`strip_zero_width` 落在 `db.py` 供 `normalize_name` 用 |
| `tests/test_names.py`、`tests/test_entities_scrape.py` | `tests/test_composite_name_split.py`、`test_performer_localization.py`（kanji 断言）、`test_entity_merge.py`（`collapse_repeated_entity_name`） | 改 pytest 风格 |
