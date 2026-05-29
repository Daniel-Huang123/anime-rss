from __future__ import annotations


def test_plan_cover_sync_splits_current_and_other(monkeypatch):
    import gui.services.cover_sync_service as svc

    monkeypatch.setattr(svc, "current_quarter", lambda: "2026Q2")
    monkeypatch.setattr(
        svc,
        "get_subscriptions",
        lambda: {
            "2026Q2": [{"title": "当季番"}],
            "2025Q4": [{"title": "旧番"}],
        },
    )

    cur_q, cur_titles, others = svc.plan_cover_sync(["当季番", "旧番", "未知番"])
    assert cur_q == "2026Q2"
    # 当季番 + 无订阅记录的「未知番」都归到当前季度
    assert set(cur_titles) == {"当季番", "未知番"}
    assert others == {"2025Q4": ["旧番"]}


def test_sync_titles_covers_matches_and_persists(monkeypatch, tmp_path):
    import gui.services.cover_sync_service as svc

    # 无订阅元数据，但当季 season_index 已缓存 → 用 match_bangumi_id 精确匹配
    monkeypatch.setattr(svc, "get_subscriptions", lambda _q=None: {"2026Q2": [{"title": "番剧A", "bangumi_id": 0, "cover_url": ""}]})
    monkeypatch.setattr(svc, "load_season_index_cached", lambda quarter, use_mirror=False: {1: 2})
    monkeypatch.setattr(svc, "get_cover_path", lambda title, bid=None: None)
    monkeypatch.setattr(svc, "fetch_cover_from_url", lambda *a, **k: None)
    monkeypatch.setattr(svc, "match_bangumi_id", lambda *a, **k: 2002)

    cover_file = tmp_path / "id_2002.jpg"
    cover_file.write_bytes(b"cover-A")
    monkeypatch.setattr(svc, "fetch_cover_from_mikanani", lambda bid: cover_file)

    persisted = {}

    def _fake_update(quarter, title, bangumi_id=None, cover_url=None):
        persisted["args"] = (quarter, title, bangumi_id, cover_url)
        return True

    monkeypatch.setattr(svc, "update_subscription_cover", _fake_update)

    result = svc.sync_titles_covers({}, ["番剧A"], "2026Q2")
    assert result == {"番剧A": b"cover-A"}
    assert persisted["args"] == ("2026Q2", "番剧A", 2002, None)


def test_sync_titles_covers_uses_cached_bangumi_cover(monkeypatch, tmp_path):
    import gui.services.cover_sync_service as svc

    monkeypatch.setattr(
        svc,
        "get_subscriptions",
        lambda _q=None: {"2026Q2": [{"title": "番剧B", "bangumi_id": 50, "cover_url": ""}]},
    )
    monkeypatch.setattr(svc, "load_season_index_cached", lambda quarter, use_mirror=False: None)

    cover_file = tmp_path / "id_50.jpg"
    cover_file.write_bytes(b"cached-B")
    monkeypatch.setattr(svc, "get_cover_path", lambda title, bid=None: cover_file if bid == 50 else None)
    # 不应触网
    monkeypatch.setattr(svc, "fetch_cover_from_url", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not fetch")))
    monkeypatch.setattr(svc, "fetch_cover_from_mikanani", lambda bid: (_ for _ in ()).throw(AssertionError("should not fetch")))
    monkeypatch.setattr(svc, "match_bangumi_id", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not match")))
    monkeypatch.setattr(svc, "update_subscription_cover", lambda *a, **k: False)

    result = svc.sync_titles_covers({}, ["番剧B"], "2026Q2")
    assert result == {"番剧B": b"cached-B"}


def test_sync_other_quarters_covers_uses_single_search_match(monkeypatch, tmp_path):
    """其他季度走单次蜜柑搜索匹配，绝不读取/构建 season_index。"""
    import gui.services.cover_sync_service as svc

    monkeypatch.setattr(
        svc,
        "get_subscriptions",
        lambda _q=None: {"2025Q4": [{"title": "旧番", "bangumi_id": 0, "cover_url": ""}]},
    )
    # 绝不应触碰季度索引（老季度索引价值低、构建慢）
    monkeypatch.setattr(
        svc,
        "load_season_index_cached",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not touch season index")),
    )
    monkeypatch.setattr(svc, "get_cover_path", lambda title, bid=None: None)
    monkeypatch.setattr(svc, "fetch_cover_from_url", lambda *a, **k: None)

    search_calls = []

    def _fake_search(title, use_mirror=False):
        search_calls.append(title)
        return [{"id": 314, "name": title}]

    monkeypatch.setattr(svc, "search_bangumi", _fake_search)

    cover_file = tmp_path / "id_314.jpg"
    cover_file.write_bytes(b"old-cover")
    monkeypatch.setattr(svc, "fetch_cover_from_mikanani", lambda bid: cover_file if bid == 314 else None)
    monkeypatch.setattr(svc, "update_subscription_cover", lambda *a, **k: True)

    out = svc.sync_other_quarters_covers({}, {"2025Q4": ["旧番"]})
    assert out == {"旧番": b"old-cover"}
    assert search_calls == ["旧番"]
