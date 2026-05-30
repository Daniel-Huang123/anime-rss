"""打包自检：在 frozen exe 内验证「匹配 + 下载」链路的关键依赖与逻辑。

用法（仅用于验证，不影响正常启动）：
    zhuifanji.exe --selftest                 # 结果写 %TEMP%\\zhuifanji_selftest.json
    zhuifanji.exe --selftest=D:\\out.json     # 指定结果文件

命中 --selftest 时只跑自检并退出（return 0 = 关键项全过，1 = 有关键项失败）。
因为打包后是 windowed（无控制台）exe，结果写 JSON 文件供外部读取。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from datetime import datetime

# 关键项：这些必须全过才算「功能上无缺陷」。qBittorrent 连接属环境项（断网/未开不算缺陷）。
_CRITICAL = {
    "imports", "filter_simplified", "filter_fallback_dedup",
    "backfill_torrent_url", "backfill_episode_dedup",
}


def is_selftest(argv: list[str]) -> bool:
    return any(a == "--selftest" or a.startswith("--selftest=") for a in argv[1:])


def _result_path(argv: list[str]) -> str:
    for i, a in enumerate(argv):
        if a.startswith("--selftest="):
            val = a.split("=", 1)[1].strip()
            if val:
                return val
        if a == "--selftest" and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            return argv[i + 1]
    return os.path.join(tempfile.gettempdir(), "zhuifanji_selftest.json")


def run_selftest(argv: list[str]) -> int:
    checks: list[dict] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    # 1) 关键依赖 + 项目模块导入（frozen 最易因缺 hidden-import 而崩的环节）
    try:
        import feedparser  # noqa: F401
        import lxml  # noqa: F401
        import qbittorrentapi  # noqa: F401
        import scrapling  # noqa: F401
        import yaml  # noqa: F401

        from gui.services.subscription_service import (  # noqa: F401
            detect_rss_filter,
            realign_qbt_rules,
        )
        from src.qbt.client import QBTClient  # noqa: F401

        record("imports", True, "feedparser/lxml/qbittorrentapi/scrapling/yaml + src/gui 均可导入")
    except Exception as e:
        record("imports", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        return _write(argv, checks)

    # 2) 匹配/筛选逻辑（离线、确定性）：简体内嵌 → (CHS|简) 正则
    try:
        from unittest.mock import MagicMock, patch

        from src.scrapers.mikanani import detect_rss_filter

        feed = MagicMock()
        feed.entries = [
            {"title": "[桜都字幕组] X / Koori [08][1080P][简繁内封]"},
            {"title": "[桜都字幕组] X / Koori [08][1080P][繁体内嵌]"},
            {"title": "[桜都字幕组] X / Koori [08][1080P][简体内嵌]"},
        ]
        with patch("src.scrapers.mikanani.feedparser.parse", return_value=feed):
            rule = detect_rss_filter("about:blank")
        ok = rule.get("must_contain") == "(CHS|简)" and rule.get("use_regex") is True
        record("filter_simplified", ok, f"rule={rule}")

        # 纯繁体（无 简/CHS）→ 不强加语言筛选，回退集数去重兜底
        feed2 = MagicMock()
        feed2.entries = [{"title": "[ANi] Y - 01 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]"}]
        with patch("src.scrapers.mikanani.feedparser.parse", return_value=feed2):
            rule2 = detect_rss_filter("about:blank")
        ok2 = rule2.get("must_contain") == "" and rule2.get("smart_filter") is True
        record("filter_fallback_dedup", ok2, f"rule={rule2}")

        # 仅「简日内嵌」(无 简体/CHS) 也必须走正则，验证词边界 bug 已修
        feed3 = MagicMock()
        feed3.entries = [{"title": "[喵萌] Z - 01 [1080p][简日内嵌]"}]
        with patch("src.scrapers.mikanani.feedparser.parse", return_value=feed3):
            rule3 = detect_rss_filter("about:blank")
        record(
            "filter_jian_only_regex",
            rule3.get("must_contain") == "(CHS|简)" and rule3.get("use_regex") is True,
            f"rule={rule3}",
        )
    except Exception as e:
        record("filter_logic", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

    # 2b) 补拉链路关键修复（离线、确定性）：种子链接取 enclosure 而非详情页 + 同集去重
    try:
        from src.qbt.client import _episode_key, _torrent_url_from_entry

        entry = {
            "title": "[ANi] X - 12 [1080P][Baha][CHT][MP4]",
            "link": "https://mikanani.me/Home/Episode/abc",  # 详情页，非种子
            "enclosures": [{"href": "https://mikanani.me/Download/x/abc.torrent",
                            "type": "application/x-bittorrent"}],
        }
        url = _torrent_url_from_entry(entry)
        record("backfill_torrent_url", url.endswith(".torrent") and "/Episode/" not in url,
               f"url={url}")

        same = _episode_key("X [08][1080P][简繁内封]") == _episode_key("X [08][1080P][简体内嵌]")
        record("backfill_episode_dedup", same, "同集简繁/简体两版 key 相同→去重")
    except Exception as e:
        record("backfill_fix", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

    # 3) 下载链路：连 qBittorrent → 列 RSS 规则 → 校验对齐（环境项）
    try:
        from gui.services.config_service import ConfigService
        from src.qbt.client import QBTClient

        cfg = ConfigService.load()
        q = cfg.get("qbittorrent", {})
        client = QBTClient(
            host=q.get("host", ""),
            port=q.get("port", 0),
            username=q.get("username", ""),
            password=q.get("password", ""),
        )
        ok_conn, msg = client.test_connection()
        record("qbt_connect", ok_conn, msg)
        if ok_conn:
            rules = client.list_rss_rules()
            record("qbt_rules_present", len(rules) > 0, f"{len(rules)} 条 RSS 规则")
            chs_rules = [
                n for n, r in rules.items()
                if r.get("useRegex") and "简" in str(r.get("mustContain", ""))
            ]
            record(
                "qbt_chs_rule_aligned",
                len(chs_rules) > 0,
                f"(CHS|简) 正则规则: {chs_rules}",
            )
    except Exception as e:
        record("qbt_link", False, f"{type(e).__name__}: {e}")

    return _write(argv, checks)


def _write(argv: list[str], checks: list[dict]) -> int:
    crit_ok = all(c["ok"] for c in checks if c["name"] in _CRITICAL)
    # 确保关键项都有被执行到（导入失败时只有 imports 一项）
    seen = {c["name"] for c in checks}
    crit_ok = crit_ok and _CRITICAL.issubset(seen)
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version,
        "all_ok": all(c["ok"] for c in checks),
        "critical_ok": crit_ok,
        "checks": checks,
    }
    path = _result_path(argv)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        traceback.print_exc()
    return 0 if crit_ok else 1
