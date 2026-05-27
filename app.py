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

# ── 使用指引 ──────────────────────────────────────────────
with st.expander("📖 使用指引", expanded=not total):
    st.markdown("""
1. **首次使用**：前往「⚙️ 设置」页面，填写 qBittorrent 账密并测试连接
2. **每季度初**：前往「📺 季度订阅」页面，从 yuc.wiki 加载番单，勾选想看的，点击订阅
3. **日常管理**：「📋 订阅管理」页面可查看/删除单个订阅
4. **季度清理**：「🗑️ 季度清理」页面删除超过 2 个季度的旧资源
    """)
