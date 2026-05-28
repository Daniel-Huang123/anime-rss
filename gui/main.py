from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from gui.themes import apply as apply_theme
from gui.views.main_window import MainWindow
from gui.services.config_service import ConfigService


def main() -> int:
    app = QApplication(sys.argv)
    cfg = ConfigService.load()
    theme_name = cfg.get("ui", {}).get("theme", "night")
    apply_theme(app, theme_name)
    win = MainWindow(app)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
