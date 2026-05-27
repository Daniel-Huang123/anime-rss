"""爬取 yuc.wiki 获取当季番剧列表。

目标页面：https://yuc.wiki/YYYYMM
页面结构（静态 Hexo HTML）：
  - 每部番剧有一个 .date_title 做标题
  - .imgep 或 .imgtext2 显示集数
  - 按星期 table.date_ 分组
  - <details> 里有完整周表
"""

from __future__ import annotations

import logging
import re
import time
from functools import lru_cache

from scrapling import Fetcher

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def get_season_list(year: int, month: int) -> list[dict]:
    """
    爬取 yuc.wiki/YYYYMM，返回番剧列表。
    每条格式：
    {
        "title": str,         # 中文/日文标题（取 .date_title 内文本）
        "episodes": str,      # 集数描述，如 "12话" 或 "全12话"
        "day": str,           # 播出日，如 "周一"
        "status": str,        # "连载中" / "完结" / "未知"
        "platforms": list[str] # 播出平台
    }
    去掉重复，标题不为空。
    """
    url = f"https://yuc.wiki/{year:04d}{month:02d}"
    logger.info("爬取 yuc.wiki: %s", url)

    try:
        page = Fetcher(auto_match=False).get(url, stealthy_headers=True)
    except Exception as e:
        logger.error("请求 yuc.wiki 失败：%s", e)
        raise RuntimeError(f"无法访问 yuc.wiki（{url}）：{e}") from e

    return _parse_page(page)


def _parse_page(page) -> list[dict]:
    """解析 yuc.wiki 页面，提取番剧列表。"""
    results: list[dict] = []
    seen_titles: set[str] = set()

    # 当前播出日
    current_day = "未知"

    # 先收集所有 table.date_ 以确定播出日
    day_tables = page.css("table.date_")

    # 获取所有 div.div_date 容器（每部番剧一个）
    # 它们紧跟在 table.date_ 之后（同级 float:left div）
    # 策略：遍历页面所有元素，按顺序处理

    # yuc.wiki 结构：
    #   <table class="date_"><tr><td class="date2">周一 (月)</td></tr></table>
    #   <div style="float:left">
    #     <div class="div_date">...</div>
    #     <table width="120px"><tr><td class="date_title">标题</td></tr>
    #       <tr class="tr_area"><td><a href="...">平台</a></td></tr>
    #     </table>
    #   </div>

    # 获取所有 .date2 （播出日标签）
    # 获取所有 .date_title （番剧标题）
    # 通过 DOM 顺序关联

    # 简化策略：直接取所有 date_title，然后往上找最近的 date2
    all_titles = page.css("td.date_title")
    all_days = page.css("td.date2")

    # 建立「日期分隔符」的位置索引（用 HTML 文本位置模拟）
    # scrapling 不直接暴露文档顺序，所以用 text 内容辅助判断

    # 构建日期段列表：[(day_text, [titles...])]
    # 用另一种方式：先取整个 body 的 HTML，然后正则分割
    html = str(page.html_content) if hasattr(page, "html_content") else page.get_all_text("")

    # 尝试从 raw HTML 解析（更可靠）
    try:
        import html as html_lib
        raw = page.content  # scrapling Response.content 是原始 HTML 字符串
        results = _parse_html_raw(raw)
    except Exception as e:
        logger.warning("raw HTML 解析失败，降级到 CSS 选择器: %s", e)
        results = _parse_with_css(page)

    return results


def _parse_html_raw(html_content: str) -> list[dict]:
    """用 re + 简单解析从原始 HTML 提取番剧信息。"""
    from html.parser import HTMLParser

    results: list[dict] = []
    seen: set[str] = set()

    class YucParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.current_day = "未知"
            self._in_date2 = False
            self._in_date_title = False
            self._in_imgep = False
            self._in_imgtext2 = False
            self._in_tr_area = False
            self._in_platform_link = False
            self._current_title = ""
            self._current_ep = ""
            self._current_status = "连载中"
            self._current_platforms: list[str] = []
            self._pending_entry: dict | None = None
            self._td_class = ""
            self._tr_class = ""

        def handle_starttag(self, tag, attrs):
            attr_dict = dict(attrs)
            cls = attr_dict.get("class", "")

            if tag == "td" and "date2" in cls:
                self._in_date2 = True
            elif tag == "td" and "date_title" in cls:
                # 新番剧开始：先保存上一条
                self._flush()
                self._in_date_title = True
                self._current_title = ""
                self._current_ep = ""
                self._current_status = "连载中"
                self._current_platforms = []
            elif tag == "p" and "imgep" in cls:
                self._in_imgep = True
            elif tag == "p" and "imgtext2" in cls:
                self._in_imgtext2 = True
            elif tag == "tr" and "tr_area" in cls:
                self._in_tr_area = True
            elif tag == "a" and self._in_tr_area:
                self._in_platform_link = True

        def handle_endtag(self, tag):
            if tag == "td":
                self._in_date2 = False
                self._in_date_title = False
            elif tag == "p":
                self._in_imgep = False
                self._in_imgtext2 = False
            elif tag == "tr":
                self._in_tr_area = False
            elif tag == "a":
                self._in_platform_link = False

        def handle_data(self, data):
            text = data.strip()
            if not text:
                return
            if self._in_date2:
                # "周一 (月) [Monday]" → 取"周X"
                m = re.match(r"(周[一二三四五六日])", text)
                if m:
                    self.current_day = m.group(1)
            elif self._in_date_title:
                self._current_title += text
            elif self._in_imgep:
                self._current_ep = text
            elif self._in_imgtext2:
                if "完结" in text:
                    self._current_status = "完结"
            elif self._in_platform_link:
                self._current_platforms.append(text)

        def _flush(self):
            title = self._current_title.strip()
            if title and title not in seen:
                seen.add(title)
                results.append({
                    "title": title,
                    "episodes": self._current_ep or "未知",
                    "day": self.current_day,
                    "status": self._current_status,
                    "platforms": list(self._current_platforms),
                })

        def close(self):
            self._flush()
            super().close()

    parser = YucParser()
    parser.feed(html_content)
    parser.close()

    return results


def _parse_with_css(page) -> list[dict]:
    """降级方案：仅用 CSS 选择器提取标题列表（不含播出日信息）。"""
    results = []
    seen: set[str] = set()
    for td in page.css("td.date_title"):
        title = td.text.strip() if hasattr(td, "text") else str(td)
        if title and title not in seen:
            seen.add(title)
            results.append({
                "title": title,
                "episodes": "未知",
                "day": "未知",
                "status": "连载中",
                "platforms": [],
            })
    return results


def get_season_list_cached(year: int, month: int) -> list[dict]:
    """带缓存的获取（用于 Streamlit session，避免重复请求）。"""
    return get_season_list(year, month)


def clear_cache() -> None:
    get_season_list.cache_clear()
