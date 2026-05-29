from __future__ import annotations


def test_collect_feed_urls_nested_tree():
    from gui.services.media_service import _collect_feed_urls

    tree = {
        "2026Q2": {
            "番剧A": {"uid": "1", "url": "https://mikanani.me/RSS/Bangumi?bangumiId=101"},
            "子文件夹": {
                "番剧B": {"uid": "2", "url": "https://mikanani.me/RSS/Bangumi?bangumiId=202"}
            },
        }
    }

    urls = _collect_feed_urls(tree)
    assert urls["2026Q2/番剧A"].endswith("bangumiId=101")
    assert urls["2026Q2/子文件夹/番剧B"].endswith("bangumiId=202")


def test_build_media_rows_can_skip_recovery(monkeypatch, tmp_path):
    import gui.services.media_service as media_service

    root = tmp_path / "anime"
    root.mkdir()

    called = {"sync": 0, "enrich": 0}

    def _mark_sync(_path):
        called["sync"] += 1
        return 0

    def _mark_enrich(_cfg):
        called["enrich"] += 1

    monkeypatch.setattr(media_service, "sync_local_subscriptions", _mark_sync)
    monkeypatch.setattr(media_service, "_try_enrich_recovered_from_qbt", _mark_enrich)
    monkeypatch.setattr(media_service, "scan_media_directory", lambda _path: [])
    monkeypatch.setattr(media_service, "enrich_with_state", lambda _folders: None)
    monkeypatch.setattr(media_service, "get_recently_played", lambda _path: {})

    rows = media_service.build_media_rows(str(root), {"host": "127.0.0.1"}, recover_existing=False)
    assert rows == []
    assert called["sync"] == 0
    assert called["enrich"] == 0
