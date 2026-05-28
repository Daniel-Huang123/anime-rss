from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.utils.file_parser import AnimeFolder, enrich_with_state, scan_media_directory
from src.utils.watch_progress import get_recently_played, get_watch_status, resume_episode


@dataclass
class AnimeRow:
    title: str
    episode_count: int
    watched_count: int
    latest_label: str
    continue_path: Path | None
    folder: AnimeFolder


def build_media_rows(media_root: str) -> list[AnimeRow]:
    path = Path(media_root)
    folders = scan_media_directory(path)
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
