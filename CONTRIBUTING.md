# 参与开发

## 开发环境

- Python ≥ 3.12 与 [uv](https://docs.astral.sh/uv/)；系统 ffmpeg/ffprobe（macOS `brew install ffmpeg`，Debian/Ubuntu `apt install ffmpeg`）；node ≥ 20（只为跑前端测试）。
- `git clone https://github.com/wanghero/Hidden-Shelf && cd Hidden-Shelf && uv sync`。

## 测试

```bash
uv run pytest -v                         # 全部 Python 测试（缺 ffmpeg 时抽帧相关的会 skip）
uv run pytest tests/test_codes.py -k 名字  # 单个测试
node --test "tests/js/**/*.test.mjs"     # 前端纯逻辑测试（node 22 的 --test 要 glob，不接受目录）
```

**测试永不联网。** `tests/conftest.py` 的 autouse 夹具 `isolated_home` 把全局配置落到临时目录并停用全部来源；要联网行为的测试自己传 `GlobalConfig()` 与假传输（见 `tests/test_scrape_run.py` 的 `replay`）。CI（`.github/workflows/test.yml`）在 ubuntu/macos/windows 上跑同样的命令，也不许联网。

## 提交规则

- 提交信息用中文；代码注释中文、标识符英文。
- 每次改代码版本号 +0.0.1，三处同改：`pyproject.toml` 的 `version`、`src/hidden_shelf/__init__.py` 的 `__version__`、`tests/test_smoke.py` 的断言。
- 先写失败的测试再写实现；一个任务一个提交。
- 设计上的决定以 `docs/superpowers/specs/2026-10-28-hidden-shelf-design.md` 为准，改规则先改文档。

## 来源坏了怎么报

站方改版是最常见的坏法。请在本机跑真实冒烟并把输出贴进 issue（模板「来源坏了」）：

```bash
uv run python scripts/smoke_sources.py <番号> --sources <站名>
```

**不要贴 Cookie 值**，只说有没有配。

## 新增来源

- 在 `src/hidden_shelf/scrape/sources/` 实现 `SiteSource` 契约（`base.py`），登记到 `sources/__init__.py` 的 `SITE_SOURCES`，并在 `scrape/access.py` 的 `SOURCES` 登记域名、是否要 Cookie、403 冷却上限。
- 加契约测试：`tests/test_sources_contract.py` 会对 `SITE_SOURCES` 里每一家跑同一组断言；解析测试用 `tests/fixtures/sources/` 下的 HTML 夹具，不联网。
- 放进来源链要改 `scrape/routes.py` 与 `scrape/policy.py`（分级与字段顺序）。

## 移植与界面

- 从 [peach](https://github.com/peach-mitao/peach)（AGPL-3.0）移植代码要在 `docs/REUSE.md` 登记：本项目文件、peach 源文件与 commit、改动摘要。
- 界面改动遵守 `docs/ux-standard/SKILL.md`：只用 `tokens.css` 的变量（`app.css`、`progress.css` 里不许有裸色值），浅/深/系统主题，中英双语（`i18n.js` 两套 key 必须一致，有测试钉着）。

---

## English summary

- Setup: Python ≥ 3.12, uv, system ffmpeg/ffprobe, node ≥ 20; `uv sync`.
- Tests: `uv run pytest -v` and `node --test "tests/js/**/*.test.mjs"`. Tests never touch the network (`isolated_home` in `tests/conftest.py`); CI runs the same commands offline.
- Commits: Chinese commit messages; bump the version by 0.0.1 in `pyproject.toml`, `src/hidden_shelf/__init__.py` and `tests/test_smoke.py` together; test first, one task per commit.
- Broken source: run `uv run python scripts/smoke_sources.py <code> --sources <site>` and paste the output into an issue. Never paste cookie values.
- New source: implement the `SiteSource` contract, register it in `SITE_SOURCES` and `access.SOURCES`, add fixture-based tests; `tests/test_sources_contract.py` covers every registered source.
- Code ported from peach must be listed in `docs/REUSE.md`; UI changes follow `docs/ux-standard/SKILL.md` (tokens only, light/dark, zh/en keys in sync).
