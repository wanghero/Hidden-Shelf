# Hidden Shelf（藏片阁）

本地番号片整理器：认番号、刮削、按 `厂牌/番号/` 归位，并在盘根目录生成纯静态站，插盘双击 `index.html` 即可浏览播放。

- 设计文档：`docs/superpowers/specs/2026-10-28-hidden-shelf-design.md`
- 实施计划 1（本地流水线）：`docs/superpowers/plans/2026-10-28-plan-1-local-pipeline.md`
- 许可：AGPL-3.0-or-later。策略模块移植自 [peach-mitao/peach](https://github.com/peach-mitao/peach)，登记见 `docs/REUSE.md`。

```bash
uv sync
uv run pytest -v
uv run shelf run <盘根目录>
```
