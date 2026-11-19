"""仓储工厂：按配置在 SQLite 与 Postgres 之间切换，业务层不关心具体实现。"""
from app.core import config
from app.repositories.pg_repo import PgRepository
from app.repositories.sqlite_repo import SqliteRepository


def build_repo():
    if config.settings.db_backend == "postgres":
        return PgRepository(config.settings.pg_dsn)
    return SqliteRepository(config.settings.sqlite_path)


def backend_name() -> str:
    return config.settings.db_backend
