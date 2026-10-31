# Hidden Shelf 计划 10：合并子目录里的旧库 Implementation Plan

> **For agentic workers:** 本计划由本机会话直接实现（用户 2026-10-30 定）。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户先在某个子目录（如 `盘/child/`）跑过 `shelf run`，后来改以母目录（`盘/`）为盘根再跑：之前母目录那趟把子目录当普通目录、整个重来（重新刮削、封面重做、子站残骸留在原地，2026-10-30 实测）。改成「导入本地资料」步把子库当作本地资料读进来，然后把子库目录搬到母库的 `HiddenShelf/legacy/nested/` 留底。

**Architecture:** 新模块 `nested.py::merge_nested_libraries(connection, paths, *, progress, move=True) -> NestedResult`。扫描步本来就跳过任何深度的 `HiddenShelf/`，所以子目录里的视频已经以 `child/...` 路径在母库里了；本模块只读子库 `shelf.db`（`mode=ro`），按「子目录相对路径 + 子库里的 `asset.path`」找到母库里的同一文件，把标量字段连同**原归属**搬过去（`require_empty=True`，母库已有的值不动，`user:*` 照旧受保护）、艺人/标签/系列/厂牌关联（经 `resolve_performer`/`resolve_named` 合并到母库实体，外站 ID 与别名一并登记）、封面/海报/九宫格文件（母库没有才复制）、`scraped_at`、探测结果（大小与 mtime 相同才搬）、头像、快照文件。最后 `shutil.move` 子目录的 `HiddenShelf/` 与 `index.html` 到 `HiddenShelf/legacy/nested/<子目录相对路径，/ 换成 __>/`。预演（`dry_run`）照常导入数据但不搬目录。

**Tech Stack:** 现有。

**Spec:** 设计文档 §4.2（真相在盘里；派生产物只在 `HiddenShelf/`）。本计划不改布局，只补一种「盘根上移」的用法。

## Global Constraints

- 版本 1.4.5 → **1.4.6**（一个任务）。三处同改，提交信息中文，提交后 push。
- 子库只读，失败（打不开、表不对）记日志跳过、不搬目录，母库照常跑完。
- 不删任何文件：子库目录整体搬到 `legacy/nested/`，撞名加 `-2`、`-3`。
- 凭据不涉及（子库里本来就没有）。

## Review Focus

1. **常见用法**：子目录跑过一次（含联网封面、艺人、标签、`scraped_at`），母目录再跑：母库这些字段齐全且归属与子库一致，封面文件在母库 `covers/`，`should_scrape` 不再要求重刮。→ `test_merge_carries_fields_entities_cover_and_scraped_at`。
2. **母库已有的值不动**：母库 `overrides.json` 给了标题（`user:manual`），子库标题不同 → 母库标题不变。→ `test_merge_does_not_override_parent_values`。
3. **子库目录搬到留底区，第二趟不再找到**：`child/HiddenShelf` 与 `child/index.html` 进 `HiddenShelf/legacy/nested/child/`，再跑一次 `libraries == 0`。→ `test_merge_moves_child_library_and_is_idempotent`。
4. **预演不搬**：`move=False` 时数据导入但 `child/HiddenShelf` 还在。→ `test_merge_dry_run_keeps_child_in_place`。
5. **坏库**：`child/HiddenShelf/shelf.db` 是垃圾文件 → 跳过、记日志、不搬、母库其余照常。→ `test_merge_skips_broken_child_db`。

---

### Task 1: `nested.merge_nested_libraries` + 接进导入步（1.4.6）

**Files:**
- Create: `src/hidden_shelf/nested.py`
- Modify: `src/hidden_shelf/local_import.py`（`import_local(..., move_nested=True)` 开头调用；`ImportResult.nested`）
- Modify: `src/hidden_shelf/pipeline.py`（`_execute` 的 `import` 分支传 `move_nested=not dry_run`）
- Modify: `src/hidden_shelf/field_owners.py`（公开 `is_valid_owner(owner) -> bool`）
- Test: `tests/test_nested.py`
- Docs: `README.md`、`README.zh.md`（FAQ 一条）、`CLAUDE.md`、`CHANGELOG.md`

**Interfaces:**
- `nested.find_nested_libraries(root: Path) -> list[Path]`：所有深度上含 `shelf.db` 的 `HiddenShelf/` 的**父目录**（即子盘根），不含 root 自己，跳过 `scan.SKIP_DIRS`，按路径排序。
- `nested.merge_nested_libraries(connection, paths, *, progress=print, move=True) -> NestedResult(libraries, assets, covers, avatars, snapshots, moved, skipped)`。
- `nested.NESTED_LEGACY_DIR = "nested"`（`paths.legacy / "nested"`）。

- [ ] Step 1: 写 `tests/test_nested.py` 五个测试（用 `fake_video` 造子盘，`pipeline.run(child, steps=("scan","import","media","build"))` 得到真子库）。
- [ ] Step 2: 实现；`uv run pytest tests/test_nested.py -v` 全过。
- [ ] Step 3: 全量测试；文档；版本 1.4.6；提交 `feat: 母目录再跑时合并子目录里的旧库（计划 10）`。
- [ ] Step 4: 本机用演示盘复现 2026-10-30 的实验，确认母目录那趟不再进 `_未知厂牌/`、子站残骸进了 `legacy/nested/`。
