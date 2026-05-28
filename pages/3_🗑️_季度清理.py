"""季度清理页面：删除超过保留期限的旧季度种子和 RSS 订阅。"""

import pandas as pd
import streamlit as st

from src.qbt.client import QBTClient
from src.utils.config import load_config
from src.utils.state import (
    get_cleanup_log,
    get_quarters_to_cleanup,
    get_subscriptions,
    log_cleanup,
    remove_subscription,
)
from src.utils.ui_refresh import apply_auto_refresh

st.set_page_config(page_title="季度清理", page_icon="🗑️", layout="wide")
st.title("🗑️ 季度清理")

try:
    cfg = load_config()
except FileNotFoundError:
    st.error("请先在「设置」页面完成配置。")
    st.stop()

apply_auto_refresh(cfg, "quarter_cleanup")

keep_quarters = cfg.get("cleanup", {}).get("keep_quarters", 2)
delete_files = cfg.get("cleanup", {}).get("delete_files", True)

qbt_cfg = cfg["qbittorrent"]
qbt = QBTClient(
    host=qbt_cfg["host"],
    port=qbt_cfg["port"],
    username=qbt_cfg["username"],
    password=qbt_cfg["password"],
)

st.info(f"当前配置：保留最近 **{keep_quarters}** 个季度的资源，超过则列为待清理。")

# ── 待清理季度 ─────────────────────────────────────────────
to_clean = get_quarters_to_cleanup(keep_quarters)

if not to_clean:
    st.success("✅ 没有需要清理的季度，一切整洁！")
else:
    st.warning(f"以下 **{len(to_clean)}** 个季度需要清理：{', '.join(to_clean)}")

    # 展示将被清理的订阅列表
    clean_items = []
    for q in to_clean:
        subs = get_subscriptions(q).get(q, [])
        for s in subs:
            clean_items.append({
                "季度": q,
                "番剧": s["title"],
                "字幕组": s["subgroup_name"],
                "RSS路径": s["qbt_feed_path"],
            })

    if clean_items:
        st.dataframe(pd.DataFrame(clean_items), use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        del_files = st.checkbox("同时删除下载的文件", value=delete_files)
    with col2:
        del_rss = st.checkbox("同时删除 qBittorrent RSS 订阅", value=True)

    st.error(
        f"⚠️ 此操作将删除 **{len(clean_items)}** 条订阅记录"
        + ("及相关下载文件" if del_files else "")
        + "，不可撤销！"
    )

    if st.button("🗑️ 确认清理", type="primary"):
        cleaned_count = 0
        errors = []

        for q in to_clean:
            subs = get_subscriptions(q).get(q, [])

            for s in subs:
                # 删除 qBit RSS
                if del_rss:
                    ok, msg = qbt.remove_rss_feed(s["qbt_feed_path"])
                    if not ok:
                        errors.append(f"RSS删除失败 {s['qbt_feed_path']}: {msg}")

                # 删除 qBit 种子（通过 tag 匹配季度）
                if del_files:
                    count, msg = qbt.delete_torrents_by_tag(q, delete_files=True)
                    cleaned_count += count

                # 删除状态记录
                remove_subscription(q, s["title"])

            log_cleanup(q, len(subs))

        if errors:
            for e in errors:
                st.warning(e)

        st.success(f"✅ 清理完成！删除订阅记录 {len(clean_items)} 条，种子 {cleaned_count} 个。")
        st.rerun()

st.divider()

# ── 清理历史 ──────────────────────────────────────────────
st.subheader("📜 清理历史")
logs = get_cleanup_log()
if logs:
    st.dataframe(pd.DataFrame(logs[::-1]), use_container_width=True, hide_index=True)
else:
    st.caption("暂无清理记录")
