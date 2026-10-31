"""生成演示盘并出站：给 GitHub Pages 的在线预览用，也可本机看效果。

    uv run python scripts/make_demo.py dist/demo

全部数据是虚构的（番号、厂牌、艺人、标题都不对应任何真实作品）；视频是 ffmpeg 合成的几秒彩条，
封面是 Pillow 画的渐变图。流程与真实盘完全一样（`pipeline.run`，离线），所以输出目录本身就是
一块「整理好的盘」：复制到哪里，双击 `index.html` 都能看。不联网。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from hidden_shelf import pipeline
from hidden_shelf.config import ShelfConfig
from hidden_shelf.paths import SHELF_DIR, ShelfPaths
from hidden_shelf.pipeline import ScrapeOptions

#: 虚构作品：番号 → 资料。厂牌与艺人名都是编的。
WORKS: dict[str, dict] = {
    "DEMO-001": {"title": "Morning Light on the Harbor", "studio": "Example Pictures", "series": "Harbor Diaries",
                 "release_date": "2024-03-15", "performers": ["Aoi Sample", "Rin Placeholder"],
                 "tags": ["ドラマ", "単体作品", "ハイビジョン"], "hue": 200},
    "DEMO-002": {"title": "Two Rooms, One Window", "studio": "Example Pictures", "series": "Harbor Diaries",
                 "release_date": "2024-05-02", "performers": ["Aoi Sample"], "tags": ["ドラマ", "単体作品"],
                 "hue": 330, "parts": 2},
    "DEMO-003": {"title": "The Last Train Home", "studio": "Example Pictures", "release_date": "2024-07-20",
                 "performers": ["Mio Fixture"], "tags": ["ドラマ", "OL"], "hue": 20},
    "SMPL-010": {"title": "Kitchen Stories", "studio": "Sample Studio", "series": "Kitchen Stories",
                 "release_date": "2023-11-11", "performers": ["Rin Placeholder", "Yui Dummy"],
                 "tags": ["コメディ", "複数プレイ"], "hue": 90},
    "SMPL-011": {"title": "Kitchen Stories 2", "studio": "Sample Studio", "series": "Kitchen Stories",
                 "release_date": "2024-01-30", "performers": ["Yui Dummy"], "tags": ["コメディ", "単体作品"], "hue": 120},
    "SMPL-012": {"title": "Rooftop Garden", "studio": "Sample Studio", "release_date": "2024-09-09",
                 "performers": ["Mio Fixture", "Yui Dummy"], "tags": ["ハイビジョン", "複数プレイ"], "hue": 160},
    "FIXT-0042": {"title": "Blueprint", "studio": "Fixture Films", "release_date": "2022-12-24",
                  "performers": ["Aoi Sample"], "tags": ["ドラマ", "ハイビジョン"], "hue": 260},
    "FIXT-0043": {"title": "Blueprint II", "studio": "Fixture Films", "release_date": "2023-06-06",
                  "performers": ["Rin Placeholder"], "tags": ["ドラマ"], "hue": 280},
    "FIXT-0044": {"title": "Night Shift", "studio": "Fixture Films", "release_date": "2024-02-14",
                  "performers": ["Mio Fixture"], "tags": ["OL", "単体作品"], "hue": 40},
}
#: 认不出番号的文件：演示「未识别」上墙。
UNRECOGNIZED = ["Holiday clips 2024.mp4", "beach_trip_raw.mov"]


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        sys.exit("需要系统 ffmpeg（macOS: brew install ffmpeg；Debian: apt install ffmpeg）")
    return path


def make_video(ffmpeg: str, path: Path, seconds: float, hue: int) -> None:
    """几秒钟的合成视频：彩条叠一层按色相调的底色，h264/aac，极小。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        ffmpeg, "-v", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=12",
        "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100",
        "-t", str(seconds), "-vf", f"hue=h={hue}:s=0.6",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "48k", "-shortest", str(path),
    ], check=True)


def make_cover(path: Path, code: str, title: str, hue: int) -> None:
    """800×538 横版封面：两色渐变 + 番号 + 标题。"""
    width, height = 800, 538
    image = Image.new("RGB", (width, height))
    top = _hsv(hue, 0.55, 0.95)
    bottom = _hsv((hue + 40) % 360, 0.75, 0.45)
    pixels = image.load()
    for y in range(height):
        t = y / (height - 1)
        color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        for x in range(width):
            pixels[x, y] = color
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, height - 170, width - 40, height - 40), fill=(0, 0, 0))
    big, small = ImageFont.load_default(size=40), ImageFont.load_default(size=22)
    draw.text((60, height - 160), code, fill=(255, 255, 255), font=big)
    draw.text((60, height - 108), title, fill=(230, 230, 230), font=small)
    draw.text((60, height - 76), "demo data", fill=(160, 160, 160), font=small)
    image.save(path, "JPEG", quality=80)


def _hsv(h: float, s: float, v: float) -> tuple[int, int, int]:
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h / 360, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def populate(root: Path, ffmpeg: str) -> None:
    """造一块「还没整理过」的盘：视频散在 `下载/` 里，封面放在视频旁边，资料写进 overrides.json。"""
    inbox = root / "Downloads"
    for code, info in WORKS.items():
        parts = info.get("parts", 1)
        for n in range(1, parts + 1):
            name = f"{code}-cd{n}.mp4" if parts > 1 else f"{code}.mp4"
            make_video(ffmpeg, inbox / name, seconds=4 + (hash(code) % 4), hue=info["hue"])
        # 封面挂在第一个视频的主名后面（`<主名>-cover.jpg`），和 Kodi/Jellyfin 的习惯一样。
        stem = f"{code}-cd1" if parts > 1 else code
        make_cover(inbox / f"{stem}-cover.jpg", code, info["title"], info["hue"])
    for name in UNRECOGNIZED:
        make_video(ffmpeg, inbox / name, seconds=3, hue=0)
    overrides = {code: {k: v for k, v in info.items() if k not in ("hue", "parts")} for code, info in WORKS.items()}
    shelf = root / SHELF_DIR
    shelf.mkdir(exist_ok=True)
    (shelf / "overrides.json").write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")


def prune(root: Path) -> None:
    """发布前去掉与浏览无关的产物：备份、日志、快照（db 留着，它是开放格式的一部分）。"""
    paths = ShelfPaths(root)
    for directory in (paths.backups, paths.logs, paths.sources, paths.legacy):
        shutil.rmtree(directory, ignore_errors=True)
    # GitHub Pages 默认走 Jekyll，会无视下划线开头的目录（如 `_未知厂牌/`）；这个空文件关掉它。
    (root / ".nojekyll").write_text("", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path, help="输出目录（会先清空）")
    parser.add_argument("--language", default="en", choices=("zh", "en", "ja"), help="站点默认语言")
    args = parser.parse_args(argv)
    root = args.output.resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    ffmpeg = _ffmpeg()
    populate(root, ffmpeg)
    config = ShelfConfig(language=args.language, dir_template="{studio}/{code}[ {title}]")
    paths = ShelfPaths(root)
    paths.ensure()
    config.save(paths)
    result = pipeline.run(root, config=config, progress=pipeline.ConsoleProgress(),
                          scrape_options=ScrapeOptions(offline=True))
    if not result.ok:
        return 1
    prune(root)
    print(f"演示盘在 {root}，打开 {root / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
