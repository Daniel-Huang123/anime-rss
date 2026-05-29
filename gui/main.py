from __future__ import annotations

import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from gui.services.config_service import ConfigService
from gui.themes import DEFAULT_THEME, apply as apply_theme
from gui.views.main_window import MainWindow
from gui.views.onboarding_dialog import OnboardingDialog
from src.utils.crash_handler import install_global_crash_handlers
from src.utils.runtime_paths import find_resource


def _load_app_icon() -> QIcon:
    for filename in ("zhuifanji.ico", "zhuifanji.png"):
        path = find_resource("assets", "logo", filename)
        if path is not None:
            return QIcon(str(path))
    return QIcon()


def main() -> int:
    app = QApplication(sys.argv)
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
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
