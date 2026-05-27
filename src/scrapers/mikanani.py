"""蜜柑计划爬虫：搜索番剧、获取字幕组列表、检查资源、构造 RSS URL。

流程：
  1. search_bangumi(title)     → 得到 bangumi_id 候选列表
  2. get_subgroups(bangumi_id) → 得到该番剧的所有字幕组
  3. has_recent_resources(...)  → 检查某字幕组最近是否有更新
  4. find_best_rss(...)         → 按优先级选最佳字幕组
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import feedparser

logger = logging.getLogger(__name__)

MIKAN_BASE = "https://mikanani.me"
MIKAN_MIRROR = "https://mikanime.tv"  # 备用镜像（某些地区使用）

# ── 磁盘缓存（搜索结果 + 字幕组列表）────────────────────
# 缓存文件放在项目根目录，季度内基本稳定，7天过期
_CACHE_FILE = Path(__file__).parent.parent.parent / ".mikan_cache.json"
_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 天


def _load_cache() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_cache(data: dict) -> None:
    try:
        _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("缓存写入失败：%s", e)


def _cache_get(key: str) -> list | None:
    data = _load_cache()
    entry = data.get(key)
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > _CACHE_TTL_SECONDS:
        return None  # 过期
    return entry.get("value")


def _cache_set(key: str, value: list) -> None:
    data = _load_cache()
    data[key] = {"ts": time.time(), "value": value}
    _save_cache(data)


# ── 请求入口 ──────────────────────────────────────────────


def _fetch(url: str) -> object | None:
    """统一请求入口：scrapling 0.4.x 用 Fetcher.get()（classmethod，无需浏览器）。"""
    try:
        from scrapling.fetchers import Fetcher
        return Fetcher.get(url)
    except Exception as e:
        logger.error("请求失败 [%s]: %s", url, e)
        return None


# ── RSS URL 构造 ──────────────────────────────────────────


def build_rss_url(bangumi_id: int, subgroup_id: int, base: str = MIKAN_BASE) -> str:
    return f"{base}/RSS/Bangumi?bangumiId={bangumi_id}&subgroupid={subgroup_id}"


# ── 搜索 ──────────────────────────────────────────────────


def search_bangumi(title: str, use_mirror: bool = False) -> list[dict]:
    """
    在蜜柑计划搜索番剧，返回候选列表。
    每条格式：{"id": int, "name": str, "url": str}

    命中磁盘缓存（7天有效）时直接返回，否则用复用的 StealthySession 请求。
    """
    cache_key = f"search:{title}:{'mirror' if use_mirror else 'main'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("搜索缓存命中：%s", title)
        return cached

    base = MIKAN_MIRROR if use_mirror else MIKAN_BASE
    url = f"{base}/Home/Search?searchstr={quote(title)}"
    logger.info("搜索蜜柑：%s", url)

    page = _fetch(url)
    if page is None:
        return []

    results = _parse_search_results(page, base)
    if results:
        _cache_set(cache_key, results)
    return results


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
    # 优先级：旧版带 class/属性的选择器 → 新版直接匹配 /Home/Bangumi/ 链接
    selectors = [
        "a.js-bangumi-item",
        "a[data-bangumi-id]",
        ".bangumi-list a",
        "a[href*='/Home/Bangumi/']",   # 新版页面：<a href="/Home/Bangumi/3899"><span>标题</span></a>
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
                            tail = href.split("/Bangumi/")[-1].strip("/")
                            if tail.isdigit():
                                bangumi_id = int(tail)

                    if bangumi_id is None or bangumi_id in seen_ids:
                        continue
                    seen_ids.add(bangumi_id)

                    # 获取标题：用 get_all_text() 提取元素内全部文本
                    # （标题在 span 内的纯文本节点，.text 只取直接文本节点会为空）
                    name = item.get_all_text().strip() if hasattr(item, "get_all_text") else item.text.strip()
                    if not name:
                        continue

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

    命中磁盘缓存（7天有效）时直接返回，否则用复用的 StealthySession 请求。
    """
    cache_key = f"subgroups:{bangumi_id}:{'mirror' if use_mirror else 'main'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("字幕组缓存命中：bangumi_id=%d", bangumi_id)
        return cached

    base = MIKAN_MIRROR if use_mirror else MIKAN_BASE
    url = f"{base}/Home/Bangumi/{bangumi_id}"
    logger.info("获取字幕组列表：%s", url)

    page = _fetch(url)
    if page is None:
        return []

    results = _parse_subgroups(page)
    if results:
        _cache_set(cache_key, results)
    return results


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

                    anchor = item.attrib.get("data-anchor", "") if hasattr(item, "attrib") else ""
                    if anchor:
                        # 新格式：#1231  旧格式：.js-subgroup-item-562
                        stripped = anchor.lstrip("#.")
                        if stripped.isdigit():
                            sg_id = int(stripped)
                        else:
                            tail = anchor.split("-")[-1].strip(")")
                            if tail.isdigit():
                                sg_id = int(tail)

                    # 从 href 解析（#1231 形式）
                    if sg_id is None:
                        href = item.attrib.get("href", "") if hasattr(item, "attrib") else ""
                        if href and href.lstrip("#").isdigit():
                            sg_id = int(href.lstrip("#"))

                    if sg_id is None or sg_id in seen_ids:
                        continue
                    seen_ids.add(sg_id)

                    name = (item.get_all_text().strip()
                            if hasattr(item, "get_all_text")
                            else item.text.strip())
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
    检查字幕组是否有资源：RSS 中有任意条目即认为有效。
    （原日期窗口检查已移除：对当季新番无意义，且是主要性能瓶颈。
      qBittorrent 自动规则会持续监控，资源活跃与否不影响订阅正确性。）
    """
    base = MIKAN_MIRROR if use_mirror else MIKAN_BASE
    rss_url = build_rss_url(bangumi_id, subgroup_id, base)
    try:
        feed = feedparser.parse(rss_url)
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


# ── 搜索词变体生成 ───────────────────────────────────────

import re as _re

# 阿拉伯数字 ↔ 汉字（季数范围内够用）
_A2C = {"1": "一", "2": "二", "3": "三", "4": "四", "5": "五",
        "6": "六", "7": "七", "8": "八", "9": "九"}
_C2A = {v: k for k, v in _A2C.items()}

# 匹配标题末尾的季数标记（保留前导空格/下划线供替换）
_SEASON_SUFFIX = _re.compile(
    r"([\s_]*)(第)([一二三四五六七八九十百\d]+)([季期])\s*$"
)


def _title_variants(title: str) -> list[str]:
    """
    为标题生成搜索变体列表，按优先级排列。

    常见导致搜索失败的原因：
      - yuc.wiki 使用「第X期」，蜜柑统一用「第X季」（且连接符可能是空格或下划线）
      - 阿拉伯数字 vs 汉字（第2季 vs 第二季）
      - 末尾季数不同但主标题一致

    策略（依次尝试）：
      1. 原标题
      2. 季数变体：期↔季、阿拉伯↔汉字、空格↔下划线 的全组合（在原标题末尾有季标时）
      3. 去末尾季数后的基础标题
      4. 第一个空格/冒号/中点前的部分
      5. 标题前6字（最后兜底）
    """
    variants: list[str] = [title]

    # ── 季数变体 ──────────────────────────────────────────
    m = _SEASON_SUFFIX.search(title)
    if m:
        base = title[: m.start()]          # 季标前的主标题
        num  = m.group(3)                  # 数字部分，如 "2" 或 "二"
        alt_num = _A2C.get(num) or _C2A.get(num) or num   # 互换形式

        # 生成 期/季 × 数字/汉字 × 空格/下划线 的全组合，去重后追加
        for n in dict.fromkeys([num, alt_num]):          # 保持顺序去重
            for suf in ("季", "期"):
                for sep in (" ", "_"):
                    candidate = f"{base}{sep}第{n}{suf}"
                    if candidate not in variants:
                        variants.append(candidate)

    # ── 去末尾季标，保留基础标题 ─────────────────────────
    no_season = _re.sub(
        r"[\s_]*(第[一二三四五六七八九十百\d]+[季期]|Season\s*\d+|S\d+)\s*$",
        "", title,
    ).strip()
    if no_season and no_season != title and no_season not in variants:
        variants.append(no_season)

    # ── 第一个分隔符前的部分 ──────────────────────────────
    for sep in (" ", "：", ":", "·", "・", "～", "~"):
        idx = title.find(sep)
        if idx >= 3:
            part = title[:idx].strip()
            if part not in variants:
                variants.append(part)
            break

    # ── 前6字兜底 ─────────────────────────────────────────
    if len(title) > 8:
        short = title[:6]
        if short not in variants:
            variants.append(short)

    return variants


# ── bgm.tv 搜索回退 ───────────────────────────────────────

import requests as _requests


def _bgm_canonical_names(title: str) -> list[str]:
    """
    用 bangumi.tv v0 API 搜索标题，返回官方名称列表（name_cn 优先，再 name）。
    用于 mikanani 标题与 yuc.wiki 标题不一致时的最后兜底。
    bgm 的搜索对别名、异体字容错极强，通常能找到准确匹配。
    """
    try:
        resp = _requests.post(
            "https://api.bgm.tv/v0/search/subjects",
            params={"limit": 5},
            json={"keyword": title, "filter": {"type": [2]}},
            headers={
                "User-Agent": "anime-rss/1.0",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=6,
        )
        if not resp.ok:
            return []
        names: list[str] = []
        for item in resp.json().get("data", [])[:3]:
            cn = (item.get("name_cn") or "").strip()
            jp = (item.get("name") or "").strip()
            if cn and cn not in names:
                names.append(cn)
            if jp and jp not in names:
                names.append(jp)
        return names
    except Exception as e:
        logger.debug("bgm 搜索失败 [%s]: %s", title, e)
        return []


# ── 辅助：获取某字幕组 RSS 最新一条的发布时间 ────────────


def _latest_rss_time(
    bangumi_id: int,
    subgroup_id: int,
    use_mirror: bool = False,
) -> "datetime | None":
    """返回该字幕组 RSS 最新一条的发布时间；解析失败返回 None。"""
    base = MIKAN_MIRROR if use_mirror else MIKAN_BASE
    try:
        feed = feedparser.parse(build_rss_url(bangumi_id, subgroup_id, base))
        for entry in feed.entries:
            pub = entry.get("published_parsed")
            if pub:
                return datetime(*pub[:6], tzinfo=timezone.utc)
    except Exception:
        pass
    return None


# ── 完整流程（搜索 + 选择最佳 RSS）──────────────────────


def resolve_anime_rss(
    title: str,
    priorities: list[str],
    weeks: int = 4,
    use_mirror: bool = False,
    search_override: str | None = None,
) -> dict | None:
    """
    一步完成：搜索番剧 → 找最佳 RSS。

    search_override：用于手动指定蜜柑搜索词（跳过自动变体逻辑）。

    选择策略：
    - 精确命中（用原始标题搜到）：取前 3 候选，选第一个有资源的（快速）
    - 模糊命中（用缩短/变体词搜到，或手动 override）：
        遍历所有候选，优先字幕组优先级，但在多个候选均有资源时
        选 RSS 最近更新时间最新的（避免误选老季度）

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
    # 确定要尝试的搜索词列表
    if search_override:
        search_terms = [search_override.strip()]
    else:
        search_terms = _title_variants(title)

    # 逐个变体搜索，找到候选即停；记录是否用了非原始词（fallback）
    candidates: list[dict] = []
    is_fallback = bool(search_override)  # 手动 override 也走 fallback 策略
    for i, term in enumerate(search_terms):
        candidates = search_bangumi(term, use_mirror)
        if candidates:
            if not search_override:
                is_fallback = (i > 0)
            logger.info("搜索词 '%s' 命中 %d 个候选 (fallback=%s)", term, len(candidates), is_fallback)
            break
        logger.info("搜索词 '%s' 无结果，尝试下一变体", term)

    if not candidates and not search_override:
        # ── bgm.tv 回退：用官方名称重新搜索 ─────────────────
        logger.info("本地变体均无结果，尝试 bgm.tv 搜索：%s", title)
        bgm_names = _bgm_canonical_names(title)
        for bgm_name in bgm_names:
            if bgm_name in search_terms:
                continue          # 已经试过
            candidates = search_bangumi(bgm_name, use_mirror)
            if candidates:
                is_fallback = True
                logger.info("bgm 名称 '%s' 命中 %d 个候选", bgm_name, len(candidates))
                break
            logger.info("bgm 名称 '%s' 仍无结果", bgm_name)

    if not candidates:
        logger.warning("未在蜜柑计划找到：%s（尝试词：%s）", title, search_terms)
        return None

    if not is_fallback:
        # ── 精确命中：取前3，选第一个有资源的 ─────────────
        for candidate in candidates[:3]:
            best = find_best_rss(candidate["id"], priorities, weeks, use_mirror)
            if best:
                return {
                    "title": title,
                    "bangumi_id": candidate["id"],
                    "bangumi_name": candidate["name"],
                    **best,
                }
            time.sleep(0.5)
    else:
        # ── 模糊命中：遍历所有候选，选最近更新的有效资源 ──
        # 用于「石纪元」等搜到多个季度的情形，确保选到当前连载季
        logger.info("模糊匹配，对 %d 个候选按更新时间择优...", len(candidates))
        best_result: dict | None = None
        best_time: "datetime | None" = None

        for candidate in candidates:
            best = find_best_rss(candidate["id"], priorities, weeks, use_mirror)
            if best:
                latest = _latest_rss_time(candidate["id"], best["subgroup_id"], use_mirror)
                if best_result is None or (
                    latest is not None
                    and (best_time is None or latest > best_time)
                ):
                    best_result = {
                        "title": title,
                        "bangumi_id": candidate["id"],
                        "bangumi_name": candidate["name"],
                        **best,
                    }
                    best_time = latest
            time.sleep(0.3)

        if best_result:
            return best_result

    logger.warning("'%s' 的所有候选番剧均无合适资源", title)
    return None
