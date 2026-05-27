"""季度订阅页面：卡片网格浏览 + 一键订阅。

UI 设计：
  - 5 列封面卡片，封面带绿色边框表示已订阅
  - 点击「＋ 订阅」按钮直接触发搜索并添加到 qBittorrent
  - 卡片底部同时显示集数（imgep）和首播时间（imgtext4）两行 metadata
"""

from __future__ import annotations

import base64

import requests
import streamlit as st

from src.qbt.client import QBTClient
from src.scrapers.mikanani import resolve_anime_rss
from src.scrapers.yuc_wiki import clear_cache, get_season_list
from src.utils.config import load_config
from src.utils.cover_cache import get_or_fetch_cover
from src.utils.season import list_season_options, quarter_to_ym
from src.utils.state import add_subscription, get_subscriptions

st.set_page_config(page_title="季度订阅", page_icon="📺", layout="wide")
st.title("📺 季度订阅")

# ── 配置 ──────────────────────────────────────────────────
try:
    cfg = load_config()
except FileNotFoundError:
    st.error("请先在「设置」页面完成配置。")
    st.stop()

priorities  = cfg.get("subtitle_priorities", ["ANi", "kirara"])
weeks       = cfg.get("resource_check", {}).get("recent_weeks", 4)
use_mirror  = cfg.get("advanced", {}).get("use_mirror", False)

qbt_cfg = cfg["qbittorrent"]
qbt = QBTClient(
    host=qbt_cfg["host"],
    port=qbt_cfg["port"],
    username=qbt_cfg["username"],
    password=qbt_cfg["password"],
)


# ── 封面下载（带 Bilibili CDN Referer 修正，session 级缓存）────
@st.cache_data(show_spinner=False)
def _cover_bytes(url: str) -> bytes | None:
    if not url:
        return None
    referer = "https://www.bilibili.com/" if "hdslb.com" in url or "bilibili" in url else "https://yuc.wiki/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
    }
    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.ok and len(r.content) > 500:
            return r.content
    except Exception:
        pass
    return None


def _cover_html(img_bytes: bytes | None, subscribed: bool) -> str:
    """生成封面 HTML：订阅 → 绿色边框，未订阅 → 暗灰色。"""
    border = "#00c853" if subscribed else "#2d2d2d"
    box_style = (
        f"border:3px solid {border};border-radius:8px;overflow:hidden;"
        f"background:#1e1e2e;aspect-ratio:5/7;"
    )
    if img_bytes:
        b64 = base64.b64encode(img_bytes).decode()
        return (
            f'<div style="{box_style}">'
            f'<img src="data:image/jpeg;base64,{b64}" '
            f'style="width:100%;height:100%;object-fit:cover;display:block;">'
            f'</div>'
        )
    return (
        f'<div style="{box_style}display:flex;align-items:center;'
        f'justify-content:center;font-size:2em;">🎬</div>'
    )


# ── 季度选择栏 ────────────────────────────────────────────
c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    season_options   = list_season_options(6)
    selected_quarter = st.selectbox("季度", season_options, index=0, label_visibility="collapsed")
with c2:
    load_btn    = st.button("🔄 加载番单", use_container_width=True)
with c3:
    refresh_btn = st.button("🔃 刷新缓存", use_container_width=True)

if refresh_btn:
    clear_cache()
    _cover_bytes.clear()
    st.session_state.pop("anime_list", None)
    st.session_state.pop("loaded_quarter", None)

if load_btn:
    st.session_state.pop("anime_list", None)

if "anime_list" not in st.session_state:
    year, month = quarter_to_ym(selected_quarter)
    with st.spinner(f"正在爬取 yuc.wiki/{year:04d}{month:02d} ..."):
        try:
            anime_list = get_season_list(year, month)
            st.session_state["anime_list"]      = anime_list
            st.session_state["loaded_quarter"]  = selected_quarter
        except Exception as e:
            st.error(f"加载失败：{e}")
            st.stop()

anime_list    = st.session_state.get("anime_list", [])
loaded_quarter = st.session_state.get("loaded_quarter", selected_quarter)

