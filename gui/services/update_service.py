from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from src.utils.runtime_paths import APP_ROOT

REPO_OWNER = "Daniel-Huang123"
REPO_NAMES = ("anime-rss", "anime-season-rss")
# 资产名关键词放宽：实际发布名形如 anime-rss-vX.Y.Z-windows-x64.zip
DESKTOP_ASSET_KEYWORDS = ("zhuifanji", "anime-rss", "desktop", "pyqt", "gui", "windows", "win64", "x64")
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


def find_update_asset(release: dict) -> dict:
    """从 release 资产里挑出可下载的 Windows 安装包（zip）及其 sha256 校验文件。

    返回 {'url','name','size','sha256_url'}；找不到返回 {}。
    """
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        return {}

    sha_by_base: dict[str, str] = {}
    zips: list[dict] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        low = name.lower()
        url = str(asset.get("browser_download_url") or "").strip()
        if not url:
            continue
        if low.endswith(".sha256"):
            sha_by_base[low[: -len(".sha256")]] = url
        elif low.endswith(".zip"):
            zips.append(asset)

    if not zips:
        return {}

    # 优先含 windows/x64 的 zip，否则取第一个 zip
    def _score(a: dict) -> int:
        n = str(a.get("name") or "").lower()
        return sum(k in n for k in ("windows", "win64", "x64", "zhuifanji", "anime-rss"))

    best = max(zips, key=_score)
    name = str(best.get("name") or "")
    return {
        "url": str(best.get("browser_download_url") or "").strip(),
        "name": name,
        "size": int(best.get("size") or 0),
        "sha256_url": sha_by_base.get(name.lower(), ""),
    }


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
                "asset": find_update_asset(release),
            }
        except Exception as exc:
            last_err = str(exc)

    return {
        "ok": False,
        "reason": last_err or "release check failed",
        "current_version": cur,
        "url": _release_url(REPO_NAMES[0]),
    }


# ── 应用内自动更新 ────────────────────────────────────────────


def can_self_update() -> bool:
    """仅在 PyInstaller 冻结态（有可替换的程序目录）才支持应用内更新。"""
    return bool(getattr(sys, "frozen", False))


def sha256_of(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download_update(
    url: str,
    dest: Path | str,
    progress_cb=None,
    timeout: float = 30.0,
) -> Path:
    """流式下载到 dest；progress_cb(done, total) 可选回调。返回 dest。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "zhuifanji-updater"}
    with requests.get(url, stream=True, timeout=timeout, headers=headers) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress_cb is not None:
                    progress_cb(done, total)
    return dest


def fetch_expected_sha256(sha256_url: str, timeout: float = 10.0) -> str:
    """读取 .sha256 文件内容，取第一段十六进制摘要。"""
    if not sha256_url:
        return ""
    try:
        resp = requests.get(sha256_url, timeout=timeout, headers={"User-Agent": "zhuifanji-updater"})
        resp.raise_for_status()
        token = resp.text.strip().split()[0] if resp.text.strip() else ""
        return token.lower() if re.fullmatch(r"[0-9a-fA-F]{64}", token or "") else ""
    except Exception:
        return ""


def _find_build_root(extract_dir: Path) -> Path:
    """定位解压后的程序根目录（含 _internal/ 的那一层）。zip 通常文件在根。"""
    if (extract_dir / "_internal").is_dir():
        return extract_dir
    for sub in extract_dir.iterdir():
        if sub.is_dir() and (sub / "_internal").is_dir():
            return sub
    return extract_dir


def _exe_name_in(root: Path) -> str:
    exes = sorted(p.name for p in root.glob("*.exe"))
    for name in exes:
        if "zhuifanji" in name.lower():
            return name
    return exes[0] if exes else "zhuifanji.exe"


def _build_updater_ps1(pid: int, new_root: Path, install_dir: Path, work_dir: Path, exe_name: str) -> str:
    """生成 PowerShell 更新脚本：等主程序退出 → robocopy 合并覆盖（保留用户数据）→ 重启 → 自清理。

    robocopy /E 只新增/覆盖、绝不删除目标里 zip 没有的文件，因此 config.yaml /
    state.json / .cover_cache / assets/covers / .mikan_cache.json / watch_history.json
    等用户数据天然保留。
    """
    return f"""$ErrorActionPreference = 'SilentlyContinue'
$log = Join-Path $env:TEMP 'zhuifanji_update.log'
"[{{0}}] updater start pid={pid}" -f (Get-Date -Format o) | Out-File -FilePath $log -Encoding utf8
$targetPid = {pid}
while (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 400 }}
Start-Sleep -Milliseconds 400
"pid gone, robocopy" | Out-File -FilePath $log -Append -Encoding utf8
$src = '{new_root}'
$dst = '{install_dir}'
robocopy $src $dst /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
"robocopy exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
try {{
    $restart = Start-Process -FilePath (Join-Path $dst '{exe_name}') -WorkingDirectory $dst -PassThru -ErrorAction Stop
    "restarted pid=$($restart.Id), cleanup" | Out-File -FilePath $log -Append -Encoding utf8
}} catch {{
    "restart failed: $($_.Exception.Message)" | Out-File -FilePath $log -Append -Encoding utf8
}}
Start-Sleep -Milliseconds 600
Remove-Item -LiteralPath '{work_dir}' -Recurse -Force -ErrorAction SilentlyContinue
"""


def prepare_update(zip_path: Path | str) -> dict:
    """解压更新包并写好 updater.ps1，返回启动 updater 所需的信息（不在此退出 app）。

    返回 {'ps1': Path, 'work': Path, 'exe_name': str, 'install_dir': Path}。
    """
    zip_path = Path(zip_path)
    install_dir = Path(APP_ROOT)
    work = Path(tempfile.mkdtemp(prefix="zhuifanji_upd_"))
    extract = work / "new"
    extract.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(extract)

    new_root = _find_build_root(extract)
    exe_name = _exe_name_in(new_root)
    ps1 = work / "apply_update.ps1"
    script = _build_updater_ps1(os.getpid(), new_root, install_dir, work, exe_name)
    # UTF-8 BOM：Windows PowerShell 5.1 才能正确解析脚本里的非 ASCII 安装路径
    ps1.write_text(script, encoding="utf-8-sig")
    return {"ps1": ps1, "work": work, "exe_name": exe_name, "install_dir": install_dir}


def launch_updater(ps1_path: Path | str) -> None:
    """后台无窗口启动 updater.ps1，随后调用方应立即退出 app。

    实测必须用 CREATE_NO_WINDOW + 把 stdio 指向 DEVNULL：DETACHED_PROCESS 系列会让
    powershell 拿不到有效标准句柄、根本不执行脚本（spawn 探针验证过）。CREATE_NO_WINDOW
    的子进程在父进程(app)退出后仍存活（无 job 对象托管），足以完成替换+重启。
    """
    CREATE_NO_WINDOW = 0x08000000
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(ps1_path),
        ],
        creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
