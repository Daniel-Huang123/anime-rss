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
from urllib.parse import quote

import feedparser
from src.utils.runtime_paths import MIKAN_CACHE_FILE

logger = logging.getLogger(__name__)

MIKAN_BASE = "https://mikanani.me"
MIKAN_MIRROR = "https://mikanime.tv"  # 备用镜像（某些地区使用）

# ── 磁盘缓存（搜索结果 + 字幕组列表）────────────────────
# 缓存文件放在项目根目录，季度内基本稳定，7天过期
_CACHE_FILE = MIKAN_CACHE_FILE
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
    """统一请求入口：requests 做 HTTP，scrapling.parser.Adaptor 做 CSS 解析。

    不使用 scrapling.Fetcher（底层 curl_cffi），因为 curl_cffi 在路径含非 ASCII
    字符（如中文目录）的 exe 中读取 CA 证书失败（curl error 77）。
    """
    try:
        import requests as _req
        from scrapling.parser import Adaptor
        r = _req.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15,
        )
        r.raise_for_status()
        return Adaptor(r.text, url=url)
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
    return _fetch_bangumi_data(bangumi_id, use_mirror)["subgroups"]


def _fetch_bangumi_data(bangumi_id: int, use_mirror: bool = False) -> dict:
    """
    获取蜜柑番剧页数据（字幕组列表 + bgm.tv subject ID），磁盘缓存 7 天。
    返回 {"subgroups": [...], "bgm_id": int | None}
    """
    cache_key = f"bangumi_data:{bangumi_id}:{'mirror' if use_mirror else 'main'}"
    cached = _cache_get(cache_key)
    if cached is not None and "bgm_id" in cached:   # 旧缓存无此字段时重新 fetch
        logger.info("番剧数据缓存命中：bangumi_id=%d", bangumi_id)
        return cached

    base = MIKAN_MIRROR if use_mirror else MIKAN_BASE
    url = f"{base}/Home/Bangumi/{bangumi_id}"
    logger.info("获取番剧页面：%s", url)

    page = _fetch(url)
    if page is None:
        return {"subgroups": [], "bgm_id": None}

    subgroups = _parse_subgroups(page)
    bgm_id    = _extract_bgm_id(page)

    result = {"subgroups": subgroups, "bgm_id": bgm_id}
    if subgroups:  # 只在有数据时缓存
        _cache_set(cache_key, result)
    return result


