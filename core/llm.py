"""Ollama 调用封装：只用标准库 urllib，避免依赖问题。"""
import json
import urllib.request
import urllib.error

OLLAMA_BASE = "http://localhost:11434"
CHAT_MODEL = "qwen2.5:7b"
EMBED_MODEL = "bge-m3"


def _post(path, payload, timeout=180):
    req = urllib.request.Request(
        f"{OLLAMA_BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat(messages, temperature=0.1, num_predict=512):
    """非流式对话，返回文本。"""
    payload = {
        "model": CHAT_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    data = _post("/api/chat", payload)
    return data.get("message", {}).get("content", "")


def embed(text, timeout=60):
    """返回向量（list[float]）。"""
    data = _post("/api/embeddings", {"model": EMBED_MODEL, "prompt": text}, timeout=timeout)
    return data.get("embedding", [])


def health():
    """检查 Ollama 是否可用，返回 (ok, 说明)。"""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        with urllib.request.urlopen(req, timeout=10) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name", "") for m in tags.get("models", [])]
        ok = any(CHAT_MODEL in n for n in names) and any(EMBED_MODEL in n for n in names)
        return ok, names
    except Exception as e:
        return False, str(e)
