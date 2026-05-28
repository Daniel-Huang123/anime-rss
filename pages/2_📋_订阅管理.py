"""订阅管理页面：查看所有订阅、删除单个或整季订阅。"""

import pandas as pd
import streamlit as st

from src.qbt.client import QBTClient
from src.utils.config import load_config
from src.utils.season import current_quarter
from src.utils.state import get_all_subscriptions_flat, remove_subscription
from src.utils.ui_refresh import apply_auto_refresh

st.set_page_config(page_title="订阅管理", page_icon="📋", layout="wide")
st.title("📋 订阅管理")

try:
    cfg = load_config()
except FileNotFoundError:
    st.error("请先在「设置」页面完成配置。")
    st.stop()

apply_auto_refresh(cfg, "subscription_manage")

qbt_cfg = cfg["qbittorrent"]
qbt_save_path = qbt_cfg.get("save_path", "").strip().strip('"').strip("'")
qbt = QBTClient(
    host=qbt_cfg["host"],
    port=qbt_cfg["port"],
    username=qbt_cfg["username"],
    password=qbt_cfg["password"],
)

# ── 加载订阅数据 ──────────────────────────────────────────
all_subs = get_all_subscriptions_flat()

if not all_subs:
    st.info("暂无订阅记录。请前往「季度订阅」页面添加。")
    st.stop()

# ── 按季度筛选 ────────────────────────────────────────────
quarters = sorted({s["quarter"] for s in all_subs}, reverse=True)
selected_q = st.selectbox("筛选季度", ["全部"] + quarters)

if selected_q != "全部":
    filtered = [s for s in all_subs if s["quarter"] == selected_q]
else:
    filtered = all_subs

st.caption(f"共 {len(filtered)} 条订阅")

# ── 展示表格 ──────────────────────────────────────────────
df = pd.DataFrame(filtered)[["quarter", "title", "subgroup_name", "added_at", "rss_url", "qbt_feed_path"]]
df.columns = ["季度", "番剧", "字幕组", "订阅日期", "RSS URL", "qBit路径"]

st.dataframe(df, use_container_width=True, hide_index=True)

st.divider()

# ── 删除单个订阅 ──────────────────────────────────────────
st.subheader("🗑️ 删除订阅")

col1, col2 = st.columns(2)
with col1:
    del_quarter = st.selectbox("季度", quarters, key="del_q")
with col2:
    quarter_titles = [s["title"] for s in all_subs if s["quarter"] == del_quarter]
    del_title = st.selectbox("番剧", quarter_titles if quarter_titles else ["（无）"], key="del_t")

del_also_qbt = st.checkbox("同时删除 qBittorrent RSS、种子和本地目录", value=True)

if st.button("🗑️ 删除", type="secondary", disabled=del_title == "（无）"):
    if del_also_qbt:
        feed_path = f"{del_quarter}/{del_title}"
        save_path = f"{qbt_save_path}/{del_quarter}/{del_title}" if qbt_save_path else ""
        ok, msg = qbt.unsubscribe(feed_path=feed_path, save_path=save_path)
        if ok:
            st.success(msg)
        else:
            st.warning(f"qBittorrent 删除失败（可能已部分不存在）：{msg}")

    removed = remove_subscription(del_quarter, del_title)
    if removed:
        st.success(f"✓ 已从记录中删除：{del_quarter} / {del_title}")
        st.rerun()
    else:
        st.error("未找到该订阅记录")
