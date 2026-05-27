"""季度订阅页面：卡片网格 + 响应式列数 + 按播出日分组 + 一键订阅。

响应式原理：
  所有番剧卡片放在同一个 st.columns(n) 中，注入 CSS 让宽度固定为 145px 并
  允许换行（flex-wrap）。窗口变宽时一行容纳更多卡片，变窄时自动折叠。
  CSS 选择器只命中 ≥4 列的 stHorizontalBlock，不影响顶部控制栏。
"""

from __future__ import annotations

import base64
from collections import defaultdict

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

# ── 响应式卡片 CSS ──────────────────────────────────────────
st.markdown("""
<style>
/* 只对 ≥4 列的 HorizontalBlock 生效（控制栏最多3列，不受影响） */
[data-testid="stHorizontalBlock"]:has(>[data-testid="stColumn"]:nth-child(4)) {
    flex-wrap: wrap !important;
    row-gap: 12px !important;
}
[data-testid="stHorizontalBlock"]:has(>[data-testid="stColumn"]:nth-child(4))
    > [data-testid="stColumn"] {
    flex: 0 0 145px !important;
    min-width: 145px !important;
    max-width: 145px !important;
}
</style>
""", unsafe_allow_html=True)

st.title("📺 季度订阅")

# ── 配置 ──────────────────────────────────────────────────
try:
    cfg = load_config()
except FileNotFoundError:
    st.error("请先在「设置」页面完成配置。")
    st.stop()

priorities = cfg.get("subtitle_priorities", ["ANi", "kirara"])
weeks      = cfg.get("resource_check", {}).get("recent_weeks", 4)
use_mirror = cfg.get("advanced", {}).get("use_mirror", False)
qbt_cfg    = cfg["qbittorrent"]
qbt = QBTClient(
    host=qbt_cfg["host"], port=qbt_cfg["port"],
    username=qbt_cfg["username"], password=qbt_cfg["password"],
)

# ── 封面下载（Bilibili CDN 需 bilibili.com Referer）─────────
@st.cache_data(show_spinner=False)
def _cover_bytes(url: str) -> bytes | None:
    if not url:
        return None
    referer = (
        "https://www.bilibili.com/"
        if ("hdslb.com" in url or "bilibili" in url)
        else "https://yuc.wiki/"
    )
    try:
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": referer,
        }, timeout=8)
        if r.ok and len(r.content) > 500:
            return r.content
    except Exception:
        pass
    return None


def _cover_html(img_bytes: bytes | None, subscribed: bool) -> str:
    border = "#00c853" if subscribed else "#2d2d2d"
    style = (
        f"border:3px solid {border};border-radius:8px;overflow:hidden;"
        f"background:#1e1e2e;aspect-ratio:5/7;"
    )
    if img_bytes:
        b64 = base64.b64encode(img_bytes).decode()
        return (
            f'<div style="{style}">'
            f'<img src="data:image/jpeg;base64,{b64}" '
            f'style="width:100%;height:100%;object-fit:cover;display:block;">'
            f'</div>'
        )
    return (
        f'<div style="{style}display:flex;align-items:center;'
        f'justify-content:center;font-size:2em;">🎬</div>'
    )


# ── 季度选择栏 ────────────────────────────────────────────
c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    selected_quarter = st.selectbox(
        "季度", list_season_options(6), index=0, label_visibility="collapsed"
    )
with c2:
    load_btn = st.button("🔄 加载番单", use_container_width=True)
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
            st.session_state["anime_list"]     = anime_list
            st.session_state["loaded_quarter"] = selected_quarter
        except Exception as e:
            st.error(f"加载失败：{e}")
            st.stop()

anime_list     = st.session_state.get("anime_list", [])
loaded_quarter = st.session_state.get("loaded_quarter", selected_quarter)

if not anime_list:
    st.info("点击「加载番单」开始")
    st.stop()

# ── 已订阅集合（预加载，避免每卡多次读文件）──────────────
subbed_titles: set[str] = {
    s["title"]
    for s in get_subscriptions(loaded_quarter).get(loaded_quarter, [])
}

# ── 筛选栏 ───────────────────────────────────────────────
fc1, fc2 = st.columns([4, 1])
with fc1:
    search_kw = st.text_input(
        "搜索", placeholder="🔍 输入关键词筛选",
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
    f"· 已订阅 **{len(subbed_titles)}** 部 "
    f"· 显示 {len(display_list)} 部"
)

# ── 按播出日分组 ──────────────────────────────────────────
DAY_ORDER = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 建立 全局索引 → anime 的映射（用于 button key 唯一性）
indexed = list(enumerate(display_list))  # [(global_idx, anime), ...]

day_groups: dict[str, list[tuple[int, dict]]] = defaultdict(list)
for gidx, anime in indexed:
    day_groups[anime.get("day", "未知")].append((gidx, anime))

ordered_days = [d for d in DAY_ORDER if d in day_groups] + \
               [d for d in day_groups if d not in DAY_ORDER]

st.divider()

