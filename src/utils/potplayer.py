"""PotPlayer 检测与播放。

媒体库的播放进度追踪依赖 PotPlayer 写入 .dpl 播放列表历史，
因此优先用 PotPlayer 启动文件；找不到时回落到系统默认关联播放器。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# 64 位优先，覆盖 Mini/标准 两套命名
_EXE_NAMES = [
    "PotPlayerMini64.exe",
    "PotPlayer64.exe",
    "PotPlayerMini.exe",
    "PotPlayer.exe",
]


def _from_registry() -> str | None:
    try:
        import winreg
    except Exception:
        return None
    app_paths = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for name in _EXE_NAMES:
            try:
                with winreg.OpenKey(root, f"{app_paths}\\{name}") as k:
                    val, _ = winreg.QueryValueEx(k, "")
                    if val and Path(val).exists():
                        return str(val)
            except Exception:
                continue
    return None


def _from_common_dirs() -> str | None:
    roots = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    for r in roots:
        if not r:
            continue
        for sub in ("PotPlayer", "PotPlayer64"):
            d = Path(r) / "DAUM" / sub
            for name in _EXE_NAMES:
                p = d / name
                if p.exists():
                    return str(p)
    return None


def detect_potplayer(config: dict | None = None) -> str | None:
    """按 配置保存路径 → 注册表 → 常见安装目录 顺序查找 PotPlayer.exe。

    找不到返回 None（此时媒体库的进度追踪功能受限）。
    """
    if config:
        saved = (config.get("ui") or {}).get("potplayer_path")
        if isinstance(saved, str) and saved.strip() and Path(saved).exists():
            return saved
    return _from_registry() or _from_common_dirs()


def play_media(path: str | Path, config: dict | None = None) -> None:
    """用 PotPlayer 启动（若可用），否则用系统默认播放器。

    失败时抛出异常，由调用方处理（弹窗提示）。
    """
    exe = detect_potplayer(config)
    if exe:
        subprocess.Popen([exe, str(path)])
    else:
        os.startfile(str(path))  # type: ignore[attr-defined]
