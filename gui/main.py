from __future__ import annotations

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from gui.services.config_service import ConfigService
from gui.themes import DEFAULT_THEME, apply as apply_theme
from gui.views.main_window import MainWindow
from gui.views.onboarding_dialog import OnboardingDialog
from src.utils.crash_handler import install_global_crash_handlers
from src.utils.runtime_paths import find_resource

_SINGLE_INSTANCE_KEY = "zhuifanji_single_instance_v1"


def _load_app_icon() -> QIcon:
    for filename in ("zhuifanji.ico", "zhuifanji.png"):
        path = find_resource("assets", "logo", filename)
        if path is not None:
            return QIcon(str(path))
    return QIcon()


def _activate_main_window(win: MainWindow) -> None:
    if win.isMinimized():
        win.showNormal()
    win.show()
    win.raise_()
    win.activateWindow()


def _ensure_single_instance() -> tuple[bool, QLocalServer | None]:
    probe = QLocalSocket()
    probe.connectToServer(_SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(120):
        try:
            probe.write(b"ACTIVATE")
            probe.flush()
            probe.waitForBytesWritten(120)
        except Exception:
            pass
        probe.disconnectFromServer()
        return False, None

    # 清理异常退出遗留的命名管道（若不存在则忽略）
    QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    if not server.listen(_SINGLE_INSTANCE_KEY):
        return False, None
    return True, server


def main() -> int:
    # 打包自检模式：只验证匹配/下载链路并退出，不创建 GUI（见 gui/selftest.py）。
    from gui.selftest import is_selftest, run_selftest
    if is_selftest(sys.argv):
        return run_selftest(sys.argv)

    app = QApplication(sys.argv)
    primary, server = _ensure_single_instance()
    if not primary:
        return 0
    app.setWindowIcon(_load_app_icon())
    install_global_crash_handlers()
    cfg = ConfigService.load()
    theme_name = cfg.get("ui", {}).get("theme", DEFAULT_THEME)
    apply_theme(app, theme_name)

    # First launch: finish onboarding before showing main window.
    save_path = str(cfg.get("qbittorrent", {}).get("save_path", "")).strip()
    if not save_path:
        dlg = OnboardingDialog()
        if dlg.exec():
            cfg = dlg.saved_config()
            # Keep runtime theme in sync if onboarding eventually writes UI settings.
            theme_name = cfg.get("ui", {}).get("theme", DEFAULT_THEME)
            apply_theme(app, theme_name)
    win = MainWindow(app)
    win.show()

    if server is not None:
        def _on_new_connection() -> None:
            sock = server.nextPendingConnection()
            if sock is None:
                return
            sock.readAll()
            sock.disconnectFromServer()
            QTimer.singleShot(0, lambda: _activate_main_window(win))

        server.newConnection.connect(_on_new_connection)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
