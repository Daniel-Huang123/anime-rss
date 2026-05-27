"""state.json 读写单元测试（使用临时文件）。"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    """将 STATE_FILE 重定向到临时目录。"""
    state_file = tmp_path / "state.json"
    state_file.write_text('{"subscriptions": {}, "cleanup_log": []}', encoding="utf-8")

    import src.utils.state as state_module
    monkeypatch.setattr(state_module, "STATE_FILE", state_file)
    return state_file


def test_add_and_get_subscription(tmp_state):
    from src.utils.state import add_subscription, get_subscriptions, is_subscribed

    entry = add_subscription(
        quarter="2026Q1",
        title="测试番剧",
        bangumi_id=123,
        subgroup_id=456,
        subgroup_name="ANi",
        rss_url="https://mikanani.me/RSS/Bangumi?bangumiId=123&subgroupid=456",
    )

    assert entry["title"] == "测试番剧"
    assert entry["subgroup_name"] == "ANi"
    assert entry["qbt_feed_path"] == "2026Q1/测试番剧"

    subs = get_subscriptions("2026Q1")
    assert len(subs["2026Q1"]) == 1

    assert is_subscribed("2026Q1", "测试番剧") is True
    assert is_subscribed("2026Q1", "不存在的番") is False


def test_remove_subscription(tmp_state):
    from src.utils.state import add_subscription, remove_subscription, is_subscribed

    add_subscription("2026Q1", "番剧A", 1, 1, "ANi", "http://rss1")
    add_subscription("2026Q1", "番剧B", 2, 2, "kirara", "http://rss2")

    removed = remove_subscription("2026Q1", "番剧A")
    assert removed is True
    assert is_subscribed("2026Q1", "番剧A") is False
    assert is_subscribed("2026Q1", "番剧B") is True


def test_add_subscription_update_existing(tmp_state):
    """同一季度同一标题重复添加时应更新而非重复。"""
    from src.utils.state import add_subscription, get_subscriptions

    add_subscription("2026Q1", "番剧A", 1, 1, "ANi", "http://rss1")
    add_subscription("2026Q1", "番剧A", 1, 2, "kirara", "http://rss2")  # 更新

    subs = get_subscriptions("2026Q1")["2026Q1"]
    assert len(subs) == 1
    assert subs[0]["subgroup_name"] == "kirara"


def test_get_quarters_to_cleanup(tmp_state, monkeypatch):
    from src.utils.state import add_subscription, get_quarters_to_cleanup
    import src.utils.season as season_module

    # 模拟当前季度为 2026Q3
    monkeypatch.setattr(season_module, "current_quarter", lambda: "2026Q3")

    add_subscription("2025Q1", "旧番1", 1, 1, "ANi", "http://r1")
    add_subscription("2026Q1", "旧番2", 2, 2, "ANi", "http://r2")
    add_subscription("2026Q2", "近期番", 3, 3, "ANi", "http://r3")
    add_subscription("2026Q3", "本季番", 4, 4, "ANi", "http://r4")

    # keep=2 → 保留 2026Q2 和 2026Q3，其他应被清理
    to_clean = get_quarters_to_cleanup(2)
    assert "2025Q1" in to_clean
    assert "2026Q1" in to_clean
    assert "2026Q2" not in to_clean
    assert "2026Q3" not in to_clean


def test_cleanup_log(tmp_state):
    from src.utils.state import log_cleanup, get_cleanup_log

    log_cleanup("2025Q1", 5)
    log_cleanup("2025Q2", 3)

    logs = get_cleanup_log()
    assert len(logs) == 2
    assert logs[0]["quarter"] == "2025Q1"
    assert logs[0]["count"] == 5
