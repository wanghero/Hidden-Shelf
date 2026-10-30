-- 0001：初始表结构（计划 1 Task 5）。
-- asset.path 是相对盘根目录的 POSIX 路径；cover_file/poster_file/sheet_file 相对 .shelf/。

CREATE TABLE IF NOT EXISTS schema_version(
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS asset(
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    medium TEXT NOT NULL,
    size INTEGER,
    mtime REAL,
    first_seen TEXT,
    last_seen TEXT,
    vanished INTEGER NOT NULL DEFAULT 0,
    code TEXT,
    code_key TEXT,
    part TEXT NOT NULL DEFAULT '',
    content_type TEXT,
    title TEXT,
    original_title TEXT,
    studio TEXT,
    series TEXT,
    release_date TEXT,
    plot TEXT,
    cover_file TEXT,
    poster_file TEXT,
    sheet_file TEXT,
    duration REAL,
    width INTEGER,
    height INTEGER,
    vcodec TEXT,
    acodec TEXT,
    container TEXT,
    play_hint TEXT,
    probed_at TEXT,
    field_owners TEXT NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS asset_code_key ON asset(code_key);
CREATE INDEX IF NOT EXISTS asset_vanished ON asset(vanished);

CREATE TABLE IF NOT EXISTS sidecar(
    id INTEGER PRIMARY KEY,
    asset_id INTEGER REFERENCES asset(id) ON DELETE SET NULL,
    path TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    moved_to TEXT
);
CREATE INDEX IF NOT EXISTS sidecar_asset ON sidecar(asset_id);

CREATE TABLE IF NOT EXISTS entity(
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('performer','studio','series','tag')),
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    UNIQUE(kind, normalized_name)
);

CREATE TABLE IF NOT EXISTS entity_alias(
    entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized TEXT NOT NULL,
    UNIQUE(entity_id, normalized)
);

CREATE TABLE IF NOT EXISTS asset_entity(
    asset_id INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1,
    PRIMARY KEY(asset_id, entity_id, role)
);
CREATE INDEX IF NOT EXISTS asset_entity_entity ON asset_entity(entity_id);

CREATE TABLE IF NOT EXISTS run(
    id INTEGER PRIMARY KEY,
    started TEXT NOT NULL,
    finished TEXT,
    step TEXT NOT NULL,
    status TEXT NOT NULL,
    stats TEXT
);

CREATE TABLE IF NOT EXISTS organize_batch(
    id INTEGER PRIMARY KEY,
    started TEXT NOT NULL,
    finished TEXT,
    log_path TEXT,
    status TEXT NOT NULL,
    moved INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0
);
