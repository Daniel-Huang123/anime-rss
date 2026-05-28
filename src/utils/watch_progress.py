"""播放进度追踪：本地 history 文件（主）+ Windows Recent Files（补充）。

本地 history（watch_history.json）：
  每次通过本 app 的 ▶ 按钮打开文件时写入，永久保存，不受 Windows Recent 数量限制。

Windows Recent 补充：
  覆盖直接在 PotPlayer 里打开的文件（未经过本 app 的记录）。
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from src.utils.runtime_paths import POTPLAYER_LOG_FILE, WATCH_HISTORY_FILE

_VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".m2ts", ".ts"}

_RECENT_DIR = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Recent"

# 本地播放历史文件
_HISTORY_FILE = WATCH_HISTORY_FILE
_POTPLAYER_LOG = POTPLAYER_LOG_FILE
_DPL_FILE      = Path(os.environ.get("APPDATA", "")) / "PotPlayerMini64" / "Playlist" / "PotPlayerMini64.dpl"


# ── 本地 history 读写 ──────────────────────────────────────

def record_played(filepath: str | Path) -> None:
    """记录一次播放事件到本地 watch_history.json。从 _open_file 调用。"""
    path_str = str(filepath)
    now_iso = datetime.now().isoformat()
    try:
        data: dict = json.loads(_HISTORY_FILE.read_text(encoding="utf-8")) if _HISTORY_FILE.exists() else {}
        data[path_str] = now_iso
        _HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _persist_to_history(entries: dict[str, datetime]) -> None:
    """
    把传入的 {路径: 时间} 写入 watch_history.json（仅补充缺失条目，不覆盖已有记录）。
    用于把 .dpl 解析结果持久化，防止 PotPlayer 切换列表后丢失进度。
    """
    if not entries:
        return
    try:
        data: dict = json.loads(_HISTORY_FILE.read_text(encoding="utf-8")) if _HISTORY_FILE.exists() else {}
        lower_existing = {k.lower() for k in data}
        changed = False
        for path, dt in entries.items():
            if path.lower() not in lower_existing:
                data[path] = dt.isoformat()
                lower_existing.add(path.lower())
                changed = True
        if changed:
            _HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_local_history(media_root: Path | str | None = None) -> dict[str, datetime]:
    """读取本地 watch_history.json。"""
    if not _HISTORY_FILE.exists():
        return {}
    try:
        data: dict = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    result: dict[str, datetime] = {}
    root_lower = str(media_root).lower().rstrip("\\/") if media_root else None
    for path_str, iso in data.items():
        if root_lower and not path_str.lower().startswith(root_lower):
            continue
        try:
            result[path_str] = datetime.fromisoformat(iso)
        except Exception:
            result[path_str] = datetime.min
    return result


# ── Windows Recent 补充 ────────────────────────────────────

def _load_windows_recent(media_root: Path | str | None = None) -> dict[str, datetime]:
    """通过 PowerShell 解析 Windows Recent .lnk，返回 {路径: 时间}。"""
    if not _RECENT_DIR.exists():
        return {}

    recent_escaped = str(_RECENT_DIR).replace("'", "''")
    ps_script = f"""
$shell = New-Object -COM WScript.Shell
Get-ChildItem '{recent_escaped}' -Filter '*.lnk' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    ForEach-Object {{
        try {{
            $target = $shell.CreateShortcut($_.FullName).TargetPath
            if ($target -match '\\.(mkv|mp4|avi|mov|wmv|flv|m2ts|ts)$') {{
                "$($_.LastWriteTime.Ticks)|$target"
            }}
        }} catch {{}}
    }}
