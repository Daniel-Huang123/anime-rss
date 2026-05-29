from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from gui.themes import apply as apply_theme, DEFAULT_THEME
from gui.views.main_window import MainWindow
from gui.services.config_service import ConfigService
from src.utils.crash_handler import install_global_crash_handlers


def main() -> int:
    app = QApplication(sys.argv)
    install_global_crash_handlers()
    cfg = ConfigService.load()
    theme_name = cfg.get("ui", {}).get("theme", DEFAULT_THEME)
    apply_theme(app, theme_name)
    win = MainWindow(app)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
