"""季度订阅页面：从 yuc.wiki 加载当季番单 → 勾选 → 批量添加到 qBittorrent。"""

import time

import pandas as pd
import streamlit as st

from src.qbt.client import QBTClient
from src.scrapers.mikanani import resolve_anime_rss
from src.scrapers.yuc_wiki import clear_cache, get_season_list
from src.utils.config import load_config
from src.utils.cover_cache import get_or_fetch_cover
from src.utils.season import list_season_options, quarter_to_ym
from src.utils.state import add_subscription, is_subscribed

st.set_page_config(page_title="季度订阅", page_icon="📺", layout="wide")
st.title("📺 季度订阅")

# ── 配置 ──────────────────────────────────────────────────
try:
    cfg = load_config()
except FileNotFoundError:
    st.error("请先在「设置」页面完成配置。")
    st.stop()

priorities = cfg.get("subtitle_priorities", ["ANi", "kirara"])
weeks = cfg.get("resource_check", {}).get("recent_weeks", 4)
delay = cfg.get("advanced", {}).get("request_delay", 1.0)
use_mirror = cfg.get("advanced", {}).get("use_mirror", False)

qbt_cfg = cfg["qbittorrent"]
qbt = QBTClient(
    host=qbt_cfg["host"],
    port=qbt_cfg["port"],
    username=qbt_cfg["username"],
    password=qbt_cfg["password"],
)

# ── 季度选择 ──────────────────────────────────────────────
col1, col2 = st.columns([2, 1])
with col1:
    season_options = list_season_options(6)
    selected_quarter = st.selectbox("选择季度", season_options, index=0)

with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    load_btn = st.button("🔄 从 yuc.wiki 加载番单", use_container_width=True)
    refresh_btn = st.button("🔃 刷新缓存重新加载", use_container_width=True)

# ── 加载番单 ──────────────────────────────────────────────
if refresh_btn:
    clear_cache()
    st.session_state.pop("anime_list", None)

if load_btn:
    st.session_state.pop("anime_list", None)

if "anime_list" not in st.session_state:
    year, month = quarter_to_ym(selected_quarter)
    with st.spinner(f"正在爬取 yuc.wiki/{year:04d}{month:02d} ..."):
        try:
            anime_list = get_season_list(year, month)
            st.session_state["anime_list"] = anime_list
            st.session_state["loaded_quarter"] = selected_quarter
            if anime_list:
                st.success(f"✓ 加载成功，共 {len(anime_list)} 部番剧")
        except Exception as e:
            st.error(f"加载失败：{e}")
            st.stop()

anime_list = st.session_state.get("anime_list", [])
loaded_quarter = st.session_state.get("loaded_quarter", selected_quarter)

if not anime_list:
    st.info("点击「从 yuc.wiki 加载番单」开始")
    st.stop()

# ── 封面网格预览（折叠） ──────────────────────────────────
with st.expander(f"🖼️ 番剧封面预览（{len(anime_list)} 部）", expanded=False):
    cover_cols = st.columns(8)
    for idx, anime in enumerate(anime_list[:40]):  # 最多展示40个
        with cover_cols[idx % 8]:
            cover_url = anime.get("cover_url")
            if cover_url:
                try:
                    st.image(cover_url, width=80, caption=anime["title"][:6])
                except Exception:
                    st.caption(anime["title"][:8])
            else:
                st.caption(f"🎬 {anime['title'][:6]}")

# ── 番单表格（可勾选）────────────────────────────────────
st.subheader(f"📋 {loaded_quarter} 番剧列表（{len(anime_list)} 部）")

# 构造 DataFrame
df_data = []
for a in anime_list:
    subscribed = is_subscribed(loaded_quarter, a["title"])
    df_data.append({
        "订阅": not subscribed,
        "番剧": a["title"],
        "集数": a["episodes"],
        "播出日": a["day"],
        "状态": a["status"],
        "平台": "、".join(a["platforms"][:3]) if a["platforms"] else "",
        "已订阅": "✓" if subscribed else "",
    })

df = pd.DataFrame(df_data)

# 筛选
col_f1, col_f2 = st.columns([3, 1])
with col_f1:
    search_kw = st.text_input("🔍 筛选番名", placeholder="输入关键词过滤")
