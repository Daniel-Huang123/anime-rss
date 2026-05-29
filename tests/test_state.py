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


def test_update_subscription_cover_fills_empty_only(tmp_state):
    from src.utils.state import (
        add_subscription,
        get_subscriptions,
        update_subscription_cover,
    )

    # recovered_local 风格：缺 bangumi_id / cover_url
    add_subscription("2026Q2", "番剧A", 0, 0, "local", "")

    changed = update_subscription_cover(
        "2026Q2", "番剧A", bangumi_id=777, cover_url="https://x/c.jpg"
    )
    assert changed is True

    sub = get_subscriptions("2026Q2")["2026Q2"][0]
    assert sub["bangumi_id"] == 777
    assert sub["cover_url"] == "https://x/c.jpg"

    # 已有值时不覆盖，也不报改动
    changed2 = update_subscription_cover(
        "2026Q2", "番剧A", bangumi_id=888, cover_url="https://y/d.jpg"
    )
    assert changed2 is False
    sub2 = get_subscriptions("2026Q2")["2026Q2"][0]
    assert sub2["bangumi_id"] == 777
    assert sub2["cover_url"] == "https://x/c.jpg"


def test_update_subscription_cover_missing_title_noop(tmp_state):
    from src.utils.state import update_subscription_cover

    assert update_subscription_cover("2026Q2", "不存在", bangumi_id=1) is False


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


def test_sync_local_subscriptions_detects_quarter_and_fallback(tmp_state, tmp_path, monkeypatch):
    from src.utils.state import get_subscriptions, sync_local_subscriptions
    import src.utils.season as season_module

    monkeypatch.setattr(season_module, "current_quarter", lambda: "2026Q2")

    media_root = tmp_path / "media"
    (media_root / "2025Q4" / "番剧A").mkdir(parents=True, exist_ok=True)
    (media_root / "番剧B").mkdir(parents=True, exist_ok=True)
    (media_root / "2025Q4" / "番剧A" / "01.mkv").write_bytes(b"x")
    (media_root / "番剧B" / "02.mp4").write_bytes(b"x")

    added = sync_local_subscriptions(media_root)
    assert added == 2

    subs = get_subscriptions()
    assert any(s["title"] == "番剧A" for s in subs["2025Q4"])
    assert any(s["title"] == "番剧B" for s in subs["2026Q2"])


def test_sync_local_subscriptions_is_incremental(tmp_state, tmp_path, monkeypatch):
    from src.utils.state import add_subscription, get_subscriptions, sync_local_subscriptions
    import src.utils.season as season_module

    monkeypatch.setattr(season_module, "current_quarter", lambda: "2026Q2")

    add_subscription("2025Q4", "番剧A", 123, 1, "ANi", "http://rss")

    media_root = tmp_path / "media"
    (media_root / "2025Q4" / "番剧A").mkdir(parents=True, exist_ok=True)
    (media_root / "2025Q4" / "番剧C").mkdir(parents=True, exist_ok=True)
    (media_root / "2025Q4" / "番剧A" / "01.mkv").write_bytes(b"x")
    (media_root / "2025Q4" / "番剧C" / "01.mkv").write_bytes(b"x")

    added = sync_local_subscriptions(media_root)
    assert added == 1

    subs = get_subscriptions("2025Q4")["2025Q4"]
    assert any(s["title"] == "番剧A" and s["subgroup_name"] == "ANi" for s in subs)
    assert any(s["title"] == "番剧C" and s.get("recovered_local") is True for s in subs)


def test_enrich_recovered_subscriptions_from_rules_by_path(tmp_state):
    from src.utils.state import enrich_recovered_subscriptions_from_rules, get_subscriptions, sync_local_subscriptions

    media_root = tmp_state.parent / "media"
    (media_root / "2026Q2" / "番剧A").mkdir(parents=True, exist_ok=True)
    (media_root / "2026Q2" / "番剧A" / "01.mkv").write_bytes(b"x")
    sync_local_subscriptions(media_root)

    rules = {
        "2026Q2/番剧A": {
            "affectedFeeds": [
                "https://mikanani.me/RSS/Bangumi?bangumiId=999&subgroupid=1"
            ]
        }
    }
    changed = enrich_recovered_subscriptions_from_rules(rules)
    assert changed == 1

    sub = get_subscriptions("2026Q2")["2026Q2"][0]
    assert sub["rss_url"].startswith("https://mikanani.me/RSS/Bangumi")
    assert sub["bangumi_id"] == 999


def test_enrich_recovered_subscriptions_from_rules_by_title_fallback(tmp_state):
    from src.utils.state import enrich_recovered_subscriptions_from_rules, get_subscriptions, sync_local_subscriptions

    media_root = tmp_state.parent / "media"
    (media_root / "2026Q2" / "番剧B").mkdir(parents=True, exist_ok=True)
    (media_root / "2026Q2" / "番剧B" / "01.mkv").write_bytes(b"x")
    sync_local_subscriptions(media_root)

    rules = {
        "2025Q4/番剧B": {
            "affectedFeeds": [
                "https://mikanani.me/RSS/Bangumi?bangumiId=111&subgroupid=1"
            ]
        },
        "2026Q2/番剧B": {
            "affectedFeeds": [
                "https://mikanani.me/RSS/Bangumi?bangumiId=222&subgroupid=1"
            ]
        },
    }
    changed = enrich_recovered_subscriptions_from_rules(rules)
    assert changed == 1

    sub = get_subscriptions("2026Q2")["2026Q2"][0]
    assert sub["rss_url"].endswith("bangumiId=222&subgroupid=1")
    assert sub["bangumi_id"] == 222


