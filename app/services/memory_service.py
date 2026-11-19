"""业务服务层：编排"检索 → 作答 → 写入"，不含 HTTP 概念。"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import retriever, writer  # noqa: E402
from app.core import config, exceptions, logging  # noqa: E402
from app.repositories.factory import build_repo  # noqa: E402
from app.repositories.pg_repo import PgRepository  # noqa: E402
from app.repositories.sqlite_repo import SqliteRepository  # noqa: E402
from app.services.scoring import retention_score  # noqa: E402

log = logging.get_logger("memkeep.service")

QUESTION_RE = re.compile(r"[？?]|吗|什么|为什么|怎么|哪|多少|是否|谁|几")


class MemoryService:
    def __init__(self, repo=None):
        self.repo = repo or build_repo()
        # 算法引擎（抽取/检索）暂时仍基于 SQLite，Postgres 作为读路径与镜像
        self.engine_repo = SqliteRepository(config.settings.sqlite_path)

    # ---------- 读 ----------
    def list(self, limit: int = 200):
        conn = self.repo.connect()
        try:
            items = self.repo.list_active(conn, limit)
            stats = self.repo.stats(conn)
            for it in items:
                it["score"] = retention_score(it)
                if not isinstance(it.get("created_at"), str):
                    it["created_at"] = str(it.get("created_at") or "")
            return items, stats
        finally:
            conn.close()

    def delete(self, mem_id: int):
        conn = self.repo.connect()
        try:
            self.repo.delete(conn, mem_id)
            return {"id": mem_id, "status": "deleted"}
        finally:
            conn.close()

    # ---------- 问答 ----------
    def chat(self, message: str):
        conn = self.engine_repo.connect()
        try:
            try:
                res = retriever.answer(
                    conn, message,
                    budget=config.settings.token_budget,
                )
            except Exception as exc:  # 模型不可用 → 降级：只回记忆原文，不生成
                log.warning("llm_failed", extra={"stage": "answer", "extra": str(exc)})
                raise exceptions.UpstreamError("模型调用失败，已降级", detail=str(exc))

            written = []
            # 只有陈述句才写入；问句不抽事实，否则"用户在问什么"会被当成记忆
            if len(message) <= 300 and not QUESTION_RE.search(message):
                try:
                    written = writer.ingest_dialogue(conn, f"用户：{message}", session_id="api")
                    self._mirror(conn, written)
                except Exception as exc:
                    log.warning("ingest_failed", extra={"stage": "ingest", "extra": str(exc)})
                    written = []
            return res, written
        finally:
            conn.close()

    # ---------- 双写镜像 ----------
    def _mirror(self, sqlite_conn, written) -> None:
        """SQLite 写入后同步到 Postgres，保证读路径与 pgvector 索引一致。"""
        if config.settings.db_backend != "postgres" or not written:
            return
        try:
            import json

            pg = PgRepository(config.settings.pg_dsn)
            pconn = pg.connect()
            try:
                for w in written:
                    value = w.get("value")
                    if not value:
                        continue
                    row = sqlite_conn.execute(
                        "SELECT * FROM memories WHERE value=? AND status='active' ORDER BY id DESC LIMIT 1",
                        (value,),
                    ).fetchone()
                    if not row:
                        continue
                    emb = json.loads(row["embedding"]) if row["embedding"] else None
                    with pconn.cursor() as cur:
                        cur.execute(
                            """SELECT id FROM memories WHERE subject=%s AND attribute=%s AND value=%s""",
                            (row["subject"], row["attribute"], row["value"]),
                        )
                        if cur.fetchone():
                            continue
                        cur.execute(
                            """INSERT INTO memories
                               (subject, attribute, value, category, confidence, source_text,
                                session_id, created_at, updated_at, access_count, last_access, embedding)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s::timestamptz,%s::timestamptz,%s,%s::timestamptz,%s)""",
                            (row["subject"], row["attribute"], row["value"], row["category"],
                             row["confidence"], row["source_text"], row["session_id"],
                             row["created_at"], row["updated_at"], row["access_count"],
                             row["last_access"], emb),
                        )
                pconn.commit()
            finally:
                pconn.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("mirror_failed", extra={"stage": "mirror", "extra": str(exc)})

    # ---------- 显式写入 ----------
    def ingest(self, text: str, session_id: str | None = None, date: str | None = None):
        conn = self.engine_repo.connect()
        try:
            written = writer.ingest_dialogue(conn, text, session_id=session_id, date=date)
            self._mirror(conn, written)
            return written
        finally:
            conn.close()

    def conflicts(self, limit: int = 30):
        conn = self.repo.connect()
        try:
            return self.repo.conflicts(conn, limit)
        finally:
            conn.close()
