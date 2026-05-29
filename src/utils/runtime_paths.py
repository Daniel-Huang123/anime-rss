"""Runtime path helpers for both dev mode and frozen executable mode."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _project_root() -> Path:
    # src/utils/runtime_paths.py -> src -> project root
    return Path(__file__).resolve().parents[2]


def app_root() -> Path:
    """Return the application root directory.

    - Dev mode: repository root.
    - Frozen mode: executable directory.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _project_root()


def _roaming_data_root() -> Path:
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "zhuifanji"

    # Fallback for rare environments where APPDATA is unavailable.
    return Path.home() / "AppData" / "Roaming" / "zhuifanji"


def _copy_file_if_missing(src: Path, dst: Path) -> None:
    if not src.is_file() or dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree_if_missing(src: Path, dst: Path) -> None:
    if not src.is_dir() or dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def _migrate_legacy_data(legacy_root: Path, data_root: Path) -> None:
    """Migrate user data from old exe-root layout into roaming data root.

    Migration is "missing-only": existing roaming files are never overwritten.
    """
    try:
        if legacy_root.resolve() == data_root.resolve():
            return
    except Exception:
        # If resolution fails for any reason, continue with best-effort checks.
        pass

    # File-based runtime state.
    for rel in (
        "config.yaml",
        "state.json",
        "watch_history.json",
        "potplayer_plays.txt",
        ".mikan_cache.json",
        ".pending_checks.json",
        "crash.log",
    ):
        _copy_file_if_missing(legacy_root / rel, data_root / rel)

    # Directory-based runtime state.
    _copy_tree_if_missing(legacy_root / ".cover_cache", data_root / ".cover_cache")
    _copy_tree_if_missing(legacy_root / "assets" / "covers", data_root / "assets" / "covers")


def data_root() -> Path:
    """Return runtime data root.

    - Dev mode: repository root (keeps local development behavior unchanged).
    - Frozen mode: %APPDATA%\\zhuifanji
    """
    if not getattr(sys, "frozen", False):
        return _project_root()

    root = _roaming_data_root()
    root.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_data(app_root(), root)
    return root


APP_ROOT = app_root()
DATA_ROOT = data_root()


def _resource_roots() -> list[Path]:
    """Possible resource roots for dev mode and PyInstaller one-dir mode."""
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        roots.append(Path(meipass))

    internal = APP_ROOT / "_internal"
    if internal.exists():
        roots.append(internal)

    roots.append(APP_ROOT)

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def find_resource(*parts: str) -> Path | None:
    """Return the first existing resource path across known roots."""
    for root in _resource_roots():
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    return None


CONFIG_FILE = DATA_ROOT / "config.yaml"
STATE_FILE = DATA_ROOT / "state.json"
WATCH_HISTORY_FILE = DATA_ROOT / "watch_history.json"
POTPLAYER_LOG_FILE = DATA_ROOT / "potplayer_plays.txt"

COVER_CACHE_DIR = DATA_ROOT / ".cover_cache"
ASSETS_COVERS_DIR = DATA_ROOT / "assets" / "covers"
MIKAN_CACHE_FILE = DATA_ROOT / ".mikan_cache.json"
PENDING_CHECKS_FILE = DATA_ROOT / ".pending_checks.json"
