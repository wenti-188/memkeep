"""并发压测：N 并发 × M 轮，出 P50/P95/失败率/吞吐，并记录错误明细。"""
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

BASE = "http://127.0.0.1:5051"
CONCURRENCY = 20
ROUNDS = 10
PATHS = ["/health", "/api/v1/memories?limit=20"]

lock = threading.Lock()
latencies: list[int] = []
err_counter: Counter = Counter()


def worker(barrier, rounds):
    local = []
    local_err = Counter()
    barrier.wait()
    for _ in range(rounds):
        for path in PATHS:
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(BASE + path, timeout=15) as r:
                    r.read()
                    if r.status != 200:
                        local_err[f"{path} {r.status}"] += 1
            except urllib.error.HTTPError as e:
                local_err[f"{path} HTTP{e.code}"] += 1
            except Exception as e:  # noqa: BLE001
                local_err[f"{path} {type(e).__name__}"] += 1
            local.append((time.perf_counter() - t0) * 1000)
    with lock:
        latencies.extend(local)
        err_counter.update(local_err)


def pct(data, p):
    if not data:
        return 0
    idx = int((len(data) - 1) * p)
    return round(sorted(data)[idx], 1)


def main():
    threads_n = int(sys.argv[1]) if len(sys.argv) > 1 else CONCURRENCY
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else ROUNDS

    barrier = threading.Barrier(threads_n)
    threads = [threading.Thread(target=worker, args=(barrier, rounds)) for _ in range(threads_n)]

    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - started

    total = len(latencies)
    errors = sum(err_counter.values())
    result = {
        "concurrency": threads_n,
        "rounds": rounds,
        "requests": total,
        "errors": errors,
        "error_rate": round(errors / total * 100, 2) if total else 0,
        "qps": round(total / elapsed, 1),
        "p50_ms": pct(latencies, 0.50),
        "p95_ms": pct(latencies, 0.95),
        "p99_ms": pct(latencies, 0.99),
        "mean_ms": round(statistics.mean(latencies), 1) if latencies else 0,
        "max_ms": round(max(latencies), 1) if latencies else 0,
        "error_detail": dict(err_counter),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
