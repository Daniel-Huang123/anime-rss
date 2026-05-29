"""蜜柑计划爬虫逻辑单元测试（mock 网络请求）。"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone


def make_feed(entries_days_ago: list[int]):
    """构造 mock feedparser 结果，entries_days_ago 是每个条目距今天数。"""
    now = datetime.now(tz=timezone.utc)
    feed = MagicMock()
    feed.entries = []
    for days in entries_days_ago:
        pub = now - timedelta(days=days)
        pub_struct = pub.timetuple()
        # feedparser entry 是 dict-like，用 .get() 取字段
        # 这里用真实的 dict 来让 entry.get("published_parsed") 正常工作
        entry = {"published_parsed": pub_struct, "title": f"Episode {days}days ago"}
        feed.entries.append(entry)
    return feed


def test_has_recent_resources_with_new_entry():
    from src.scrapers.mikanani import has_recent_resources
    mock_feed = make_feed([3, 10])  # 3天前有更新

    with patch("src.scrapers.mikanani.feedparser.parse", return_value=mock_feed):
        assert has_recent_resources(100, 200, weeks=4) is True


def test_has_recent_resources_with_old_entry():
    from src.scrapers.mikanani import has_recent_resources
    mock_feed = make_feed([60, 90])  # 最近只有2个月前的

    with patch("src.scrapers.mikanani.feedparser.parse", return_value=mock_feed):
        assert has_recent_resources(100, 200, weeks=4) is True


def test_has_recent_resources_empty_feed():
    from src.scrapers.mikanani import has_recent_resources
    mock_feed = MagicMock()
    mock_feed.entries = []

    with patch("src.scrapers.mikanani.feedparser.parse", return_value=mock_feed):
        assert has_recent_resources(100, 200, weeks=4) is False


def test_find_best_rss_uses_priority():
    """优先选择 ANi，跳过 kirara。"""
    from src.scrapers.mikanani import find_best_rss

    subgroups = [
        {"id": 100, "name": "ANi"},
        {"id": 200, "name": "kirara-fansub"},
        {"id": 300, "name": "豌豆字幕组"},
    ]

    with patch("src.scrapers.mikanani._fetch_bangumi_data", return_value={"subgroups": subgroups, "bgm_id": 1}), \
         patch("src.scrapers.mikanani.has_recent_resources", return_value=True):
        result = find_best_rss(999, ["ANi", "kirara"], weeks=4)

    assert result is not None
    assert result["subgroup_name"] == "ANi"
    assert result["subgroup_id"] == 100


def test_find_best_rss_falls_back():
    """ANi 无资源时回退到 kirara。"""
    from src.scrapers.mikanani import find_best_rss

    subgroups = [
        {"id": 100, "name": "ANi"},
        {"id": 200, "name": "kirara-fansub"},
    ]

    def mock_has_resources(bangumi_id, subgroup_id, weeks, use_mirror=False):
        return subgroup_id == 200  # 只有 kirara 有资源

    with patch("src.scrapers.mikanani._fetch_bangumi_data", return_value={"subgroups": subgroups, "bgm_id": 1}), \
         patch("src.scrapers.mikanani.has_recent_resources", side_effect=mock_has_resources):
        result = find_best_rss(999, ["ANi", "kirara"], weeks=4)

    assert result is not None
    assert result["subgroup_name"] == "ANi"
    assert result["subgroup_id"] == 100


def test_find_best_rss_all_fallback():
    """优先组都无资源，回退到任意有资源的组。"""
    from src.scrapers.mikanani import find_best_rss

    subgroups = [
        {"id": 100, "name": "ANi"},
        {"id": 200, "name": "kirara-fansub"},
        {"id": 300, "name": "豌豆字幕组"},
    ]

    def mock_has_resources(bangumi_id, subgroup_id, weeks, use_mirror=False):
        return subgroup_id == 300  # 只有豌豆有资源

    with patch("src.scrapers.mikanani._fetch_bangumi_data", return_value={"subgroups": subgroups, "bgm_id": 1}), \
         patch("src.scrapers.mikanani.has_recent_resources", side_effect=mock_has_resources):
        result = find_best_rss(999, ["ANi", "kirara"], weeks=4)

    assert result is not None
    assert result["subgroup_name"] == "ANi"


def test_find_best_rss_no_resources():
    """所有组都无资源，返回 None。"""
    from src.scrapers.mikanani import find_best_rss

    subgroups = [{"id": 100, "name": "豌豆字幕组"}]

    with patch("src.scrapers.mikanani._fetch_bangumi_data", return_value={"subgroups": subgroups, "bgm_id": 1}), \
         patch("src.scrapers.mikanani.has_recent_resources", return_value=False):
        result = find_best_rss(999, ["ANi", "kirara"], weeks=4)

    assert result is None


def test_match_bangumi_id_via_season_index():
    """bgm API 命中 → season_index 反查得到 bangumi_id。"""
    from src.scrapers.mikanani import match_bangumi_id

    season_index = {555: 1001}  # bgm_id → bangumi_id
    with patch("src.scrapers.mikanani._bgm_canonical_names", return_value=([555], [])):
        bid = match_bangumi_id("某番剧", season_index, "2026Q2")
    assert bid == 1001


def test_match_bangumi_id_title_fallback():
    """bgm 不命中时退回季度标题反查（剥掉季号后缀）。"""
    from src.scrapers.mikanani import match_bangumi_id

    with patch("src.scrapers.mikanani._bgm_canonical_names", return_value=([], [])), \
         patch("src.scrapers.mikanani.load_season_title_index", return_value={"某番剧": 2002}):
        bid = match_bangumi_id("某番剧 第2季", {999: 1}, "2026Q2")
    assert bid == 2002


def test_match_bangumi_id_no_match_returns_none():
    from src.scrapers.mikanani import match_bangumi_id

    with patch("src.scrapers.mikanani._bgm_canonical_names", return_value=([42], [])), \
         patch("src.scrapers.mikanani.load_season_title_index", return_value={}):
        bid = match_bangumi_id("无关番", {555: 1001}, "2026Q2")
    assert bid is None


def test_build_rss_url():
    from src.scrapers.mikanani import build_rss_url
    url = build_rss_url(228, 562)
    assert url == "https://mikanani.me/RSS/Bangumi?bangumiId=228&subgroupid=562"
