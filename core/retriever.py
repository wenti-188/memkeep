"""检索层：意图路由 + token 预算 + 边界控制。"""
import json
import math
import re

from core import llm
from storage import db

PREF_WORDS = ["讨厌", "喜欢", "偏好", "愿意", "接受", "不能", "不想", "爱"]
TIME_WORDS = ["什么时候", "哪天", "几月", "上周", "上个月", "最近", "昨天", "今天", "去年"]
FACT_WORDS = ["哪家", "哪些", "投了", "面了", "什么岗", "哪个岗", "哪所", "什么专业", "多少钱"]

REFUSE_REPLY = "没有相关记录。你还没跟我提过这件事，我不编。"


def route(question):
    q = question.lower()
    if any(w in question for w in PREF_WORDS):
        return "preference"
    if any(w in question for w in TIME_WORDS):
        return "time"
    if any(w in question for w in FACT_WORDS):
        return "fact"
    return "semantic"


def _cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb + 1e-9)


def _rows(conn, status="active"):
    return conn.execute("SELECT * FROM memories WHERE status=?", (status,)).fetchall()


STOP_BITS = (
    "什么", "做过", "哪个", "哪些", "我的", "你的", "是不", "不是", "怎么", "怎样",
    "如何", "多少", "有没有", "是不", "吗", "呢", "的", "了", "过", "我", "你",
    "他", "她", "这", "那", "一些", "哪个", "什么", "告诉",
)


def _keywords(question):
    """中文 2-3 gram + 英文/数字 token，用来跟记忆文本做字面匹配。"""
    keys = set()
    # 英文与数字串
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9._+-]*", question):
        if len(tok) >= 2:
            keys.add(tok.lower())
    # 中文 n-gram
    zh = re.sub(r"[^\u4e00-\u9fa5]", " ", question)
    for seg in zh.split():
        if len(seg) < 2:
            continue
        for n in (2, 3):
            for i in range(len(seg) - n + 1):
                g = seg[i:i + n]
                if any(s in g for s in STOP_BITS):
                    continue
                keys.add(g)
    return keys


def retrieve(conn, question, intent=None, top_k=8, budget=1200, min_score=0.008):
    """三路召回（向量 / 关键词 / 保留分）+ RRF 融合，按意图做类别加权。

    RRF 的好处是三路各取前 40 名再融合，关键词噪声不会把语义正确的条目挤掉。
    """
    from collections import defaultdict

    intent = intent or route(question)
    all_rows = _rows(conn)

    qvec = None
    try:
        qvec = llm.embed(question)
    except Exception:
        qvec = None

    keys = _keywords(question)

    sim_list, key_list = [], []
    base_of = {}
    for r in all_rows:
        text = f"{r['subject']} {r['attribute']} {r['value']}".lower()
        # 3-gram 命中权重更高，减少 2-gram 噪声主导
        kh = 0.0
        for k in keys:
            if k in text:
                kh += 1.0 if len(k) >= 3 else 0.5

        sim = 0.0
        if qvec and r["embedding"]:
            try:
                sim = max(0.0, _cosine(qvec, json.loads(r["embedding"])))
            except Exception:
                sim = 0.0

        base_of[r["id"]] = db.retention_score(r)
        if sim > 0.15:
            sim_list.append((sim, r["id"]))
        if kh > 0:
            key_list.append((kh, r["id"]))

    rrf = defaultdict(float)
    for lst in (sim_list, key_list):
        lst.sort(key=lambda x: x[0], reverse=True)
        for rank, (sc, rid) in enumerate(lst[:15]):
            rrf[rid] += 1.0 / (60.0 + rank)

    row_by_id = {r["id"]: r for r in all_rows}
    scored = []
    for rid, val in rrf.items():
        r = row_by_id[rid]
        cat = r["category"]
        boost = 1.0
        if intent == "preference" and cat in ("preference", "identity", "goal", "relation"):
            boost = 1.15
        elif intent == "time" and cat == "event":
            boost = 1.15
        elif intent == "fact" and cat in ("event", "identity"):
            boost = 1.10
        scored.append((val * boost * (1 + 0.15 * base_of[rid]), r))

    scored.sort(key=lambda x: x[0], reverse=True)

    picked = []
    used = 0
    for score, r in scored:
        if score < min_score:
            break
        if len(picked) >= top_k:
            break
        cost = len(r["value"]) // 2
        if used + cost > budget:
            continue
        picked.append({"id": r["id"], "attribute": r["attribute"], "value": r["value"],
                       "category": r["category"], "score": round(float(score), 3)})
        used += cost

    return picked, intent, bool(picked)


def build_context(picked):
    lines = []
    for p in picked:
        lines.append(f"- {p['attribute']}：{p['value']}")
    return "\n".join(lines)


ANSWER_PROMPT = """你是记忆问答助手。下面是关于用户的历史记忆条目。

记忆：
{memory}

要求：
1. 只使用上面的记忆回答，不要补充记忆里没有的事实，不要编造。
2. **必须作答**：从记忆里挑出与问题最相关的条目，据此给出答案，即使只是部分相关。
3. 回答一两句话，必须说清具体对象，不要只给"是的""不喜欢"这种孤立判断。
4. 不要复述"根据记忆/根据你之前说的"这类套话。
5. 若多条互相矛盾，指出哪条更新、哪条更早。

问题：{question}
"""


def answer(conn, question, budget=1200):
    picked, intent, hit = retrieve(conn, question, budget=budget)
    if not hit:
        return {"answer": REFUSE_REPLY, "intent": intent, "used": [], "refused": True}

    ctx = build_context(picked)
    prompt = ANSWER_PROMPT.format(memory=ctx, question=question)
    reply = llm.chat([{"role": "user", "content": prompt}], temperature=0.0, num_predict=256).strip()
    if not reply:
        reply = REFUSE_REPLY
    return {"answer": reply, "intent": intent, "used": picked, "refused": False}
