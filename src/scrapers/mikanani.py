"""蜜柑计划爬虫：搜索番剧、获取字幕组列表、检查资源、构造 RSS URL。

流程：
  1. search_bangumi(title)     → 得到 bangumi_id 候选列表
  2. get_subgroups(bangumi_id) → 得到该番剧的所有字幕组
  3. has_recent_resources(...)  → 检查某字幕组最近是否有更新
  4. find_best_rss(...)         → 按优先级选最佳字幕组
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import feedparser

logger = logging.getLogger(__name__)

MIKAN_BASE = "https://mikanani.me"
MIKAN_MIRROR = "https://mikanime.tv"  # 备用镜像（某些地区使用）


# ── RSS URL 构造 ──────────────────────────────────────────


def build_rss_url(bangumi_id: int, subgroup_id: int, base: str = MIKAN_BASE) -> str:
    return f"{base}/RSS/Bangumi?bangumiId={bangumi_id}&subgroupid={subgroup_id}"


# ── 搜索 ──────────────────────────────────────────────────


def search_bangumi(title: str, use_mirror: bool = False) -> list[dict]:
    """
    在蜜柑计划搜索番剧，返回候选列表。
    每条格式：{"id": int, "name": str, "url": str}

    使用 StealthyFetcher 应对可能的 Cloudflare 保护。
    """
    base = MIKAN_MIRROR if use_mirror else MIKAN_BASE
    url = f"{base}/Home/Search?searchstr={quote(title)}"
    logger.info("搜索蜜柑：%s", url)

    try:
        from scrapling import StealthyFetcher
        page = StealthyFetcher(auto_match=False).get(url, stealthy_headers=True)
    except Exception as e:
        logger.error("蜜柑搜索请求失败：%s", e)
        return []

    return _parse_search_results(page, base)


def _parse_search_results(page, base: str) -> list[dict]:
    """解析搜索结果页，提取番剧列表。

    蜜柑搜索结果页结构（左侧栏）：
      <div class="js-search-result-left">
        <a class="js-bangumi-item" data-bangumi-id="228" href="/Home/Bangumi/228">
          <p class="bangumi-title">番剧标题</p>
        </a>
      ...
    """
    results = []
    seen_ids: set[int] = set()

    # 尝试多种选择器（页面结构可能调整）
    selectors = [
        "a.js-bangumi-item",
        "a[data-bangumi-id]",
        ".bangumi-list a",
    ]

    for selector in selectors:
        items = page.css(selector)
        if items:
            for item in items:
                try:
                    # 获取 bangumi_id（从 data-bangumi-id 属性或 href 解析）
                    bangumi_id = None

                    # 方式1：data-bangumi-id 属性
                    data_id = item.attrib.get("data-bangumi-id") if hasattr(item, "attrib") else None
                    if data_id:
                        bangumi_id = int(data_id)

                    # 方式2：从 href 解析 /Home/Bangumi/228
                    if bangumi_id is None:
                        href = item.attrib.get("href", "") if hasattr(item, "attrib") else ""
                        if "/Bangumi/" in href:
                            bangumi_id = int(href.split("/Bangumi/")[-1].strip("/"))

                    if bangumi_id is None or bangumi_id in seen_ids:
                        continue
                    seen_ids.add(bangumi_id)

                    # 获取标题
                    title_el = item.css_first(".bangumi-title") or item.css_first("p")
                    name = title_el.text.strip() if title_el else item.text.strip()

                    results.append({
                        "id": bangumi_id,
                        "name": name,
                        "url": f"{base}/Home/Bangumi/{bangumi_id}",
                    })
                except (ValueError, AttributeError) as e:
                    logger.debug("解析搜索项失败：%s", e)
                    continue
            if results:
                break  # 找到就停止尝试其他选择器

    logger.info("搜索 '%s' 找到 %d 个结果", "", len(results))
    return results


# ── 字幕组列表 ────────────────────────────────────────────


def get_subgroups(bangumi_id: int, use_mirror: bool = False) -> list[dict]:
    """
    获取番剧页面上列出的所有字幕组。
    返回：[{"id": int, "name": str}]

    番剧页 URL：https://mikanani.me/Home/Bangumi/{bangumi_id}
    字幕组列表在左侧 .subgroup-list 或 .js-subgroup-item 中。
    """
    base = MIKAN_MIRROR if use_mirror else MIKAN_BASE
    url = f"{base}/Home/Bangumi/{bangumi_id}"
    logger.info("获取字幕组列表：%s", url)

    try:
        from scrapling import StealthyFetcher
        page = StealthyFetcher(auto_match=False).get(url, stealthy_headers=True)
    except Exception as e:
        logger.error("获取字幕组失败：%s", e)
        return []

    return _parse_subgroups(page)


def _parse_subgroups(page) -> list[dict]:
    """解析番剧页面的字幕组列表。

    蜜柑番剧页结构（左侧字幕组栏）：
      <div class="bangumi-left-list-container">
        <a class="subgroup-title active" data-anchor=".js-subgroup-item-562">
          ANi
        </a>
        <a class="subgroup-title" data-anchor=".js-subgroup-item-230">
          豌豆字幕组
        </a>
      ...
    """
    results = []
    seen_ids: set[int] = set()

    selectors = [
        "a.subgroup-title",
        "a[data-anchor]",
        ".js-subgroup-item",
    ]

    for selector in selectors:
        items = page.css(selector)
        if items:
            for item in items:
                try:
                    sg_id = None

                    # 从 data-anchor 属性解析 id：".js-subgroup-item-562" → 562
                    anchor = item.attrib.get("data-anchor", "") if hasattr(item, "attrib") else ""
                    if anchor:
                        m_id = anchor.split("-")[-1].strip(")")
                        if m_id.isdigit():
                            sg_id = int(m_id)

                    # 从 href 解析
                    if sg_id is None:
                        href = item.attrib.get("href", "") if hasattr(item, "attrib") else ""
                        if href and href.strip("#").isdigit():
                            sg_id = int(href.strip("#"))

                    if sg_id is None or sg_id in seen_ids:
                        continue
                    seen_ids.add(sg_id)

                    name = item.text.strip() if hasattr(item, "text") else str(item)
                    if name:
                        results.append({"id": sg_id, "name": name})

                except (ValueError, AttributeError) as e:
                    logger.debug("解析字幕组失败：%s", e)
                    continue

            if results:
                break

    logger.info("找到 %d 个字幕组", len(results))
    return results


# ── 资源检查 ──────────────────────────────────────────────


def has_recent_resources(
    bangumi_id: int,
    subgroup_id: int,
    weeks: int = 4,
    use_mirror: bool = False,
) -> bool:
    """
    通过解析 RSS XML 检查字幕组在最近 weeks 周内是否有更新。
    RSS 无需登录即可访问。
    """
    base = MIKAN_MIRROR if use_mirror else MIKAN_BASE
    rss_url = build_rss_url(bangumi_id, subgroup_id, base)

    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return False

        cutoff = datetime.now(tz=timezone.utc) - timedelta(weeks=weeks)
        has_any_date = False
        for entry in feed.entries:
            pub = entry.get("published_parsed")
            if pub:
                has_any_date = True
                pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                if pub_dt >= cutoff:
                    return True

        # 所有条目都有日期但没有一条在时间窗口内 → 无近期资源
        if has_any_date:
            return False

        # 没有任何日期信息（feedparser 解析不到时间），有 entries 就保守认为有资源
        return len(feed.entries) > 0

    except Exception as e:
        logger.warning("检查 RSS 资源失败 [%d/%d]: %s", bangumi_id, subgroup_id, e)
        return False


# ── 优先级选择（核心逻辑）────────────────────────────────


def find_best_rss(
    bangumi_id: int,
    priorities: list[str],
    weeks: int = 4,
    use_mirror: bool = False,
) -> dict | None:
    """
    按优先级找最佳字幕组。

    逻辑：
      阶段1：遍历 priorities，找到名称匹配的组且 has_recent_resources → 立即返回（不继续找）
      阶段2：回退到任意有资源的字幕组

    返回：
      {"subgroup_id": int, "subgroup_name": str, "rss_url": str}
      或 None（没有任何组有资源）
    """
    subgroups = get_subgroups(bangumi_id, use_mirror)
    if not subgroups:
        logger.warning("番剧 %d 没有找到任何字幕组", bangumi_id)
        return None

    base = MIKAN_MIRROR if use_mirror else MIKAN_BASE

    def build_result(sg: dict) -> dict:
        return {
            "subgroup_id": sg["id"],
            "subgroup_name": sg["name"],
            "rss_url": build_rss_url(bangumi_id, sg["id"], base),
        }

    # 阶段1：按优先级匹配
    for priority in priorities:
        for sg in subgroups:
            if priority.lower() in sg["name"].lower():
                logger.info("检查优先字幕组 [%s] 资源...", sg["name"])
                if has_recent_resources(bangumi_id, sg["id"], weeks, use_mirror):
                    logger.info("✓ 使用字幕组 [%s]", sg["name"])
                    return build_result(sg)
                else:
                    logger.info("✗ 字幕组 [%s] 最近无更新，跳过", sg["name"])

    # 阶段2：回退任意有资源的组
    logger.info("优先字幕组无资源，回退搜索...")
    for sg in subgroups:
        if has_recent_resources(bangumi_id, sg["id"], weeks, use_mirror):
            logger.info("回退使用字幕组 [%s]", sg["name"])
            return build_result(sg)

    logger.warning("番剧 %d 所有字幕组均无近期资源", bangumi_id)
    return None


# ── 完整流程（搜索 + 选择最佳 RSS）──────────────────────


def resolve_anime_rss(
    title: str,
    priorities: list[str],
    weeks: int = 4,
    use_mirror: bool = False,
) -> dict | None:
    """
    一步完成：搜索番剧 → 找最佳 RSS。
    返回：
    {
      "title": str,
      "bangumi_id": int,
      "bangumi_name": str,
      "subgroup_id": int,
      "subgroup_name": str,
      "rss_url": str,
    }
    或 None（未找到）。
    """
    candidates = search_bangumi(title, use_mirror)
    if not candidates:
        logger.warning("未在蜜柑计划找到：%s", title)
        return None

    # 取第一个最匹配的候选（搜索结果按相关度排序）
    # 如果第一个没有资源，尝试下一个
    for candidate in candidates[:3]:  # 最多尝试前3个候选
        best = find_best_rss(candidate["id"], priorities, weeks, use_mirror)
        if best:
            return {
                "title": title,
                "bangumi_id": candidate["id"],
                "bangumi_name": candidate["name"],
                **best,
            }
        # 候选间稍作间隔，避免请求过快
        time.sleep(0.5)

    logger.warning("'%s' 的所有候选番剧均无合适资源", title)
    return None
