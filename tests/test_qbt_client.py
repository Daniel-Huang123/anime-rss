from __future__ import annotations

from src.qbt.client import _episode_key, _torrent_url_from_entry


def test_episode_key_dedups_simplified_variants_same_episode():
    # 桜都同集两个简体版应得到相同 key → 补拉时去重
    a = _episode_key("[桜都字幕组] 冰之城墙 / Koori no Jouheki [08][1080P][简繁内封]")
    b = _episode_key("[桜都字幕组] 冰之城墙 / Koori no Jouheki [08][1080P][简体内嵌]")
    assert a == b and a is not None


def test_episode_key_distinguishes_different_episodes():
    e8 = _episode_key("[ANi] X - 08 [1080P][Baha][CHT]")
    e9 = _episode_key("[ANi] X - 09 [1080P][Baha][CHT]")
    assert e8 != e9


def test_episode_key_ignores_resolution_token():
    # 不能把 1080 当集数
    assert _episode_key("[ANi] X - 03 [1080P][Baha][CHT]") == _episode_key("X 第03话")


def test_torrent_url_prefers_enclosure_over_page_link():
    """蜜柑 entry.link 是剧集详情页，不能喂给 qB；必须取 enclosure 里的 .torrent。"""
    entry = {
        "title": "[ANi] X - 12 [1080P][Baha][CHT][MP4]",
        "link": "https://mikanani.me/Home/Episode/abc123",  # 详情页，非种子
        "enclosures": [
            {"href": "https://mikanani.me/Download/20260527/abc123.torrent",
             "type": "application/x-bittorrent"}
        ],
    }
    assert _torrent_url_from_entry(entry) == "https://mikanani.me/Download/20260527/abc123.torrent"


def test_torrent_url_falls_back_to_bittorrent_link():
    entry = {
        "title": "Y - 01",
        "link": "https://mikanani.me/Home/Episode/def",
        "links": [
            {"href": "https://mikanani.me/Home/Episode/def", "type": "text/html"},
            {"href": "https://mikanani.me/Download/x/def.torrent",
             "type": "application/x-bittorrent"},
        ],
    }
    assert _torrent_url_from_entry(entry) == "https://mikanani.me/Download/x/def.torrent"


def test_torrent_url_does_not_return_episode_page():
    """没有任何种子链接、只有详情页时，不应误把详情页当种子返回。"""
    entry = {"title": "Z", "link": "https://mikanani.me/Home/Episode/zzz"}
    assert _torrent_url_from_entry(entry) == ""


def test_torrent_url_accepts_magnet_in_link():
    entry = {"title": "W", "link": "magnet:?xt=urn:btih:deadbeef"}
    assert _torrent_url_from_entry(entry) == "magnet:?xt=urn:btih:deadbeef"
