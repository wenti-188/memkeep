"""写入流程：对话 → 抽取 → 冲突判定 → 入库。"""
import os
import re
from datetime import datetime, timezone

from core import extractor, llm
from storage import db


def _set_created_at(conn, mem_id, date_str):
    if not date_str:
        return
    # 只保留日期部分并补时区，避免与 now 比较出错
    try:
        d = datetime.fromisoformat(date_str)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc).astimezone()
    except Exception:
        return
    conn.execute("UPDATE memories SET created_at=? WHERE id=?", (d.isoformat(timespec="seconds"), mem_id))
    conn.commit()


def _merge_same_batch(items, date):
    """同一段对话的多次采样结果先合并：同属性不互判冲突，而是合并语义。"""
    by_attr = {}
    for it in items:
        subject, attr, val = it["subject"], it["attribute"], it["value"]
        key = (subject, attr)
        if key not in by_attr:
            by_attr[key] = it
            continue
        prev = by_attr[key]
        a, b = prev["value"], it["value"]
        # 一条几乎包含另一条 → 留更长的
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        if short[:8] in long_:
            if len(b) >= len(a):
                by_attr[key] = it
            continue
        # 同一属性不同侧面 → 合并成一条，不判冲突
        merged_val = f"{a}；{b}"
        keep = dict(prev)
        keep["value"] = merged_val
        keep["confidence"] = max(prev["confidence"], it["confidence"])
        by_attr[key] = keep

    out = []
    for (subject, attr), it in by_attr.items():
        val = it["value"]
        if it["category"] == "event" and date and not val.startswith("["):
            val = f"[{date}] {val}"
        it = dict(it)
        it["value"] = val
        it["attribute"] = attr
        out.append(it)
    return out


def ingest_dialogue(conn, conversation, session_id=None, date=None, verbose=False):
    """把一段对话写入记忆库，返回处理明细。"""
    items = _merge_same_batch(extractor.extract(conversation), date)
    results = []

    for it in items:
        subject, attr, val = it["subject"], it["attribute"], it["value"]

        # 1) 完全同值 → 视为复述，只增访问次数
        same = conn.execute(
            "SELECT id FROM memories WHERE subject=? AND attribute=? AND value=? AND status='active'",
            (subject, attr, val),
        ).fetchone()
        if same:
            results.append({"action": "repeat", "id": same["id"], "attr": attr, "value": val})
            continue

        # 2) 查冲突
        conflicts = db.find_conflicts(conn, subject, attr, val)
        try:
            emb = llm.embed(f"{attr}：{val}")
        except Exception:
            emb = None
        mid = db.add_memory(conn, subject, attr, val,
                            category=it["category"], confidence=it["confidence"],
                            source_text=conversation[-200:], session_id=session_id,
                            embedding=emb)
        _set_created_at(conn, mid, date)

        if conflicts:
            old = conflicts[0]
            resolution, reason = extractor.judge_conflict(
                attr, old["value"], old["created_at"] or "", val, date or ""
            )
            if resolution == "update":
                # 覆盖前把旧值的关键信息保留进新值，避免"为什么/原来是什么"永久丢失
                # 旧值里已有的"（此前：…）"要剥掉，否则每次 update 都会套一层
                old_clean = re.sub(r"（此前：.*$", "", old["value"]).strip()
                merged = f"{val}（此前：{old_clean}）" if old_clean and old_clean not in val else val
                conn.execute("UPDATE memories SET value=? WHERE id=?", (merged, mid))
                conn.commit()
                val = merged
                db.supersede(conn, old["id"], mid, reason)
                action = "update"
            else:
                db.log_coexist(conn, old["id"], mid, reason)
                action = "coexist"
            results.append({"action": action, "id": mid, "old_id": old["id"],
                            "attr": attr, "old": old["value"], "value": val, "reason": reason})
        else:
            results.append({"action": "new", "id": mid, "attr": attr, "value": val})

        if verbose:
            print(f"  [{results[-1]['action']}] {attr} = {val}")

    return results


def ingest_seeds(conn, seed_path, verbose=True):
    """批量灌入种子对话。"""
    import json
    with open(seed_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    total = 0
    for d in data.get("dialogues", []):
        convo = "\n".join(d.get("turns", []))
        if verbose:
            print(f"--- {d['id']} ({d.get('date','')}) ---")
        res = ingest_dialogue(conn, convo, session_id=d["id"], date=d.get("date"), verbose=verbose)
        total += len(res)
    return total
