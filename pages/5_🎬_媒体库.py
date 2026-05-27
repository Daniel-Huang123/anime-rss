"""媒体库页面：扫描下载目录，展示已下载番剧，支持剧集列表和本地播放。

功能：
  - 按最近更新排序展示所有已下载番剧（带封面）
  - 点击番剧 → 展开剧集列表
  - 点击剧集 → 用系统默认播放器打开
"""

from __future__ import annotations

import os
import subprocess
import sys
from itertools import groupby
from pathlib import Path

import streamlit as st

from src.utils.config import load_config
from src.utils.cover_cache import get_cover_path, get_or_fetch_cover
from src.utils.file_parser import AnimeFolder, enrich_with_state, scan_media_directory
from src.utils.state import get_all_subscriptions_flat

st.set_page_config(page_title="媒体库", page_icon="🎬", layout="wide")


# ── 辅助函数（先定义，再使用）────────────────────────────

def _get_cover_bytes(folder: AnimeFolder) -> bytes | None:
    """返回封面图片字节，没有则返回 None。"""
    subs = {s["title"]: s for s in get_all_subscriptions_flat()}
    sub = subs.get(folder.title)
    bangumi_id = sub.get("bangumi_id") if sub else None
    cover_url  = folder.cover_url or (sub.get("cover_url") if sub else None)

    path = get_cover_path(folder.title, bangumi_id)
    if path is None and cover_url:
        path = get_or_fetch_cover(folder.title, bangumi_id, cover_url)
    if path and path.exists():
        try:
            return path.read_bytes()
        except Exception:
            pass
    return None


def _open_file(filepath: str) -> None:
    """用系统默认播放器打开文件（Windows: os.startfile；Mac: open；Linux: xdg-open）。"""
    try:
        if sys.platform == "win32":
            os.startfile(filepath)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", filepath])
        else:
            subprocess.Popen(["xdg-open", filepath])
    except Exception as e:
        st.error(f"无法打开文件：{e}")


def _render_detail(folder: AnimeFolder) -> None:
    """渲染番剧详情页（剧集列表 + 播放按钮）。"""
    if st.button("← 返回媒体库", key="back_btn"):
        st.session_state.pop("selected_anime", None)
        st.rerun()

    # ── 番剧头部 ──
    cover_bytes = _get_cover_bytes(folder)
    h1, h2 = st.columns([1, 4])
    with h1:
        if cover_bytes:
            st.image(cover_bytes, width=160)
        else:
            st.markdown(
                '<div style="background:#2d2d2d;width:120px;height:180px;border-radius:8px;'
                'display:flex;align-items:center;justify-content:center;font-size:3em;">🎬</div>',
                unsafe_allow_html=True,
            )
    with h2:
        st.subheader(folder.title)
        latest = folder.latest_episode
        st.markdown(
            f"共 **{folder.episode_count}** 集 ｜ "
            f"最新：**{latest.episode_label if latest else '-'}** ｜ "
            f"最后更新：`{folder.latest_mtime.strftime('%Y-%m-%d %H:%M')}`"
        )
        if latest and latest.subgroup:
            st.caption(f"字幕组：{latest.subgroup}")

    st.divider()
    st.subheader("📂 剧集列表")

    episodes = folder.sorted_episodes()
    if not episodes:
        st.info("没有找到剧集文件。")
        return

    # 按 season 分组展示
    for season_num, eps_iter in groupby(episodes, key=lambda e: e.season):
        eps_list = list(eps_iter)
        season_label = f"Season {season_num:02d}" if season_num > 0 else "特别篇 / OVA"

        with st.expander(f"📁 {season_label}（{len(eps_list)} 集）", expanded=True):
            # 4列网格
            for row_start in range(0, len(eps_list), 4):
                row = eps_list[row_start:row_start + 4]
                cols = st.columns(4)
                for col, ep in zip(cols, row):
                    with col:
                        ep_path_str = str(ep.file_path)
                        res_tag = f" [{ep.resolution}]" if ep.resolution else ""
                        # 文件大小
                        try:
                            size_mb = ep.file_path.stat().st_size / 1024 / 1024
                            size_str = f"{size_mb:.0f} MB"
                        except Exception:
                            size_str = ""

                        btn_label = f"▶ {ep.episode_label}{res_tag}"
                        if st.button(
                            btn_label,
                            key=f"play_{ep_path_str}",
                            use_container_width=True,
                            help=f"{ep.file_path.name}\n{size_str}",
                        ):
                            _open_file(ep_path_str)
                            st.toast(f"正在播放：{ep.episode_label}", icon="▶️")

                        if size_str:
                            st.caption(size_str)


