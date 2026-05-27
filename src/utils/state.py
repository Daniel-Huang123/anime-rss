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
from datetime import date
from pathlib import Path


STATE_FILE = Path(__file__).parent.parent.parent / "state.json"

_EMPTY: dict = {"subscriptions": {}, "cleanup_log": []}


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


# ── 订阅操作 ──────────────────────────────────────────────


def add_subscription(
    quarter: str,
    title: str,
    bangumi_id: int,
    subgroup_id: int,
    subgroup_name: str,
    rss_url: str,
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
