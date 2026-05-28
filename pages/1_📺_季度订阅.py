"""季度订阅页面：卡片网格 + 响应式列数 + 按播出日分组 + 一键订阅。

响应式原理：
  所有番剧卡片放在同一个 st.columns(n) 中，注入 CSS 让宽度固定为 145px 并
  允许换行（flex-wrap）。窗口变宽时一行容纳更多卡片，变窄时自动折叠。
  CSS 选择器只命中 ≥4 列的 stHorizontalBlock，不影响顶部控制栏。
"""

from __future__ import annotations

import base64
import html
from collections import defaultdict

import requests
import streamlit as st

from src.qbt.client import QBTClient
from src.scrapers.mikanani import build_season_index, build_yuc_bgm_map, detect_rss_filter, load_season_title_index, resolve_anime_rss
from src.scrapers.yuc_wiki import clear_cache, get_season_list
from src.utils.config import load_config
from src.utils.cover_cache import get_or_fetch_cover
from src.utils.runtime_paths import COVER_CACHE_DIR
from src.utils.season import list_season_options, quarter_to_ym
from src.utils.state import add_subscription, get_subscriptions, remove_subscription
from src.utils.ui_refresh import apply_auto_refresh

st.set_page_config(page_title="季度订阅", page_icon="📺", layout="wide")

