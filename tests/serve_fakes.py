"""测试共用的假流水线：按步调用 progress 回调，不碰 ffmpeg 也不碰网络。"""
from __future__ import annotations

import threading
from pathlib import Path

from hidden_shelf import pipeline


def fake_pipeline(*, fail=(), skip=(), gate: threading.Event | None = None, check_cancel=False, raise_error=None):
    """假流水线：按步调用 progress 回调；`gate` 阻塞在第一步后；`check_cancel` 每步后查取消。"""
    calls = []

    def run(root, *, config=None, steps=pipeline.STEPS, progress=None, scrape_options=None, cancel=None,
            dry_run=False):
        calls.append({"root": root, "steps": tuple(steps), "move": config.move_unrecognized if config else None,
                      "offline": scrape_options.offline if scrape_options else None, "dry_run": dry_run})
        if raise_error:
            raise raise_error
        result = pipeline.RunResult(log_path=Path(root) / ".shelf" / "logs" / "x.log", dry_run=dry_run)
        for index, name in enumerate(steps):
            if check_cancel and cancel is not None and cancel():
                result.cancelled = True
                break
            progress.step(name)
            if name in skip:
                progress.skipped(name, "--offline")
                result.steps[name] = {"skipped": True}
                continue
            progress.advance(1, f"[1/2] {name} 第一行")
            progress.advance(1, f"[2/2] {name} 第二行")
            if name in fail:
                progress.failed(name, "RuntimeError: 炸了")
                if name == "scrape":
                    result.steps[name] = {"error": "RuntimeError: 炸了"}
                    continue
                result.ok = False
                result.failed_step = name
                result.error = "RuntimeError: 炸了"
                break
            stats = {"added": index}
            result.steps[name] = stats
            progress.done(stats)
            if gate is not None and index == 0:
                gate.wait(timeout=10)
        if result.ok and "build" in result.steps:
            result.index_html = Path(root) / "index.html"
        return result

    run.calls = calls
    return run
