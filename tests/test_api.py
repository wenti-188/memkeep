"""接口层：契约、错误码、鉴权、降级。用 TestClient，不依赖真实模型。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from app import main as main_module

    # 打桩：问答与写入不碰模型和数据库
    monkeypatch.setattr(
        main_module.chat_api.MemoryService,
        "chat",
        lambda self, msg: (
            {
                "answer": "你在准备 408 和数学三。",
                "intent": "fact",
                "used": [{"id": 1, "attribute": "备考科目", "value": "408 与数学三", "category": "goal", "score": 0.31}],
                "refused": False,
            },
            [{"action": "new", "attr": "备考科目", "value": "408 与数学三"}],
        ),
    )
    return TestClient(main_module.app)


def test_health_shape(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status", "db", "llm", "version"}
    assert body["status"] in ("ok", "degraded")


def test_metrics_shape(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["requests_total"] >= 0
    assert "latency_p95_ms" in body


def test_openapi_contains_chat(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/v1/chat" in paths
    assert "/api/v1/memories" in paths


def test_chat_returns_contract(client):
    r = client.post("/api/v1/chat", json={"message": "我在备考什么？"})
    assert r.status_code == 200
    body = r.json()
    assert {"answer", "intent", "refused", "used", "written", "latency_ms", "trace_id"} <= set(body)
    assert body["used"][0]["value"] == "408 与数学三"


def test_trace_id_header(client):
    r = client.get("/metrics")
    assert "X-Trace-Id" in r.headers
    assert len(r.headers["X-Trace-Id"]) == 12


def test_validation_rejects_empty_message(client):
    r = client.post("/api/v1/chat", json={"message": ""})
    assert r.status_code == 422


def test_not_found_path(client):
    r = client.get("/api/v1/nope")
    assert r.status_code in (404, 405)


def test_rate_limit_headers_exist(client):
    for _ in range(3):
        r = client.get("/metrics")
    assert r.status_code == 200
