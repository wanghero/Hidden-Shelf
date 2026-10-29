-- 0002：联网刮削（计划 2 Task 7）。
-- entity_alias 加来源与置信度；新表 entity_external_ref 挂外站 ID；entity 加头像与元数据；asset 记刮削时刻。
-- 表结构取自 peach migrations/0002_canonical_entities.sql 与 0032_entity_external_ref_multi_id.sql（AGPL-3.0-or-later），
-- 列名按本项目缩短（metadata / synced_at）。

CREATE TABLE entity_alias_new(
    entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'scrape',
    confidence REAL NOT NULL DEFAULT 1,
    UNIQUE(entity_id, normalized, source)
);
INSERT INTO entity_alias_new(entity_id, alias, normalized)
    SELECT entity_id, alias, normalized FROM entity_alias;
DROP TABLE entity_alias;
ALTER TABLE entity_alias_new RENAME TO entity_alias;
CREATE INDEX IF NOT EXISTS entity_alias_normalized ON entity_alias(normalized);

CREATE TABLE IF NOT EXISTS entity_external_ref(
    entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    external_kind TEXT NOT NULL,
    external_id TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    synced_at TEXT,
    PRIMARY KEY(provider, external_kind, external_id),
    UNIQUE(entity_id, provider, external_kind, external_id)
);
CREATE INDEX IF NOT EXISTS entity_external_ref_entity ON entity_external_ref(entity_id);

ALTER TABLE entity ADD COLUMN avatar_file TEXT;
ALTER TABLE entity ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}';

ALTER TABLE asset ADD COLUMN scraped_at TEXT;
ALTER TABLE asset ADD COLUMN scrape_note TEXT;
