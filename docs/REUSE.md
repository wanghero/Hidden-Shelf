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
