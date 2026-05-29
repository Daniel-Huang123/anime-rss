from __future__ import annotations

import importlib.metadata
import json
import re

import requests

from src.utils.runtime_paths import APP_ROOT

REPO_OWNER = "Daniel-Huang123"
REPO_NAME = "zhuifanji"
REPO_NAME_FALLBACK = "anime-rss"


def _api_url(repo_name: str) -> str:
    return f"https://api.github.com/repos/{REPO_OWNER}/{repo_name}/releases/latest"


def _release_url(repo_name: str) -> str:
    return f"https://github.com/{REPO_OWNER}/{repo_name}/releases"


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

    pyproject = APP_ROOT / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8")
        m = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return "0.0.0"


def check_latest_release(timeout: float = 5.0) -> dict:
    """Check latest GitHub release and compare with local version."""
    cur = current_version()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "zhuifanji-update-check"}
    last_err = ""

    for repo_name in (REPO_NAME, REPO_NAME_FALLBACK):
        try:
            resp = requests.get(_api_url(repo_name), timeout=timeout, headers=headers)
            if resp.status_code == 404:
                last_err = f"{repo_name} not found"
                continue
            resp.raise_for_status()
            payload = resp.json() if isinstance(resp.text, str) else json.loads(resp.text)
            latest = str(payload.get("tag_name") or payload.get("name") or "").strip()
            page_url = str(payload.get("html_url") or _release_url(repo_name)).strip() or _release_url(repo_name)
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

    return {"ok": False, "reason": last_err or "release check failed", "current_version": cur, "url": _release_url(REPO_NAME)}