def _extract_bgm_id(page) -> "int | None":
    """从蜜柑番剧页提取 bgm.tv subject ID（如 https://bgm.tv/subject/377130）。"""
    for link in page.css('a[href*="bgm.tv/subject/"]'):
        href = link.attrib.get("href", "")
        m = _re.search(r"bgm\.tv/subject/(\d+)", href)
        if m:
            return int(m.group(1))
    return None


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
    data = _fetch_bangumi_data(bangumi_id, use_mirror)
    subgroups = data["subgroups"]
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

    # 阶段1：按优先级顺序，第一个名称匹配即直接返回（不验证 RSS）
    for priority in priorities:
        for sg in subgroups:
            if priority.lower() in sg["name"].lower():
                logger.info("✓ 优先字幕组 [%s] 直接使用", sg["name"])
                r = build_result(sg)
                r["mikan_bgm_id"] = data.get("bgm_id")
                return r

    # 阶段2：回退——并行检查所有字幕组，取第一个有条目的
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

    logger.info("无优先字幕组，并行检查 %d 个组...", len(subgroups))

    def _check(sg: dict) -> dict | None:
        return sg if has_recent_resources(bangumi_id, sg["id"], weeks, use_mirror) else None

    # 保留原始顺序优先：先完成的返回，但按 subgroups 顺序作二次保底
    found: dict | None = None
    with ThreadPoolExecutor(max_workers=6) as pool:
        future_to_sg = {pool.submit(_check, sg): sg for sg in subgroups}
        for future in _as_completed(future_to_sg):
            result_sg = future.result()
            if result_sg and found is None:
                found = result_sg
                # 不 break：让其他 future 完成，避免线程泄漏

    if found:
        logger.info("回退使用字幕组 [%s]", found["name"])
        r = build_result(found)
        r["mikan_bgm_id"] = data.get("bgm_id")
        return r

    logger.warning("番剧 %d 所有字幕组均无资源", bangumi_id)
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
      - 标题含中文引号/括号（如 "我爱你"），蜜柑搜索引擎不识别

    策略（依次尝试）：
      1. 原标题
      2. 去引号/括号的净化标题（如存在特殊字符）
      3. 季数变体：期↔季、阿拉伯↔汉字、空格↔下划线 的全组合（在原标题末尾有季标时）
      4. 去末尾季数后的基础标题
      5. 第一个空格/冒号/中点前的部分
      6. 净化后前6字（最后兜底）
    """
    variants: list[str] = [title]

    # ── 去引号/括号净化（放第二位，优先于季数变体）──────
    # 中文引号 “”、单引号 ‘’、日式/全角括号等
    # 在蜜柑搜索引擎里会导致 0 结果，需去除后重搜
    _PUNCT_CHARS = (
        "“”"   # " "  中文双引号
        "‘’"   # ‘ ‘  中文单引号
        "「」"   # 「」 日式括号
        "『』"   # 『』 日式书名号
        "（）"   # （） 全角圆括号
        "【】"   # 【】 全角方括号
        "〔〕"   # 〔〕 全角方括号2
        "《》"   # 《》 书名号
        "〈〉"   # 〈〉 单书名号
    )
    _PUNCT = str.maketrans("", "", _PUNCT_CHARS)
    clean_title = title.translate(_PUNCT).strip()
    if clean_title and clean_title != title and clean_title not in variants:
        variants.append(clean_title)

    # 后续变体既基于 title 也基于 clean_title（以 clean 版为基础做季数变体）
    _bases = dict.fromkeys([title, clean_title] if clean_title != title else [title])

    # ── 季数变体 ──────────────────────────────────────────
    for base_title in _bases:
        m = _SEASON_SUFFIX.search(base_title)
        if m:
            base = base_title[: m.start()]          # 季标前的主标题
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
    for base_title in _bases:
        no_season = _re.sub(
            r"[\s_]*(第[一二三四五六七八九十百\d]+[季期]|Season\s*\d+|S\d+)\s*$",
            "", base_title,
        ).strip()
        if no_season and no_season != base_title and no_season not in variants:
            variants.append(no_season)

    # ── 第一个分隔符前的部分 ──────────────────────────────
    for base_title in _bases:
        for sep in (" ", "：", ":", "·", "・", "～", "~"):
            idx = base_title.find(sep)
            if idx >= 3:
                part = base_title[:idx].strip()
                if part not in variants:
                    variants.append(part)
                break

    # ── 净化标题前6字兜底 ──────────────────────────────────
    # 以 clean_title 为基础，避免截断后首字是引号
    fallback_base = clean_title if clean_title else title
    if len(fallback_base) > 8:
        short = fallback_base[:6]
        if short not in variants:
            variants.append(short)

    return variants


# ── bgm.tv 搜索回退 ───────────────────────────────────────

import requests as _requests


def _bgm_canonical_names(title: str) -> "tuple[list[int], list[str]]":
    """
    用 bangumi.tv v0 API 搜索标题，返回 (bgm_id_list, [canonical_names])。

    bgm_id_list：按搜索结果顺序，最多 5 个 subject ID。
      用于在 season_index 中逐一匹配蜜柑当季番剧，解决同名多季时第一个 ID
      可能是旧季（如咒术回战第三期搜出「死灭回游」arc 对应的旧 ID）的问题。

    canonical_names：仅取第一个结果的中/日文名，供异体字兜底搜蜜柑用。
    """
    try:
        from urllib.parse import quote as _quote
        _hdrs = {"User-Agent": "zhuifanji/1.0", "Accept": "application/json"}

        # 旧版 API：排序与网站一致，能正确区分多季
        resp = _requests.get(
            f"https://api.bgm.tv/search/subject/{_quote(title)}",
            params={"type": 2, "responseGroup": "small", "max_results": 10},
            headers=_hdrs, timeout=6,
        )
        items = (resp.json().get("list") or []) if resp.ok else []

        # 旧版无结果时回退 v0 API（对错别字/异体字更宽容）
        if not items:
            resp2 = _requests.post(
                "https://api.bgm.tv/v0/search/subjects",
                params={"limit": 10},
                json={"keyword": title, "filter": {"type": [2]}},
                headers={**_hdrs, "Content-Type": "application/json"},
                timeout=6,
            )
            items = (resp2.json().get("data") or []) if resp2.ok else []
        if not items:
            return [], []

        # 收集最多 10 个有效 ID（先过滤无 id 条目，再截取前10）
        bgm_ids: list[int] = [item["id"] for item in items if item.get("id")][:10]

        # 只用第一个结果的名字做异体字兜底搜蜜柑，避免误用无关作品名
        first = items[0]
        names: list[str] = []
        cn = (first.get("name_cn") or "").strip()
        jp = (first.get("name") or "").strip()
        if cn:
            names.append(cn)
        if jp and jp != cn:
            names.append(jp)
        return bgm_ids, names
    except Exception as e:
        logger.debug("bgm 搜索失败 [%s]: %s", title, e)
        return [], []


# ── 季度索引（核心加速）─────────────────────────────────

import re as _re_mod   # requests 已作为 _requests 导入

_Q_TO_SEASON = {1: "冬", 2: "春", 3: "夏", 4: "秋"}
_SEASON_INDEX_TTL = 7 * 24 * 3600  # 7 天，与番剧页缓存一致


def quarter_to_season_params(quarter: str) -> "tuple[int, str]":
    """'2026Q2' → (2026, '春')"""
    year = int(quarter[:4])
    q    = int(quarter[5])
    return year, _Q_TO_SEASON[q]


def build_season_index(
    quarter: str,
    use_mirror: bool = False,
) -> "dict[int, int]":
    """
    预建 {bgm_id: bangumi_id} 索引，磁盘缓存 7 天。

    流程：
      1. 一次 HTTP 请求拿到蜜柑当季所有 bangumi_id
      2. 并行 fetch 每个番剧页，提取 bgm.tv subject_id
      3. 构建并缓存 {bgm_id: bangumi_id}

    之后订阅只需 bgm_search → bgm_id → dict[bgm_id] → find_best_rss，
    不再搜索蜜柑、不再逐个验证。
    """
    cache_key = f"season_index:{quarter}:{'mirror' if use_mirror else 'main'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("季度索引缓存命中：%s (%d 条)", quarter, len(cached))
        # cache 存的是 list of [bgm_id, bangumi_id]，还原为 dict
        if isinstance(cached, list):
            return {int(k): int(v) for k, v in cached}
        return cached

    year, season_str = quarter_to_season_params(quarter)
    base = MIKAN_MIRROR if use_mirror else MIKAN_BASE

    # Step 1: 获取季度页 bangumi_id 列表
    logger.info("构建蜜柑季度索引：%d %s ...", year, season_str)
    try:
        resp = _requests.get(
            f"{base}/Home/BangumiCoverFlowByDayOfWeek",
            params={"year": year, "seasonStr": season_str},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{base}/",
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning("获取蜜柑季度页失败：%s", e)
        return {}

    html = resp.text
    bangumi_ids = list(dict.fromkeys(
        int(m) for m in _re_mod.findall(r"/Home/Bangumi/(\d+)", html)
    ))
    logger.info("季度页找到 %d 个 bangumi_id", len(bangumi_ids))

    if not bangumi_ids:
        return {}

    # Step 2: 并行 fetch 所有番剧页，提取 bgm_id（标题已从季度页 HTML 直接拿到，省去半数请求）
    from concurrent.futures import ThreadPoolExecutor
    import requests as _req_lib
    from requests.adapters import HTTPAdapter
    from html import unescape as _unescape

    # 蜜柑对单 IP 高并发会限速/丢连接（实测 32 并发会触发 read timeout），
    # 且服务端本身近乎串行处理；16 并发是兼顾吞吐与稳定的折中。
    _WORKERS = 16

    index: dict[int, int] = {}        # bgm_id → bangumi_id
    title_index: dict[str, int] = {}  # 归一化标题 → bangumi_id（反查用）

    # ── 标题反查索引：直接解析季度页 HTML，零额外请求 ──
    # 季度页锚点形如：<a class="an-text" href="/Home/Bangumi/3884" target="_blank" title="番剧名">
    for _bid_str, _raw_title in _re_mod.findall(
        r'/Home/Bangumi/(\d+)"[^>]*?\btitle="([^"]*)"', html
    ):
        mikan_title = _unescape(_raw_title).strip()
        if not mikan_title:
            continue
        bid = int(_bid_str)
        base_title = _re_mod.sub(
            r"[\s　]*第[一二三四五六七八九十百\d]+[季期]$", "", mikan_title
        ).strip()
        if base_title:
            title_index.setdefault(base_title, bid)
        title_index[mikan_title] = bid

    # 共享 Session：连接池上限对齐 worker 数，避免高并发下连接持续丢弃/重建
    _sess = _req_lib.Session()
    _sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"{base}/",
    })
    _adapter = HTTPAdapter(pool_connections=_WORKERS, pool_maxsize=_WORKERS, max_retries=1)
    _sess.mount("https://", _adapter)
    _sess.mount("http://", _adapter)

    def _fetch_bgm_id(bid: int) -> "tuple[int, int | None, list | None]":
        """抓一次详情页：同时提取 bgm_id 和字幕组。

        返回 (bid, bgm_id, subgroups)；subgroups 为 None 表示走了缓存或抓取失败、
        无需回写（缓存写入统一在主线程批量进行，避免多线程并发写同一文件）。
        """
        ck = f"bangumi_data:{bid}:{'mirror' if use_mirror else 'main'}"
        cached_b = _cache_get(ck)
        if cached_b is not None and "bgm_id" in cached_b:
            return bid, cached_b.get("bgm_id"), None
        try:
            r = _sess.get(f"{base}/Home/Bangumi/{bid}", timeout=15)
            if r.ok:
                m = _re_mod.search(r"bgm\.tv/subject/(\d+)", r.text)
                bgm_id = int(m.group(1)) if m else None
                # 顺带解析字幕组，供后续「订阅」复用（结构对齐 _fetch_bangumi_data）
                try:
                    from scrapling.parser import Adaptor
                    subgroups = _parse_subgroups(Adaptor(r.text, url=r.url))
                except Exception:
                    subgroups = []
                return bid, bgm_id, subgroups
        except Exception as exc:
            logger.debug("fetch bgm_id bangumi=%d 失败: %s", bid, exc)
        return bid, None, None

    # 并行提取 bgm_id（命中缓存的直接返回）；新抓到的字幕组累积到主线程，循环后批量写
    fresh: dict[int, dict] = {}   # bid → {"subgroups": [...], "bgm_id": ...}
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for bid, bgm_id, subgroups in pool.map(_fetch_bgm_id, bangumi_ids):
            if bgm_id is not None:
                index[bgm_id] = bid
            if subgroups:  # 非空才回写（与原 _fetch_bangumi_data 行为一致）
                fresh[bid] = {"subgroups": subgroups, "bgm_id": bgm_id}

    _sess.close()
    logger.info("索引构建完成：bgm=%d条 标题=%d条（共%d番，新抓%d番）",
                len(index), len(title_index), len(bangumi_ids), len(fresh))

    # 批量写缓存：一次读-改-写，避免线程内并发写文件导致丢失/损坏
    data = _load_cache()
    ts = time.time()
    suffix = "mirror" if use_mirror else "main"
    for bid, val in fresh.items():
        data[f"bangumi_data:{bid}:{suffix}"] = {"ts": ts, "value": val}
    data[cache_key] = {"ts": ts, "value": [[k, v] for k, v in index.items()]}
    data[cache_key + ":titles"] = {"ts": ts, "value": [[k, v] for k, v in title_index.items()]}
    _save_cache(data)
    return index


def load_season_index_cached(
    quarter: str, use_mirror: bool = False
) -> "dict[int, int] | None":
    """只读已缓存的 {bgm_id: bangumi_id} 季度索引；未缓存返回 None（不触发构建）。

    供封面同步等「不想为此付一次 30-40s 冷构建」的场景复用：有缓存就借用，
    没有就走更轻的单次搜索匹配，绝不抢着重建当季索引、拖慢订阅页加载。
    """
    cache_key = f"season_index:{quarter}:{'mirror' if use_mirror else 'main'}"
    cached = _cache_get(cache_key)
    if cached is None:
        return None
    if isinstance(cached, list):
        return {int(k): int(v) for k, v in cached}
    return cached


def load_season_title_index(quarter: str, use_mirror: bool = False) -> "dict[str, int]":
    """返回 {归一化标题: bangumi_id}，由 build_season_index 构建时写入缓存。"""
    cache_key = f"season_index:{quarter}:{'mirror' if use_mirror else 'main'}:titles"
    cached = _cache_get(cache_key)
    if cached is None:
        return {}
    return {str(k): int(v) for k, v in cached}


def match_bangumi_id(
    title: str,
    season_index: "dict[int, int]",
    quarter: str = "",
    use_mirror: bool = False,
) -> "int | None":
    """仅做「标题 → 蜜柑 bangumi_id」匹配，不解析 RSS（供封面同步复用）。

    复用 resolve_anime_rss 的 season_index 命中逻辑，但省掉 find_best_rss：
      ① bgm API 全名搜索 → bgm_id_list → season_index 反查
      ② 季度标题反查索引兜底（剥掉「第X季/期」后缀）
    命中返回 bangumi_id，否则 None。
    """
    if season_index:
        bgm_id_list, _ = _bgm_canonical_names(title)
        for bgm_id in bgm_id_list:
            bid = season_index.get(bgm_id)
            if bid:
                return bid

    if quarter:
        title_idx = load_season_title_index(quarter, use_mirror)
        if title_idx:
            base_title = _re_mod.sub(
                r"[\s　]*第[一二三四五六七八九十百\d]+[季期].*$", "", title
            ).strip()
            bid = title_idx.get(title) or title_idx.get(base_title)
            if bid:
                return bid

    return None


def build_yuc_bgm_map(
    titles: "list[str]",
    season_index: "dict[int, int]",
    quarter: str,
    use_mirror: bool = False,
) -> "dict[str, int]":
    """
    为 yuc.wiki 番单标题建立 {title: bgm_id} 映射，缓存 7 天。

    第一步：title_index 直接/归一化匹配（无网络请求）。
    第二步：未命中的标题并行调 BGM API，用返回的 bgm_id_list 与
            season_index 比对，逻辑与订阅时的第二种匹配完全相同。

    season_index 在首次加载时已拿到当季全部 {bgm_id: bangumi_id}，
    所以只要 BGM API 返回的前 5 个 ID 里有当季条目，就能命中。
    """
    cache_key = f"yuc_bgm_map:{quarter}:{'mirror' if use_mirror else 'main'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {str(k): int(v) for k, v in cached}

    title_idx = load_season_title_index(quarter, use_mirror)

    # 归一化辅助
    def _norm(t: str) -> str:
        s = _re_mod.sub(
            r"[\s　]*(第[一二三四五六七八九十百\d]+[季期].*|Season\s*\d+.*|S\d+.*)$",
            "", t, flags=_re_mod.IGNORECASE,
        )
        return s.strip().replace(" ", "").replace("　", "")

    norm_title_idx: "dict[str, int]" = {_norm(k): v for k, v in title_idx.items()}
    result: "dict[str, int]" = {}
    unmatched: "list[str]" = []

    for title in titles:
        bid = title_idx.get(title) or norm_title_idx.get(_norm(title))
        if bid and bid in {v for v in season_index.values()}:
            # bangumi_id → bgm_id（从 season_index 反查）
            bgm_id = next((k for k, v in season_index.items() if v == bid), None)
            if bgm_id:
                result[title] = bgm_id
                continue
        unmatched.append(title)

    # 第二步：BGM API 搜索（并行，5 workers）
    if unmatched:
        from concurrent.futures import ThreadPoolExecutor as _TPE

        def _match(title: str) -> "tuple[str, int | None]":
            bgm_ids, _ = _bgm_canonical_names(title)
            for bgm_id in bgm_ids:
                if bgm_id in season_index:
                    return title, bgm_id
            return title, None

        with _TPE(max_workers=10) as pool:
            for title, bgm_id in pool.map(_match, unmatched):
                if bgm_id:
                    result[title] = bgm_id

    _cache_set(cache_key, [[k, v] for k, v in result.items()])
    logger.info("yuc→bgm 映射构建完成：%d/%d 命中", len(result), len(titles))
    return result


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


def _pick_best_fallback(
    title: str,
    candidates: list[dict],
    priorities: list[str],
    weeks: int,
    use_mirror: bool,
) -> "dict | None":
    """
    search_override 时使用：从候选列表中选 RSS 最近更新的番剧（不做 bgm 验证）。
    用于用户已明确知道搜索词时，对结果择优。
    """
    best_result: "dict | None" = None
    best_time: "datetime | None" = None

    for candidate in candidates:
        best = find_best_rss(candidate["id"], priorities, weeks, use_mirror)
        if best:
            latest = _latest_rss_time(candidate["id"], best["subgroup_id"], use_mirror)
            if best_result is None or (
                latest is not None and (best_time is None or latest > best_time)
            ):
                best_result = {
                    "title": title,
                    "bangumi_id": candidate["id"],
                    "bangumi_name": candidate["name"],
                    **best,
                }
                best_time = latest

    return best_result


def resolve_anime_rss(
    title: str,
    priorities: list[str],
    weeks: int = 4,
    use_mirror: bool = False,
    search_override: str | None = None,
    season_index: "dict[int, int] | None" = None,
    quarter: str = "",
) -> dict | None:
    """
    一步完成：搜索番剧 → 找最佳 RSS。

    两条路径：

    ① season_index 路径（有索引时）：
       bgm 全名搜一次 → bgm_id → season_index[bgm_id] → find_best_rss
       不做任何 mikanani 标题变体搜索。
       未命中（bgm 返回非当季 ID）→ None，用户用 search_override 手动重试。

    ② 无索引路径（无索引或 search_override）：
       search_override：直接用指定词搜蜜柑，跳过 bgm 验证。
       无 override：bgm 全名搜一次 → bgm_id，mikanani 标题搜索 + bgm_id 验证。
    """
    # ── search_override：用户手动指定搜索词，跳过 bgm 验证 ──
    if search_override:
        cands = search_bangumi(search_override.strip(), use_mirror)
        if not cands:
            logger.warning("override 搜索词 '%s' 在蜜柑无结果", search_override)
            return None
        return _pick_best_fallback(title, cands, priorities, weeks, use_mirror)

    # ── bgm 搜索（一次，全名，不做变形）────────────────────
    bgm_id_list, bgm_fallback_names = _bgm_canonical_names(title)
    target_bgm_id = bgm_id_list[0] if bgm_id_list else None
    logger.info("bgm_ids=%s  候选名=%s", bgm_id_list, bgm_fallback_names)

    # ── ① season_index 路径：直接查表，不搜蜜柑标题 ─────────
    if season_index is not None:
        # 按 bgm 搜索顺序逐一在 season_index 中查找，第一个命中即为当季正确条目
        bangumi_id = None
        for bgm_id in bgm_id_list:
            bangumi_id = season_index.get(bgm_id)
            if bangumi_id:
                if bgm_id != target_bgm_id:
                    logger.info("bgm_id 兜底命中：%d（排第%d位）→ mikan_id=%d",
                                bgm_id, bgm_id_list.index(bgm_id) + 1, bangumi_id)
                break

        # 未命中（bgm 返回老季 ID / bgm 找不到）→ 标题反查
        if not bangumi_id and quarter:
            title_idx = load_season_title_index(quarter, use_mirror)
            # 剥掉「第X期 Part.1」等整个季号+附加信息
            base_title = _re_mod.sub(
                r"[\s　]*第[一二三四五六七八九十百\d]+[季期].*$", "", title
            ).strip()
            bangumi_id = title_idx.get(title) or title_idx.get(base_title)
            if bangumi_id:
                logger.info("标题反查命中：'%s'(base=%r) → mikan_id=%d",
                            title, base_title, bangumi_id)
            else:
                logger.warning("'%s' bgm_id=%s 不在索引且无标题命中 → None",
                               title, target_bgm_id)

        if bangumi_id:
            best = find_best_rss(bangumi_id, priorities, weeks, use_mirror)
            if best:
                return {"title": title, "bangumi_id": bangumi_id,
                        "bangumi_name": title, **best}
            logger.warning("mikan_id=%d 无可用 RSS", bangumi_id)
        return None

    # season_index 不存在时才检查 bgm 结果
    if target_bgm_id is None:
        logger.warning("bgm.tv 未找到 '%s' → None", title)
        return None

    # ── ② 无索引路径：mikanani 标题搜索 + bgm_id 验证 ────────
    search_terms = _title_variants(title)

    bgm_id_set = set(bgm_id_list)

    def _find_bgm_match(cands: list[dict]) -> "dict | None":
        for c in cands:
            data = _fetch_bangumi_data(c["id"], use_mirror)
            mikan_bgm = data.get("bgm_id")
            logger.info("  mikan_id=%d mikan_bgm=%s targets=%s",
                        c["id"], mikan_bgm, bgm_id_list)
            if mikan_bgm in bgm_id_set:
                return c
        return None

    matched: "dict | None" = None

    # 并行跑 bgm（已完成）+第一词蜜柑搜索
    first_cands = search_bangumi(search_terms[0], use_mirror)
    if first_cands:
        matched = _find_bgm_match(first_cands)

    if matched is None:
        for term in search_terms[1:]:
            cands = search_bangumi(term, use_mirror)
            if cands:
                matched = _find_bgm_match(cands)
                if matched:
                    break

    # bgm 官方名称重搜（异体字兜底，如工坊→工房）
    if matched is None:
        for bgm_name in bgm_fallback_names:
            if bgm_name in search_terms:
                continue
            cands = search_bangumi(bgm_name, use_mirror)
            if cands:
                matched = _find_bgm_match(cands)
                if matched:
                    break

    if matched is None:
        logger.warning("bgm_ids=%s 蜜柑无匹配：'%s' → None", bgm_id_list, title)
        return None

    best = find_best_rss(matched["id"], priorities, weeks, use_mirror)
    if not best:
        return None
    return {"title": title, "bangumi_id": matched["id"],
            "bangumi_name": matched["name"], **best}


# ── RSS 集数去重过滤检测 ──────────────────────────────────

import re as _re2

# 简体中文相关标签（ANi/字幕组常用命名）
_CHS_PATTERN = _re2.compile(
    r'\bCHS\b'          # [CHS] 简体
    r'|CHS&CHT'         # [CHS&CHT] 双语
    r'|简体|GB(?!\d)'   # 中文"简体"或 GB 编码标记
    r'|\[简\]',
    _re2.IGNORECASE,
)
_JIAN_PATTERN = _re2.compile(r"简")

# 来源标签：原始词 → 标准化的 must_contain 字符串
_SOURCE_NORM = {
    "CR":          "CR",
    "CRUNCHYROLL": "CR",
    "BAHA":        "Baha",
    "BAHAMUT":     "Baha",
    "ABEMA":       "Abema",
    "B-GLOBAL":    "B-Global",
    "BILIBILI":    "Bilibili",
}

_SOURCE_PATTERN = _re2.compile(
    r'\b(?P<src>CR|Crunchyroll|Baha|Bahamut|Abema|B-Global|Bilibili)\b',
    _re2.IGNORECASE,
)

# 多来源时优先选取的顺序
_SOURCE_PRIORITY = ["B-Global", "Baha", "Abema", "CR", "Bilibili"]


def detect_rss_filter(rss_url: str) -> dict:
    """
    扫描 RSS 前 10 条条目，检测最优的去重过滤规则。

    策略（按优先级）：
      1. 检测到简体标记（CHS / 简繁内封 / 简体内嵌 / 简日 / [简] 等）
         → must_contain="(CHS|简)" use_regex=True，只下简体、放过纯繁体，
           同集多个简体变体由 smart_filter 去重。
      2. 多来源（CR + Abema 等）且无简体标记 → 按优先级锁定一个来源的
         must_contain，避免同集多源被同时下载（smart_filter 无法跨命名格式去重）。
      3. 都没命中 → must_contain="" smart_filter=True，回退到纯集数去重兜底。

    返回 dict 供 QBTClient.add_rss_feed 直接使用。
    """
    try:
        feed = feedparser.parse(rss_url)
        titles = [e.get("title", "") for e in feed.entries[:10]]
    except Exception:
        titles = []

    if not titles:
        return {
            "must_contain": "",
            "must_not_contain": "",
            "use_regex": False,
            "smart_filter": True,
        }

    def _filter_hits(
        items: list[str],
        must_contain: str,
        must_not_contain: str = "",
        use_regex: bool = False,
    ) -> int:
        if not must_contain and not must_not_contain:
            return len(items)
        n = 0
        if use_regex:
            try:
                must_re = _re2.compile(must_contain, _re2.IGNORECASE) if must_contain else None
                not_re = _re2.compile(must_not_contain, _re2.IGNORECASE) if must_not_contain else None
            except Exception:
                return 0
            for t in items:
                if must_re and not must_re.search(t):
                    continue
                if not_re and not_re.search(t):
                    continue
                n += 1
            return n

        for t in items:
            if must_contain and must_contain not in t:
                continue
            if must_not_contain and must_not_contain in t:
                continue
            n += 1
        return n

    # 简体中文标记：CHS / 简繁内封 / 简体内嵌 / [简] / 简日 / GB 等。
    # 统一用正则 (CHS|简) 锁定简体版本，命中即只下简体、放过纯繁体（繁体内嵌不含「简」）。
    #
    # 必须用 use_regex=True：qBittorrent 对非正则 must_contain 会按 \b<词>\b 词边界匹配，
    # 而「简」紧邻别的 CJK 字符（如「简日内嵌」「简体内嵌」）时 \b简\b 不成立 → 漏配。
    # 正则模式做子串匹配（无词边界），才能正确命中这些内嵌命名。
    has_simplified = any(_CHS_PATTERN.search(t) or _JIAN_PATTERN.search(t) for t in titles)
    if has_simplified:
        rule = {
            "must_contain": "(CHS|简)",
            "must_not_contain": "",
            "use_regex": True,
            "smart_filter": True,
        }
        # 兜底校验：正则确实能命中样本才采用，否则落到下面的来源/去重兜底
        if _filter_hits(titles, rule["must_contain"], use_regex=True) > 0:
            logger.info("RSS 检测到简体中文标记，设置 must_contain=(CHS|简) (regex) smart_filter=True")
            return rule

    # 收集所有出现的来源：key=归一化名（用于优先级比较），value=RSS 原始大小写（用于 must_contain）
    sources: dict[str, str] = {}   # norm_key → original_str
    for t in titles:
        m = _SOURCE_PATTERN.search(t)
        if m:
            norm_key = _SOURCE_NORM.get(m.group("src").upper())
            if norm_key and norm_key not in sources:
                sources[norm_key] = m.group("src")   # 保留 RSS 里的原始大小写

    if len(sources) > 1:
        # 多来源：按优先级选最优的一个来源，锁死 must_contain 避免重复下载
        # must_contain 已唯一定位来源，smart_filter 反而会让新规则跳过历史集数，关掉
        for preferred in _SOURCE_PRIORITY:
            if preferred in sources:
                contain_str = sources[preferred]
                logger.info("RSS 多来源 %s，锁定 must_contain=%s", set(sources), contain_str)
                return {
                    "must_contain": contain_str,
                    "must_not_contain": "",
                    "use_regex": False,
                    "smart_filter": False,
                }

    return {
        "must_contain": "",
        "must_not_contain": "",
        "use_regex": False,
        "smart_filter": True,
    }
