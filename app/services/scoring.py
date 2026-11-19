"""保留分计算：与存储后端解耦，SQLite 与 Postgres 共用同一套公式。"""
import math
from datetime import datetime, timezone

CATEGORY_WEIGHTS = {
    "identity": (1.00, 0.002),
    "preference": (0.95, 0.005),
    "goal": (0.90, 0.005),
    "relation": (0.85, 0.008),
    "event": (0.60, 0.030),
}


def retention_score(row: dict, now: datetime | None = None) -> float:
    """保留分 = 基础权重 × (1+log(1+访问次数)) × exp(-λ×距上次访问天数)"""
    now = now or datetime.now(timezone.utc).astimezone()
    base, lam = CATEGORY_WEIGHTS.get(row.get("category"), (0.6, 0.03))
    last = row.get("last_access") or row.get("created_at")
    if isinstance(last, datetime):
        last_dt = last
    else:
        try:
            last_dt = datetime.fromisoformat(str(last))
        except Exception:  # noqa: BLE001
            last_dt = now
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - last_dt).total_seconds() / 86400.0)
    freq = 1.0 + math.log(1.0 + (row.get("access_count") or 0))
    return round(base * freq * math.exp(-lam * days), 4)
