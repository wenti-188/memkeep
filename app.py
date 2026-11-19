"""MemKeep Web 界面：左侧对话，右侧记忆面板。"""
import os
import re
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify, render_template

from core import retriever, writer
from storage import db

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "storage", "memory.db")


def conn():
    return db.connect(DB_PATH)


@app.route("/")
def index():
    return render_template("index.html")


QUESTION_RE = re.compile(r"[？?]|吗|什么|为什么|怎么|哪|多少|是否|谁|几")


@app.post("/api/chat")
def api_chat():
    payload = request.get_json(force=True, silent=True) or {}
    msg = (payload.get("message") or "").strip()
    if not msg:
        return jsonify({"error": "empty message"}), 400

    c = conn()
    try:
        r = retriever.answer(c, msg)
        # 只有陈述句才写入记忆；问句不抽事实，否则会把"用户在问什么"当成记忆
        written = []
        if len(msg) <= 200 and not QUESTION_RE.search(msg):
            written = writer.ingest_dialogue(c, f"用户：{msg}", session_id="web")
        return jsonify({
            "answer": r["answer"],
            "intent": r["intent"],
            "used": r["used"],
            "refused": r["refused"],
            "written": [{"action": w["action"], "attr": w.get("attr"), "value": w.get("value")} for w in written],
        })
    finally:
        c.close()


@app.get("/api/memories")
def api_memories():
    c = conn()
    try:
        rows = db.list_memories(c)
        stats = db.stats(c)
        return jsonify({"memories": rows, "stats": stats})
    finally:
        c.close()


@app.delete("/api/memories/<int:mid>")
def api_delete(mid):
    c = conn()
    try:
        c.execute("UPDATE memories SET status='deleted' WHERE id=?", (mid,))
        c.commit()
        return jsonify({"ok": True})
    finally:
        c.close()


@app.get("/api/conflicts")
def api_conflicts():
    c = conn()
    try:
        rows = c.execute("SELECT * FROM conflicts ORDER BY id DESC LIMIT 30").fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        c.close()


PORT = int(os.environ.get("MEMKEEP_PORT", "5051"))

if __name__ == "__main__":
    print(f"MemKeep 启动: http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False)