def _render_grid(folders: list[AnimeFolder]) -> None:
    """网格视图：5列封面卡片。"""
    COLS = 5
    for row_start in range(0, len(folders), COLS):
        row = folders[row_start:row_start + COLS]
        cols = st.columns(COLS)
        for col, folder in zip(cols, row):
            with col:
                cover_bytes = _get_cover_bytes(folder)
                if cover_bytes:
                    st.image(cover_bytes, use_container_width=True)
                else:
                    st.markdown(
                        '<div style="background:#1e1e2e;height:160px;border-radius:8px;'
                        'display:flex;align-items:center;justify-content:center;'
                        'font-size:2.5em;color:#555;">🎬</div>',
                        unsafe_allow_html=True,
                    )

                # 标题 + 最新集 + 日期
                display_title = (folder.title[:10] + "…") if len(folder.title) > 10 else folder.title
                latest = folder.latest_episode
                ep_hint = latest.episode_label if latest else ""
                st.caption(
                    f"**{display_title}**  \n"
                    f"{ep_hint} · {folder.latest_mtime.strftime('%m/%d')}"
                )

                if st.button("查看剧集", key=f"g_{folder.title}", use_container_width=True):
                    st.session_state["selected_anime"] = folder.title
                    st.rerun()


def _render_list(folders: list[AnimeFolder]) -> None:
    """列表视图：每行一部番剧。"""
    for folder in folders:
        cover_bytes = _get_cover_bytes(folder)
        latest = folder.latest_episode

        c1, c2, c3 = st.columns([1, 6, 1])
        with c1:
            if cover_bytes:
                st.image(cover_bytes, width=75)
            else:
                st.markdown("🎬")
        with c2:
            st.markdown(f"**{folder.title}**")
            ep_info   = latest.episode_label if latest else "无剧集"
            sub_info  = f" ｜ {latest.subgroup}" if (latest and latest.subgroup) else ""
            date_info = folder.latest_mtime.strftime("%Y-%m-%d")
            st.caption(f"{folder.episode_count} 集 ｜ 最新：{ep_info}{sub_info} ｜ {date_info}")
        with c3:
            if st.button("▶ 查看", key=f"l_{folder.title}", use_container_width=True):
                st.session_state["selected_anime"] = folder.title
                st.rerun()

        st.divider()


# ══════════════════════════════════════════════════════════
# 主渲染入口
# ══════════════════════════════════════════════════════════

st.title("🎬 媒体库")

# ── 配置加载 ──────────────────────────────────────────────
try:
    cfg = load_config()
except FileNotFoundError:
    st.error("请先在「设置」页面完成配置。")
    st.stop()

media_path_str = cfg["qbittorrent"].get("save_path", "")
media_path = Path(media_path_str) if media_path_str else Path()

if not media_path_str or not media_path.exists():
    st.warning(f"媒体目录不存在或未配置：`{media_path_str}`")
    st.info("请在「⚙️ 设置」页面确认 qBittorrent 下载路径，并确保目录存在。")
    st.stop()

# ── 如果已选中某个番剧，直接渲染详情页 ───────────────────
if "selected_anime" in st.session_state:
    # 需要先加载 folders
    if "media_folders" not in st.session_state:
        with st.spinner("扫描媒体目录..."):
            folders = scan_media_directory(media_path)
            enrich_with_state(folders)
            st.session_state["media_folders"] = folders

    folders: list[AnimeFolder] = st.session_state["media_folders"]
    sel = st.session_state["selected_anime"]
    sel_folder = next((f for f in folders if f.title == sel), None)

    if sel_folder:
        _render_detail(sel_folder)
    else:
        st.session_state.pop("selected_anime", None)
        st.rerun()
    st.stop()

# ── 媒体库列表视图 ────────────────────────────────────────
top1, top2, top3 = st.columns([4, 1, 1])
with top1:
    st.caption(f"📁 扫描路径：`{media_path_str}`")
with top2:
    if st.button("🔄 刷新扫描", use_container_width=True):
        st.session_state.pop("media_folders", None)
        st.rerun()
with top3:
    view_mode = st.radio("视图", ["网格", "列表"], horizontal=True, label_visibility="collapsed")

# 扫描目录（有缓存则用缓存）
if "media_folders" not in st.session_state:
    with st.spinner(f"正在扫描 {media_path_str} ..."):
        folders = scan_media_directory(media_path)
        enrich_with_state(folders)
        st.session_state["media_folders"] = folders

folders: list[AnimeFolder] = st.session_state["media_folders"]

if not folders:
    st.info("媒体目录为空，或没有识别到视频文件（支持 .mkv .mp4 .avi .ts 等格式）。")
    st.stop()

total_eps = sum(f.episode_count for f in folders)
st.caption(f"共 **{len(folders)}** 部番剧，**{total_eps}** 个文件，按最近更新排序")
st.divider()

# 搜索过滤
search = st.text_input("🔍 搜索番剧", placeholder="输入关键词筛选", label_visibility="collapsed")
display_folders = [f for f in folders if search.lower() in f.title.lower()] if search else folders

# 渲染
if view_mode == "网格":
    _render_grid(display_folders)
else:
    _render_list(display_folders)
