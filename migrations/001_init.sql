-- MemKeep 初始化：记忆表 + 冲突表 + HNSW 向量索引
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
    id            BIGSERIAL PRIMARY KEY,
    subject       TEXT NOT NULL,
    attribute     TEXT NOT NULL,
    value         TEXT NOT NULL,
    category      TEXT NOT NULL DEFAULT 'event',
    confidence    REAL DEFAULT 0.8,
    source_turn   INTEGER,
    source_text   TEXT,
    session_id    TEXT,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    access_count  INTEGER DEFAULT 0,
    last_access   TIMESTAMPTZ,
    status        TEXT DEFAULT 'active',
    superseded_by BIGINT,
    embedding     vector(1024)
);

CREATE INDEX IF NOT EXISTS idx_pg_subject_attr ON memories (subject, attribute);
CREATE INDEX IF NOT EXISTS idx_pg_status       ON memories (status);
CREATE INDEX IF NOT EXISTS idx_pg_category     ON memories (category);
CREATE INDEX IF NOT EXISTS idx_pg_updated      ON memories (updated_at DESC);

-- 近邻检索：余弦距离。列表越大收益越明显（万级从全表扫降到毫秒）
CREATE INDEX IF NOT EXISTS idx_pg_embedding
    ON memories USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    started_at     TIMESTAMPTZ DEFAULT now(),
    ended_at       TIMESTAMPTZ,
    summary        TEXT,
    token_estimate INTEGER DEFAULT 0,
    folded         INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conflicts (
    id         BIGSERIAL PRIMARY KEY,
    old_id     BIGINT,
    new_id     BIGINT,
    resolution TEXT,
    reason     TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