if not anime_list:
    st.info("点击「加载番单」开始")
    st.stop()

# ── 预加载已订阅集合（避免每卡多次读文件）─────────────────
subbed_titles: set[str] = {
    s["title"]
    for s in get_subscriptions(loaded_quarter).get(loaded_quarter, [])
}

sub_count = len(subbed_titles)

# ── 筛选栏 ───────────────────────────────────────────────
fc1, fc2 = st.columns([4, 1])
with fc1:
    search_kw = st.text_input(
        "搜索", placeholder="🔍 输入关键词筛选番名",
        label_visibility="collapsed",
    )
with fc2:
    hide_subbed = st.checkbox("隐藏已订阅", value=False)

display_list = anime_list
if search_kw:
    display_list = [a for a in display_list if search_kw.lower() in a["title"].lower()]
if hide_subbed:
    display_list = [a for a in display_list if a["title"] not in subbed_titles]

st.caption(
    f"**{loaded_quarter}** · 共 {len(anime_list)} 部 "
    f"· 已订阅 **{sub_count}** 部 · 显示 {len(display_list)} 部"
)
st.divider()

# ── 卡片网格 ─────────────────────────────────────────────
COLS = 5

for row_start in range(0, len(display_list), COLS):
    row_items = list(enumerate(display_list[row_start:row_start + COLS], start=row_start))
    cols = st.columns(COLS, gap="small")

    for col_obj, (gidx, anime) in zip(cols, row_items):
        title      = anime["title"]
        cover_url  = anime.get("cover_url") or ""
        broadcast  = anime.get("broadcast_time", "")
        episodes   = anime.get("episodes", "")
        day        = anime.get("day", "")
        is_sub     = title in subbed_titles

        with col_obj:
            # ── 封面 ──
            img_bytes = _cover_bytes(cover_url)
            st.markdown(_cover_html(img_bytes, is_sub), unsafe_allow_html=True)

            # ── 标题（最多 2 行） ──
            disp_title = title[:16] + "…" if len(title) > 16 else title
            st.markdown(
                f'<p style="font-size:0.8em;font-weight:600;margin:4px 0 2px;'
                f'line-height:1.3;min-height:2.4em;word-break:break-all;">'
                f'{disp_title}</p>',
                unsafe_allow_html=True,
            )

            # ── Metadata：播出时间 + 集数（两列均显示）──
            time_str = f"{day} {broadcast}".strip() if (day or broadcast) else ""
            if time_str:
                st.caption(f"🕐 {time_str}")
            if episodes:
                st.caption(f"📺 {episodes}")

            # ── 订阅按钮 / 已订阅标记 ──
            if is_sub:
                st.markdown(
                    '<p style="color:#00c853;font-size:0.85em;text-align:center;'
                    'margin:4px 0;font-weight:700;">✓ 已订阅</p>',
                    unsafe_allow_html=True,
                )
            else:
                if st.button("＋ 订阅", key=f"sub_{gidx}", use_container_width=True, type="primary"):
                    with st.spinner(f"订阅 {title[:12]}..."):
                        result = resolve_anime_rss(title, priorities, weeks, use_mirror)

                    if result is None:
                        st.error("蜜柑计划未找到合适资源", icon="❌")
                    else:
                        ok, qbt_msg = qbt.add_rss_feed(
                            url=result["rss_url"],
                            path=f"{loaded_quarter}/{title}",
                        )
                        if ok:
                            get_or_fetch_cover(title, result["bangumi_id"], cover_url or None)
                            add_subscription(
                                quarter=loaded_quarter,
                                title=title,
                                bangumi_id=result["bangumi_id"],
                                subgroup_id=result["subgroup_id"],
                                subgroup_name=result["subgroup_name"],
                                rss_url=result["rss_url"],
                                cover_url=cover_url or None,
                            )
                            # 更新本地已订阅集合，使封面立刻变绿（无需等完整 rerun）
                            subbed_titles.add(title)
                            st.rerun()
                        else:
                            st.warning(f"RSS 已找到但添加 qBit 失败：{qbt_msg}")
