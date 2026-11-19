"""集中配置：所有可变项走环境变量，代码里不出现魔法值。"""
import os
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


@dataclass(frozen=True)
class Settings:
    # 应用
    app_name: str = "MemKeep"
    version: str = "1.0.0"
    host: str = _env("MEMKEEP_HOST", "127.0.0.1")
    port: int = int(_env("MEMKEEP_PORT", "5051"))
    log_level: str = _env("MEMKEEP_LOG_LEVEL", "INFO")

    # 存储：sqlite | postgres
    db_backend: str = _env("MEMKEEP_DB", "sqlite")
    sqlite_path: str = _env("MEMKEEP_SQLITE", os.path.join(ROOT, "storage", "memory.db"))
    pg_dsn: str = _env(
        "MEMKEEP_PG_DSN",
        "postgresql://memkeep:memkeep@127.0.0.1:5433/memkeep",
    )
    pg_pool_min: int = int(_env("MEMKEEP_PG_POOL_MIN", "2"))
    pg_pool_max: int = int(_env("MEMKEEP_PG_POOL_MAX", "32"))

    # 模型
    llm_base: str = _env("OLLAMA_BASE", "http://127.0.0.1:11434")
    chat_model: str = _env("MEMKEEP_CHAT_MODEL", "qwen2.5:7b")
    embed_model: str = _env("MEMKEEP_EMBED_MODEL", "bge-m3:latest")
    llm_timeout: float = float(_env("MEMKEEP_LLM_TIMEOUT", "60"))
    llm_retries: int = int(_env("MEMKEEP_LLM_RETRIES", "2"))

    # 检索
    top_k: int = int(_env("MEMKEEP_TOP_K", "8"))
    token_budget: int = int(_env("MEMKEEP_TOKEN_BUDGET", "1200"))

    # 安全与限流
    api_key: str = _env("MEMKEEP_API_KEY", "")
    rate_limit_per_min: int = int(_env("MEMKEEP_RATE_LIMIT", "120"))

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key)


settings = Settings()
