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
