"""三档对照：全历史直塞 / 纯向量 top-k / MemKeep 混合检索。

同一批题、同一个判分器，只换"给模型看什么"，用来回答"这套设计到底值不值"。
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import llm, retriever  # noqa: E402
from storage import db  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTSET = os.path.join(ROOT, "eval", "testset.json")
OUT = os.path.join(ROOT, "eval", "baseline_result.json")

PROMPT = """你是记忆问答助手。下面是关于用户的历史记忆条目。

记忆：
{memory}

要求：只使用上面的记忆回答，不要编造；必须给出具体对象；一两句话。

问题：{question}
"""


def judge(case, reply):
    if case["type"] == "refuse":
        from eval.run_eval import REFUSE_MARKERS

        return any(m in reply for m in REFUSE_MARKERS)
    kws = [k.lower() for k in case.get("keywords", [])]
    if not kws:
        return False
    hit = sum(1 for k in kws if k in reply.lower())
    return hit >= max(1, int(len(kws) * 0.5) + (len(kws) % 2))


def _all_rows(conn):
    return conn.execute("SELECT * FROM memories WHERE status='active'").fetchall()


def _context(rows, limit_chars=2400):
    lines = [f"- {r['attribute']}：{r['value']}" for r in rows]
    return "\n".join(lines)[:limit_chars]


def _cos(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb + 1e-9)


def answer_full(conn, q):
    """基线 A：把所有活跃记忆无差别塞进上下文。"""
    rows = _all_rows(conn)
    ctx = _context(rows, 3000)
    reply = llm.chat([{"role": "user", "content": PROMPT.format(memory=ctx, question=q)}], temperature=0.0, num_predict=256)
    return reply, len(ctx)


def answer_vec(conn, q, k=5):
    """基线 B：只按向量相似度取 top-k，不看类别、不看保留分。"""
    rows = _all_rows(conn)
    qv = llm.embed(q)
    scored = []
    for r in rows:
        emb = None
        if r["embedding"]:
            try:
                emb = json.loads(r["embedding"])
            except Exception:  # noqa: BLE001
                emb = None
        scored.append((_cos(qv, emb), r))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [r for _, r in scored[:k]]
    ctx = _context(picked, 1200)
    reply = llm.chat([{"role": "user", "content": PROMPT.format(memory=ctx, question=q)}], temperature=0.0, num_predict=256)
    return reply, len(ctx)


def answer_memkeep(conn, q):
    res = retriever.answer(conn, q)
    ctx_len = sum(len(u["value"]) for u in res["used"])
    return res["answer"], ctx_len


def run(limit=None):
    conn = db.connect(os.path.join(ROOT, "storage", "memory.db"))
    with open(TESTSET, "r", encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    if limit:
        cases = cases[:limit]

    arms = {
        "A_全历史直塞": answer_full,
        "B_纯向量top5": answer_vec,
        "C_MemKeep混合": answer_memkeep,
    }
    summary = {}
    details = []

    for name, fn in arms.items():
        ok = 0
        total_lat = 0
        ctx_chars = 0
        rows_out = []
        for c in cases:
            t0 = time.perf_counter()
            try:
                reply, c_len = fn(conn, c["question"])
            except Exception as exc:  # noqa: BLE001
                reply, c_len = f"ERROR {exc}", 0
            lat = int((time.perf_counter() - t0) * 1000)
            good = judge(c, reply)
            ok += 1 if good else 0
            total_lat += lat
            ctx_chars += c_len
            rows_out.append({"id": c["id"], "ok": good, "reply": reply[:120], "latency_ms": lat, "ctx_chars": c_len})
            print(f"{name} [{c['id']:02d}] {'OK' if good else 'FAIL'} {lat}ms")
        n = len(cases)
        summary[name] = {
            "accuracy": round(ok / n * 100, 1),
            "correct": ok,
            "total": n,
            "avg_latency_ms": int(total_lat / n),
            "avg_ctx_chars": int(ctx_chars / n),
        }
        details.append({"arm": name, "cases": rows_out})
        print(f"== {name}: {ok}/{n} = {ok/n*100:.1f}%, {int(total_lat/n)}ms, ctx {int(ctx_chars/n)} 字符")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"limit": limit, "summary": summary, "details": details}, f, ensure_ascii=False, indent=2)
    print("写入", OUT)
    conn.close()
    return summary


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(lim)
