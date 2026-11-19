"""SQLite 记忆库：schema、CRUD、保留分计算。"""
import os
import sqlite3
import json
import math
from datetime import datetime, timezone, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "memory.db")

# 各类记忆的基础权重与衰减系数（天数）
CATEGORY_WEIGHTS = {
    "identity":   (1.00, 0.002),   # 身份：衰减极慢
    "preference": (0.95, 0.005),   # 偏好：慢
    "goal":       (0.90, 0.005),   # 目标：慢
    "relation":   (0.85, 0.008),   # 关系：中
    "event":      (0.60, 0.030),   # 事件：快
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    attribute TEXT NOT NULL,
    value TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'event',
    confidence REAL DEFAULT 0.8,
    source_turn INTEGER,
    source_text TEXT,
    session_id TEXT,
    created_at TEXT,
    updated_at TEXT,
    access_count INTEGER DEFAULT 0,
    last_access TEXT,
    status TEXT DEFAULT 'active',
    superseded_by INTEGER,
    embedding TEXT
);
CREATE INDEX IF NOT EXISTS idx_subject_attr ON memories(subject, attribute);
CREATE INDEX IF NOT EXISTS idx_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_category ON memories(category);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT,
    ended_at TEXT,
    summary TEXT,
    token_estimate INTEGER DEFAULT 0,
    folded INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    old_id INTEGER,
    new_id INTEGER,
    resolution TEXT,
    reason TEXT,
    created_at TEXT
);
"""


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect(db_path=None):
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def add_memory(conn, subject, attribute, value, category="event", confidence=0.8,
               source_turn=None, source_text=None, session_id=None, embedding=None):
    """插入一条记忆。返回 id；若与现有完全同值，则只增访问次数并返回原 id。"""
    same = conn.execute(
        "SELECT id FROM memories WHERE subject=? AND attribute=? AND value=? AND status='active'",
        (subject, attribute, value),
    ).fetchone()
    if same:
        conn.execute(
            "UPDATE memories SET access_count=access_count+1, last_access=? WHERE id=?",
            (now_iso(), same["id"]),
        )
        conn.commit()
        return same["id"]

    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO memories
           (subject, attribute, value, category, confidence, source_turn, source_text,
            session_id, created_at, updated_at, last_access, embedding)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (subject, attribute, value, category, confidence, source_turn, source_text,
         session_id, ts, ts, ts, json.dumps(embedding) if embedding else None),
    )
    conn.commit()
    return cur.lastrowid


def find_conflicts(conn, subject, attribute, value):
    """找出同主体同属性但值不同的活跃条目。"""
    rows = conn.execute(
        "SELECT * FROM memories WHERE subject=? AND attribute=? AND status='active' AND value<>?",
        (subject, attribute, value),
    ).fetchall()
    return [dict(r) for r in rows]


def supersede(conn, old_id, new_id, reason=""):
    conn.execute(
        "UPDATE memories SET status='superseded', superseded_by=? WHERE id=?",
        (new_id, old_id),
    )
    conn.execute(
        "INSERT INTO conflicts (old_id, new_id, resolution, reason, created_at) VALUES (?,?,?,?,?)",
        (old_id, new_id, "update", reason, now_iso()),
    )
    conn.commit()


def log_coexist(conn, old_id, new_id, reason=""):
    conn.execute(
        "INSERT INTO conflicts (old_id, new_id, resolution, reason, created_at) VALUES (?,?,?,?,?)",
        (old_id, new_id, "coexist", reason, now_iso()),
    )
    conn.commit()


def retention_score(row, now=None):
    """保留分 = 基础权重 × (1+log(1+访问次数)) × exp(-λ×距上次访问天数)"""
    now = now or datetime.now(timezone.utc).astimezone()
    base, lam = CATEGORY_WEIGHTS.get(row["category"], (0.6, 0.03))
    last = row["last_access"] or row["created_at"] or now.isoformat()
    try:
        last_dt = datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except Exception:
        last_dt = now
    days = max(0.0, (now - last_dt).total_seconds() / 86400.0)
    freq = 1.0 + math.log(1.0 + (row["access_count"] or 0))
    decay = math.exp(-lam * days)
    return round(base * freq * decay, 4)


def list_memories(conn, status="active", limit=200):
    rows = conn.execute(
        "SELECT * FROM memories WHERE status=? ORDER BY updated_at DESC LIMIT ?",
        (status, limit),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["score"] = retention_score(r)
        d.pop("embedding", None)
        out.append(d)
    return out


def stats(conn):
    rows = conn.execute(
        "SELECT category, COUNT(*) n FROM memories WHERE status='active' GROUP BY category"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) n FROM memories").fetchone()["n"]
    return {"total": total, "by_category": {r["category"]: r["n"] for r in rows}}
