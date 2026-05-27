"""设置页面：qBittorrent 连接配置、字幕组优先级、清理规则。"""

import streamlit as st

from src.qbt.client import QBTClient
from src.utils.config import load_config, save_config

st.set_page_config(page_title="设置", page_icon="⚙️", layout="wide")
st.title("⚙️ 设置")

# ── 读取当前配置 ──────────────────────────────────────────
try:
    cfg = load_config()
except FileNotFoundError:
    cfg = {
        "qbittorrent": {"host": "localhost", "port": 8080, "username": "admin", "password": "adminadmin", "save_path": "D:/Anime"},
        "subtitle_priorities": ["ANi", "kirara"],
        "resource_check": {"recent_weeks": 4},
        "cleanup": {"keep_quarters": 2, "delete_files": True},
        "advanced": {"use_mirror": False, "request_delay": 1.0},
    }

# ── qBittorrent 配置 ──────────────────────────────────────
st.subheader("🖥️ qBittorrent 连接")

qbt_cfg = cfg.get("qbittorrent", {})
col1, col2 = st.columns(2)
with col1:
    host = st.text_input("Host", value=qbt_cfg.get("host", "localhost"))
    username = st.text_input("用户名", value=qbt_cfg.get("username", "admin"))
    save_path = st.text_input("下载保存路径", value=qbt_cfg.get("save_path", "D:/Anime"))
with col2:
    port = st.number_input("端口", value=qbt_cfg.get("port", 8080), min_value=1, max_value=65535)
    password = st.text_input("密码", value=qbt_cfg.get("password", ""), type="password")

test_col, _ = st.columns([1, 3])
with test_col:
    if st.button("🔌 测试连接", use_container_width=True):
        with st.spinner("连接中..."):
            client = QBTClient(host, port, username, password)
            ok, msg = client.test_connection()
        if ok:
            st.success(msg)
        else:
            st.error(msg)

st.divider()

# ── 字幕组优先级 ──────────────────────────────────────────
st.subheader("🎬 字幕组优先级")
st.caption("按优先级从高到低排列，名称包含关键词即匹配（不区分大小写）。找到有资源的就停止。")

current_priorities = cfg.get("subtitle_priorities", ["ANi", "kirara"])
priorities_text = st.text_area(
    "每行一个关键词",
    value="\n".join(current_priorities),
    height=150,
    help="例：\nANi\nkirara\n豌豆\n第一行优先级最高",
)

st.divider()

# ── 资源检查 ──────────────────────────────────────────────
st.subheader("🔍 资源检查")
recent_weeks = st.slider(
    "「有资源」的时间窗口（周）",
    min_value=1, max_value=12,
    value=cfg.get("resource_check", {}).get("recent_weeks", 4),
    help="字幕组在最近 N 周内有更新，才算「有资源」",
)

st.divider()

# ── 清理规则 ──────────────────────────────────────────────
st.subheader("🗑️ 清理规则")
col_c1, col_c2 = st.columns(2)
with col_c1:
    keep_quarters = st.number_input(
        "保留季度数", min_value=1, max_value=8,
        value=cfg.get("cleanup", {}).get("keep_quarters", 2),
        help="超过此季度数的旧资源会在「季度清理」页面列出",
    )
with col_c2:
    delete_files = st.checkbox(
        "清理时删除下载文件",
        value=cfg.get("cleanup", {}).get("delete_files", True),
    )

st.divider()

# ── 高级选项 ──────────────────────────────────────────────
st.subheader("🔧 高级选项")
col_a1, col_a2 = st.columns(2)
with col_a1:
    use_mirror = st.checkbox(
        "使用 mikanime.tv 镜像",
        value=cfg.get("advanced", {}).get("use_mirror", False),
        help="某些地区无法访问 mikanani.me 时开启",
    )
with col_a2:
    request_delay = st.number_input(
        "批量订阅请求间隔（秒）",
        min_value=0.5, max_value=10.0, step=0.5,
        value=float(cfg.get("advanced", {}).get("request_delay", 1.0)),
    )

# ── 保存 ──────────────────────────────────────────────────
st.divider()
if st.button("💾 保存配置", type="primary", use_container_width=False):
    new_priorities = [p.strip() for p in priorities_text.strip().splitlines() if p.strip()]

    new_cfg = {
        "qbittorrent": {
            "host": host,
            "port": int(port),
            "username": username,
            "password": password,
            "save_path": save_path,
        },
        "subtitle_priorities": new_priorities,
        "resource_check": {"recent_weeks": int(recent_weeks)},
        "cleanup": {"keep_quarters": int(keep_quarters), "delete_files": delete_files},
        "advanced": {"use_mirror": use_mirror, "request_delay": float(request_delay)},
    }
    save_config(new_cfg)
    st.success("✅ 配置已保存！")

# ── 如何获取蜜柑计划 Token（参考）────────────────────────
with st.expander("📖 如何获取蜜柑计划 RSS Token（可选）"):
    st.markdown("""
蜜柑计划的公开 RSS（按番剧+字幕组查询）**无需登录**，当前系统默认使用此方式。

如需使用个人订阅 RSS（`/RSS/MyBangumi?token=xxx`），获取方式：
1. 登录 [mikanani.me](https://mikanani.me)
2. 右上角点击头像 → **我的订阅**
3. 页面中有「RSS 链接」按钮，点击后 URL 末尾的 `token=xxxxxxxx` 即为 token

> 目前版本未使用 token（公开 RSS 足够满足按番剧订阅的需求）。
    """)