for day in ordered_days:
    items = day_groups[day]
    sub_n = sum(1 for _, a in items if a["title"] in subbed_titles)

    # ── 日期标题 ──
    sub_hint = f" · ✓ {sub_n}" if sub_n else ""
    st.markdown(
        f'<div style="font-weight:700;font-size:1.05em;margin:4px 0 6px;">'
        f'{day}'
        f'<span style="color:#888;font-weight:400;font-size:0.82em;margin-left:6px;">'
        f'{len(items)} 部{sub_hint}</span></div>',
        unsafe_allow_html=True,
    )

    # ── 卡片行（CSS flex-wrap 让其自动换行）──
    # max(len, 4) 确保至少 4 列，触发响应式 CSS
    n_cols = max(len(items), 4)
    cols   = st.columns(n_cols)

    for col_obj, (gidx, anime) in zip(cols, items):
        title     = anime["title"]
        cover_url = anime.get("cover_url") or ""
        broadcast = anime.get("broadcast_time", "")
        episodes  = anime.get("episodes", "")
        day_label = anime.get("day", "")
        is_sub    = title in subbed_titles

        with col_obj:
            # 封面
            img_bytes = _cover_bytes(cover_url)
            st.markdown(_cover_html(img_bytes, is_sub), unsafe_allow_html=True)

            # 标题（≤16字，超出截断）
            disp = title[:15] + "…" if len(title) > 15 else title
            st.markdown(
                f'<p style="font-size:0.8em;font-weight:600;margin:4px 0 2px;'
                f'line-height:1.3;min-height:2.4em;word-break:break-all;">'
                f'{disp}</p>',
                unsafe_allow_html=True,
            )

            # Metadata：播出时间 + 集数
            time_str = f"{broadcast}".strip()
            if time_str:
                st.caption(f"🕐 {time_str}")
            if episodes:
                st.caption(f"📺 {episodes}")

            # 订阅按钮 / 已订阅标记 / 搜索失败重试
            fail_key   = f"fail_{gidx}"
            retry_key  = f"retry_term_{gidx}"

            if is_sub:
                st.markdown(
                    '<p style="color:#00c853;font-size:0.85em;text-align:center;'
                    'margin:4px 0;font-weight:700;">✓ 已订阅</p>',
                    unsafe_allow_html=True,
                )

            elif st.session_state.get(fail_key):
                # ── 失败重试区 ──────────────────────────────
                st.markdown(
                    '<p style="color:#ff4b4b;font-size:0.75em;text-align:center;'
                    'margin:2px 0;">❌ 未找到</p>',
                    unsafe_allow_html=True,
                )
                custom_term = st.text_input(
                    "搜索词", key=f"ct_{gidx}",
                    value=st.session_state.get(retry_key, title),
                    label_visibility="collapsed",
                    placeholder="修改蜜柑搜索词",
                )
                c_retry, c_cancel = st.columns(2)
                with c_retry:
                    do_retry = st.button("重试", key=f"rb_{gidx}",
                                        use_container_width=True, type="primary")
                with c_cancel:
                    if st.button("取消", key=f"rc_{gidx}", use_container_width=True):
                        st.session_state.pop(fail_key, None)
                        st.rerun()

                if do_retry:
                    st.session_state[retry_key] = custom_term
                    with st.spinner("重试中..."):
                        result = resolve_anime_rss(
                            title, priorities, weeks, use_mirror,
                            search_override=custom_term,
                        )
                    if result is None:
                        st.error("仍然未找到", icon="❌")
                    else:
                        ok, qbt_msg = qbt.add_rss_feed(
                            url=result["rss_url"],
                            path=f"{loaded_quarter}/{title}",
                        )
                        if ok:
                            get_or_fetch_cover(title, result["bangumi_id"], cover_url or None)
                            add_subscription(
                                quarter=loaded_quarter, title=title,
                                bangumi_id=result["bangumi_id"],
                                subgroup_id=result["subgroup_id"],
                                subgroup_name=result["subgroup_name"],
                                rss_url=result["rss_url"],
                                cover_url=cover_url or None,
                            )
                            subbed_titles.add(title)
                            st.session_state.pop(fail_key, None)
                            st.rerun()
                        else:
                            st.warning(qbt_msg)

            else:
                # ── 正常订阅按钮 ────────────────────────────
                if st.button("＋ 订阅", key=f"sub_{gidx}",
                             use_container_width=True, type="primary"):
                    with st.spinner(f"订阅 {title[:12]}..."):
                        result = resolve_anime_rss(title, priorities, weeks, use_mirror)

                    if result is None:
                        # 记录失败，显示重试 UI
                        st.session_state[fail_key]  = True
                        st.session_state[retry_key] = title
                        st.rerun()
                    else:
                        ok, qbt_msg = qbt.add_rss_feed(
                            url=result["rss_url"],
                            path=f"{loaded_quarter}/{title}",
                        )
                        if ok:
                            get_or_fetch_cover(title, result["bangumi_id"], cover_url or None)
                            add_subscription(
                                quarter=loaded_quarter, title=title,
                                bangumi_id=result["bangumi_id"],
                                subgroup_id=result["subgroup_id"],
                                subgroup_name=result["subgroup_name"],
                                rss_url=result["rss_url"],
                                cover_url=cover_url or None,
                            )
                            subbed_titles.add(title)
                            st.rerun()
                        else:
                            st.warning(f"RSS 已找到但添加 qBit 失败：{qbt_msg}")

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    st.divider()
