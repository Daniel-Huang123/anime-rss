"""媒体库：按番名分组 + 继续观看 + 播放进度追踪。"""

from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import streamlit as st
from urllib.parse import quote as _url_quote

from src.utils.config import load_config
from src.utils.file_parser import AnimeFolder, enrich_with_state, scan_media_directory
from src.utils.watch_progress import (
    get_recently_played,
    get_watch_status,
    last_watched_episode,
    next_unwatched_episode,
    record_played,
)

st.set_page_config(page_title="媒体库", page_icon="🎬", layout="wide")

# ── query-param 跳转（由封面 JS 点击触发，同标签页内导航）──
if "anime" in st.query_params:
    st.session_state["selected_anime"] = st.query_params["anime"]
    st.query_params.clear()


# ── @st.cache_data 加速：硬导航后无需重新扫描 ──
@st.cache_data(ttl=30, show_spinner=False)
def _scan_folders(path_str: str):
    folders = scan_media_directory(Path(path_str))
    enrich_with_state(folders)
    return folders


@st.cache_data(ttl=15, show_spinner=False)
def _get_recent(path_str: str):
    return get_recently_played(Path(path_str))


# ── 封面读取（优先 .cover_cache/ 磁盘缓存，与订阅页一致）──

_COVER_CACHE_DIR = Path(__file__).parent.parent / ".cover_cache"


def _folder_cover(folder: AnimeFolder) -> bytes | None:
    """按优先级获取封面：.cover_cache → assets/covers → 在线 fetch。"""
    import requests as _req
    # 1. .cover_cache（订阅时预取的 yuc.wiki 封面）
    if folder.cover_url:
        cache_path = _COVER_CACHE_DIR / (hashlib.md5(folder.cover_url.encode()).hexdigest() + ".jpg")
        if cache_path.exists():
            return cache_path.read_bytes()
        # 不在缓存则尝试 fetch 并写盘
        try:
            referer = (
                "https://www.bilibili.com/"
                if ("hdslb.com" in folder.cover_url or "bilibili" in folder.cover_url)
                else "https://yuc.wiki/"
            )
            r = _req.get(folder.cover_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": referer,
            }, timeout=6)
            if r.ok and len(r.content) > 500:
                _COVER_CACHE_DIR.mkdir(exist_ok=True)
                cache_path.write_bytes(r.content)
                return r.content
        except Exception:
            pass
    # 2. assets/covers（老缓存）
    from src.utils.cover_cache import get_cover_path
    from src.utils.state import get_all_subscriptions_flat
    subs = {s["title"]: s for s in get_all_subscriptions_flat()}
    sub = subs.get(folder.title)
    bgm_id = sub.get("bangumi_id") if sub else None
    p = get_cover_path(folder.title, bgm_id)
    if p and p.exists():
        return p.read_bytes()
    return None


def _open_file(filepath: str) -> None:
    try:
        record_played(filepath)
        _get_recent.clear()                          # 让下次渲染立即用最新进度
        st.session_state.pop("recently_played", None)
        if sys.platform == "win32":
            os.startfile(filepath)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", filepath])
        else:
            subprocess.Popen(["xdg-open", filepath])
    except Exception as e:
        st.error(f"无法打开：{e}")


def _cover_card_html(img_bytes: bytes | None, watched_ratio: float = 0.0,
                     href: str = "") -> str:
    """封面卡片 HTML。<a> 绝对定位覆盖，不参与流式布局，彻底消除黑边。"""
    bar = ""
    if watched_ratio > 0:
        pct = int(watched_ratio * 100)
        color = "#00c853" if watched_ratio >= 0.9 else "#ff9800"
        bar = (
            f'<div style="position:absolute;bottom:0;left:0;right:0;height:4px;background:#333;">'
            f'<div style="width:{pct}%;height:100%;background:{color};"></div>'
            f'</div>'
        )
    hover = (
        '<div style="position:absolute;inset:0;background:rgba(0,0,0,0);'
        'display:flex;align-items:center;justify-content:center;'
        'color:#fff;font-size:1em;font-weight:600;opacity:0;'
        'transition:background .18s,opacity .18s;" '
        'onmouseover="this.style.background=\'rgba(0,0,0,.45)\';this.style.opacity=\'1\';" '
        'onmouseout="this.style.background=\'rgba(0,0,0,0)\';this.style.opacity=\'0\';">'
        '查看</div>'
    ) if href else ""
    link = (
        f'<a href="{href}" target="_self" style="position:absolute;inset:0;"></a>'
        if href else ""
    )
    if img_bytes:
        b64 = base64.b64encode(img_bytes).decode()
        content = (
            f'<img src="data:image/jpeg;base64,{b64}" '
            f'style="width:100%;height:100%;object-fit:cover;display:block;">'
        )
    else:
        content = (
            '<div style="display:flex;align-items:center;justify-content:center;'
            'height:100%;font-size:2.5em;color:#555;">🎬</div>'
        )
    return (
        f'<div style="position:relative;width:100%;border-radius:8px;overflow:hidden;'
        f'background:#1e1e2e;aspect-ratio:5/7;">'
        f'{content}{bar}{hover}{link}</div>'
    )


