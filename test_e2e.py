"""端到端测试：直接打本地 HTTP 接口，验证 UTF-8 与检索链路。"""
import json
import urllib.request

BASE = "http://127.0.0.1:5051"


def post(path, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


questions = [
    "搜狐二面为什么没过？",
    "我喜欢什么颜色？",
    "我养宠物吗？",
]

for q in questions:
    r = post("/api/chat", {"message": q})
    print("=" * 60)
    print("Q:", q)
    print("A:", r.get("answer"))
    print("used:", [u["attribute"] for u in r.get("used", [])])
    print("written:", r.get("written"))

m = get("/api/memories")
print("=" * 60)
print("库内条目:", m["stats"]["total"], m["stats"]["by_category"])
