from __future__ import annotations

import hashlib
from pathlib import Path

import requests
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from src.utils.cover_cache import get_cover_path
from src.utils.file_parser import AnimeFolder
from src.utils.runtime_paths import COVER_CACHE_DIR
from src.utils.state import get_all_subscriptions_flat

_MEMO: dict[str, bytes] = {}


def _cache_path_for_url(url: str) -> Path:
    return COVER_CACHE_DIR / (hashlib.md5(url.encode()).hexdigest() + ".jpg")


def fetch_cover_bytes(url: str | None) -> bytes | None:
    if not url:
        return None
    if url in _MEMO:
        return _MEMO[url]

    COVER_CACHE_DIR.mkdir(exist_ok=True)
    path = _cache_path_for_url(url)
    if path.exists():
        data = path.read_bytes()
        _MEMO[url] = data
        return data

    referer = "https://www.bilibili.com/" if ("hdslb.com" in url or "bilibili" in url) else "https://yuc.wiki/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer,
    }
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.ok and len(resp.content) > 500:
            path.write_bytes(resp.content)
            _MEMO[url] = resp.content
            return resp.content
    except Exception:
        return None
    return None


def folder_cover_bytes(folder: AnimeFolder) -> bytes | None:
    subs_map = {s["title"]: s for s in get_all_subscriptions_flat()}
    sub = subs_map.get(folder.title, {})
    url = sub.get("cover_url") or folder.cover_url
    data = fetch_cover_bytes(url)
    if data:
        return data
    bgm_id = sub.get("bangumi_id") if sub else None
    p = get_cover_path(folder.title, bgm_id)
    if p and p.exists():
        return p.read_bytes()
    return None


def bytes_to_pixmap(data: bytes | None, width: int = 140, height: int = 196) -> QPixmap:
    if data:
        pix = QPixmap()
        pix.loadFromData(data)
        if not pix.isNull():
            return pix.scaled(
                width, height,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
    fallback = QPixmap(width, height)
    fallback.fill(Qt.GlobalColor.darkGray)
    return fallback
