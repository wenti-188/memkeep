"""跑 50 题跨会话记忆评测。"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import retriever
from storage import db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "storage", "memory.db")
TESTSET = os.path.join(ROOT, "eval", "testset.json")
OUT = os.path.join(ROOT, "eval", "eval_result.json")

REFUSE_MARKERS = [
    "没有相关记录", "没提过", "没有记录", "没有提及", "不清楚", "不知道",
    "没有关于", "无法回答", "没有相关", "未提及", "没有提到", "无从得知", "没有这方面的",
]


def judge(case, reply):
    if case["type"] == "refuse":
        return any(m in reply for m in REFUSE_MARKERS)
    kws = [k.lower() for k in case.get("keywords", [])]
    if not kws:
        return False
    hit = sum(1 for k in kws if k in reply.lower())
    return hit >= max(1, int(len(kws) * 0.5) + (len(kws) % 2))


def main(limit=None):
    conn = db.connect(DB)
    with open(TESTSET, "r", encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    if limit:
        cases = cases[:limit]

    results = []
    by_cat = {}
    for c in cases:
        r = retriever.answer(conn, c["question"])
        ok = judge(c, r["answer"])
        row = {"id": c["id"], "category": c["category"], "type": c["type"],
               "question": c["question"], "expected": c["expected"],
               "reply": r["answer"], "refused": r["refused"],
               "intent": r["intent"], "used_ids": [u["id"] for u in r["used"]],
               "ok": ok}
        results.append(row)
        d = by_cat.setdefault(c["category"], [0, 0])
        d[0] += 1 if ok else 0
        d[1] += 1
        print(f"[{c['id']:02d}] {'OK ' if ok else 'FAIL'} ({c['category']}/{c['type']}) {c['question']}")
        print(f"     -> {r['answer'][:100]}")

    total_ok = sum(1 for r in results if r["ok"])
    print("\n=== 汇总 ===")
    for cat, (ok, n) in by_cat.items():
        print(f"{cat:12s} {ok}/{n} = {ok/n*100:.1f}%")
    print(f"{'TOTAL':12s} {total_ok}/{len(results)} = {total_ok/len(results)*100:.1f}%")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"total": len(results), "correct": total_ok,
                   "by_category": {k: {"correct": v[0], "total": v[1]} for k, v in by_cat.items()},
                   "results": results}, f, ensure_ascii=False, indent=2)
    print("结果写入", OUT)
    conn.close()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit)
