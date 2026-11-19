"""检索层：意图路由、关键词切分、拒答边界、分数排序。"""
import json

import pytest

from core import retriever


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """检索测试不依赖模型：embed 固定返回，chat 固定返回。"""
    monkeypatch.setattr(retriever.llm, "embed", lambda text, timeout=60: [0.1] * 1024)
    monkeypatch.setattr(retriever.llm, "chat", lambda *a, **k: "固定回答")


def test_route_preference():
    assert retriever.route("我讨厌什么工作？") == "preference"


def test_route_time():
    assert retriever.route("上周投了哪家？") == "time"


def test_route_fact():
    assert retriever.route("我投了哪些公司？") == "fact"


def test_route_default_semantic():
    assert retriever.route("搜狐那件事后来怎样了") == "semantic"


def test_keywords_contains_english_token():
    keys = retriever._keywords("我在学 PyTorch 和 408")
    assert "pytorch" in keys


def test_keywords_contains_chinese_ngram():
    keys = retriever._keywords("搜狐面试结果")
    assert any(len(k) == 3 and "搜狐" in k for k in keys)


def test_empty_db_refuses(tmp_db_conn):
    res = retriever.answer(tmp_db_conn, "我养宠物吗？")
    assert res["refused"] is True
    assert res["used"] == []


def test_answer_uses_memory(tmp_db_conn, seed_memory):
    seed_memory(tmp_db_conn, "主攻方向", "计算机视觉", "preference")
    res = retriever.answer(tmp_db_conn, "我喜欢什么方向？")
    assert res["refused"] is False
    assert res["used"]
    assert "计算机视觉" in res["answer"] or res["used"][0]["value"] == "计算机视觉"
