"""媒体库封面同步。

把本地媒体库里「没有封面」的番剧（多为迁移/重装后从磁盘恢复、缺少元数据的
recovered_local 记录）匹配到蜜柑 bangumi_id，抓取封面并缓存，同时把发现的
bangumi_id / cover_url 写回 state.json，使下次加载直接命中缓存。

刷新链路（由 MediaLibraryPage 驱动，每个媒体路径每个会话只跑一次）：
  1. 第一次读完本地媒体库（扫描 + 离线/在线封面批量加载）
  2. 当季：用 season_index 做一次匹配 → 更新封面（命中即缓存，后续走缓存）
  3. 其他季度：每个标题只做「单次蜜柑搜索」匹配（不逐季重建 season_index，
     避免老季度匹配浪费时间）→ 更新缓存与封面

匹配结果都会写回 state.json，下次启动经普通 folder_cover_bytes 路径直接命中。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from src.scrapers.mikanani import (
    load_season_index_cached,
    match_bangumi_id,
    search_bangumi,
)
from src.utils.cover_cache import (
    fetch_cover_from_mikanani,
    fetch_cover_from_url,
    get_cover_path,
)
from src.utils.season import current_quarter
from src.utils.state import get_subscriptions, update_subscription_cover

logger = logging.getLogger(__name__)


def _title_quarter_map() -> dict[str, str]:
    """title → quarter；同名跨季度时取较新的季度（字符串比较在 YYYYQN 下合法）。"""
    mapping: dict[str, str] = {}
    for quarter, subs in get_subscriptions().items():
        for s in subs:
            title = str(s.get("title", "")).strip()
            if not title:
                continue
            if title not in mapping or quarter > mapping[title]:
                mapping[title] = quarter
    return mapping


def plan_cover_sync(titles: list[str]) -> tuple[str, list[str], dict[str, list[str]]]:
    """把缺封面的标题按季度归类。

    返回 (当前季度, 当前季度标题列表, {其他季度: [标题,...]})。
    没有订阅记录的标题归到当前季度（最常见：刚下载、尚未走过订阅流程）。
    """
    qmap = _title_quarter_map()
    cur_q = current_quarter()
    cur_titles: list[str] = []
    others: dict[str, list[str]] = {}
    for title in titles:
        quarter = qmap.get(title, cur_q)
        if quarter == cur_q:
            cur_titles.append(title)
        else:
            others.setdefault(quarter, []).append(title)
    return cur_q, cur_titles, others


def _quarter_subs(quarter: str) -> dict[str, dict]:
    return {
        str(s.get("title", "")).strip(): s
        for s in get_subscriptions(quarter).get(quarter, [])
    }


def _resolve_cover(
    title: str,
    entry: dict,
    match_fn: Callable[[str], int | None],
) -> tuple[bytes | None, int | None, str | None]:
    """单个标题的封面解析（纯网络/IO，不写 state）。

    顺序：bangumi_id 缓存 → cover_url 直下 → match_fn 找 bangumi_id 后从蜜柑抓。
    返回 (cover_bytes|None, bangumi_id|None, cover_url|None)，供调用方串行写回 state。
    """
    cover_url = (str(entry.get("cover_url") or "").strip()) or None
    bangumi_id = int(entry.get("bangumi_id") or 0) or None
    try:
        path = get_cover_path(title, bangumi_id) if bangumi_id else None

        if path is None and cover_url:
            path = fetch_cover_from_url(cover_url, title, bangumi_id)

        if path is None:
            if bangumi_id is None:
                bangumi_id = match_fn(title)
            if bangumi_id:
                path = fetch_cover_from_mikanani(bangumi_id)

        if path is not None and path.exists():
            return path.read_bytes(), bangumi_id, cover_url
    except Exception:
        logger.exception("封面解析失败：%s", title)
    return None, bangumi_id, cover_url


def _sync_quarter(
    quarter: str, titles: list[str], match_fn: Callable[[str], int | None]
) -> dict[str, bytes]:
    """并行解析一个季度的封面，再串行把发现的元数据写回 state（避免并发写盘竞争）。"""
    if not titles:
        return {}
    subs = _quarter_subs(quarter)

    def _work(title: str) -> tuple[str, bytes | None, int | None, str | None]:
        data, bid, cov = _resolve_cover(title, subs.get(title, {}), match_fn)
        return title, data, bid, cov

    result: dict[str, bytes] = {}
    writebacks: list[tuple[str, int | None, str | None]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for title, data, bid, cov in pool.map(_work, titles):
            if data:
                result[title] = data
                writebacks.append((title, bid, cov))

    for title, bid, cov in writebacks:
        try:
            update_subscription_cover(quarter, title, bangumi_id=bid, cover_url=cov)
        except Exception:
            logger.exception("封面元数据写回失败：%s（%s）", title, quarter)

    if result:
        logger.info("封面同步 %s：%d/%d 命中", quarter, len(result), len(titles))
    return result


def _search_matcher(use_mirror: bool) -> Callable[[str], int | None]:
    """轻量匹配：单次蜜柑搜索取首个候选（search_bangumi 自带 7 天磁盘缓存）。"""

    def _match(title: str) -> int | None:
        cands = search_bangumi(title, use_mirror)
        return int(cands[0]["id"]) if cands else None

    return _match


def sync_titles_covers(cfg: dict, titles: list[str], quarter: str) -> dict[str, bytes]:
    """当季封面同步：并行抓取，返回 {title: cover_bytes}。

    匹配策略：若当季 season_index 已被订阅页构建并缓存，则借用它做精确匹配；
    否则退回单次搜索匹配——绝不在此为封面而冷构建当季索引（那会抢 30-40s、
    拖慢订阅页的番单加载）。
    """
    if not titles:
        return {}
    use_mirror = bool(cfg.get("advanced", {}).get("use_mirror", False))
    season_index = load_season_index_cached(quarter, use_mirror)

    if season_index:
        _fallback_match = _search_matcher(use_mirror)

        def _match(title: str) -> int | None:
            bid = match_bangumi_id(title, season_index, quarter, use_mirror)
            if bid:
                return bid
            return _fallback_match(title)
    else:
        _match = _search_matcher(use_mirror)

    return _sync_quarter(quarter, titles, _match)


def sync_other_quarters_covers(
    cfg: dict, by_quarter: dict[str, list[str]]
) -> dict[str, bytes]:
    """其他季度封面同步：每个标题只做一次蜜柑搜索匹配，不逐季重建 season_index。

    老季度 season_index 价值低、构建慢；这里退化为「单次搜索取首个候选」的轻量匹配
    （search_bangumi 自带 7 天磁盘缓存，重复运行也廉价）。
    """
    use_mirror = bool(cfg.get("advanced", {}).get("use_mirror", False))
    _match = _search_matcher(use_mirror)

    result: dict[str, bytes] = {}
    for quarter, titles in by_quarter.items():
        result.update(_sync_quarter(quarter, titles, _match))
    return result
