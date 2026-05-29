from __future__ import annotations

import hashlib
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from src.utils.cover_cache import get_cover_path, get_or_fetch_cover
from src.utils.file_parser import AnimeFolder
from src.utils.runtime_paths import COVER_CACHE_DIR
from src.utils.state import get_all_subscriptions_flat

if TYPE_CHECKING:
    from PyQt6.QtGui import QPixmap

_MEMO: dict[str, bytes] = {}
_MISS_KEYS: set[str] = set()


def _norm_title(title: str) -> str:
    return str(title or "").strip().lower()


def _subscription_score(sub: dict) -> int:
    score = 0
    if sub.get("cover_url"):
        score += 8
    try:
        if int(sub.get("bangumi_id") or 0) > 0:
            score += 6
    except Exception:
        pass
    if sub.get("rss_url"):
        score += 2
    if not sub.get("recovered_local"):
        score += 4
    if str(sub.get("subgroup_name", "")).strip().lower() not in {"", "local"}:
        score += 1
    return score


def _pick_subscription(folder_title: str, subs: list[dict]) -> dict | None:
    ft = _norm_title(folder_title)
    if not ft:
        return None

    exact = [s for s in subs if _norm_title(s.get("title", "")) == ft]
    if exact:
        return max(exact, key=_subscription_score)

    fuzzy = []
    for s in subs:
        st = _norm_title(s.get("title", ""))
        if not st:
            continue
        if st in ft or ft in st:
            fuzzy.append(s)
    if fuzzy:
        return max(fuzzy, key=lambda s: (_subscription_score(s), len(_norm_title(s.get("title", "")))))
    return None


def _extract_bangumi_id(rss_url: str) -> int | None:
    if not rss_url:
        return None
    try:
        query = parse_qs(urlparse(rss_url).query)
        values = query.get("bangumiId") or query.get("bangumiid")
        if not values:
            return None
        bid = int(values[0])
        return bid if bid > 0 else None
    except Exception:
        return None


def _cache_path_for_url(url: str) -> Path:
    return COVER_CACHE_DIR / (hashlib.md5(url.encode()).hexdigest() + ".jpg")


def _fetch_cover_bytes_cached(url: str | None) -> bytes | None:
    if not url:
        return None
    if url in _MEMO:
        return _MEMO[url]
    path = _cache_path_for_url(url)
    if path.exists():
        data = path.read_bytes()
        _MEMO[url] = data
        return data
    return None


def _cover_lookup_key(title: str, bangumi_id: int | None, url: str | None) -> str:
    return f"{_norm_title(title)}|{int(bangumi_id or 0)}|{str(url or '').strip()}"


def fetch_cover_bytes(url: str | None) -> bytes | None:
    data = _fetch_cover_bytes_cached(url)
    if data:
        return data
    if not url:
        return None

    COVER_CACHE_DIR.mkdir(exist_ok=True)
    path = _cache_path_for_url(url)
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


def folder_cover_bytes(
    folder: AnimeFolder,
    *,
    subs: list[dict] | None = None,
    allow_network: bool = True,
) -> bytes | None:
    subs = subs if subs is not None else get_all_subscriptions_flat()
    sub = _pick_subscription(folder.title, subs)
    url = (sub or {}).get("cover_url") or folder.cover_url
    data = fetch_cover_bytes(url) if allow_network else _fetch_cover_bytes_cached(url)
    if data:
        return data

    bangumi_id: int | None = None
    cache_title = folder.title
    if sub:
        cache_title = str(sub.get("title", "")).strip() or folder.title
        try:
            bid = int(sub.get("bangumi_id") or 0)
            if bid > 0:
                bangumi_id = bid
        except Exception:
            bangumi_id = None
        if bangumi_id is None:
            bangumi_id = _extract_bangumi_id(str(sub.get("rss_url", "")))

    p = get_cover_path(cache_title, bangumi_id)
    if p and p.exists():
        return p.read_bytes()

    if not allow_network:
        return None

    miss_key = _cover_lookup_key(cache_title, bangumi_id, url)
    if miss_key in _MISS_KEYS:
        return None

    # Last chance: fetch and cache by known metadata.
    fetched = get_or_fetch_cover(cache_title, bangumi_id, url)
    if fetched and fetched.exists():
        return fetched.read_bytes()
    _MISS_KEYS.add(miss_key)
    return None


def batch_folder_cover_bytes(
    folders: list[AnimeFolder],
    *,
    allow_network: bool = True,
) -> dict[str, bytes]:
    subs = get_all_subscriptions_flat()
    result: dict[str, bytes] = {}
    for folder in folders:
        data = folder_cover_bytes(folder, subs=subs, allow_network=allow_network)
        if data:
            result[folder.title] = data
    return result


def bytes_to_pixmap(data: bytes | None, width: int = 140, height: int = 196) -> "QPixmap":
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap

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
