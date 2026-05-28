from datetime import datetime
from pathlib import Path

from src.utils.watch_progress import next_unwatched_episode, resume_episode


def test_resume_episode_prefers_last_watched_episode():
    eps = [Path("ep1.mkv"), Path("ep2.mkv"), Path("ep3.mkv")]
    recently_played = {
        "ep1.mkv": datetime(2026, 1, 1, 20, 0, 0),
        "ep2.mkv": datetime(2026, 1, 1, 21, 0, 0),
    }

    assert resume_episode(eps, recently_played) == Path("ep2.mkv")


def test_resume_episode_falls_back_to_first_episode_without_history():
    eps = [Path("ep1.mkv"), Path("ep2.mkv")]

    assert resume_episode(eps, {}) == Path("ep1.mkv")


def test_next_unwatched_episode_still_points_to_next_episode():
    eps = [Path("ep1.mkv"), Path("ep2.mkv"), Path("ep3.mkv")]
    recently_played = {"ep2.mkv": datetime(2026, 1, 1, 21, 0, 0)}

    assert next_unwatched_episode(eps, recently_played) == Path("ep3.mkv")
