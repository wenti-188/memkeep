"""把种子对话灌入记忆库。"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import writer
from storage import db

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "memory.db")
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval", "seed_dialogues.json")

if os.path.exists(DB):
    os.remove(DB)

conn = db.connect(DB)
total = writer.ingest_seeds(conn, SEED, verbose=True)
print(f"\n共写入 {total} 条")
print("统计:", db.stats(conn))
conn.close()
