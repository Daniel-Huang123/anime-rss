from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThreadPool, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStackedWidget,
    QWidget,
)

from gui.qt.workers import Worker
from gui.services.config_service import ConfigService
from gui.services.update_service import (
    can_self_update,
    check_latest_release,
    download_update,
    fetch_expected_sha256,
    launch_updater,
    prepare_update,
    sha256_of,
)
from gui.views.dashboard_page import DashboardPage
from gui.views.media_library_page import MediaLibraryPage
from gui.views.quarter_cleanup_page import QuarterCleanupPage
from gui.views.season_subscription_page import SeasonSubscriptionPage
from gui.views.settings_page import SettingsPage
from gui.views.subscription_management_page import SubscriptionManagementPage


class _ProgressEmitter(QObject):
    progress = pyqtSignal(int, int)


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
        self._update_info: dict = {}
        self._dl_cancelled: bool = False
        self.setWindowTitle("追番姬")
        if self._app is not None:
            self.setWindowIcon(self._app.windowIcon())
        self.resize(1280, 800)
        self._cfg = ConfigService.load()
        self._build_ui()
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
        self.season_sub_page.subscription_changed.connect(self.media_page.resync_covers)
        self.sub_manage_page.subscription_changed.connect(self.media_page.resync_covers)
        self.sub_manage_page.subscription_changed.connect(self.season_sub_page.refresh_subscription_state)

        for page in (self.dashboard_page, self.season_sub_page, self.sub_manage_page,
                     self.cleanup_page, self.media_page, self.settings_page):
            self.stack.addWidget(page)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self._update_notice = QLabel("")
        self._update_notice.setTextFormat(Qt.TextFormat.RichText)
        self._update_notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._update_notice.linkActivated.connect(self._on_notice_link)
        self._update_notice.setVisible(False)
        self.statusBar().addPermanentWidget(self._update_notice)

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

        self._update_info = result
        latest = str(result.get("latest_version", "")).strip()
        current = str(result.get("current_version", "")).strip()
        self._release_url = str(result.get("url", "")).strip()
        asset = result.get("asset") or {}
        can_in_app = can_self_update() and bool(asset.get("url"))

        if can_in_app:
            self._update_notice.setText(
                f'<span style="color:#cf1f1f;">● 发现新版本 {latest}（当前 {current}）</span>　'
                f'<a href="act:update" style="color:#cf1f1f;">立即更新</a>　·　'
                f'<a href="{self._release_url}" style="color:#888;text-decoration:none;">手动下载</a>'
            )
            self._update_notice.setVisible(True)
        elif self._release_url:
            self._update_notice.setText(
                f'<a href="{self._release_url}" style="color:#cf1f1f;text-decoration:none;">'
                f"● 发现新版本 {latest}（当前 {current}），点击前往下载</a>"
            )
            self._update_notice.setVisible(True)

    def _on_notice_link(self, href: str) -> None:
        if href == "act:update":
            self._start_in_app_update()
        elif href:
            QDesktopServices.openUrl(QUrl(href))

    # ── 应用内更新流程 ────────────────────────────────────────

    def _start_in_app_update(self) -> None:
        asset = (self._update_info.get("asset") or {}) if self._update_info else {}
        url = str(asset.get("url") or "")
        if not (can_self_update() and url):
            if self._release_url:
                QDesktopServices.openUrl(QUrl(self._release_url))
            return

        latest = str(self._update_info.get("latest_version", "")).strip()
        size_mb = int(asset.get("size") or 0) / 1024 / 1024
        size_txt = f"约 {size_mb:.0f} MB" if size_mb >= 1 else "未知大小"
        ret = QMessageBox.question(
            self,
            "更新追番姬",
            f"将更新到 {latest}（{size_txt}）。\n\n"
            "下载完成后程序会自动重启完成替换，\n"
            "你的订阅、设置、观看进度和封面缓存都会保留。\n\n现在更新吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._begin_download(asset)

    def _begin_download(self, asset: dict) -> None:
        self._dl_cancelled = False
        self._dl_progress = QProgressDialog("正在下载更新…", "取消", 0, 100, self)
        self._dl_progress.setWindowTitle("下载更新")
        self._dl_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._dl_progress.setMinimumDuration(0)
        self._dl_progress.setAutoClose(False)
        self._dl_progress.setAutoReset(False)
        self._dl_progress.setValue(0)
        self._dl_progress.canceled.connect(self._cancel_download)

        self._dl_emitter = _ProgressEmitter()
        self._dl_emitter.progress.connect(self._on_dl_progress)

        dest = Path(__import__("tempfile").gettempdir()) / (asset.get("name") or "zhuifanji_update.zip")
        worker = Worker(self._download_job, str(asset.get("url") or ""), str(dest), str(asset.get("sha256_url") or ""))
        self._active_workers.append(worker)
        worker.signals.result.connect(self._on_download_done)
        worker.signals.error.connect(self._on_download_error)
        worker.signals.finished.connect(
            lambda w=worker: self._active_workers.remove(w) if w in self._active_workers else None
        )
        self._thread_pool.start(worker)

    def _cancel_download(self) -> None:
        self._dl_cancelled = True

    def _download_job(self, url: str, dest: str, sha_url: str) -> str:
        def _cb(done: int, total: int) -> None:
            if self._dl_cancelled:
                raise RuntimeError("cancelled")
            self._dl_emitter.progress.emit(done, total)

        download_update(url, dest, progress_cb=_cb)
        expected = fetch_expected_sha256(sha_url) if sha_url else ""
        if expected:
            actual = sha256_of(dest)
            if actual.lower() != expected.lower():
                raise RuntimeError("文件校验失败（sha256 不匹配），可能下载损坏")
        return dest

    def _on_dl_progress(self, done: int, total: int) -> None:
        if not hasattr(self, "_dl_progress") or self._dl_progress is None:
            return
        if total > 0:
            self._dl_progress.setMaximum(100)
            self._dl_progress.setValue(int(done * 100 / total))
            self._dl_progress.setLabelText(f"正在下载更新…  {done // 1024 // 1024} / {total // 1024 // 1024} MB")
        else:
            self._dl_progress.setMaximum(0)

    def _on_download_done(self, dest: str) -> None:
        if hasattr(self, "_dl_progress") and self._dl_progress is not None:
            self._dl_progress.close()
        try:
            info = prepare_update(dest)
            launch_updater(info["ps1"])
        except Exception as exc:
            QMessageBox.critical(self, "更新失败", f"准备更新失败：\n{exc}\n\n可点「手动下载」前往发布页。")
            return
        # 退出应用，让 updater 接管替换并重启（用户数据保留）
        QApplication.instance().quit()

    def _on_download_error(self, text: str) -> None:
        if hasattr(self, "_dl_progress") and self._dl_progress is not None:
            self._dl_progress.close()
        if "cancelled" in text.lower():
            return
        QMessageBox.warning(
            self,
            "下载失败",
            f"更新下载失败：\n{text}\n\n可点「手动下载」前往发布页手动更新。",
        )
