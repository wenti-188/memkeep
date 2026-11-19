"""pytest 公共 fixture。"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("MEMKEEP_DB", "sqlite")
os.environ.setdefault("MEMKEEP_SQLITE", os.path.join(ROOT, "storage", "memory.db"))


@pytest.fixture
def tmp_db_conn(tmp_path):
    """独立临时库，测试之间互不影响。"""
    from storage import db

    conn = db.connect(str(tmp_path / "test.db"))
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def seed_memory():
    from storage import db

    def _seed(conn, attribute, value, category="event"):
        return db.add_memory(conn, "用户", attribute, value, category=category)

    return _seed
