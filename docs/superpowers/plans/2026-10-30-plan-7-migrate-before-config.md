# Hidden Shelf 计划 7：老盘迁移要在写配置之前 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修一个本机 2026-10-30 在真实老盘上实跑 v0.4.4 撞到的 bug：老盘（只有 `.shelf/`）第一次用新版本跑，程序先建了 `HiddenShelf/config.json`，再进迁移时看到两个目录并存就抛 `ShelfLayoutConflict`，而且是裸 traceback 不是退出码 2。迁移必须发生在任何会创建 `HiddenShelf/` 的动作之前。

**Architecture:** 现在的顺序是 `check_writable → check_layout → ShelfConfig.load（文件不存在就 save，顺手 mkdir HiddenShelf/）→ pipeline.run（这里才 migrate_legacy_dir）`。改成把 `migrate_legacy_dir(root)` 放到开跑前检查里：命令行 `cli.py` 与网页 `serve/runner.py` 都在 `check_layout` 之后、`ShelfConfig.load` 之前调它；`pipeline.run` 开头那次保留当兜底（给直接调 `pipeline.run` 的测试与脚本用）。另外 `ShelfConfig.load` 本身别再「读配置时顺手建目录」——文件不存在只返回默认值，由 `ShelfPaths.ensure()` 统一建目录和写默认配置。

**Tech Stack:** 现有。

**Spec:** 计划 6 Review Focus 1（老盘迁移「任何子命令、网页也一样」）在实跑中没成立，本计划补上。

## Global Constraints

- 版本接着 `main` 当前的 **0.4.4** → 0.4.5（一个任务）。三处同改。提交信息中文。
- 复现实况（本机真实盘，已恢复到迁移前）：`.shelf/` 存在、`HiddenShelf/` 不存在 → `uv run shelf run <盘根> --offline` → 结果 `HiddenShelf/` 里只有一个 `config.json`（与 `.shelf/config.json` 内容相同），traceback 止于 `paths.py` 的 `check_layout`。
- 老盘上已有的 `.shelf/config.json` 必须原样带过去（它在迁移时随目录改名），**不能**被默认值覆盖。

## Review Focus

1. **命令行老盘首跑**：`.shelf/` 带着非默认配置（如 `move_unrecognized=false`），`shelf scan <盘根>` 之后 `HiddenShelf/config.json` 里还是 `false`，`.shelf/` 不在。→ `test_cli_migrates_legacy_before_loading_config`。
2. **网页老盘首跑**：`POST /api/run` 对同样的盘，`run.start` 之后 `.shelf/` 不在、`HiddenShelf/config.json` 保留原值。→ `test_runner_migrates_legacy_before_loading_config`。
3. **并存时的错误通道**：`pipeline.run` 里再抛 `ShelfLayoutConflict`（理论上前置检查已经挡了，但直接调 `pipeline.run` 的调用方会碰到）→ `cli.main` 退出码 2 并打印那句话，不是 traceback；网页记为「流水线没能开始」。→ `test_cli_layout_conflict_from_pipeline_exits_2`。
4. **`ShelfConfig.load` 不再写盘**：对一个空目录 `load` 之后目录仍为空；`ensure()` 之后才有 `config.json`。→ `test_config_load_does_not_create_dir`。

---

### Task 1: 迁移前置，配置读取不建目录

**Files:**
- Modify: `src/hidden_shelf/cli.py`（`check_layout(root)` 后加 `migrate_legacy_dir(root)`，把它也纳入那个 `except`；`pipeline.run` 调用包一层 `except ShelfLayoutConflict` → 打印、退出码 2）
- Modify: `src/hidden_shelf/serve/runner.py:54-56,174`（同样在 `check_layout` 后 `migrate_legacy_dir`；`ShelfConfig.load` 之前）
- Modify: `src/hidden_shelf/config.py:29-33`（`load` 文件不存在只 `return cls()`，不 `save`）、`src/hidden_shelf/paths.py`（`ensure()` 末尾：`config.json` 不存在就写默认值——把原来 `load` 里的那次 `save` 挪到这里）
- Modify: `src/hidden_shelf/pipeline.py:148`（保留 `migrate_legacy_dir`，`migrated` 为真时日志那行不变）
- Test: `tests/test_pipeline_cli.py`、`tests/test_runner.py`、`tests/test_paths_config.py`

