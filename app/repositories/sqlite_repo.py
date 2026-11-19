"""数据访问层：把"怎么存"从业务里剥离。当前实现是 SQLite，后续可换 pgvector。"""
import os
import sys
from typing import Protocol

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from storage import db  # noqa: E402


class MemoryRepository(Protocol):
    def connect(self): ...


class SqliteRepository:
    """SQLite 实现。开 WAL 支持并发读。"""

    def __init__(self, path: str):
        self.path = path

    def connect(self):
        conn = db.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def list_active(self, conn, limit: int = 200):
        return db.list_memories(conn, status="active", limit=limit)

    def stats(self, conn):
        return db.stats(conn)

    def delete(self, conn, mem_id: int):
        conn.execute("UPDATE memories SET status='deleted' WHERE id=?", (mem_id,))
        conn.commit()

    def conflicts(self, conn, limit: int = 30):
        rows = conn.execute(
            "SELECT * FROM conflicts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
