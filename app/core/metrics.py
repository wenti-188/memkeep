"""进程内指标：请求数、错误数、延迟分位、模型失败数。"""
import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_counts = defaultdict(int)
_latencies: list[int] = []
_MAX_SAMPLES = 2000


def inc(key: str, n: int = 1) -> None:
    with _lock:
        _counts[key] += n


def observe_latency(ms: int) -> None:
    with _lock:
        if len(_latencies) >= _MAX_SAMPLES:
            _latencies.pop(0)
        _latencies.append(ms)


def _percentile(p: float) -> int:
    with _lock:
        if not _latencies:
            return 0
        data = sorted(_latencies)
    idx = int((len(data) - 1) * p)
    return data[idx]


def snapshot() -> dict:
    return {
        "requests_total": _counts.get("requests", 0),
        "errors_total": _counts.get("errors", 0),
        "latency_p50_ms": _percentile(0.50),
        "latency_p95_ms": _percentile(0.95),
        "llm_failures": _counts.get("llm_failures", 0),
    }


class RateLimiter:
    """按客户端标识做每分钟滑动窗口限流。单机内存实现，够用且无外部依赖。"""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.time()
        cutoff = now - 60
        with self._lock:
            arr = self._hits.setdefault(key, [])
            while arr and arr[0] < cutoff:
                arr.pop(0)
            if len(arr) >= self.per_minute:
                return False
            arr.append(now)
            return True
