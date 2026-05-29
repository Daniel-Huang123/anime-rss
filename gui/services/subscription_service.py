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
from src.utils.runtime_paths import PENDING_CHECKS_FILE
from src.utils.season import quarter_to_ym
from src.utils.state import add_subscription, get_subscriptions, remove_subscription

_PENDING_FILE = PENDING_CHECKS_FILE


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


def build_season_grid(cfg: dict, quarter: str) -> SeasonDataset:
    """快路径：只抓 yuc.wiki 番单即可渲染网格。

    不构建蜜柑索引，因此 bgm_url 暂空、season_index/yuc_bgm_map 为空——
    这些由后台 build_season_index_and_map 构建完成后再回填（见 season 页两段式加载）。
    """
    year, month = quarter_to_ym(quarter)
    anime_list = get_season_list(year, month)

    subbed_titles = {s["title"] for s in get_subscriptions(quarter).get(quarter, [])}
    day_order = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6}

    items = [
        SeasonAnimeItem(
            title=a["title"],
            day=a.get("day", "其他"),
            episodes=str(a.get("episodes", "") or "—"),
            broadcast_time=str(a.get("broadcast_time", "") or "—"),
            cover_url=a.get("cover_url"),
            bgm_url="",
            subscribed=a["title"] in subbed_titles,
        )
        for a in anime_list
    ]
    items.sort(key=lambda x: (day_order.get(x.day, 99), x.title))
    return SeasonDataset(quarter=quarter, items=items, season_index={}, yuc_bgm_map={})


def build_season_index_and_map(cfg: dict, quarter: str) -> tuple[dict[int, int], dict[str, int]]:
    """慢路径（后台执行）：构建蜜柑 bgm_id 索引 + yuc→bgm 映射。

    返回 (season_index, yuc_bgm_map)，由调用方回填到已渲染的 dataset。
    """
    use_mirror = cfg.get("advanced", {}).get("use_mirror", False)
    season_index = build_season_index(quarter, use_mirror=use_mirror)

    year, month = quarter_to_ym(quarter)
    titles = [a["title"] for a in get_season_list(year, month)]
    yuc_bgm_map = (
        build_yuc_bgm_map(titles, season_index, quarter, use_mirror=use_mirror)
        if titles else {}
    )
    return season_index, yuc_bgm_map


def build_season_dataset(cfg: dict, quarter: str) -> SeasonDataset:
    """同步全量构建（grid + 索引），保留供非两段式调用方/测试使用。"""
    dataset = build_season_grid(cfg, quarter)
    season_index, yuc_bgm_map = build_season_index_and_map(cfg, quarter)
    dataset.season_index = season_index
    dataset.yuc_bgm_map = yuc_bgm_map
    apply_bgm_map(dataset, yuc_bgm_map)
    return dataset


def apply_bgm_map(dataset: SeasonDataset, yuc_bgm_map: dict[str, int]) -> None:
    """把 yuc→bgm 映射回填到 dataset.items 的 bgm_url（就地修改）。"""
    for it in dataset.items:
        if it.title in yuc_bgm_map:
            it.bgm_url = f"https://bgm.tv/subject/{yuc_bgm_map[it.title]}"


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
        # 索引未就绪（{}）时传 None，自动走 resolve 的按需解析兜底路径
        season_index=None if search_override else (season_index or None),
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

