from __future__ import annotations


def test_plan_cover_sync_splits_current_and_other(monkeypatch):
    import gui.services.cover_sync_service as svc

    monkeypatch.setattr(svc, "current_quarter", lambda: "2026Q2")
    monkeypatch.setattr(
        svc,
        "get_subscriptions",
        lambda: {
            "2026Q2": [{"title": "Current Show"}],
            "2025Q4": [{"title": "Old Show"}],
        },
    )

    cur_q, cur_titles, others = svc.plan_cover_sync(["Current Show", "Old Show", "Unknown Show"])
    assert cur_q == "2026Q2"
    assert set(cur_titles) == {"Current Show", "Unknown Show"}
    assert others == {"2025Q4": ["Old Show"]}


def test_sync_titles_covers_matches_and_persists(monkeypatch, tmp_path):
    import gui.services.cover_sync_service as svc

    monkeypatch.setattr(
        svc,
        "get_subscriptions",
        lambda _q=None: {"2026Q2": [{"title": "Show A", "bangumi_id": 0, "cover_url": ""}]},
    )
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

    result = svc.sync_titles_covers({}, ["Show A"], "2026Q2")
    assert result == {"Show A": b"cover-A"}
    assert persisted["args"] == ("2026Q2", "Show A", 2002, None)


def test_sync_titles_covers_uses_cached_bangumi_cover(monkeypatch, tmp_path):
    import gui.services.cover_sync_service as svc

    monkeypatch.setattr(
        svc,
        "get_subscriptions",
        lambda _q=None: {"2026Q2": [{"title": "Show B", "bangumi_id": 50, "cover_url": ""}]},
    )
    monkeypatch.setattr(svc, "load_season_index_cached", lambda quarter, use_mirror=False: None)

    cover_file = tmp_path / "id_50.jpg"
    cover_file.write_bytes(b"cached-B")
    monkeypatch.setattr(svc, "get_cover_path", lambda title, bid=None: cover_file if bid == 50 else None)
    monkeypatch.setattr(
        svc,
        "fetch_cover_from_url",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )
    monkeypatch.setattr(
        svc,
        "fetch_cover_from_mikanani",
        lambda bid: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )
    monkeypatch.setattr(
        svc,
        "match_bangumi_id",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not match")),
    )
    monkeypatch.setattr(svc, "update_subscription_cover", lambda *a, **k: False)

    result = svc.sync_titles_covers({}, ["Show B"], "2026Q2")
    assert result == {"Show B": b"cached-B"}


def test_sync_other_quarters_covers_uses_single_search_match(monkeypatch, tmp_path):
    import gui.services.cover_sync_service as svc

    monkeypatch.setattr(
        svc,
        "get_subscriptions",
        lambda _q=None: {"2025Q4": [{"title": "Old Show", "bangumi_id": 0, "cover_url": ""}]},
    )
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

    out = svc.sync_other_quarters_covers({}, {"2025Q4": ["Old Show"]})
    assert out == {"Old Show": b"old-cover"}
    assert search_calls == ["Old Show"]


def test_sync_titles_covers_falls_back_to_search_when_index_miss(monkeypatch, tmp_path):
    import gui.services.cover_sync_service as svc

    monkeypatch.setattr(
        svc,
        "get_subscriptions",
        lambda _q=None: {"2026Q2": [{"title": "Show C", "bangumi_id": 0, "cover_url": ""}]},
    )
    monkeypatch.setattr(svc, "load_season_index_cached", lambda quarter, use_mirror=False: {1: 2})
    monkeypatch.setattr(svc, "match_bangumi_id", lambda *a, **k: None)
    monkeypatch.setattr(svc, "get_cover_path", lambda *a, **k: None)
    monkeypatch.setattr(svc, "fetch_cover_from_url", lambda *a, **k: None)

    search_calls = []

    def _fake_search(title, use_mirror=False):
        search_calls.append(title)
        return [{"id": 7788, "name": title}]

    monkeypatch.setattr(svc, "search_bangumi", _fake_search)

    cover_file = tmp_path / "id_7788.jpg"
    cover_file.write_bytes(b"cover-C")
    monkeypatch.setattr(svc, "fetch_cover_from_mikanani", lambda bid: cover_file if bid == 7788 else None)
    monkeypatch.setattr(svc, "update_subscription_cover", lambda *a, **k: True)

    result = svc.sync_titles_covers({}, ["Show C"], "2026Q2")
    assert result == {"Show C": b"cover-C"}
    assert search_calls == ["Show C"]
