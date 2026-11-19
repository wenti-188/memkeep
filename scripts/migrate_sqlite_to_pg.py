"""把现有 SQLite 记忆搬到 Postgres，并带上向量。一次性脚本，可重复执行（按 subject+attr+value 判重）。"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import config  # noqa: E402
from app.repositories.pg_repo import PgRepository  # noqa: E402


def main():
    src = config.settings.sqlite_path
    if not os.path.exists(src):
        print("SQLite 不存在：", src)
        return
    sconn = sqlite3.connect(src)
    sconn.row_factory = sqlite3.Row
    rows = sconn.execute("SELECT * FROM memories").fetchall()
    print("源库条数:", len(rows))

    repo = PgRepository(config.settings.pg_dsn)
    conn = repo.connect()
    moved = skipped = 0
    try:
        for r in rows:
            emb = None
            if r["embedding"]:
                try:
                    emb = json.loads(r["embedding"])
                except Exception:  # noqa: BLE001
                    emb = None
            if not emb:
                skipped += 1
                continue
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id FROM memories
                       WHERE subject=%s AND attribute=%s AND value=%s AND status=%s""",
                    (r["subject"], r["attribute"], r["value"], r["status"]),
                )
                if cur.fetchone():
                    skipped += 1
                    continue
                cur.execute(
                    """INSERT INTO memories
                       (subject, attribute, value, category, confidence, source_text,
                        session_id, created_at, updated_at, access_count, last_access,
                        status, superseded_by, embedding)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (r["subject"], r["attribute"], r["value"], r["category"], r["confidence"],
                     r["source_text"], r["session_id"], r["created_at"], r["updated_at"],
                     r["access_count"], r["last_access"], r["status"], r["superseded_by"], emb),
                )
            moved += 1
        conn.commit()
        print(f"导入 {moved} 条，跳过 {skipped} 条（无向量或已存在）")
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM memories WHERE status='active'")
            print("Postgres active 条数:", cur.fetchone()["n"])
    finally:
        conn.close()
        sconn.close()


if __name__ == "__main__":
    main()
