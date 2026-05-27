"""番剧封面图片本地缓存。

封面来源优先级：
  1. mikanani.me 番剧页面的 <img> 封面（质量最好，400×567）
  2. yuc.wiki 季度页面的 <img data-src="..."> 缩略图（120px）

缓存路径：assets/covers/{bangumi_id}.jpg 或 assets/covers/title_{hash}.jpg
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

COVERS_DIR = Path(__file__).parent.parent.parent / "assets" / "covers"
COVERS_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://mikanani.me/",
}


def _title_to_key(title: str) -> str:
    return hashlib.md5(title.encode("utf-8")).hexdigest()[:12]


def cover_path_by_id(bangumi_id: int) -> Path:
    return COVERS_DIR / f"id_{bangumi_id}.jpg"


def cover_path_by_title(title: str) -> Path:
    return COVERS_DIR / f"title_{_title_to_key(title)}.jpg"


def get_cover_path(title: str, bangumi_id: int | None = None) -> Path | None:
    """返回已缓存的封面路径，不存在返回 None。"""
    if bangumi_id is not None:
        p = cover_path_by_id(bangumi_id)
        if p.exists():
            return p
    p = cover_path_by_title(title)
    if p.exists():
        return p
    return None


def download_cover(url: str, save_path: Path, timeout: int = 10) -> bool:
    """下载封面图片到 save_path，返回是否成功。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type and len(resp.content) < 1000:
            logger.warning("封面响应疑似非图片：%s", content_type)
            return False
        save_path.write_bytes(resp.content)
        logger.info("封面已缓存：%s → %s", url, save_path.name)
        return True
    except Exception as e:
        logger.warning("封面下载失败 [%s]: %s", url, e)
        return False


def fetch_cover_from_mikanani(bangumi_id: int) -> Path | None:
    """
    从 mikanani.me 番剧页面抓取封面，缓存后返回本地路径。
    封面 HTML: <img src="/images/Bangumi/YYYYMM/xxxxxxxx.jpg?width=400&...">
    """
    cached = cover_path_by_id(bangumi_id)
    if cached.exists():
        return cached

    url = f"https://mikanani.me/Home/Bangumi/{bangumi_id}"
    try:
        from scrapling import StealthyFetcher
        page = StealthyFetcher(auto_match=False).get(url, stealthy_headers=True)

        # 找封面 img：src 包含 /images/Bangumi/
        img = page.css_first("img[src*='/images/Bangumi/']")
        if img is None:
            img = page.css_first(".bangumi-poster img, .cover img, img.cover")

        if img is None:
            return None

        src = img.attrib.get("src", "") if hasattr(img, "attrib") else ""
        if not src:
            return None

        # 拼成完整 URL
        if src.startswith("//"):
            img_url = "https:" + src
        elif src.startswith("/"):
            img_url = "https://mikanani.me" + src
        else:
            img_url = src

        # 去掉 resize 参数，拿原图
        img_url = img_url.split("?")[0]

        if download_cover(img_url, cached):
            return cached

    except Exception as e:
        logger.warning("从蜜柑获取封面失败 [bangumi_id=%d]: %s", bangumi_id, e)

    return None


def fetch_cover_from_url(url: str, title: str, bangumi_id: int | None = None) -> Path | None:
    """
    直接用给定 URL 下载封面（用于 yuc.wiki 的 data-src）。
    优先以 bangumi_id 命名，否则以 title hash 命名。
    """
    if bangumi_id is not None:
        save_path = cover_path_by_id(bangumi_id)
    else:
        save_path = cover_path_by_title(title)

    if save_path.exists():
        return save_path

    # yuc.wiki 图片 referer
    headers = {**HEADERS, "Referer": "https://yuc.wiki/"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        if len(resp.content) > 500:
            save_path.write_bytes(resp.content)
            return save_path
    except Exception as e:
        logger.warning("封面下载失败 [%s]: %s", url, e)

    return None


def get_or_fetch_cover(
    title: str,
    bangumi_id: int | None = None,
    cover_url: str | None = None,
) -> Path | None:
    """
    统一入口：先查缓存，没有则按优先级下载。
    1. 有 cover_url → 直接下载（来自 yuc.wiki data-src 或 mikanani img）
    2. 有 bangumi_id → 访问 mikanani 页面抓取
    """
    # 查缓存
    cached = get_cover_path(title, bangumi_id)
    if cached:
        return cached

    # 有直接 URL → 优先用
    if cover_url:
        result = fetch_cover_from_url(cover_url, title, bangumi_id)
        if result:
            return result

    # 有 bangumi_id → 从 mikanani 抓
    if bangumi_id is not None:
        result = fetch_cover_from_mikanani(bangumi_id)
        if result:
            return result

    return None