"""
    try:
        ps_utf8 = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n" + ps_script
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", ps_utf8],
            capture_output=True, timeout=10,
        )
        lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    except Exception:
        return {}

    played: dict[str, datetime] = {}
    root_lower = str(media_root).lower().rstrip("\\/") if media_root else None
    for line in lines:
        if "|" not in line:
            continue
        ticks_str, target = line.split("|", 1)
        target = target.strip()
        if not target:
            continue
        if root_lower and not target.lower().startswith(root_lower):
            continue
        try:
            ticks = int(ticks_str)
            dt = datetime(1601, 1, 1) + __import__("datetime").timedelta(microseconds=ticks // 10)
        except Exception:
            dt = datetime.min
        played[target] = dt

    return played


# ── 公开接口 ───────────────────────────────────────────────

def _load_potplayer_dpl(media_root: Path | str | None = None) -> dict[str, datetime]:
    """
    解析 PotPlayer 的 .dpl 播放列表文件。
    逻辑：列表中排在 playname 之前（含）的集数视为已看。
    """
    if not _DPL_FILE.exists():
        return {}
    try:
        text = _DPL_FILE.read_text(encoding="utf-16", errors="replace")
    except Exception:
        try:
            text = _DPL_FILE.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return {}

    playname = ""
    entries: list[str] = []          # 按列表顺序存文件路径

    root_lower = str(media_root).lower().rstrip("\\/") if media_root else None

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("playname="):
            playname = line[len("playname="):]
        elif "*file*" in line:
            # 格式：1*file*C:\path\to\file.mkv
            path = line.split("*file*", 1)[-1].strip()
            entries.append(path)

    if not playname or not entries:
        return {}

    # 找 playname 在列表里的位置（大小写不敏感）
    playname_lower = playname.lower()
    current_idx = next(
        (i for i, p in enumerate(entries) if p.lower() == playname_lower),
        len(entries) - 1,   # 找不到就取末尾
    )

    # 列表顺序中 <= current_idx 的都视为已看
    mtime = datetime.fromtimestamp(_DPL_FILE.stat().st_mtime)
    result: dict[str, datetime] = {}
    for i, path in enumerate(entries[: current_idx + 1]):
        if root_lower and not path.lower().startswith(root_lower):
            continue
        # 越早看时间越早（用秒偏移保证相对顺序）
        result[path] = mtime - __import__("datetime").timedelta(seconds=current_idx - i)

    # 立即持久化到 watch_history.json，防止 PotPlayer 切换列表后数据丢失
    _persist_to_history(result)
    return result


def _load_potplayer_log(media_root: Path | str | None = None) -> dict[str, datetime]:
    """读取 PotPlayer AngelScript 写入的播放日志（potplayer_plays.txt）。"""
    if not _POTPLAYER_LOG.exists():
        return {}
    try:
        lines = _POTPLAYER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return {}

    root_lower = str(media_root).lower().rstrip("\\/") if media_root else None
    # 用行号作为相对时序（行越靠后越新），统一映射到文件修改时间附近
    log_mtime = datetime.fromtimestamp(_POTPLAYER_LOG.stat().st_mtime)

    result: dict[str, datetime] = {}
    for i, line in enumerate(lines):
        path = line.strip()
        if not path:
            continue
        if root_lower and not path.lower().startswith(root_lower):
            continue
        # 越靠后的行给越晚的时间（以秒为单位偏移，不影响实际排序逻辑）
        result[path] = log_mtime + __import__("datetime").timedelta(seconds=i)

    return result


def get_recently_played(media_root: Path | str | None = None) -> dict[str, datetime]:
    """
    合并本地 history + PotPlayer 日志 + Windows Recent。
    优先级：本地 history > PotPlayer 日志 > Windows Recent。
    """
    local    = _load_local_history(media_root)
    dpl      = _load_potplayer_dpl(media_root)       # .dpl 播放列表（位置前的集数）
    potplayer = _load_potplayer_log(media_root)      # AngelScript 日志（如已配置）
    recent   = _load_windows_recent(media_root)

    # 低优先级先写，高优先级后覆盖
    merged: dict[str, datetime] = {}
    for source in (recent, dpl, potplayer, local):
        for path, dt in source.items():
            existing_lower = {k.lower(): k for k in merged}
            key_lower = path.lower()
            if key_lower in existing_lower:
                old_key = existing_lower[key_lower]
                if dt >= merged[old_key]:
                    del merged[old_key]
                    merged[path] = dt
            else:
                merged[path] = dt

    return merged


def get_watch_status(
    episode_files: list[Path],
    recently_played: dict[str, datetime],
) -> dict[str, datetime | None]:
    """返回 {文件路径字符串: 最后播放时间 | None}，大小写不敏感。"""
    lower_to_played: dict[str, datetime] = {
        k.lower(): v for k, v in recently_played.items()
    }
    result: dict[str, datetime | None] = {}
    for f in episode_files:
        result[str(f)] = lower_to_played.get(str(f).lower())
    return result


def last_watched_episode(
    episode_files: list[Path],
    recently_played: dict[str, datetime],
) -> tuple[Path | None, datetime | None]:
    """返回最近一次播放的剧集及其时间。"""
    status = get_watch_status(episode_files, recently_played)
    candidates = [(Path(k), v) for k, v in status.items() if v is not None]
    if not candidates:
        return None, None
    return max(candidates, key=lambda x: x[1])


def resume_episode(
    episode_files: list[Path],
    recently_played: dict[str, datetime],
) -> Path | None:
    """继续观看目标：优先最近播放的当前集；无历史时回到第一集。"""
    last, _ = last_watched_episode(episode_files, recently_played)
    if last is not None:
        return last
    return episode_files[0] if episode_files else None


def next_unwatched_episode(
    episode_files: list[Path],
    recently_played: dict[str, datetime],
) -> Path | None:
    """找到上次看到的集数之后的第一个未看集。episode_files 应已按集数顺序排列。"""
    status = get_watch_status(episode_files, recently_played)
    watched = {Path(k) for k, v in status.items() if v is not None}

    if not watched:
        return episode_files[0] if episode_files else None

    last_idx = -1
    for i, f in enumerate(episode_files):
        if f in watched:
            last_idx = i

    next_idx = last_idx + 1
    if next_idx < len(episode_files):
        return episode_files[next_idx]
    return episode_files[last_idx] if last_idx >= 0 else None
