"""消融实验：去掉一个部件，看准确率掉多少，从而知道每个部件到底值不值。

变体：
  full        —— 全开（线上配置）
  no_keyword  —— 只留向量路
  no_rrf      —— 不做 RRF 融合
  no_base     —— 不乘保留分
  no_boost    —— 不做意图类别加权（通过 intent 强制 semantic 模拟）
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import retriever  # noqa: E402
from storage import db  # noqa: E402
from eval.run_eval import judge  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTSET = os.path.join(ROOT, "eval", "testset.json")
OUT = os.path.join(ROOT, "eval", "ablation_result.json")

VARIANTS = {
    "full": {},
    "no_keyword": {"use_keywords": False},
    "no_rrf": {"use_rrf": False},
    "no_base": {"use_base": False},
}


def run(limit=None):
    conn = db.connect(os.path.join(ROOT, "storage", "memory.db"))
    with open(TESTSET, "r", encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    if limit:
        cases = cases[:limit]

    summary = {}
    for name, flags in VARIANTS.items():
        ok = 0
        lat = 0
        for c in cases:
            t0 = time.perf_counter()
            try:
                res = retriever.answer(conn, c["question"], **flags)
                reply = res["answer"]
            except Exception as exc:  # noqa: BLE001
                reply = f"ERROR {exc}"
            lat += int((time.perf_counter() - t0) * 1000)
            ok += 1 if judge(c, reply) else 0
            print(f"{name} [{c['id']:02d}] {'OK' if judge(c, reply) else 'FAIL'}")
        n = len(cases)
        summary[name] = {"accuracy": round(ok / n * 100, 1), "correct": ok, "total": n,
                         "avg_latency_ms": int(lat / n)}
        print(f"== {name}: {ok}/{n} = {ok/n*100:.1f}%")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"limit": limit, "summary": summary}, f, ensure_ascii=False, indent=2)
    print("写入", OUT)
    conn.close()
    return summary


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    run(lim)