# ══════════════════════════════════════════════════════════
# 主渲染
# ══════════════════════════════════════════════════════════

st.title("🎬 媒体库")

try:
    cfg = load_config()
except FileNotFoundError:
    st.error("请先在「设置」页面完成配置。")
    st.stop()

media_path_str = cfg["qbittorrent"].get("save_path", "")
media_path = Path(media_path_str) if media_path_str else Path()

if not media_path_str or not media_path.exists():
    st.warning(f"媒体目录不存在：`{media_path_str}`")
    st.stop()

# ── 详情页 ────────────────────────────────────────────────
if "selected_anime" in st.session_state:
    folders: list[AnimeFolder] = _scan_folders(media_path_str)
    sel = st.session_state["selected_anime"]
    folder = next((f for f in folders if f.title == sel), None)

    if not folder:
        st.session_state.pop("selected_anime", None)
        st.rerun()

    if st.button("← 返回媒体库", key="back_btn"):
        st.session_state.pop("selected_anime", None)
        st.rerun()

    # 播放进度
    recently_played = get_recently_played(media_path)
    all_eps = folder.sorted_episodes()
    all_paths = [e.file_path for e in all_eps]
    status = get_watch_status(all_paths, recently_played)
    watched_set = {Path(k) for k, v in status.items() if v is not None}
    watched_count = len(watched_set)

    h1, h2 = st.columns([1, 4])
    with h1:
        cover = _folder_cover(folder)
        if cover:
            st.image(cover, width=160)
        else:
            st.markdown(
                '<div style="background:#2d2d2d;width:120px;height:180px;'
                'border-radius:8px;display:flex;align-items:center;'
                'justify-content:center;font-size:3em;">🎬</div>',
                unsafe_allow_html=True,
            )
    with h2:
        st.subheader(folder.title)
        latest = folder.latest_episode
        st.markdown(
            f"共 **{folder.episode_count}** 集"
            + (f"  ·  已看 **{watched_count}** 集" if watched_count else "")
            + (f"  ·  最新：**{latest.episode_label}**" if latest else "")
        )
        # 继续观看按钮
        nxt = next_unwatched_episode(all_paths, recently_played)
        if nxt:
            nxt_ep = next((e for e in all_eps if e.file_path == nxt), None)
            btn_label = f"▶ 继续观看  {nxt_ep.episode_label if nxt_ep else nxt.name}"
            if st.button(btn_label, type="primary", key="continue_main"):
                _open_file(str(nxt))
                st.toast(f"正在播放：{nxt.name[:40]}", icon="▶️")

    st.divider()
    st.subheader("📂 剧集列表")

    if not all_eps:
        st.info("没有找到剧集文件。")
        st.stop()

    for row_start in range(0, len(all_eps), 4):
        row = all_eps[row_start:row_start + 4]
        cols = st.columns(4)
        for col, ep in zip(cols, row):
            with col:
                is_watched = ep.file_path in watched_set
                ep_path_str = str(ep.file_path)
                try:
                    size_mb = ep.file_path.stat().st_size / 1024 / 1024
                    size_str = f"{size_mb:.0f} MB"
                except Exception:
                    size_str = ""

                res = f" [{ep.resolution}]" if ep.resolution else ""
                watched_mark = " ✓" if is_watched else ""
                btn_label = f"▶ {ep.episode_label}{res}{watched_mark}"

                if st.button(btn_label, key=f"ep_{ep_path_str}",
                             use_container_width=True,
                             type="secondary" if is_watched else "primary"):
                    _open_file(ep_path_str)
                    st.toast(f"正在播放：{ep.episode_label}", icon="▶️")
                if size_str:
                    st.caption(size_str)

    st.stop()

# ── 列表视图 ──────────────────────────────────────────────
ctrl1, ctrl2, ctrl3 = st.columns([4, 1, 1])
with ctrl1:
    st.caption(f"📁 `{media_path_str}`")
with ctrl2:
    if st.button("🔄 刷新", use_container_width=True):
        _scan_folders.clear()
        _get_recent.clear()
        st.session_state.pop("recently_played", None)
        st.rerun()
with ctrl3:
    view_mode = st.radio("视图", ["网格", "列表"], horizontal=True, label_visibility="collapsed")

# 扫描目录（@st.cache_data，硬导航后命中缓存无需重扫）
folders: list[AnimeFolder] = _scan_folders(media_path_str)

if not folders:
    st.info("没有找到视频文件。")
    st.stop()

