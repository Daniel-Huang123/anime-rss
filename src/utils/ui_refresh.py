"""UI 自动刷新辅助。"""

from __future__ import annotations

import streamlit as st


def apply_auto_refresh(cfg: dict, page_key: str) -> None:
    """按配置注入前端定时刷新。"""
    ui_cfg = cfg.get("ui", {}) if isinstance(cfg, dict) else {}
    enabled = bool(ui_cfg.get("auto_refresh_enabled", False))
    if not enabled:
        return

    seconds = int(ui_cfg.get("auto_refresh_seconds", 30) or 30)
    seconds = max(5, min(seconds, 3600))
    ms = seconds * 1000

    safe_key = "".join(ch for ch in page_key if ch.isalnum() or ch in ("_", "-")) or "default"
    st.caption(f"⏱️ 自动刷新：每 {seconds} 秒")
    st.markdown(
        f"""
<script>
const timerKey = "__anime_rss_refresh_{safe_key}";
if (window[timerKey]) {{
  clearTimeout(window[timerKey]);
}}
window[timerKey] = setTimeout(() => {{
  window.location.reload();
}}, {ms});
</script>
""",
        unsafe_allow_html=True,
    )

