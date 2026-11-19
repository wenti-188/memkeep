"""冒烟测试：起一个临时 uvicorn，逐个请求关键接口，全部通过才算骨架 OK。"""
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

PORT = 5052
PY = sys.executable


def get(url, method="GET", body=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def main():
    env = {"MEMKEEP_PORT": str(PORT), "PYTHONUTF8": "1"}
    import os

    full_env = os.environ.copy()
    full_env.update(env)
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=r"C:\项目\MemKeep",
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    base = f"http://127.0.0.1:{PORT}"
    ok = False
    for _ in range(40):
        st, _raw = get(base + "/health")
        if st == 200:
            ok = True
            break
        time.sleep(0.5)

    results = []
    if not ok:
        results.append(("startup", -1, "服务未在 20s 内就绪"))
    else:
        for name, url, method, body in [
            ("health", "/health", "GET", None),
            ("metrics", "/metrics", "GET", None),
            ("memories", "/api/v1/memories?limit=5", "GET", None),
            ("conflicts", "/api/v1/conflicts?limit=5", "GET", None),
            ("openapi", "/openapi.json", "GET", None),
            ("chat", "/api/v1/chat", "POST", {"message": "我喜欢什么技术方向？"}),
        ]:
            st, raw = get(base + url, method, body)
            results.append((name, st, raw[:220]))

    print("=" * 60)
    for name, st, raw in results:
        print(f"[{st}] {name}: {raw}")
    print("=" * 60)

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001
        proc.kill()


if __name__ == "__main__":
    main()
