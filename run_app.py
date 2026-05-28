"""Windows exe 启动入口：在打包后直接运行 Streamlit 应用。"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from streamlit.web import cli as stcli


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _resolve_app_file(base_dir: Path) -> Path | None:
    candidates = [
        base_dir / "app.py",
        base_dir / "_internal" / "app.py",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _log_path(base_dir: Path) -> Path:
    return base_dir / "launcher.log"


def _write_log(base_dir: Path, message: str) -> None:
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        _log_path(base_dir).open("a", encoding="utf-8").write(f"[{ts}] {message}\n")
    except Exception:
        pass


def _prepare_streamlit_config(base_dir: Path) -> None:
    cfg_dir = base_dir / ".streamlit"
    cfg_dir.mkdir(exist_ok=True)
    os.environ["STREAMLIT_CONFIG_DIR"] = str(cfg_dir)
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_GLOBAL_EMAIL"] = ""

    (cfg_dir / "config.toml").write_text(
        "[global]\ndevelopmentMode = false\n\n"
        "[browser]\ngatherUsageStats = false\n",
        encoding="utf-8",
    )
    (cfg_dir / "credentials.toml").write_text(
        "[general]\nemail = \"\"\n",
        encoding="utf-8",
    )


def _pick_free_port(start: int = 8512, attempts: int = 30) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 8501


def _open_browser_later(base_dir: Path, port: int) -> None:
    def _run() -> None:
        time.sleep(3.0)
        try:
            url = f"http://127.0.0.1:{port}"
            webbrowser.open(url)
            _write_log(base_dir, f"browser open requested: {url}")
        except Exception as exc:
            _write_log(base_dir, f"browser open failed: {exc}")

    threading.Thread(target=_run, daemon=True).start()


def main() -> int:
    base_dir = _base_dir()
    _write_log(base_dir, f"launcher started, base={base_dir}")

    # 在 PyInstaller 冻结态下，确保 _MEIPASS 在 sys.path 最前面
    # 这样 src、feedparser、qbittorrentapi 等包才能被 import
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = sys._MEIPASS
        if meipass not in sys.path:
            sys.path.insert(0, meipass)
        _write_log(base_dir, f"_MEIPASS={meipass}")
    _write_log(base_dir, f"sys.path={sys.path[:4]}")

    _prepare_streamlit_config(base_dir)

    app_file = _resolve_app_file(base_dir)
    if app_file is None:
        _write_log(
            base_dir,
            f"app.py not found: {base_dir / 'app.py'} ; {base_dir / '_internal' / 'app.py'}",
        )
        return 1

    os.chdir(app_file.parent)
    _write_log(base_dir, f"cwd switched to {Path.cwd()}")
    port = _pick_free_port()
    _write_log(base_dir, f"selected port={port}")
    _open_browser_later(base_dir, port)

    sys.argv = [
        "streamlit",
        "run",
        str(app_file),
        "--server.headless=true",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--global.developmentMode=false",
        "--browser.gatherUsageStats=false",
        "--server.fileWatcherType=none",
    ]
    _write_log(base_dir, f"argv={sys.argv}")
    try:
        rc = stcli.main()
        _write_log(base_dir, f"streamlit exited rc={rc}")
        return int(rc or 0)
    except Exception:
        _write_log(base_dir, "streamlit crashed:\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
