"""state.json 的读写封装。

State 结构：
{
  "subscriptions": {
    "2026Q1": [
      {
        "title": "进击的巨人",
        "bangumi_id": 228,
        "subgroup_id": 562,
        "subgroup_name": "ANi",
        "rss_url": "https://mikanani.me/RSS/Bangumi?bangumiId=228&subgroupid=562",
        "qbt_feed_path": "2026Q1/进击的巨人",
        "added_at": "2026-01-10"
      }
    ]
  },
  "cleanup_log": [
    {"quarter": "2025Q3", "cleaned_at": "2026-01-10", "count": 5}
  ]
}
"""

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.utils.runtime_paths import STATE_FILE

_EMPTY: dict = {"subscriptions": {}, "cleanup_log": []}
_QUARTER_RE = re.compile(r"^\d{4}Q[1-4]$", re.IGNORECASE)
_SKIP_SEGMENTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
    "node_modules",
}


def _norm_title(text: str) -> str:
    return str(text or "").strip().lower()


def _parse_bangumi_id_from_url(url: str) -> int:
    if not url:
        return 0
    try:
        query = parse_qs(urlparse(url).query)
        values = query.get("bangumiId") or query.get("bangumiid")
        if not values:
            return 0
        bid = int(values[0])
        return bid if bid > 0 else 0
    except Exception:
        return 0


def _load() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return _EMPTY.copy()
    return _EMPTY.copy()


