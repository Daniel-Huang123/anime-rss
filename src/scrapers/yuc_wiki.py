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
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


@lru_cache(maxsize=8)
def get_season_list(year: int, month: int) -> list[dict]:
    """
    爬取 yuc.wiki/YYYYMM，返回番剧列表。
    每条格式：
    {
        "title": str,          # 中文/日文标题（取 .date_title 内文本）
        "episodes": str,       # 集数描述，如 "12话" 或 "全12话"
        "day": str,            # 播出日，如 "周一"
        "status": str,         # "连载中" / "完结" / "未知"
        "platforms": list[str],# 播出平台
        "cover_url": str|None, # 封面图 URL（来自 img data-src）
    }
    去掉重复，标题不为空。
    yuc.wiki 是纯静态 Hexo 站点，无 Cloudflare，直接用 requests 即可。
    """
    url = f"https://yuc.wiki/{year:04d}{month:02d}"
    logger.info("爬取 yuc.wiki: %s", url)

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
    except Exception as e:
        logger.error("请求 yuc.wiki 失败：%s", e)
        raise RuntimeError(f"无法访问 yuc.wiki（{url}）：{e}") from e

    return _parse_html_raw(resp.text)


def _parse_html_raw(html_content: str) -> list[dict]:
    """用 HTMLParser 从原始 HTML 提取番剧信息（含封面 data-src）。

    yuc.wiki 的每部番剧 HTML 结构：
      <div style="float:left">
        <div class="div_date">
          <p class="imgtext2">完结</p>
          <p class="imgep">(全12话)</p>
          <img width="120px" data-src="https://xxx.jpg">  ← 封面
        </div>
        <table width="120px">
          <tr><td class="date_title">番剧标题</td></tr>
          <tr class="tr_area"><td><a href="...">Bilibili</a></td></tr>
        </table>
      </div>

    关键点：img 在 date_title 之前，所以用 pending_cover 暂存，
    遇到 date_title 时把 pending_cover 关联到本条目。
    """
    from html.parser import HTMLParser

    results: list[dict] = []
    seen: set[str] = set()

    class YucParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.current_day = "未知"

            # 状态标志
            self._in_date2 = False
            self._in_date_title = False
            self._in_imgep = False
            self._in_imgtext2 = False
            self._in_tr_area = False
            self._in_platform_link = False
            self._in_div_date = False   # <div class="div_date"> 内部

            # 当前番剧临时数据
            self._current_title = ""
            self._current_ep = ""
            self._current_status = "连载中"
            self._current_platforms: list[str] = []
            self._pending_cover: str = ""   # div_date 里的 data-src 暂存

        def handle_starttag(self, tag, attrs):
            attr_dict = dict(attrs)
            cls = attr_dict.get("class", "")

            if tag == "div" and "div_date" in cls:
                self._in_div_date = True

            elif tag == "img" and self._in_div_date:
                # 封面图（懒加载用 data-src）
                src = attr_dict.get("data-src") or attr_dict.get("src", "")
                if src and ("jpg" in src or "png" in src or "webp" in src or "jpeg" in src):
                    self._pending_cover = src

            elif tag == "td" and "date2" in cls:
                self._in_date2 = True

            elif tag == "td" and "date_title" in cls:
                # 新番剧开始 → flush 上一条，重置状态
                self._flush()
                self._in_date_title = True
                self._current_title = ""
                self._current_ep = ""
                self._current_status = "连载中"
                self._current_platforms = []
                # pending_cover 不重置，它属于紧接着的这个 date_title

            elif tag == "p" and "imgep" in cls:
                self._in_imgep = True
            elif tag == "p" and "imgtext2" in cls:
                self._in_imgtext2 = True
            elif tag == "tr" and "tr_area" in cls:
                self._in_tr_area = True
            elif tag == "a" and self._in_tr_area:
                self._in_platform_link = True

        def handle_endtag(self, tag):
            if tag == "div":
                self._in_div_date = False
            elif tag == "td":
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
                    "cover_url": self._pending_cover or None,
                })
            # 封面用完就清，避免串到下一条
            self._pending_cover = ""

        def close(self):
            self._flush()
            super().close()

    parser = YucParser()
    parser.feed(html_content)
    parser.close()

    return results



def get_season_list_cached(year: int, month: int) -> list[dict]:
    """带缓存的获取（用于 Streamlit session，避免重复请求）。"""
    return get_season_list(year, month)


def clear_cache() -> None:
    get_season_list.cache_clear()
