from __future__ import annotations


def test_folder_cover_prefers_richer_subscription(monkeypatch):
    import gui.services.cover_service as cover_service
    from src.utils.file_parser import AnimeFolder

    subs = [
        {"title": "测试番剧", "recovered_local": True, "cover_url": None, "bangumi_id": 0, "rss_url": ""},
        {"title": "测试番剧", "recovered_local": False, "cover_url": "https://example.com/cover.jpg", "bangumi_id": 123, "rss_url": ""},
    ]
    monkeypatch.setattr(cover_service, "get_all_subscriptions_flat", lambda: subs)
    monkeypatch.setattr(
        cover_service,
        "fetch_cover_bytes",
        lambda url, **_kw: b"cover-bytes" if url == "https://example.com/cover.jpg" else None,
    )

    folder = AnimeFolder(title="测试番剧")
    data = cover_service.folder_cover_bytes(folder)
    assert data == b"cover-bytes"


def test_folder_cover_can_recover_bangumi_id_from_rss_url(monkeypatch, tmp_path):
    import gui.services.cover_service as cover_service
    from src.utils.file_parser import AnimeFolder

    subs = [
        {
            "title": "测试番剧",
            "recovered_local": True,
            "cover_url": None,
            "bangumi_id": 0,
            "rss_url": "https://mikanani.me/RSS/Bangumi?bangumiId=456&subgroupid=7",
        }
    ]
    monkeypatch.setattr(cover_service, "get_all_subscriptions_flat", lambda: subs)
    monkeypatch.setattr(cover_service, "fetch_cover_bytes", lambda _url, **_kw: None)
    monkeypatch.setattr(cover_service, "get_cover_path", lambda _title, _bid: None)

    out = tmp_path / "id_456.jpg"
    out.write_bytes(b"fetched-cover")
    called = {}

    def _fake_get_or_fetch_cover(title: str, bangumi_id: int | None = None, cover_url: str | None = None):
        called["title"] = title
        called["bangumi_id"] = bangumi_id
        called["cover_url"] = cover_url
        return out

    monkeypatch.setattr(cover_service, "get_or_fetch_cover", _fake_get_or_fetch_cover)

    folder = AnimeFolder(title="测试番剧")
    data = cover_service.folder_cover_bytes(folder)
    assert data == b"fetched-cover"
    assert called["bangumi_id"] == 456


def test_batch_folder_cover_bytes_reads_subscriptions_once(monkeypatch):
    import gui.services.cover_service as cover_service
    from src.utils.file_parser import AnimeFolder

    calls = {"subs": 0, "fetch": 0}
    subs = [{"title": "番剧A", "cover_url": "https://example.com/a.jpg", "recovered_local": False}]

    monkeypatch.setattr(cover_service, "get_all_subscriptions_flat", lambda: calls.__setitem__("subs", calls["subs"] + 1) or subs)

    def _fake_fetch(url, **_kw):
        calls["fetch"] += 1
        return b"img-a" if url and url.endswith("/a.jpg") else None

    monkeypatch.setattr(cover_service, "fetch_cover_bytes", _fake_fetch)
    monkeypatch.setattr(cover_service, "get_cover_path", lambda _title, _bid: None)
    monkeypatch.setattr(cover_service, "get_or_fetch_cover", lambda *_args, **_kwargs: None)

    cover_map = cover_service.batch_folder_cover_bytes([AnimeFolder(title="番剧A"), AnimeFolder(title="番剧B")])
    assert cover_map.get("番剧A") == b"img-a"
    assert calls["subs"] == 1
    assert calls["fetch"] >= 1