def _save(data: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _prepare_subscription_index(data: dict) -> tuple[dict[str, set[str]], bool]:
    pruned = False
    for quarter, subs in list(data.get("subscriptions", {}).items()):
        cleaned: list[dict] = []
        for item in subs:
            title = str(item.get("title", "")).strip()
            title_l = title.lower()
            if (
                item.get("recovered_local")
                and not str(item.get("rss_url", "")).strip()
                and (title_l.startswith(".") or title_l in _SKIP_SEGMENTS)
            ):
                pruned = True
                continue
            cleaned.append(item)
        data["subscriptions"][quarter] = cleaned

    existing: dict[str, set[str]] = {
        quarter: {str(item.get("title", "")).strip() for item in subs if str(item.get("title", "")).strip()}
        for quarter, subs in data.get("subscriptions", {}).items()
    }
    return existing, pruned


def _apply_discovered_subscriptions(data: dict, existing: dict[str, set[str]], discovered: set[tuple[str, str]]) -> int:
    added = 0
    for quarter, title in sorted(discovered):
        known_titles = existing.setdefault(quarter, set())
        if title in known_titles:
            continue
        entry = {
            "title": title,
            "bangumi_id": 0,
            "subgroup_id": 0,
            "subgroup_name": "local",
            "rss_url": "",
            "qbt_feed_path": f"{quarter}/{title}",
            "added_at": date.today().isoformat(),
            "cover_url": None,
            "bgm_id": None,
            "recovered_local": True,
        }
        data.setdefault("subscriptions", {}).setdefault(quarter, []).append(entry)
        known_titles.add(title)
        added += 1
    return added


def sync_local_subscriptions(media_root: Path | str) -> int:
    """
    Backfill state subscriptions from existing local media files.
    Returns how many new entries were created.
    """
    from src.utils.file_parser import VIDEO_EXTS, parse_filename
    from src.utils.season import current_quarter

    root = Path(media_root)
    if not root.exists():
        return 0

    data = _load()
    existing, pruned = _prepare_subscription_index(data)

    fallback_quarter = current_quarter()
    discovered: set[tuple[str, str]] = set()

    try:
        for file_path in root.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in VIDEO_EXTS:
                continue
            try:
                rel = file_path.relative_to(root)
            except ValueError:
                continue
            parts = rel.parts
            if not parts:
                continue
            segment_names = [str(p).strip().lower() for p in parts[:-1]]
            if any((name.startswith(".") or name in _SKIP_SEGMENTS) for name in segment_names):
                continue

            quarter = fallback_quarter
            title = ""
            if len(parts) >= 2 and _QUARTER_RE.match(parts[0]):
                quarter = parts[0].upper()
                title = parts[1].strip()
            elif len(parts) >= 2:
                title = parts[0].strip()
            else:
                parsed = parse_filename(file_path)
                if parsed:
                    title = parsed.title.strip()
                else:
                    title = file_path.stem.strip()

            if not title:
                continue
            discovered.add((quarter, title))
    except PermissionError:
        pass

    added = _apply_discovered_subscriptions(data, existing, discovered)

    if added or pruned:
        _save(data)
    return added


def sync_local_subscriptions_from_folders(
    media_root: Path | str,
    folders: list,
) -> int:
    """
    Backfill subscriptions from already-scanned AnimeFolder list.
    This avoids a second full filesystem traversal during media refresh.
    """
    from src.utils.season import current_quarter

    root = Path(media_root)
    if not root.exists():
        return 0

    data = _load()
    existing, pruned = _prepare_subscription_index(data)
    fallback_quarter = current_quarter()
    discovered: set[tuple[str, str]] = set()

    for folder in folders:
        title = str(getattr(folder, "title", "")).strip()
        if not title:
            continue
        title_l = title.lower()
        if title_l.startswith(".") or title_l in _SKIP_SEGMENTS:
            continue

        quarter = fallback_quarter
        episodes = list(getattr(folder, "episodes", []) or [])
        if episodes:
            sample_path = getattr(episodes[0], "file_path", None)
            if isinstance(sample_path, Path):
                try:
                    rel = sample_path.relative_to(root)
                    if len(rel.parts) >= 2 and _QUARTER_RE.match(rel.parts[0]):
                        quarter = rel.parts[0].upper()
                except Exception:
                    pass
        discovered.add((quarter, title))

    added = _apply_discovered_subscriptions(data, existing, discovered)
    if added or pruned:
        _save(data)
    return added


def recovered_entries_missing_rss() -> int:
    data = _load()
    missing = 0
    for subs in data.get("subscriptions", {}).values():
        for item in subs:
            if not item.get("recovered_local"):
                continue
            if str(item.get("rss_url", "")).strip():
                continue
            missing += 1
    return missing


def enrich_recovered_subscriptions_from_rules(rules: dict) -> int:
    """
    Fill recovered_local entries by matching qB RSS rules.
    Rules are expected as: {rule_name: {affectedFeeds: [rss_url, ...], ...}, ...}
    Returns number of updated entries.
    """
    if not isinstance(rules, dict) or not rules:
        return 0

    data = _load()
    by_path: dict[str, str] = {}
    by_title: dict[str, list[tuple[str, str]]] = {}

    for rule_name, rule_def in rules.items():
        if not isinstance(rule_name, str):
            continue
        name = rule_name.strip().replace("\\", "/")
        if not name:
            continue

        rss_url = ""
        if isinstance(rule_def, dict):
            feeds = rule_def.get("affectedFeeds")
            if isinstance(feeds, (list, tuple)):
                for feed in feeds:
                    if str(feed or "").strip():
                        rss_url = str(feed).strip()
                        break
            if not rss_url and str(rule_def.get("url", "")).strip():
                rss_url = str(rule_def.get("url")).strip()
        if not rss_url:
            continue

        key = name.lower()
        by_path[key] = rss_url
        title = name.split("/")[-1].strip()
        if title:
            by_title.setdefault(_norm_title(title), []).append((name, rss_url))

    if not by_path and not by_title:
        return 0

    changed = 0
    for quarter, subs in data.get("subscriptions", {}).items():
        for item in subs:
            if not item.get("recovered_local"):
                continue
            if str(item.get("rss_url", "")).strip():
                continue

            title = str(item.get("title", "")).strip()
            if not title:
                continue

            feed_path = str(item.get("qbt_feed_path", "")).strip().replace("\\", "/")
            if not feed_path:
                feed_path = f"{quarter}/{title}"
                item["qbt_feed_path"] = feed_path

            rss_url = by_path.get(feed_path.lower(), "")
            if not rss_url:
                candidates = by_title.get(_norm_title(title), [])
                if candidates:
                    same_quarter = [c for c in candidates if c[0].split("/")[0].upper() == str(quarter).upper()]
                    chosen = max(same_quarter or candidates, key=lambda c: c[0])
                    feed_path = chosen[0]
                    rss_url = chosen[1]

            if not rss_url:
                continue

            item["qbt_feed_path"] = feed_path
            item["rss_url"] = rss_url
            if int(item.get("bangumi_id") or 0) <= 0:
                bid = _parse_bangumi_id_from_url(rss_url)
                if bid > 0:
                    item["bangumi_id"] = bid
            changed += 1

    if changed:
        _save(data)
    return changed


# ── 订阅操作 ──────────────────────────────────────────────


def add_subscription(
    quarter: str,
    title: str,
    bangumi_id: int,
    subgroup_id: int,
    subgroup_name: str,
    rss_url: str,
    cover_url: str | None = None,
    bgm_id: int | None = None,
) -> dict:
    """添加一条订阅记录，返回该记录 dict。如果已存在则更新。"""
    data = _load()
    subs = data["subscriptions"].setdefault(quarter, [])

    entry = {
        "title": title,
        "bangumi_id": bangumi_id,
        "subgroup_id": subgroup_id,
        "subgroup_name": subgroup_name,
        "rss_url": rss_url,
        "qbt_feed_path": f"{quarter}/{title}",
        "added_at": date.today().isoformat(),
        "cover_url": cover_url,
        "bgm_id": bgm_id,
    }

    # 更新已有记录（按 title 去重）
    for i, s in enumerate(subs):
        if s["title"] == title:
            subs[i] = entry
            _save(data)
            return entry

    subs.append(entry)
    _save(data)
    return entry


def update_subscription_cover(
    quarter: str,
    title: str,
    bangumi_id: int | None = None,
    cover_url: str | None = None,
) -> bool:
    """把封面同步发现的元数据写回已有订阅记录。

    只在字段当前为空时补写（不覆盖用户/订阅流程已有的值），
    返回是否产生改动。匹配按 title 精确比对（封面同步的标题来自本地媒体库，
    与 recovered_local 记录的 title 一致）。
    """
    data = _load()
    subs = data.get("subscriptions", {}).get(quarter, [])
    target = str(title or "").strip()
    changed = False
    for item in subs:
        if str(item.get("title", "")).strip() != target:
            continue
        if bangumi_id and int(item.get("bangumi_id") or 0) <= 0:
            item["bangumi_id"] = int(bangumi_id)
            changed = True
        if cover_url and not str(item.get("cover_url") or "").strip():
            item["cover_url"] = cover_url
            changed = True
        break
    if changed:
        _save(data)
    return changed


def remove_subscription(quarter: str, title: str) -> bool:
    """删除指定季度的某条订阅，返回是否找到并删除。"""
    data = _load()
    subs = data["subscriptions"].get(quarter, [])
    before = len(subs)
    data["subscriptions"][quarter] = [s for s in subs if s["title"] != title]
    _save(data)
    return len(data["subscriptions"][quarter]) < before


def get_subscriptions(quarter: str | None = None) -> dict[str, list[dict]]:
    """返回订阅字典。quarter 非空则只返回该季度。"""
    data = _load()
    if quarter:
        return {quarter: data["subscriptions"].get(quarter, [])}
    return data["subscriptions"]


def get_all_subscriptions_flat() -> list[dict]:
    """返回所有订阅的扁平列表，每条附加 'quarter' 字段。"""
    data = _load()
    result = []
    for q, subs in data["subscriptions"].items():
        for s in subs:
            result.append({**s, "quarter": q})
    return result


def is_subscribed(quarter: str, title: str) -> bool:
    data = _load()
    return any(s["title"] == title for s in data["subscriptions"].get(quarter, []))


# ── 清理日志 ───────────────────────────────────────────────


def log_cleanup(quarter: str, count: int) -> None:
    data = _load()
    data["cleanup_log"].append(
        {"quarter": quarter, "cleaned_at": date.today().isoformat(), "count": count}
    )
    _save(data)


def get_cleanup_log() -> list[dict]:
    return _load()["cleanup_log"]


def get_quarters_to_cleanup(keep: int = 2) -> list[str]:
    """返回应该被清理的季度列表（超过 keep 个季度前的）。"""
    from src.utils.season import current_quarter, quarters_ago
    threshold = quarters_ago(keep)

    data = _load()
    result = []
    for q in data["subscriptions"]:
        # 字符串比较在 YYYYQN 格式下是合法的时间序
        # <= threshold 表示该季度及更早的都需要清理（threshold 本身也已超过保留期）
        if q <= threshold:
            result.append(q)
    return sorted(result)