def test_sync_from_folders_detects_subgroup(tmp_state, tmp_path, monkeypatch):
    from src.utils.state import get_subscriptions, sync_local_subscriptions_from_folders
    from src.utils.file_parser import AnimeFolder, ParsedAnime
    import src.utils.season as season_module

    monkeypatch.setattr(season_module, "current_quarter", lambda: "2026Q2")

    root = tmp_path / "media"
    (root / "2026Q2" / "番剧X").mkdir(parents=True, exist_ok=True)
    f1 = root / "2026Q2" / "番剧X" / "01.mkv"
    f2 = root / "2026Q2" / "番剧X" / "02.mkv"
    f1.write_bytes(b"x")
    f2.write_bytes(b"x")
    eps = [
        ParsedAnime(file_path=f1, title="番剧X", episode="1", subgroup="ANi"),
        ParsedAnime(file_path=f2, title="番剧X", episode="2", subgroup="ANi"),
    ]
    folder = AnimeFolder(title="番剧X", episodes=eps)

    added = sync_local_subscriptions_from_folders(root, [folder])
    assert added == 1
    sub = get_subscriptions("2026Q2")["2026Q2"][0]
    assert sub["subgroup_name"] == "ANi"
    assert sub["recovered_local"] is True


def test_sync_from_folders_backfills_subgroup_on_existing_local(tmp_state, tmp_path, monkeypatch):
    from src.utils.state import get_subscriptions, sync_local_subscriptions_from_folders
    from src.utils.file_parser import AnimeFolder, ParsedAnime
    import src.utils.season as season_module

    monkeypatch.setattr(season_module, "current_quarter", lambda: "2026Q2")

    # 预置一条旧的 recovered_local（subgroup_name="local"）
    raw = json.loads(tmp_state.read_text(encoding="utf-8"))
    raw["subscriptions"]["2026Q2"] = [{
        "title": "番剧Y", "bangumi_id": 0, "subgroup_id": 0,
        "subgroup_name": "local", "rss_url": "", "qbt_feed_path": "2026Q2/番剧Y",
        "added_at": "2026-05-29", "cover_url": None, "bgm_id": None,
        "recovered_local": True,
    }]
    tmp_state.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    root = tmp_path / "media"
    (root / "2026Q2" / "番剧Y").mkdir(parents=True, exist_ok=True)
    f1 = root / "2026Q2" / "番剧Y" / "01.mkv"
    f1.write_bytes(b"x")
    folder = AnimeFolder(
        title="番剧Y",
        episodes=[ParsedAnime(file_path=f1, title="番剧Y", episode="1", subgroup="kirara")],
    )

    added = sync_local_subscriptions_from_folders(root, [folder])
    assert added == 0  # 已存在，不新增
    sub = get_subscriptions("2026Q2")["2026Q2"][0]
    assert sub["subgroup_name"] == "kirara"  # 已回填


def test_sync_local_subscriptions_skips_dev_dirs(tmp_state):
    from src.utils.state import get_subscriptions, sync_local_subscriptions

    media_root = tmp_state.parent / "media"
    (media_root / ".venv" / "lib").mkdir(parents=True, exist_ok=True)
    (media_root / ".venv" / "lib" / "junk.ts").write_bytes(b"x")
    (media_root / "2026Q2" / "番剧D").mkdir(parents=True, exist_ok=True)
    (media_root / "2026Q2" / "番剧D" / "01.mkv").write_bytes(b"x")

    added = sync_local_subscriptions(media_root)
    assert added == 1
    subs = get_subscriptions("2026Q2")["2026Q2"]
    assert any(s["title"] == "番剧D" for s in subs)
    assert all(s["title"] != ".venv" for s in subs)


def test_sync_local_subscriptions_prunes_bad_recovered_entries(tmp_state):
    from src.utils.state import get_subscriptions, sync_local_subscriptions

    raw = json.loads(tmp_state.read_text(encoding="utf-8"))
    raw["subscriptions"]["2026Q2"] = [
        {
            "title": ".venv",
            "bangumi_id": 0,
            "subgroup_id": 0,
            "subgroup_name": "local",
            "rss_url": "",
            "qbt_feed_path": "2026Q2/.venv",
            "added_at": "2026-05-29",
            "cover_url": None,
            "bgm_id": None,
            "recovered_local": True,
        }
    ]
    tmp_state.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    media_root = tmp_state.parent / "media"
    (media_root / "2026Q2" / "番剧E").mkdir(parents=True, exist_ok=True)
    (media_root / "2026Q2" / "番剧E" / "01.mkv").write_bytes(b"x")
    sync_local_subscriptions(media_root)

    subs = get_subscriptions("2026Q2")["2026Q2"]
    titles = {s["title"] for s in subs}
    assert ".venv" not in titles
    assert "番剧E" in titles
