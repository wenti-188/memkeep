"""Ollama 调用封装：超时、重试、明确的失败信号。只用标准库。"""
import json
import os
import time
import urllib.error
import urllib.request

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://127.0.0.1:11434")
CHAT_MODEL = os.environ.get("MEMKEEP_CHAT_MODEL", "qwen2.5:7b")
EMBED_MODEL = os.environ.get("MEMKEEP_EMBED_MODEL", "bge-m3")
TIMEOUT = float(os.environ.get("MEMKEEP_LLM_TIMEOUT", "60"))
RETRIES = int(os.environ.get("MEMKEEP_LLM_RETRIES", "2"))


class LLMError(RuntimeError):
    """模型不可用。上层据此降级，而不是把异常抛到用户面前。"""


def _post(path, payload, timeout=None, retries=None):
    timeout = timeout or TIMEOUT
    retries = RETRIES if retries is None else retries
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{OLLAMA_BASE}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(0.4 * (2 ** attempt))  # 指数退避，避免上游被打穿
    raise LLMError(f"{path} 失败 {retries + 1} 次：{last_err}")


def chat(messages, temperature=0.1, num_predict=512):
    payload = {
        "model": CHAT_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    data = _post("/api/chat", payload)
    return data.get("message", {}).get("content", "")


def embed(text, timeout=60):
    data = _post("/api/embeddings", {"model": EMBED_MODEL, "prompt": text}, timeout=timeout)
    return data.get("embedding", [])


def health():
    """返回 (ok, 说明)。"""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        with urllib.request.urlopen(req, timeout=10) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name", "") for m in tags.get("models", [])]
        ok = any(CHAT_MODEL in n for n in names) and any(EMBED_MODEL in n for n in names)
        return ok, names
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
