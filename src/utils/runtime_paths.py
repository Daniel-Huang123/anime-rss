"""统一管理开发态与 exe 打包态的运行时路径。"""

from __future__ import annotations

import sys
from pathlib import Path


def _project_root() -> Path:
    # src/utils/runtime_paths.py -> src -> project_root
    return Path(__file__).resolve().parents[2]


def app_root() -> Path:
    """
    返回运行根目录：
    - 开发态：项目根目录（包含 gui_main.py）
    - PyInstaller 冻结态：exe 所在目录（便于配置和状态持久化）
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _project_root()


APP_ROOT = app_root()


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

CONFIG_FILE = APP_ROOT / "config.yaml"
STATE_FILE = APP_ROOT / "state.json"
WATCH_HISTORY_FILE = APP_ROOT / "watch_history.json"
POTPLAYER_LOG_FILE = APP_ROOT / "potplayer_plays.txt"

COVER_CACHE_DIR = APP_ROOT / ".cover_cache"
ASSETS_COVERS_DIR = APP_ROOT / "assets" / "covers"
MIKAN_CACHE_FILE = APP_ROOT / ".mikan_cache.json"
