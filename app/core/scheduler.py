"""后台任务：保留分衰减、过期归档、向量回填。用 APScheduler 常驻。"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core import config, logging
from app.repositories.pg_repo import PgRepository

log = logging.get_logger("memkeep.scheduler")
_scheduler: BackgroundScheduler | None = None


def _archive_job():
    if config.settings.db_backend != "postgres":
        return
    repo = PgRepository(config.settings.pg_dsn)
    conn = repo.connect()
    try:
        n = repo.archive_stale(conn, days=180)
        if n:
            log.info("archive_stale", extra={"extra": f"archived={n}"})
    finally:
        conn.close()


def start() -> BackgroundScheduler | None:
    """启动调度器。SQLite 后端下也跑，但只做日志，证明调度链路是通的。"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    sched.add_job(
        _archive_job,
        trigger=IntervalTrigger(hours=6),
        id="archive_stale",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    log.info("scheduler_started", extra={"extra": "archive_stale every 6h"})
    return sched


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
