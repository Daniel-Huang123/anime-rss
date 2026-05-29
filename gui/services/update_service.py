from __future__ import annotations

import importlib.metadata
import json
import re
import sys
from pathlib import Path

import requests

from src.utils.runtime_paths import APP_ROOT

REPO_OWNER = "Daniel-Huang123"
REPO_NAMES = ("anime-rss", "anime-season-rss")
DESKTOP_ASSET_KEYWORDS = ("zhuifanji", "desktop", "pyqt", "gui")
DESKTOP_ASSET_EXTENSIONS = (".exe", ".msi", ".zip", ".7z")


def _api_url(repo_name: str) -> str:
    return f"https://api.github.com/repos/{REPO_OWNER}/{repo_name}/releases?per_page=20"


def _release_url(repo_name: str) -> str:
    return f"https://github.com/{REPO_OWNER}/{repo_name}/releases"


def _desktop_asset_url(release: dict) -> str:
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        return ""

    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").lower()
        if not name.endswith(DESKTOP_ASSET_EXTENSIONS):
            continue
        if not any(keyword in name for keyword in DESKTOP_ASSET_KEYWORDS):
            continue
        return str(asset.get("browser_download_url") or asset.get("html_url") or "").strip()

    return ""


def _is_desktop_release(release: dict) -> bool:
    if _desktop_asset_url(release):
        return True

    marker_text = " ".join(
        str(release.get(key) or "").lower() for key in ("tag_name", "name", "body")
    )
    has_desktop_marker = any(keyword in marker_text for keyword in DESKTOP_ASSET_KEYWORDS)
    has_streamlit_marker = "streamlit" in marker_text or "web" in marker_text
    return has_desktop_marker and not has_streamlit_marker


def _release_download_url(release: dict, repo_name: str) -> str:
    return _desktop_asset_url(release) or str(release.get("html_url") or _release_url(repo_name)).strip()


def _version_tuple(raw: str) -> tuple[int, ...]:
    norm = raw.strip().lstrip("vV")
    parts = re.split(r"[.-]", norm)
    nums: list[int] = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
        else:
            break
    return tuple(nums) if nums else (0,)


def current_version() -> str:
    try:
        return importlib.metadata.version("zhuifanji")
    except Exception:
        pass

    pyprojects = [APP_ROOT / "pyproject.toml"]
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        pyprojects.append(Path(bundle_root) / "pyproject.toml")

    for pyproject in pyprojects:
        if not pyproject.exists():
            continue
        text = pyproject.read_text(encoding="utf-8")
        m = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return "0.0.0"


def check_latest_release(timeout: float = 5.0) -> dict:
    """Check latest desktop GUI release and compare with local version."""
    cur = current_version()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "zhuifanji-update-check"}
    last_err = ""

    for repo_name in REPO_NAMES:
        try:
            resp = requests.get(_api_url(repo_name), timeout=timeout, headers=headers)
            if resp.status_code == 404:
                last_err = f"{repo_name} not found"
                continue
            resp.raise_for_status()
            payload = resp.json() if isinstance(resp.text, str) else json.loads(resp.text)
            releases = payload if isinstance(payload, list) else [payload]

            release = next(
                (
                    item
                    for item in releases
                    if isinstance(item, dict)
                    and not item.get("draft")
                    and not item.get("prerelease")
                    and _is_desktop_release(item)
                ),
                None,
            )
            if not release:
                last_err = f"{repo_name} has no desktop GUI release"
                continue

            latest = str(release.get("tag_name") or release.get("name") or "").strip()
            page_url = _release_download_url(release, repo_name) or _release_url(repo_name)
            if not latest:
                return {"ok": False, "reason": "latest release missing tag_name"}

            has_update = _version_tuple(latest) > _version_tuple(cur)
            return {
                "ok": True,
                "has_update": has_update,
                "current_version": cur,
                "latest_version": latest,
                "url": page_url,
            }
        except Exception as exc:
            last_err = str(exc)

    return {
        "ok": False,
        "reason": last_err or "release check failed",
        "current_version": cur,
        "url": _release_url(REPO_NAMES[0]),
    }
