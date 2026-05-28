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
        """
        yuc.wiki 的每个番剧块结构：
          <div style="float:left">
            <div class="div_date">          ← _in_div_date
              <p class="imgtext4">21:00~</p> ← _pending_broadcast_time
              <p class="imgep">(全12话)</p>
              <img data-src="cover.jpg">     ← _pending_cover
            </div>
            <div>
              <table>
                <td class="date_title_">标题[<br>第5话]</td>  ← 触发 flush
                <tr class="tr_area"><a>平台</a></tr>
              </table>
            </div>
          </div>

        关键设计：img/imgtext4 在 date_title 之前出现，所以用 _pending_*
        保存，等 date_title 触发时先 flush 上一部，再把 _pending_* 转移到
        _current_* 供新番剧使用。
        """

        def __init__(self):
            super().__init__()
            self.current_day = "未知"

            # 状态标志
            self._in_date2 = False
            self._in_date_title = False
            self._title_done = False      # 遇到集数型 <br> 后停止捕获标题
            self._title_br_pending = False  # 遇到 <br> 暂存，等下一段文字判断
            self._in_imgep = False
            self._in_imgtext4 = False     # 播出时间段，如 "21:00~"
            self._in_imgtext2 = False     # 状态（完结等）
            self._in_tr_area = False
            self._in_platform_link = False
            self._in_div_date = False

            # pending：在 div_date 内收集，属于"即将到来"的番剧
            self._pending_cover: str = ""
            self._pending_broadcast_time: str = ""
            self._pending_ep: str = ""
            self._pending_status: str = ""

            # current：属于"正在处理"的番剧（date_title 触发后填入）
            self._current_title = ""
            self._current_ep = ""
            self._current_cover: str = ""
            self._current_broadcast_time: str = ""
            self._current_status = "连载中"
            self._current_platforms: list[str] = []

        def handle_starttag(self, tag, attrs):
            attr_dict = dict(attrs)
            cls = attr_dict.get("class", "")

            if tag == "div" and "div_date" in cls:
                self._in_div_date = True

            elif tag == "img" and self._in_div_date:
                src = attr_dict.get("data-src") or attr_dict.get("src", "")
                if src and any(ext in src for ext in ("jpg", "png", "webp", "jpeg")):
                    self._pending_cover = src

            elif tag == "td" and "date2" in cls:
                self._in_date2 = True

            elif tag == "td" and "date_title" in cls:
                # ★ 核心修复：
                #   1. flush 上一部（使用 _current_* 变量，与 _pending_* 无关）
                #   2. 把 _pending_* 转移到 _current_*，开始构建新番剧
                self._flush()
                self._in_date_title = True
                self._title_done = False
                self._current_title = ""
                self._current_platforms = []
                # 转移 pending → current
                self._current_cover = self._pending_cover
                self._current_broadcast_time = self._pending_broadcast_time
                self._current_ep = self._pending_ep
                self._current_status = self._pending_status or "连载中"
                self._pending_cover = ""
                self._pending_broadcast_time = ""
                self._pending_ep = ""
                self._pending_status = ""

            elif tag == "br" and self._in_date_title and not self._title_done:
                # 暂不立即截断：等下一个文字片段判断是"集数"还是标题续行
                self._title_br_pending = True

            elif tag == "p" and "imgep" in cls:
                self._in_imgep = True
            elif tag == "p" and "imgtext4" in cls:
                self._in_imgtext4 = True
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
                self._title_done = False
                self._title_br_pending = False
            elif tag == "p":
                self._in_imgep = False
                self._in_imgtext4 = False
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
                elif "网络放送" in text or "其他" in text:
                    self.current_day = "其他"
            elif self._in_date_title and not self._title_done:
                if self._title_br_pending:
                    self._title_br_pending = False
                    # 判断 <br> 后的内容：
                    #   集数标记（第X话/集、EP X）→ 截断，不加入标题
                    #   季号标记（第X季/期）     → 追加到标题（如"第4期"）
                    #   其他                     → 视为标题续行
                    _EP_PATTERN = re.compile(
                        r"^第[一二三四五六七八九十百\d]+[话集]"
                        r"|^\d+话"
                        r"|^EP\d+",
                        re.IGNORECASE,
                    )
                    _SEASON_PATTERN = re.compile(
                        r"^第[一二三四五六七八九十百\d]+[季期]",
                    )
                    if _EP_PATTERN.match(text):
                        self._title_done = True
                        return  # 集数标记，截断
                    if _SEASON_PATTERN.match(text):
                        self._current_title += " " + text  # 季号追加到标题
                        self._title_done = True
                        return
                # 续行加空格（避免"动物狂想曲最终章"这样粘连）
                self._current_title += (" " if self._current_title else "") + text
            elif self._in_imgep:
                self._pending_ep = text
            elif self._in_imgtext4:
                # imgtext4 在 div_date 内，此时尚未进入 date_title，存入 pending
                self._pending_broadcast_time = text
            elif self._in_imgtext2:
                if "完结" in text:
                    self._pending_status = "完结"
            elif self._in_platform_link:
                self._current_platforms.append(text)

        def _flush(self):
            title = self._current_title.strip()
            if title and title not in seen:
                seen.add(title)
                results.append({
                    "title": title,
                    "episodes": self._current_ep or "",
                    "broadcast_time": self._current_broadcast_time or "",
                    "day": self.current_day,
                    "status": self._current_status,
                    "platforms": list(self._current_platforms),
                    "cover_url": self._current_cover or None,
                })
            # 清空 current（pending 由 date_title 负责管理）
            self._current_cover = ""
            self._current_broadcast_time = ""

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