# ── 响应式卡片 CSS ──────────────────────────────────────────
st.markdown("""
<style>
/* 只对 ≥4 列的 HorizontalBlock 生效（控制栏最多3列，不受影响） */
[data-testid="stHorizontalBlock"]:has(>[data-testid="stColumn"]:nth-child(4)) {
    flex-wrap: wrap !important;
    row-gap: 12px !important;
    align-items: flex-start !important;
}
[data-testid="stHorizontalBlock"]:has(>[data-testid="stColumn"]:nth-child(4))
    > [data-testid="stColumn"] {
    flex: 0 0 145px !important;
    width: 145px !important;
    min-width: 145px !important;
    max-width: 145px !important;
    padding-left: 4px !important;
    padding-right: 4px !important;
    box-sizing: border-box !important;
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

apply_auto_refresh(cfg, "season_subscribe")

priorities = cfg.get("subtitle_priorities", ["ANi", "kirara"])
weeks      = cfg.get("resource_check", {}).get("recent_weeks", 4)
use_mirror = cfg.get("advanced", {}).get("use_mirror", False)
qbt_cfg    = cfg["qbittorrent"]
qbt_save_path = qbt_cfg.get("save_path", "").strip().strip('"').strip("'")
qbt = QBTClient(
    host=qbt_cfg["host"], port=qbt_cfg["port"],
    username=qbt_cfg["username"], password=qbt_cfg["password"],
)

# ── 封面磁盘缓存（只缓存成功结果，失败不写盘，下次重试）──
import hashlib as _hashlib

_COVER_CACHE_DIR = COVER_CACHE_DIR
_COVER_CACHE_DIR.mkdir(exist_ok=True)


def _cover_bytes(url: str) -> bytes | None:
    """下载封面图并磁盘缓存（只缓存成功结果；失败自动重试最多 3 次）。"""
    if not url:
        return None
    cache_path = _COVER_CACHE_DIR / (_hashlib.md5(url.encode()).hexdigest() + ".jpg")
    if cache_path.exists():
        return cache_path.read_bytes()
    referer = (
        "https://www.bilibili.com/"
        if ("hdslb.com" in url or "bilibili" in url)
        else "https://yuc.wiki/"
    )
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer,
    }
    import time as _time
    for attempt in range(3):
        try:
            r = requests.get(url, headers=hdrs, timeout=8)
            if r.ok and len(r.content) > 500:
                cache_path.write_bytes(r.content)
                return r.content
        except Exception:
            pass
        if attempt < 2:
            _time.sleep(0.5 * (attempt + 1))  # 0.5s, 1.0s
    return None


def _cover_html(img_bytes: bytes | None, status: str = "normal", bgm_url: str = "") -> str:
    """status: 'normal' | 'subscribed' | 'failed'"""
    border = {"subscribed": "#00c853", "failed": "#ff4b4b"}.get(status, "#2d2d2d")
    # <a> 用绝对定位覆盖整个封面，不参与流式布局，彻底避免黑线
    link = (
        f'<a href="{bgm_url}" target="_blank" '
        f'style="position:absolute;inset:0;"></a>'
        if bgm_url else ""
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
            'height:100%;font-size:2em;">🎬</div>'
        )
    return (
        f'<div style="position:relative;width:100%;border:3px solid {border};'
        f'border-radius:8px;overflow:hidden;background:#1e1e2e;aspect-ratio:5/7;">'
        f'{content}{link}</div>'
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
    # 只清季度数据缓存（yuc.wiki 番单 + mikan 索引），封面缓存永久保留
    clear_cache()
    from src.scrapers.mikanani import _CACHE_FILE as _mikan_cache_file
    import json as _json
    # 只删 season_index 和 yuc_bgm_map 相关 key，保留 bangumi_data（含封面来源）
    if _mikan_cache_file.exists():
        try:
            _cd = _json.loads(_mikan_cache_file.read_text(encoding="utf-8"))
            _cd = {k: v for k, v in _cd.items()
                   if not (k.startswith("season_index:") or k.startswith("yuc_bgm_map:"))}
            _mikan_cache_file.write_text(_json.dumps(_cd, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            _mikan_cache_file.unlink(missing_ok=True)  # 损坏则直接删掉，下次重建
    st.session_state.pop("anime_list", None)
    st.session_state.pop("loaded_quarter", None)
    st.session_state.pop("season_index", None)
    st.session_state.pop("covers_prefetched", None)
    st.session_state["search_kw"] = ""

if load_btn:
    st.session_state.pop("anime_list", None)
    st.session_state["search_kw"] = ""

if "anime_list" not in st.session_state:
    year, month = quarter_to_ym(selected_quarter)
    with st.spinner(f"正在爬取 yuc.wiki/{year:04d}{month:02d} ..."):
        try:
            anime_list = get_season_list(year, month)
            st.session_state["anime_list"]     = anime_list
            st.session_state["loaded_quarter"] = selected_quarter
            st.session_state.pop("season_index", None)  # 季度变更时清索引
        except Exception as e:
            st.error(f"加载失败：{e}")
            st.stop()

# 构建/加载蜜柑季度索引（首次需要，后续走磁盘缓存自动命中）
# 用 not season_index 而非 not in session_state，避免空 dict {} 卡住后续流程
if not st.session_state.get("season_index"):
    with st.spinner("正在构建蜜柑番组索引（首次约 30-40 秒，之后自动缓存 7 天）..."):
        st.session_state["season_index"] = build_season_index(
            selected_quarter, use_mirror=use_mirror
        )
    st.session_state.pop("yuc_bgm_map", None)  # 索引刷新时重建映射

# 构建 yuc标题 → bgm_id 映射（首次含 BGM API 补全，之后走缓存）
if "yuc_bgm_map" not in st.session_state:
    _titles = [a["title"] for a in st.session_state.get("anime_list", [])]
    if _titles:
        with st.spinner("正在补全 BGM 映射..."):
            st.session_state["yuc_bgm_map"] = build_yuc_bgm_map(
                _titles,
                st.session_state.get("season_index") or {},
                selected_quarter,
                use_mirror=use_mirror,
            )

# 并行预取封面（只取未缓存的，已有磁盘缓存的跳过）
if "covers_prefetched" not in st.session_state:
    _uncached_urls = [
        a.get("cover_url") for a in st.session_state.get("anime_list", [])
        if a.get("cover_url") and not (
            _COVER_CACHE_DIR / (_hashlib.md5(a["cover_url"].encode()).hexdigest() + ".jpg")
        ).exists()
    ]
    if _uncached_urls:
        from concurrent.futures import ThreadPoolExecutor as _TPE
        with st.spinner(f"正在预取 {len(_uncached_urls)} 张封面..."):
            with _TPE(max_workers=10) as _pool:
                list(_pool.map(_cover_bytes, _uncached_urls))
    st.session_state["covers_prefetched"] = True

anime_list     = st.session_state.get("anime_list", [])
loaded_quarter = st.session_state.get("loaded_quarter", selected_quarter)
season_index   = st.session_state.get("season_index") or {}

_yuc_bgm_map: dict[str, int] = st.session_state.get("yuc_bgm_map") or {}

def _get_bgm_url(title: str) -> str:
    bgm_id = _yuc_bgm_map.get(title)
    return f"https://bgm.tv/subject/{bgm_id}" if bgm_id else ""

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
        key="search_kw",
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
DAY_ORDER = ["周一", "周二", "周三", "周四", "周五", "周六", "周日", "其他"]

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
            _bgm_url = _get_bgm_url(title)
            _card_status = (
                "subscribed" if is_sub
                else "failed" if st.session_state.get(f"fail_{gidx}")
                else "normal"
            )
            st.markdown(_cover_html(img_bytes, _card_status, _bgm_url), unsafe_allow_html=True)

            # 标题（≤16字，超出截断）
            disp = title[:15] + "…" if len(title) > 15 else title
            disp = html.escape(disp)
            st.markdown(
                f'<p style="font-size:0.8em;font-weight:600;margin:4px 0 2px;'
                f'line-height:1.3;min-height:2.4em;word-break:break-all;">'
                f'{disp}</p>',
                unsafe_allow_html=True,
            )

            # Metadata：播出时间 + 集数（固定两行高度，空值显示破折号）
            time_str = str(broadcast).strip() or "—"
            ep_str   = str(episodes).strip()  or "—"
            st.markdown(
                f'<div style="font-size:0.75em;color:#888;line-height:1.6;'
                f'min-height:3.2em;margin:2px 0 4px;">'
                f'🕐 {time_str}<br>📺 {ep_str}'
                f'</div>',
                unsafe_allow_html=True,
            )

            # 订阅按钮 / 已订阅标记 / 搜索失败重试
            fail_key   = f"fail_{gidx}"
            retry_key  = f"retry_term_{gidx}"

            if is_sub:
                confirm_key = f"confirm_unsub_{gidx}"
                if st.session_state.get(confirm_key):
                    # ── 确认取消订阅 ──────────────────────
                    st.markdown(
                        '<p style="color:#ff4b4b;font-size:0.75em;text-align:center;'
                        'margin:2px 0;">确认取消订阅？</p>',
                        unsafe_allow_html=True,
                    )
                    cy, cn_ = st.columns(2)
                    with cy:
                        if st.button("确认", key=f"usy_{gidx}",
                                     type="primary", use_container_width=True):
                            # 查找订阅记录拿 rss_url
                            sub_rec = next(
                                (s for s in get_subscriptions(loaded_quarter)
                                 .get(loaded_quarter, [])
                                 if s["title"] == title), None
                            )
                            feed_path = f"{loaded_quarter}/{title}"
                            _sp = (f"{qbt_save_path}/{loaded_quarter}/{title}"
                                   if qbt_save_path else "")
                            qbt.unsubscribe(feed_path=feed_path, save_path=_sp)
                            remove_subscription(loaded_quarter, title)
                            subbed_titles.discard(title)
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                    with cn_:
                        if st.button("取消", key=f"usn_{gidx}",
                                     use_container_width=True):
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                else:
                    if st.button("✓ 已订阅", key=f"subbed_{gidx}",
                                 use_container_width=True):
                        st.session_state[confirm_key] = True
                        st.rerun()

            elif st.session_state.get(fail_key):
                # ── 失败重试区 ──────────────────────────────
                edit_key = f"edit_{gidx}"
                if st.session_state.get(edit_key):
                    # 展开态：输入框 + 确认/取消
                    custom_term = st.text_input(
                        "搜索词", key=f"ct_{gidx}",
                        value=st.session_state.get(retry_key, title),
                        label_visibility="collapsed",
                        placeholder="修改蜜柑搜索词",
                    )
                    ce, cc = st.columns(2)
                    with ce:
                        do_retry = st.button("确认", key=f"rb_{gidx}",
                                             use_container_width=True, type="primary")
                    with cc:
                        if st.button("取消", key=f"rc_{gidx}", use_container_width=True):
                            st.session_state.pop(edit_key, None)
                            st.rerun()
                    if do_retry:
                        st.session_state[retry_key] = custom_term
                        st.session_state.pop(edit_key, None)
                        with st.spinner("重试中..."):
                            result = resolve_anime_rss(
                                title, priorities, weeks, use_mirror,
                                search_override=custom_term,
                                season_index=None,
                            )
                        if result is None:
                            st.error("仍然未找到", icon="❌")
                        else:
                            _dl_path = (
                                f"{qbt_save_path}/{loaded_quarter}/{title}"
                                if qbt_save_path else ""
                            )
                            _rss_filter = detect_rss_filter(result["rss_url"])
                            ok, qbt_msg = qbt.add_rss_feed(
                                url=result["rss_url"],
                                path=f"{loaded_quarter}/{title}",
                                save_path=_dl_path,
                                **_rss_filter,
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
                                    bgm_id=result.get("mikan_bgm_id"),
                                )
                                subbed_titles.add(title)
                                st.session_state.pop(fail_key, None)
                                # 更新 bgm URL 映射，下次渲染立即生效
                                _bgm_new = result.get("mikan_bgm_id")
                                if _bgm_new:
                                    _map = st.session_state.get("yuc_bgm_map") or {}
                                    _map[title] = _bgm_new
                                    st.session_state["yuc_bgm_map"] = _map
                                st.rerun()
                            else:
                                st.warning(qbt_msg)
                else:
                    # 折叠态：与「确认取消订阅」等高
                    st.markdown(
                        '<p style="color:#ff4b4b;font-size:0.75em;text-align:center;'
                        'margin:2px 0;">❌ 未找到</p>',
                        unsafe_allow_html=True,
                    )
                    cf, cx = st.columns(2)
                    with cf:
                        if st.button("搜索", key=f"rb_{gidx}",
                                     use_container_width=True, type="primary"):
                            st.session_state[edit_key] = True
                            st.rerun()
                    with cx:
                        if st.button("✕", key=f"rc_{gidx}", use_container_width=True):
                            st.session_state.pop(fail_key, None)
                            st.rerun()

            else:
                # ── 正常订阅按钮 ────────────────────────────
                if st.button("＋ 订阅", key=f"sub_{gidx}",
                             use_container_width=True, type="primary"):
                    with st.spinner(f"订阅 {title[:12]}..."):
                        result = resolve_anime_rss(
                            title, priorities, weeks, use_mirror,
                            season_index=season_index,
                            quarter=loaded_quarter,
                        )

                    if result is None:
                        # 记录失败，显示重试 UI
                        st.session_state[fail_key]  = True
                        st.session_state[retry_key] = title
                        st.rerun()
                    else:
                        _dl_path = (
                            f"{qbt_save_path}/{loaded_quarter}/{title}"
                            if qbt_save_path else ""
                        )
                        _rss_filter = detect_rss_filter(result["rss_url"])
                        ok, qbt_msg = qbt.add_rss_feed(
                            url=result["rss_url"],
                            path=f"{loaded_quarter}/{title}",
                            save_path=_dl_path,
                            **_rss_filter,
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
                                bgm_id=result.get("mikan_bgm_id"),
                            )
                            subbed_titles.add(title)
                            st.rerun()
                        else:
                            st.warning(f"RSS 已找到但添加 qBit 失败：{qbt_msg}")

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    st.divider()