**Interfaces:**
- Consumes: `paths.migrate_legacy_dir(root) -> bool`、`paths.check_layout(root)`、`ShelfLayoutConflict`、`RootNotWritable`。
- Produces: 行为改变，无新接口。`ShelfConfig.load(paths)` 不再有副作用；默认 `config.json` 由 `ShelfPaths.ensure()` 写出（`pipeline.run` 开头已经调 `ensure()`，所以命令行与网页首跑后文件照样在）。

- [ ] **Step 1: 写失败的测试**

`tests/test_pipeline_cli.py`：

```python
def _legacy_disk(tmp_root: Path) -> Path:
    legacy = tmp_root / ".shelf"
    legacy.mkdir()
    (legacy / "config.json").write_text(json.dumps({"move_unrecognized": False}), encoding="utf-8")
    return tmp_root


def test_cli_migrates_legacy_before_loading_config(tmp_root: Path, capsys):
    _legacy_disk(tmp_root)
    assert cli.main(["scan", str(tmp_root)]) == 0
    assert not (tmp_root / ".shelf").exists()
    assert json.loads((tmp_root / SHELF_DIR / "config.json").read_text(encoding="utf-8"))["move_unrecognized"] is False
    assert "同时有" not in capsys.readouterr().err


def test_cli_layout_conflict_from_pipeline_exits_2(tmp_root: Path, capsys, monkeypatch):
    monkeypatch.setattr(cli.pipeline, "run", lambda *a, **k: (_ for _ in ()).throw(ShelfLayoutConflict(tmp_root)))
    assert cli.main(["scan", str(tmp_root)]) == 2
    assert "同时有" in capsys.readouterr().err
```

`tests/test_runner.py` 加 `test_runner_migrates_legacy_before_loading_config`：同样造 `.shelf/config.json`，用真 `pipeline.run`（`steps=("scan",)`）跑完后断言同上。

`tests/test_paths_config.py` 加 `test_config_load_does_not_create_dir`：`ShelfConfig.load(ShelfPaths(tmp_path))` 之后 `tmp_path` 为空；`ShelfPaths(tmp_path).ensure()` 之后 `HiddenShelf/config.json` 存在且能 `load` 回默认值。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pipeline_cli.py tests/test_runner.py tests/test_paths_config.py -k "legacy or layout_conflict or does_not_create" -v`
Expected: 前两个 FAIL 于 `ShelfLayoutConflict`/traceback，第三个 FAIL 于目录已被创建

- [ ] **Step 3: 实现**

按 Files 里的说明改。注意 `cli.py` 里 `migrate_legacy_dir` 可能抛 `RootNotWritable`，和 `check_writable` 共用同一个 `except`。

- [ ] **Step 4: 全量测试**

Run: `uv run pytest -q && node --test "tests/js/**/*.test.mjs"`
Expected: 全部 PASS（原有 `test_ensure_migrates_legacy_dot_shelf`、`test_ensure_refuses_both_dirs` 也要过）

- [ ] **Step 5: 文档**：`CLAUDE.md`「当前阶段」资料目录那条加一句「迁移在 `cli.py`/`runner.py` 开跑前检查里做，先于 `ShelfConfig.load`；`load` 无副作用，默认配置由 `ensure()` 写」；`CHANGELOG.md` 加 0.4.5 修复条目。

- [ ] **Step 6: 版本 0.4.5，提交**

```bash
git commit -am "fix: 老盘迁移提前到读配置之前，ShelfConfig.load 不再建目录"
```

完成后本机复跑：`uv run shelf run "<真实老盘>" --offline`，期望看到「已把 .shelf/ 改名为 HiddenShelf/」且 `index.html` 引用 `HiddenShelf/site/`。
