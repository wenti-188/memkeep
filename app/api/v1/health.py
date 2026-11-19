"""健康检查与指标。"""
import os
import sys

from fastapi import APIRouter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import llm  # noqa: E402

from app.core import config, metrics  # noqa: E402
from app.repositories.sqlite_repo import SqliteRepository  # noqa: E402
from app.schemas.memory import HealthResponse, MetricsResponse  # noqa: E402

router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthResponse, summary="检查数据库与模型可用性")
def health():
    db_state = "ok"
    try:
        if config.settings.db_backend == "postgres":
            from app.repositories.pg_repo import PgRepository

            repo = PgRepository(config.settings.pg_dsn)
            conn = repo.connect()
            if not repo.health(conn):
                db_state = "error: pg select failed"
            conn.close()
        else:
            repo = SqliteRepository(config.settings.sqlite_path)
            conn = repo.connect()
            conn.execute("SELECT 1")
            conn.close()
    except Exception as exc:  # noqa: BLE001
        db_state = f"error: {exc}"

    llm_ok, detail = llm.health()
    llm_state = "ok" if llm_ok else f"unavailable: {detail}"

    status = "ok" if db_state == "ok" and llm_ok else "degraded"
    return HealthResponse(status=status, db=db_state, llm=llm_state, version=config.settings.version)


@router.get("/metrics", response_model=MetricsResponse, summary="进程内指标快照")
def get_metrics():
    return MetricsResponse(**metrics.snapshot())
