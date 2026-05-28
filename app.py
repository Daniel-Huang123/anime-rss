"""番剧自动订阅系统 — Streamlit 主页（Dashboard）。

启动：uv run streamlit run app.py
"""

import streamlit as st

from src.utils.config import load_config
from src.utils.season import current_quarter, list_season_options
from src.utils.state import get_all_subscriptions_flat, get_cleanup_log, get_quarters_to_cleanup

st.set_page_config(
    page_title="番剧订阅管理",
    page_icon="🎌",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🎌 番剧自动订阅管理")

# ── 配置读取 ──────────────────────────────────────────────
try:
    cfg = load_config()
    config_ok = True
except FileNotFoundError:
    st.error("⚠️ 找不到 config.yaml，请前往「设置」页面创建配置。")
    config_ok = False

# ── 概览卡片 ──────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("当前季度", current_quarter())

with col2:
    all_subs = get_all_subscriptions_flat()
    total = len(all_subs)
    st.metric("总订阅数", total)

with col3:
    quarters_set = {s["quarter"] for s in all_subs}
    st.metric("已跨季度", len(quarters_set))

with col4:
    to_clean = get_quarters_to_cleanup(cfg.get("cleanup", {}).get("keep_quarters", 2) if config_ok else 2)
    st.metric("待清理季度", len(to_clean), delta="需处理" if to_clean else None, delta_color="inverse")

st.divider()

# ── 当前季度订阅状态 ──────────────────────────────────────
st.subheader(f"📋 {current_quarter()} 订阅列表")

current_q_subs = [s for s in all_subs if s["quarter"] == current_quarter()]
if current_q_subs:
    import pandas as pd
    df = pd.DataFrame(current_q_subs)[["title", "subgroup_name", "added_at", "rss_url"]]
    df.columns = ["番剧", "字幕组", "订阅日期", "RSS URL"]
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("当前季度暂无订阅。请前往「季度订阅」页面添加。")

# ── 清理提示 ──────────────────────────────────────────────
if to_clean:
    st.warning(
        f"⚠️ 以下季度超过保留期限，建议清理：**{', '.join(to_clean)}**\n\n"
        "请前往「季度清理」页面操作。"
    )

# ── 媒体库快捷入口 ────────────────────────────────────────
st.divider()
st.subheader("🎬 媒体库")

import base64 as _b64
import hashlib as _hashlib
from pathlib import Path
from urllib.parse import quote as _quote

from src.utils.file_parser import scan_media_directory
from src.utils.state import get_all_subscriptions_flat as _get_subs

_COVER_CACHE = Path(__file__).parent / ".cover_cache"

def _dash_cover(folder) -> "bytes | None":
    """优先从 .cover_cache 取封面（与订阅页一致）。"""
    subs_map = {s["title"]: s for s in _get_subs()}
    sub = subs_map.get(folder.title, {})
    url = sub.get("cover_url") or (folder.cover_url if hasattr(folder, "cover_url") else None)
    if url:
        p = _COVER_CACHE / (_hashlib.md5(url.encode()).hexdigest() + ".jpg")
        if p.exists():
            return p.read_bytes()
    from src.utils.cover_cache import get_cover_path
    bid = sub.get("bangumi_id") if sub else None
    cp = get_cover_path(folder.title, bid)
    return cp.read_bytes() if cp and cp.exists() else None

def _dash_card(img_bytes: "bytes | None", title: str, ep_label: str, href: str) -> str:
    content = (
        f'<img src="data:image/jpeg;base64,{_b64.b64encode(img_bytes).decode()}" '
        f'style="width:100%;height:100%;object-fit:cover;display:block;">'
        if img_bytes else
        '<div style="display:flex;align-items:center;justify-content:center;'
        'height:100%;font-size:2.5em;color:#555;">🎬</div>'
    )
    hover = (
        '<div style="position:absolute;inset:0;background:rgba(0,0,0,0);'
        'display:flex;align-items:center;justify-content:center;'
        'color:#fff;font-size:0.9em;font-weight:600;opacity:0;'
        'transition:background .18s,opacity .18s;" '
        'onmouseover="this.style.background=\'rgba(0,0,0,.45)\';this.style.opacity=\'1\';" '
        'onmouseout="this.style.background=\'rgba(0,0,0,0)\';this.style.opacity=\'0\';">'
        '查看</div>'
    )
    link = f'<a href="{href}" target="_self" style="position:absolute;inset:0;"></a>'
    disp = (title[:9] + "…") if len(title) > 9 else title
    return (
        f'<div style="position:relative;width:100%;border-radius:8px;overflow:hidden;'
        f'background:#1e1e2e;aspect-ratio:5/7;">{content}{hover}{link}</div>'
        f'<p style="font-size:0.78em;font-weight:600;margin:4px 0 1px;'
        f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{disp}</p>'
        f'<p style="font-size:0.72em;color:#888;margin:0;">{ep_label}</p>'
    )

media_path = cfg.get("qbittorrent", {}).get("save_path", "").strip().strip('"').strip("'") if config_ok else ""
if media_path and Path(media_path).exists():
    with st.spinner("快速扫描..."):
        folders = scan_media_directory(media_path)

    if folders:
        recent = sorted(folders, key=lambda f: f.latest_mtime, reverse=True)[:8]
        cols = st.columns(len(recent))
        for col, folder in zip(cols, recent):
            latest = folder.latest_episode
            ep_label = latest.episode_label if latest else f"{folder.episode_count}集"
            href = f"pages/5_🎬_媒体库.py?anime={_quote(folder.title)}"
            with col:
                st.markdown(
                    _dash_card(_dash_cover(folder), folder.title, ep_label, href),
                    unsafe_allow_html=True,
                )
        st.page_link("pages/5_🎬_媒体库.py", label="→ 打开完整媒体库", icon="🎬")
    else:
        st.info("媒体目录暂无内容。")
else:
    st.info("前往「⚙️ 设置」配置下载路径后，媒体库将在此显示最近更新。")

# ── 使用指引 ──────────────────────────────────────────────
with st.expander("📖 使用指引", expanded=not total):
    st.markdown("""
1. **首次使用**：前往「⚙️ 设置」页面，填写 qBittorrent 账密并测试连接
2. **每季度初**：前往「📺 季度订阅」页面，从 yuc.wiki 加载番单，勾选想看的，点击订阅
3. **日常管理**：「📋 订阅管理」页面可查看/删除单个订阅
4. **季度清理**：「🗑️ 季度清理」页面删除超过 2 个季度的旧资源
5. **看番**：前往「🎬 媒体库」页面，点击番剧查看剧集，点击剧集用本地播放器播放
    """)
