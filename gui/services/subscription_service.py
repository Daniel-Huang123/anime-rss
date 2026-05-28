from __future__ import annotations

import json
from dataclasses import dataclass

from src.qbt.client import QBTClient
from src.scrapers.mikanani import (
    build_season_index,
    build_yuc_bgm_map,
    detect_rss_filter,
    resolve_anime_rss,
)
from src.scrapers.yuc_wiki import get_season_list
from src.utils.cover_cache import get_or_fetch_cover
from src.utils.runtime_paths import APP_ROOT
from src.utils.season import quarter_to_ym
from src.utils.state import add_subscription, get_subscriptions, remove_subscription

_PENDING_FILE = APP_ROOT / ".pending_checks.json"


def _load_pending() -> dict[str, list[str]]:
    if _PENDING_FILE.exists():
        try:
            return json.loads(_PENDING_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_pending(data: dict[str, list[str]]) -> None:
    try:
        _PENDING_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def get_pending_checks() -> dict[str, list[str]]:
    """Return {quarter: [titles]} for anime that previously failed to match RSS."""
    return _load_pending()


def add_pending_check(quarter: str, title: str) -> None:
    data = _load_pending()
    lst = data.setdefault(quarter, [])
    if title not in lst:
        lst.append(title)
        _save_pending(data)


def remove_pending_check(quarter: str, title: str) -> None:
    data = _load_pending()
    if quarter in data and title in data[quarter]:
        data[quarter].remove(title)
        if not data[quarter]:
            del data[quarter]
        _save_pending(data)


@dataclass
class SeasonAnimeItem:
    title: str
    day: str
    episodes: str
    broadcast_time: str
    cover_url: str | None
    bgm_url: str
    subscribed: bool


@dataclass
class SeasonDataset:
    quarter: str
    items: list[SeasonAnimeItem]
    season_index: dict[int, int]
    yuc_bgm_map: dict[str, int]


def build_season_dataset(cfg: dict, quarter: str) -> SeasonDataset:
    year, month = quarter_to_ym(quarter)
    anime_list = get_season_list(year, month)

    use_mirror = cfg.get("advanced", {}).get("use_mirror", False)
    season_index = build_season_index(quarter, use_mirror=use_mirror)

    titles = [a["title"] for a in anime_list]
    yuc_bgm_map = build_yuc_bgm_map(titles, season_index, quarter, use_mirror=use_mirror) if titles else {}

    subbed_titles = {s["title"] for s in get_subscriptions(quarter).get(quarter, [])}
    day_order = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6}

    items = [
        SeasonAnimeItem(
            title=a["title"],
            day=a.get("day", "其他"),
            episodes=str(a.get("episodes", "") or "—"),
            broadcast_time=str(a.get("broadcast_time", "") or "—"),
            cover_url=a.get("cover_url"),
            bgm_url=(f"https://bgm.tv/subject/{yuc_bgm_map[a['title']]}" if a["title"] in yuc_bgm_map else ""),
            subscribed=a["title"] in subbed_titles,
        )
        for a in anime_list
    ]
    items.sort(key=lambda x: (day_order.get(x.day, 99), x.title))
    return SeasonDataset(quarter=quarter, items=items, season_index=season_index, yuc_bgm_map=yuc_bgm_map)


def subscribe_title(cfg: dict, quarter: str, title: str, cover_url: str | None, season_index: dict[int, int], search_override: str | None = None) -> tuple[bool, str]:
    priorities = cfg.get("subtitle_priorities", ["ANi", "kirara"])
    weeks = cfg.get("resource_check", {}).get("recent_weeks", 4)
    use_mirror = cfg.get("advanced", {}).get("use_mirror", False)
    qbt_cfg = cfg["qbittorrent"]
    qbt_save_path = qbt_cfg.get("save_path", "").strip().strip('"').strip("'")

    result = resolve_anime_rss(
        title,
        priorities,
        weeks,
        use_mirror,
        season_index=None if search_override else season_index,
        search_override=search_override,
        quarter=quarter,
    )
    if result is None:
        return False, f"未找到可用RSS：{title}"

    qbt = QBTClient(
        host=qbt_cfg["host"],
        port=qbt_cfg["port"],
        username=qbt_cfg["username"],
        password=qbt_cfg["password"],
    )
    rss_filter = detect_rss_filter(result["rss_url"])
    dl_path = f"{qbt_save_path}/{quarter}/{title}" if qbt_save_path else ""
    ok, msg = qbt.add_rss_feed(
        url=result["rss_url"],
        path=f"{quarter}/{title}",
        save_path=dl_path,
        **rss_filter,
    )
    if not ok:
        return False, msg

    get_or_fetch_cover(title, result["bangumi_id"], cover_url or None)
    add_subscription(
        quarter=quarter,
        title=title,
        bangumi_id=result["bangumi_id"],
        subgroup_id=result["subgroup_id"],
        subgroup_name=result["subgroup_name"],
        rss_url=result["rss_url"],
        cover_url=cover_url or None,
        bgm_id=result.get("mikan_bgm_id"),
    )
    return True, f"订阅成功：{title}"


def clear_season_caches() -> None:
    """Clear yuc.wiki and mikan index caches. Keeps cover cache and bangumi data intact."""
    from src.scrapers.yuc_wiki import clear_cache as _clear_yuc
    from src.scrapers.mikanani import _CACHE_FILE
    _clear_yuc()
    if _CACHE_FILE.exists():
        try:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            data = {k: v for k, v in data.items()
                    if not (k.startswith("season_index:") or k.startswith("yuc_bgm_map:"))}
            _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            _CACHE_FILE.unlink(missing_ok=True)


def unsubscribe_title(cfg: dict, quarter: str, title: str, delete_qbt: bool = True) -> tuple[bool, str]:
    qbt_cfg = cfg["qbittorrent"]
    qbt_save_path = qbt_cfg.get("save_path", "").strip().strip('"').strip("'")
    if delete_qbt:
        qbt = QBTClient(
            host=qbt_cfg["host"],
            port=qbt_cfg["port"],
            username=qbt_cfg["username"],
            password=qbt_cfg["password"],
        )
        feed_path = f"{quarter}/{title}"
        save_path = f"{qbt_save_path}/{quarter}/{title}" if qbt_save_path else ""
        qbt.unsubscribe(feed_path=feed_path, save_path=save_path)

    removed = remove_subscription(quarter, title)
    if removed:
        return True, f"已取消订阅：{quarter}/{title}"
    return False, f"未找到订阅记录：{quarter}/{title}"

