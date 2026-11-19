"""保留分公式：权重、频率、衰减三部分各测一遍，防止改系数时悄悄跑偏。"""
from datetime import datetime, timedelta, timezone

from app.services.scoring import retention_score


def _row(category="event", access_count=0, days_ago=0):
    now = datetime.now(timezone.utc)
    return {
        "category": category,
        "access_count": access_count,
        "last_access": (now - timedelta(days=days_ago)).isoformat(),
    }


def test_identity_decays_slower_than_event():
    """同样放 30 天，身份分必须高于事件分。"""
    assert retention_score(_row("identity", 0, 30)) > retention_score(_row("event", 0, 30))


def test_more_access_raises_score():
    assert retention_score(_row("preference", 10, 0)) > retention_score(_row("preference", 0, 0))


def test_score_in_range():
    """保留分不是概率，可大于 1（访问次数带来 1+log 增益）。上限按公式推导。"""
    for cat in ("identity", "preference", "goal", "relation", "event"):
        val = retention_score(_row(cat, 3, 7))
        assert 0 < val <= 3.0, f"{cat} 得分越界：{val}"


def test_fresh_event_near_base():
    """刚发生的 event 基础权重 0.6，访问 0 次时应接近 0.6。"""
    val = retention_score(_row("event", 0, 0))
    assert 0.55 <= val <= 0.62


def test_long_idle_approaches_zero():
    val = retention_score(_row("event", 0, 3650))
    assert val < 0.01


def test_unknown_category_uses_default():
    row = _row("unknown_kind", 0, 0)
    assert retention_score(row) > 0
