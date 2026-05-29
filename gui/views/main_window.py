from __future__ import annotations

from PyQt6.QtCore import Qt, QThreadPool, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from gui.qt.workers import Worker
from gui.services.config_service import ConfigService
from gui.services.update_service import check_latest_release
from gui.views.dashboard_page import DashboardPage
from gui.views.media_library_page import MediaLibraryPage
from gui.views.onboarding_dialog import OnboardingDialog
from gui.views.quarter_cleanup_page import QuarterCleanupPage
from gui.views.season_subscription_page import SeasonSubscriptionPage
from gui.views.settings_page import SettingsPage
from gui.views.subscription_management_page import SubscriptionManagementPage

_NAV_ITEMS = [
    ("🏠  仪表盘",  "dashboard"),
    ("📺  季度订阅", "season_sub"),
    ("📋  订阅管理", "sub_manage"),
    ("🗑️  季度清理", "cleanup"),
    ("🎬  媒体库",  "media"),
    ("⚙️  设置",   "settings"),
]


class MainWindow(QMainWindow):
    def __init__(self, app=None) -> None:
        super().__init__()
        self._app = app
        self._thread_pool = QThreadPool.globalInstance()
        self._active_workers: list[Worker] = []
        self._release_url: str = ""
        self.setWindowTitle("🎌 追番姬")
        self.resize(1280, 800)
        self._cfg = ConfigService.load()
        self._build_ui()
        QTimer.singleShot(200, self._maybe_show_onboarding)
        QTimer.singleShot(900, self._check_update_async)

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(200)
        self.nav.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        for label, _ in _NAV_ITEMS:
            item = QListWidgetItem(label)
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.nav.addItem(item)
        root.addWidget(self.nav)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, stretch=1)

        self.dashboard_page    = DashboardPage(self._cfg)
        self.season_sub_page   = SeasonSubscriptionPage(self._cfg)
        self.sub_manage_page   = SubscriptionManagementPage(self._cfg)
        self.cleanup_page      = QuarterCleanupPage(self._cfg)
        self.media_page        = MediaLibraryPage(self._cfg)
        self.settings_page     = SettingsPage()

        self.settings_page.config_saved.connect(self._on_config_saved)

        for page in (self.dashboard_page, self.season_sub_page, self.sub_manage_page,
                     self.cleanup_page, self.media_page, self.settings_page):
            self.stack.addWidget(page)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self._update_notice = QLabel("")
        self._update_notice.setTextFormat(Qt.TextFormat.RichText)
        self._update_notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._update_notice.linkActivated.connect(self._open_release_page)
        self._update_notice.setVisible(False)
        self.statusBar().addPermanentWidget(self._update_notice)

    def _maybe_show_onboarding(self) -> None:
        save_path = self._cfg.get("qbittorrent", {}).get("save_path", "").strip()
        if save_path:
            return
        dlg = OnboardingDialog(self)
        if dlg.exec():
            self._on_config_saved(dlg.saved_config())

    def _on_config_saved(self, cfg: dict) -> None:
        self._cfg = cfg
        # Apply theme change immediately
        if self._app:
            from gui.themes import apply as apply_theme, DEFAULT_THEME
            apply_theme(self._app, cfg.get("ui", {}).get("theme", DEFAULT_THEME))

        for page in (self.dashboard_page, self.season_sub_page, self.sub_manage_page,
                     self.cleanup_page, self.media_page):
            page.apply_config(cfg)
        self.dashboard_page.refresh()
        self.media_page.refresh_async()

    def _check_update_async(self) -> None:
        worker = Worker(check_latest_release)
        self._active_workers.append(worker)
        worker.signals.result.connect(self._on_update_check_done)
        worker.signals.finished.connect(lambda w=worker: (
            self._active_workers.remove(w) if w in self._active_workers else None,
        ))
        self._thread_pool.start(worker)

    def _on_update_check_done(self, result: dict) -> None:
        if not isinstance(result, dict) or not result.get("ok"):
            return
        if not result.get("has_update"):
            self._update_notice.setVisible(False)
            return

        latest = str(result.get("latest_version", "")).strip()
        current = str(result.get("current_version", "")).strip()
        self._release_url = str(result.get("url", "")).strip()
        if not self._release_url:
            return
        self._update_notice.setText(
            f'<a href="{self._release_url}" style="color:#cf1f1f;text-decoration:none;">'
            f"● 发现新版本 {latest}（当前 {current}），点击前往下载</a>"
        )
        self._update_notice.setVisible(True)

    def _open_release_page(self, _: str) -> None:
        if self._release_url:
            QDesktopServices.openUrl(QUrl(self._release_url))
