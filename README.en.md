# Hidden Shelf

A local organizer for JAV-style video collections: recognizes product codes, scrapes metadata, files everything under `studio/code/`, and writes a fully static site at the disk root. Plug in the drive, double-click `index.html`, browse and play.

![tests](https://github.com/wanghero/Hidden-Shelf/actions/workflows/test.yml/badge.svg) · [中文](README.md)

| Poster wall | Progress page | Folder picker |
|---|---|---|
| ![Poster wall](docs/images/wall.jpg) | ![Progress page](docs/images/progress.jpg) | ![Folder picker](docs/images/picker.jpg) |

All screenshots use demo data.

## What it does to your disk

One `shelf run` goes through six steps:

1. **Scan**: registers every video and its sidecars (NFO, cover, subtitles) and recognizes the product code in the file name.
2. **Import local data**: reads NFO files and covers left by earlier scrapers, plus your hand-written `HiddenShelf/overrides.json`.
3. **Scrape online**: asks the sources for title, studio, performers, tags, release date, cover and avatars where data is missing; offline it just skips, the later steps still run.
4. **Organize**: renames into `studio/code/code[-cdN].ext`; videos without a recognizable code go to `未识别/` ("unrecognized").
5. **Media**: probes duration and resolution, extracts frames for a contact sheet, uses a frame as the cover when none exists, crops a portrait poster.
6. **Build**: writes `index.html` at the disk root, an offline poster wall with filters by performer, studio and tag; click to play.

**Safety promises** (each pinned by tests):

- Only same-volume renames. **Never deletes** an original file, **never overwrites** an existing target.
- The database is backed up before every organize (last 5 kept).
- Every batch of moves is logged as JSONL (`HiddenShelf/logs/organize-*.jsonl`) and can be rolled back.
- All derived output (database, covers, posters, sheets, site data, logs, backups) lives under `HiddenShelf/`; **nothing is written next to your media**.
- `--dry-run` shows the list first: every file that would move and every reason one would not, without touching anything.

## Install

Prerequisites: Python ≥ 3.12 and system ffmpeg/ffprobe (the media step needs them; if they are missing the run stops there and tells you how to install them).

- macOS: `brew install ffmpeg`
- Debian/Ubuntu: `sudo apt install ffmpeg`
- Windows: download from [ffmpeg.org](https://ffmpeg.org/download.html) and add `bin/` to PATH

Install the CLI (either one):

```bash
uv tool install git+https://github.com/wanghero/Hidden-Shelf
pipx install git+https://github.com/wanghero/Hidden-Shelf
```

Developers:

```bash
git clone https://github.com/wanghero/Hidden-Shelf && cd Hidden-Shelf
uv sync
uv run shelf --version
```

## Three steps

```bash
shelf run <disk root> --dry-run   # 1. preview: list only
shelf run <disk root>             # 2. the real run
open <disk root>/index.html       # 3. look at the result (Windows: double-click index.html)
```

1. **Preview**: the terminal prints "N to move, M in place, K skipped", one line `current → target` per move; past 200 lines the full list is in `HiddenShelf/logs/plan-<time>.txt`. A preview still scans, imports local data and scrapes (that is how the plan is computed, and all of it writes only to `HiddenShelf/`); nothing else on the disk is touched.
2. **Real run**: same arguments, moves exactly what the preview listed. Each step prints a one-line summary; it ends with the path of `index.html`.
3. **Result**: double-click `index.html` at the disk root. Plug the drive into another machine and it still works; every path is relative.

## Progress page

If you would rather not use the terminal, `shelf serve` starts a small web page bound to `127.0.0.1` only (default `http://127.0.0.1:8031/`; if the port is taken it tries 8000–8099, `--port` picks one, `--no-browser` does not open the browser). Enter the disk root (or click "Browse" next to it and pick with the mouse; folders that already have a library are marked), set the four switches ("move unrecognized videos", "stay offline", "preview only", "force re-scrape") and press Start. Six step rows with status and progress, a live log, and "Open result" when done; "Stop" takes effect after the current step. The page and the CLI run the same pipeline with identical output.

## Online scraping

### Global config

Proxy and per-site cookies live in `~/.hidden-shelf/config.json` (`HIDDEN_SHELF_HOME` changes the directory); the first run writes the defaults.
Credentials live only there: never in any file on the disk, never in logs, never in snapshots. `shelf config` only reports whether a cookie is set, never its value.

```json
{
  "network": { "mode": "environment", "proxy": "" },
  "sources": {
    "javdb":  { "enabled": true, "cookie": "_jdb_session=...; over18=1" },
    "javbus": { "enabled": true, "cookie": "existmag=all" },
    "avbase": { "enabled": false, "cookie": "" }
  },
  "routes": { "censored": ["r18dev", "dmm", "javdb"] }
}
```

- `network.mode`: `environment` (follow `HTTPS_PROXY` etc.), `direct` (ignore the environment and connect directly), `proxy` (use `network.proxy`, e.g. `http://127.0.0.1:7890` or `socks5h://127.0.0.1:1080`).
- `sources.<site>.cookie`: the one-line Cookie request header copied from your browser; only javdb (quota and login wall) and javbus (age gate) need one. `enabled: false` disables a site.

If you would rather not copy cookies by hand, sign in through a browser: install Playwright once (`uv sync --extra login`, then `uv run playwright install chromium`) and run

```bash
uv run shelf login javdb      # a browser opens; sign in, then close the window or press Enter. Same for javbus and avbase
```

The "Sources & sign-in" panel in `shelf serve` does the same, with a per-site switch and a one-click "clear pause" for sites in cooldown. AVBase has no account, but its Cloudflare check is passed the same way: wait for the check in the window, then click "I have signed in". Cookies and the browser's User-Agent live only in the local global config, never on the disk, in logs or in snapshots.- `routes`: replaces the whole source chain for a content type. Types are `censored | amateur | uncensored | fc2`; sources are `r18dev dmm 1pondo fc2 javarchive avbase javbus javdb`. Each site is its own tier and the chain short-circuits: the first site that answers wins.

Snapshots (`<code>-<source>.json`) and cooldowns (`_cooldown.json`) live in `<disk root>/HiddenShelf/sources/`; a code is not asked again within 7 days. A 403 pauses the site for 15 minutes, doubling on repeat; a 429 honors the site's Retry-After.

### Sources

| Source | Content | Cookie needed | Smoke test on the author's machine, 2026-10-29 |
|---|---|---|---|
| r18dev | censored | no | works directly |
| dmm | censored | no | answered "no such code" for `ABW-358` |
| 1pondo | uncensored (1pondo) | no | not tested |
| fc2 | FC2 | no | works directly |
| javarchive | FC2 (delisted reposts) | no | works directly |
| javdb | censored, amateur, uncensored, FC2 | yes | works directly |
| javbus | censored, amateur, uncensored | yes (age gate) | works directly |
| avbase | censored, amateur, uncensored | no (but Cloudflare) | 403, went into cooldown; needs a browser cookie |

Default chains: censored `r18dev → dmm → avbase → javbus → javdb`; amateur `avbase → javbus → javdb → r18dev`; uncensored `1pondo → avbase → javbus → javdb`; FC2 `fc2 → javarchive → javdb`. When sources disagree, a local NFO ranks highest, then official sites, then community sites; whatever you write in `overrides.json` is never overwritten.

## Layout on the disk

```
<disk root>/
  index.html                       the result, double-click to open
  studio/code/code[-cdN].ext       organized videos (template is configurable)
  未识别/…                          unrecognized videos, original folder structure kept
  HiddenShelf/
    shelf.db                       SQLite database, the source of truth
    config.json                    per-disk settings: templates, move unrecognized, site language, scrape on/off
    overrides.json                 your manual edits, highest priority
    site/                          site data (works.js and friends)
    covers/  posters/  sheets/     covers, portrait posters, contact sheets
    avatars/                       performer avatars
    sources/                       scrape snapshots and cooldowns
    legacy/<code>/                 old NFO files and covers, kept
    logs/                          run-*.log, organize-*.jsonl, plan-*.txt
    backups/                       database backups taken before organizing (5 kept)
```

Manual edits go in `HiddenShelf/overrides.json` and are merged on the next `shelf run`:

```json
{
  "ABP-758": { "title": "Corrected title", "studio": "Prestige", "performers": ["鈴村あいり"], "tags": ["solo"] }
}
```

## FAQ

- **Does it work on another computer?** Yes. The site uses relative paths only, so the drive works wherever it is plugged in.
- **The file name is not a product code.** By default it moves to `未识别/` (keeping the original folder structure) and is listed separately on the site; `--no-move-unrecognized` leaves such files where they are.
- **NFO files and covers from an earlier scraper?** They are imported first, then moved to `HiddenShelf/legacy/<code>/`, so nothing stays next to the media.
- **Screenshots or notes left in the work's own folder?** A folder whose name carries the code counts as the work's own folder; its top-level loose files move along with the video, names unchanged, subfolders stay. The dry-run plan lists them as `EXTRA` rows.
- **A move went wrong, how do I roll back?** Each batch has `HiddenShelf/logs/organize-<time>.jsonl`. For now you call `hidden_shelf.organize.apply.rollback_batch(connection, paths, log_path)` from Python; there is no CLI entry point yet.
- **javdb wants a login.** Log in with your browser and paste the Cookie request header into `sources.javdb.cookie` in the global config.
- **The network dropped mid-run.** A scrape failure is recorded for that step only; organize, media and build still run. Run again when you are online to fill in the gaps.
- **A `.shelf/` folder from an earlier version?** Since 0.4.2 the data folder is the visible `HiddenShelf/`; the next run of any command renames it automatically. If both folders exist the run refuses and asks you to keep one.
- **The disk is read-only (NTFS on macOS is the usual case).** The run refuses up front and tells you why and what to do: install an NTFS driver or reformat as exFAT/APFS.

## Platforms

- macOS: verified (the author's daily driver).
- Linux: verified by CI.
- Windows: **not verified**. The CI job is allowed to fail; reports welcome.

## Disclaimer

- This tool is for adult (18+) content.
- It fetches public metadata and covers only; it does not download videos.
- No site credentials are bundled; cookies and each site's terms of use are your responsibility.
- The program is designed not to delete or overwrite and backs up before organizing, but **backups are still your job**; no liability is accepted for data loss.

## License and credits

- **AGPL-3.0-or-later**: modify and use it commercially, but a modified version offered as a network service must be open-sourced too.
- The rule modules are ported from [peach-mitao/peach](https://github.com/peach-mitao/peach) (AGPL-3.0), file by file in `docs/REUSE.md`.
- The UI follows `docs/ux-standard/`.

## Design history

- Design document: `docs/superpowers/specs/2026-10-28-hidden-shelf-design.md`
- Plan 1 (local pipeline): `docs/superpowers/plans/2026-10-28-plan-1-local-pipeline.md`
- Plan 2 (online scraping): `docs/superpowers/plans/2026-10-28-plan-2-online-scraping.md`
- Plan 3 (progress page): `docs/superpowers/plans/2026-10-29-plan-3-progress-web.md`
- Plan 4 (folder picker): `docs/superpowers/plans/2026-10-29-plan-4-folder-picker.md`
- Plan 5 (open-source prep): `docs/superpowers/plans/2026-10-29-plan-5-open-source.md`