# 播放进度（@st.cache_data，TTL=15s；session 层做即时失效）
if "recently_played" not in st.session_state:
    st.session_state["recently_played"] = _get_recent(media_path_str)
recently_played: dict = st.session_state["recently_played"]

# 搜索
search = st.text_input("🔍 搜索", placeholder="输入关键词筛选", label_visibility="collapsed")
display_folders = [f for f in folders if search.lower() in f.title.lower()] if search else folders

# ── 继续观看区 ─────────────────────────────────────────────
in_progress = []
for f in display_folders:
    eps = f.sorted_episodes()
    nxt = next_unwatched_episode([e.file_path for e in eps], recently_played)
    if nxt and any(e.file_path in {Path(k) for k, v in get_watch_status(
            [e.file_path for e in eps], recently_played).items() if v} for e in eps):
        in_progress.append((f, nxt))

if in_progress:
    st.markdown("##### ▶ 继续观看")
    for f, nxt in in_progress[:4]:
        eps_f = f.sorted_episodes()
        paths_f = [e.file_path for e in eps_f]
        ws_f = get_watch_status(paths_f, recently_played)
        watched_n_f = sum(1 for v in ws_f.values() if v)

        c_img, c_info = st.columns([1, 4])
        with c_img:
            cover_f = _folder_cover(f)
            if cover_f:
                st.image(cover_f, use_container_width=True)
            else:
                st.markdown(
                    '<div style="background:#2d2d2d;border-radius:8px;'
                    'aspect-ratio:5/7;display:flex;align-items:center;'
                    'justify-content:center;font-size:2.5em;">🎬</div>',
                    unsafe_allow_html=True,
                )
        with c_info:
            st.subheader(f.title)
            latest_f = f.latest_episode
            st.markdown(
                f"共 **{f.episode_count}** 集"
                + (f"  ·  已看 **{watched_n_f}** 集" if watched_n_f else "")
                + (f"  ·  最新：**{latest_f.episode_label}**" if latest_f else "")
            )
            nxt_ep_f = next((e for e in eps_f if e.file_path == nxt), None)
            btn_lbl = f"▶ 继续观看  {nxt_ep_f.episode_label if nxt_ep_f else nxt.name}"
            if st.button(btn_lbl, key=f"ip_{f.title}", type="primary"):
                _open_file(str(nxt))
                st.toast(f"▶ {f.title[:20]}", icon="▶️")
        st.divider()

# ── 全部番剧 ──────────────────────────────────────────────
total_eps = sum(f.episode_count for f in display_folders)
st.caption(f"共 **{len(display_folders)}** 部 · **{total_eps}** 个文件")

COLS = 5 if view_mode == "网格" else 1

if view_mode == "网格":
    for row_start in range(0, len(display_folders), COLS):
        row = display_folders[row_start:row_start + COLS]
        cols = st.columns(COLS)
        for col, f in zip(cols, row):
            with col:
                eps = f.sorted_episodes()
                all_paths = [e.file_path for e in eps]
                ws = get_watch_status(all_paths, recently_played)
                watched_n = sum(1 for v in ws.values() if v)
                ratio = watched_n / len(eps) if eps else 0.0

                cover = _folder_cover(f)
                href = f"?anime={_url_quote(f.title)}"
                st.markdown(
                    _cover_card_html(cover, ratio, href=href),
                    unsafe_allow_html=True,
                )
                # 封面下方：标题 / 集数 / 更新日期
                disp = (f.title[:10] + "…") if len(f.title) > 10 else f.title
                ep_hint = f"{watched_n}/{f.episode_count}" if watched_n else str(f.episode_count)
                st.caption(
                    f"**{disp}**  \n"
                    f"{ep_hint}集 · {f.latest_mtime.strftime('%m/%d')}"
                )
else:
    for f in display_folders:
        eps = f.sorted_episodes()
        ws = get_watch_status([e.file_path for e in eps], recently_played)
        watched_n = sum(1 for v in ws.values() if v)

        c1, c2, c3 = st.columns([1, 6, 1])
        with c1:
            cover = _folder_cover(f)
            if cover:
                st.image(cover, width=60)
            else:
                st.markdown("🎬")
        with c2:
            st.markdown(f"**{f.title}**")
            latest = f.latest_episode
            ep_info = latest.episode_label if latest else "无剧集"
            progress = f"  ·  已看 {watched_n}/{f.episode_count}" if watched_n else ""
            st.caption(
                f"{f.episode_count} 集{progress}  ·  最新：{ep_info}"
                f"  ·  {f.latest_mtime.strftime('%Y-%m-%d')}"
            )
        with c3:
            if st.button("▶ 查看", key=f"l_{f.title}", use_container_width=True):
                st.session_state["selected_anime"] = f.title
                st.rerun()
        st.divider()