with col_f2:
    hide_subscribed = st.checkbox("隐藏已订阅", value=True)

if search_kw:
    df = df[df["番剧"].str.contains(search_kw, case=False, na=False)]
if hide_subscribed:
    df = df[df["已订阅"] != "✓"]

edited_df = st.data_editor(
    df,
    column_config={
        "订阅": st.column_config.CheckboxColumn("订阅", default=True, width="small"),
        "番剧": st.column_config.TextColumn("番剧", width="large"),
        "集数": st.column_config.TextColumn("集数", width="small"),
        "播出日": st.column_config.TextColumn("播出日", width="small"),
        "状态": st.column_config.TextColumn("状态", width="small"),
        "平台": st.column_config.TextColumn("平台", width="medium"),
        "已订阅": st.column_config.TextColumn("已订阅", width="small"),
    },
    disabled=["番剧", "集数", "播出日", "状态", "平台", "已订阅"],
    use_container_width=True,
    hide_index=True,
    height=400,
)

selected = edited_df[edited_df["订阅"] == True]["番剧"].tolist()
already = [a["title"] for a in anime_list if is_subscribed(loaded_quarter, a["title"])]

col_s1, col_s2, col_s3 = st.columns([2, 2, 1])
with col_s1:
    st.caption(f"已勾选 **{len(selected)}** 部待订阅")
with col_s2:
    st.caption(f"已订阅 **{len(already)}** 部")
with col_s3:
    start_btn = st.button("🚀 开始订阅", type="primary", disabled=not selected, use_container_width=True)

# ── 批量订阅 ──────────────────────────────────────────────
if start_btn and selected:
    # 建立 title → cover_url 的映射（来自 yuc.wiki）
    cover_map = {a["title"]: a.get("cover_url") for a in anime_list}

    st.divider()
    st.subheader("⏳ 订阅进度")

    progress = st.progress(0)
    status_container = st.container()
    results_log = []

    total = len(selected)
    for i, title in enumerate(selected):
        with status_container:
            st.write(f"**[{i+1}/{total}]** 正在处理：{title} ...")

        yuc_cover_url = cover_map.get(title)

        # 1. 在蜜柑计划搜索
        result = resolve_anime_rss(title, priorities, weeks, use_mirror)

        if result is None:
            msg = f"❌ **{title}** — 蜜柑计划未找到合适资源"
            results_log.append(("error", msg))
        else:
            # 2. 下载封面（优先用 yuc.wiki，备选 mikanani）
            cover_url_to_save = yuc_cover_url
            cover_path = get_or_fetch_cover(
                title=title,
                bangumi_id=result["bangumi_id"],
                cover_url=yuc_cover_url,
            )

            # 3. 添加 RSS 到 qBittorrent
            ok, qbt_msg = qbt.add_rss_feed(
                url=result["rss_url"],
                path=f"{loaded_quarter}/{title}",
            )

            if ok:
                # 4. 保存到 state.json（含封面 URL）
                add_subscription(
                    quarter=loaded_quarter,
                    title=title,
                    bangumi_id=result["bangumi_id"],
                    subgroup_id=result["subgroup_id"],
                    subgroup_name=result["subgroup_name"],
                    rss_url=result["rss_url"],
                    cover_url=cover_url_to_save,
                )
                cover_hint = "🖼️" if cover_path else ""
                msg = f"✅ **{title}** — 字幕组：{result['subgroup_name']} {cover_hint}"
                results_log.append(("success", msg))
            else:
                msg = f"⚠️ **{title}** — RSS 已找到但添加 qBit 失败：{qbt_msg}"
                results_log.append(("warning", msg))

        progress.progress((i + 1) / total)
        time.sleep(delay)

    # 汇总结果
    st.divider()
    success = sum(1 for t, _ in results_log if t == "success")
    error   = sum(1 for t, _ in results_log if t == "error")
    warning = sum(1 for t, _ in results_log if t == "warning")
    st.success(f"完成！成功 {success} 部 | 失败 {error} 部 | 警告 {warning} 部")

    for typ, msg in results_log:
        if typ == "success":
            st.success(msg)
        elif typ == "error":
            st.error(msg)
        else:
            st.warning(msg)

    st.session_state.pop("anime_list", None)
