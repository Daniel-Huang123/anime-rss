from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.qbt.client import QBTClient
from src.utils.file_parser import AnimeFolder, enrich_with_state, scan_media_directory
from src.utils.state import (
    enrich_recovered_subscriptions_from_rules,
    recovered_entries_missing_rss,
    sync_local_subscriptions,
    sync_local_subscriptions_from_folders,
)
from src.utils.watch_progress import get_recently_played, get_watch_status, resume_episode


def _collect_feed_urls(tree: dict, prefix: str = "") -> dict[str, str]:
    urls: dict[str, str] = {}
    if not isinstance(tree, dict):
        return urls
    for key, value in tree.items():
        if not isinstance(key, str):
            continue
        name = key.strip()
        if not name:
            continue
        path = f"{prefix}/{name}" if prefix else name
        if not isinstance(value, dict):
            continue
        url = str(value.get("url", "")).strip()
        if url:
            urls[path.replace("\\", "/")] = url

        nested = {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, dict)}
        if nested:
            urls.update(_collect_feed_urls(nested, path))
    return urls


@dataclass
class AnimeRow:
    title: str
    episode_count: int
    watched_count: int
    latest_label: str
    continue_path: Path | None
    folder: AnimeFolder


def _try_enrich_recovered_from_qbt(qbt_cfg: dict) -> None:
    if recovered_entries_missing_rss() <= 0:
        return
    try:
        qbt = QBTClient(
            host=str(qbt_cfg.get("host", "127.0.0.1")).strip() or "127.0.0.1",
            port=int(qbt_cfg.get("port", 8080)),
            username=str(qbt_cfg.get("username", "")).strip(),
            password=str(qbt_cfg.get("password", "")),
        )
        rules = qbt.list_rss_rules()
        if isinstance(rules, dict) and rules:
            enrich_recovered_subscriptions_from_rules(rules)

        if recovered_entries_missing_rss() > 0:
            feeds = qbt.list_rss_feeds()
            feed_urls = _collect_feed_urls(feeds) if isinstance(feeds, dict) else {}
            if feed_urls:
                pseudo_rules = {
                    path: {"affectedFeeds": [url]}
                    for path, url in feed_urls.items()
                    if str(url).strip()
                }
                if pseudo_rules:
                    enrich_recovered_subscriptions_from_rules(pseudo_rules)
    except Exception:
        # Best-effort enrichment only; media refresh should not fail here.
        return


def build_media_rows(
    media_root: str,
    qbt_cfg: dict | None = None,
    recover_existing: bool = True,
) -> list[AnimeRow]:
    path = Path(media_root)
    folders = scan_media_directory(path)
    # Backfill once per path/app-session from caller side; avoids repeated deep scan + qB API.
    if recover_existing:
        try:
            sync_local_subscriptions_from_folders(path, folders)
        except Exception:
            # Compatibility fallback for old states.
            sync_local_subscriptions(path)
        if qbt_cfg:
            _try_enrich_recovered_from_qbt(qbt_cfg)
    enrich_with_state(folders)
    recently_played = get_recently_played(path)
    rows: list[AnimeRow] = []

    for folder in folders:
        episodes = folder.sorted_episodes()
        episode_paths = [e.file_path for e in episodes]
        status = get_watch_status(episode_paths, recently_played)
        watched_count = sum(1 for value in status.values() if value is not None)
        latest_label = folder.latest_episode.episode_label if folder.latest_episode else "-"
        continue_path = resume_episode(episode_paths, recently_played)
        rows.append(
            AnimeRow(
                title=folder.title,
                episode_count=folder.episode_count,
                watched_count=watched_count,
                latest_label=latest_label,
                continue_path=continue_path,
                folder=folder,
            )
        )

    return rows
