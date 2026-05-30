from __future__ import annotations


def test_unsubscribe_title_is_idempotent_when_state_record_missing(monkeypatch):
    import gui.services.subscription_service as svc

    cfg = {"qbittorrent": {"host": "", "port": 0, "username": "", "password": "", "save_path": ""}}
    monkeypatch.setattr(svc, "remove_subscription", lambda quarter, title: False)
    monkeypatch.setattr(svc, "get_subscriptions", lambda quarter=None: {"2026Q2": []})

    ok, msg = svc.unsubscribe_title(cfg, "2026Q2", "Re:从零开始的异世界生活 第4期", delete_qbt=False)
    assert ok is True
    assert "2026Q2" in msg


def test_unsubscribe_title_still_fails_when_state_record_exists(monkeypatch):
    import gui.services.subscription_service as svc

    cfg = {"qbittorrent": {"host": "", "port": 0, "username": "", "password": "", "save_path": ""}}
    monkeypatch.setattr(svc, "remove_subscription", lambda quarter, title: False)
    monkeypatch.setattr(
        svc,
        "get_subscriptions",
        lambda quarter=None: {"2026Q2": [{"title": "Re:从零开始的异世界生活 第4期"}]},
    )

    ok, msg = svc.unsubscribe_title(cfg, "2026Q2", "Re:从零开始的异世界生活 第4期", delete_qbt=False)
    assert ok is False
    assert "未找到订阅记录" in msg
