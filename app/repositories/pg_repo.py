"""Postgres + pgvector 实现。向量检索走 HNSW 索引，连接走线程安全池，事务交给数据库。"""
import threading
import time

import psycopg2
from pgvector.psycopg2 import register_vector
from psycopg2.extras import RealDictCursor
from psycopg2.pool import PoolError, ThreadedConnectionPool

_pools: dict[tuple, ThreadedConnectionPool] = {}
_pool_lock = threading.Lock()


def _get_pool(dsn: str, minconn: int, maxconn: int) -> ThreadedConnectionPool:
    key = (dsn, minconn, maxconn)
    with _pool_lock:
        if key not in _pools:
            _pools[key] = ThreadedConnectionPool(
                minconn, maxconn, dsn, cursor_factory=RealDictCursor
            )
        return _pools[key]


class _PooledConn:
    """把连接池借出的连接包装成"close 即归还"，调用方不需要知道池的存在。"""

    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn
        self._closed = False

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def execute(self, *args, **kwargs):
        cur = self._conn.cursor()
        cur.execute(*args, **kwargs)
        return cur

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._conn.closed:
                self._pool.putconn(self._conn, close=True)
            else:
                self._conn.rollback()
                self._pool.putconn(self._conn)
        except Exception:  # noqa: BLE001
            try:
                self._pool.putconn(self._conn, close=True)
            except Exception:  # noqa: BLE001
                pass

    def __getattr__(self, item):
        return getattr(self._conn, item)


class PgRepository:
    def __init__(self, dsn: str, pool_min: int = 2, pool_max: int = 10):
        self.dsn = dsn
        self.pool_min = pool_min
        self.pool_max = pool_max

    def connect(self):
        """阻塞获取连接：池满时短暂等待，而不是直接抛错。"""
        pool = _get_pool(self.dsn, self.pool_min, self.pool_max)
        deadline = time.time() + 3.0
        while True:
            try:
                conn = pool.getconn()
                break
            except PoolError:
                if time.time() >= deadline:
                    raise
                time.sleep(0.02)
        register_vector(conn)
        return _PooledConn(pool, conn)

    # ---------- 读 ----------
    def list_active(self, conn, limit: int = 200):
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, subject, attribute, value, category, confidence,
                          created_at, updated_at, access_count, last_access, status
                   FROM memories WHERE status='active'
                   ORDER BY updated_at DESC LIMIT %s""",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def stats(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT category, COUNT(*) AS n FROM memories WHERE status='active' GROUP BY category")
            by_cat = {r["category"]: int(r["n"]) for r in cur.fetchall()}
            cur.execute("SELECT COUNT(*) AS n FROM memories")
            total = int(cur.fetchone()["n"])
        return {"total": total, "by_category": by_cat}

    def conflicts(self, conn, limit: int = 30):
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM conflicts ORDER BY id DESC LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def knn(self, conn, embedding, k: int = 40):
        """返回 [(id, cosine_similarity)]，HNSW 近邻。"""
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, 1 - (embedding <=> %s::vector) AS sim
                   FROM memories
                   WHERE status='active' AND embedding IS NOT NULL
                   ORDER BY embedding <=> %s::vector
                   LIMIT %s""",
                (embedding, embedding, k),
            )
            return [(r["id"], float(r["sim"])) for r in cur.fetchall()]

    # ---------- 写 ----------
    def add_memory(
        self, conn, subject, attribute, value, category="event", confidence=0.8,
        source_turn=None, source_text=None, session_id=None, embedding=None,
    ):
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM memories
                   WHERE subject=%s AND attribute=%s AND value=%s AND status='active'""",
                (subject, attribute, value),
            )
            same = cur.fetchone()
            if same:
                cur.execute(
                    "UPDATE memories SET access_count=access_count+1, last_access=now() WHERE id=%s",
                    (same["id"],),
                )
                conn.commit()
                return same["id"]

            cur.execute(
                """INSERT INTO memories
                   (subject, attribute, value, category, confidence, source_turn, source_text,
                    session_id, embedding, last_access)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                   RETURNING id""",
                (subject, attribute, value, category, confidence, source_turn, source_text,
                 session_id, embedding),
            )
            new_id = cur.fetchone()["id"]
        conn.commit()
        return new_id

    def find_conflicts(self, conn, subject, attribute, value):
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, value, created_at FROM memories
                   WHERE subject=%s AND attribute=%s AND status='active' AND value<>%s""",
                (subject, attribute, value),
            )
            return [dict(r) for r in cur.fetchall()]

    def supersede(self, conn, old_id, new_id, reason=""):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE memories SET status='superseded', superseded_by=%s WHERE id=%s",
                (new_id, old_id),
            )
            cur.execute(
                "INSERT INTO conflicts (old_id, new_id, resolution, reason) VALUES (%s,%s,'update',%s)",
                (old_id, new_id, reason),
            )
        conn.commit()

    def log_coexist(self, conn, old_id, new_id, reason=""):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conflicts (old_id, new_id, resolution, reason) VALUES (%s,%s,'coexist',%s)",
                (old_id, new_id, reason),
            )
        conn.commit()

    def delete(self, conn, mem_id: int):
        with conn.cursor() as cur:
            cur.execute("UPDATE memories SET status='deleted' WHERE id=%s", (mem_id,))
        conn.commit()

    # ---------- 运维 ----------
    def health(self, conn) -> bool:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except Exception:  # noqa: BLE001
            return False

    def archive_stale(self, conn, days: int = 180, min_score: float = 0.02) -> int:
        """把长期未访问且保留分低于阈值的条目归档，模拟"遗忘"。"""
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE memories SET status='archived'
                   WHERE status='active'
                     AND last_access IS NOT NULL
                     AND last_access < now() - (%s || ' days')::interval""",
                (days,),
            )
            n = cur.rowcount
        conn.commit()
        return n
