from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QThreadPool, QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.qt.workers import Worker
from gui.services.cover_service import bytes_to_pixmap, folder_cover_bytes
from gui.services.media_service import AnimeRow, build_media_rows
from gui.themes import repolish
from gui.views.widgets.cover_card import CoverCard
from src.utils.file_parser import AnimeFolder
from src.utils.watch_progress import (
    get_recently_played,
    get_watch_status,
    record_played,
    resume_episode,
)


# ── Episode detail page (full page, not dialog) ──────────────────

class EpisodeDetailPage(QWidget):
    """Detail view rendered inline inside MediaLibraryPage's QStackedWidget."""

    def __init__(self, parent: "MediaLibraryPage") -> None:
        super().__init__(parent)
        self._parent = parent
        self._row: AnimeRow | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # 标题行
        title_row = QHBoxLayout()
        title_lbl = QLabel("🎬  媒体库")
        title_lbl.setObjectName("page-title")
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)
        root.addLayout(title_row)

        # 返回按钮
        self.back_btn = QPushButton("← 返回媒体库")
        self.back_btn.setObjectName("back-btn")
        self.back_btn.clicked.connect(self._parent.show_grid)
        root.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # 头部信息（封面 + 标题 + 继续观看）
        header = QHBoxLayout()
        header.setSpacing(20)
        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(180, 252)
        self.cover_lbl.setStyleSheet("border-radius: 8px; background: #333;")
        self.cover_lbl.setScaledContents(True)
        header.addWidget(self.cover_lbl)

        info_col = QVBoxLayout()
        info_col.setSpacing(10)
        self.title_lbl = QLabel("—")
        self.title_lbl.setObjectName("featured-title")
        self.title_lbl.setWordWrap(True)
        info_col.addWidget(self.title_lbl)

        self.meta_lbl = QLabel()
        self.meta_lbl.setObjectName("featured-meta")
        info_col.addWidget(self.meta_lbl)

        self.continue_btn = QPushButton("▶ 继续观看")
        self.continue_btn.setObjectName("hot-btn")
        self.continue_btn.setMinimumWidth(220)
        self.continue_btn.clicked.connect(self._play_continue)
        info_col.addWidget(self.continue_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        info_col.addStretch(1)
        header.addLayout(info_col, stretch=1)
        root.addLayout(header)

        # 分隔
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #444;")
        root.addWidget(sep)

        # 剧集列表
        eps_lbl = QLabel("📁  剧集列表")
        eps_lbl.setObjectName("section-header")
        root.addWidget(eps_lbl)

        self.eps_host = QWidget()
        self.eps_grid = QGridLayout(self.eps_host)
        self.eps_grid.setSpacing(12)
        self.eps_grid.setContentsMargins(0, 4, 0, 0)
        root.addWidget(self.eps_host)
        root.addStretch(1)

    def load(self, row: AnimeRow) -> None:
        self._row = row
        self.title_lbl.setText(row.title)

        # cover
        data = folder_cover_bytes(row.folder)
        if data:
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                self.cover_lbl.setPixmap(
                    pix.scaled(
                        180, 252,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                self.cover_lbl.clear()
        else:
            self.cover_lbl.clear()

        # episodes & watch state
        media_root = Path(
            self._parent._cfg.get("qbittorrent", {}).get("save_path", "").strip().strip('"').strip("'")
        )
        eps = row.folder.sorted_episodes()
        recent = get_recently_played(media_root)
        status = get_watch_status([e.file_path for e in eps], recent)
        watched_paths = {Path(k) for k, v in status.items() if v is not None}
        continue_ep = resume_episode([e.file_path for e in eps], recent)

        latest = row.folder.latest_episode.episode_label if row.folder.latest_episode else "—"
        self.meta_lbl.setText(
            f"共 {len(eps)} 集  ·  已看 {len(watched_paths)} 集  ·  最新：{latest}"
        )

        if continue_ep is not None:
            # find the episode label for continue_ep
            label = ""
            for ep in eps:
                if ep.file_path == continue_ep:
                    label = ep.episode_label
                    break
            self.continue_btn.setText(f"▶ 继续观看  {label}" if label else "▶ 继续观看")
            self.continue_btn.setEnabled(True)
            self.continue_btn.setProperty("continue_path", str(continue_ep))
        elif eps:
            # never watched → start from episode 1
            first_ep = eps[0]
            self.continue_btn.setText(f"👀 快看看我  {first_ep.episode_label}")
            self.continue_btn.setEnabled(True)
            self.continue_btn.setProperty("continue_path", str(first_ep.file_path))
        else:
            self.continue_btn.setEnabled(False)

        # episode grid
        self._clear_eps()
        cols = 4
        for i, ep in enumerate(eps):
            is_watched = ep.file_path in watched_paths
            btn_text = f"{'✓ ' if is_watched else '▶ '}{ep.episode_label}"
            cell = QVBoxLayout()
            cell.setSpacing(2)
            btn = QPushButton(btn_text)
            btn.setObjectName("ep-btn")
            btn.setProperty("watched", "true" if is_watched else "false")
            btn.clicked.connect(lambda _checked=False, p=ep.file_path: self._open_file(p))
            cell.addWidget(btn)
            try:
                size_mb = ep.file_path.stat().st_size / 1024 / 1024
                size_text = f"{size_mb:.0f} MB"
            except Exception:
                size_text = ""
            size_lbl = QLabel(size_text)
            size_lbl.setObjectName("ep-size")
            cell.addWidget(size_lbl)
            wrapper = QWidget()
            wrapper.setLayout(cell)
            self.eps_grid.addWidget(wrapper, i // cols, i % cols)

    def _clear_eps(self) -> None:
        while self.eps_grid.count():
            item = self.eps_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _play_continue(self) -> None:
        path = self.continue_btn.property("continue_path")
        if path:
            self._open_file(Path(path))

    def _open_file(self, path: Path) -> None:
        try:
            record_played(path)
            os.startfile(str(path))  # type: ignore[attr-defined]
            # reload to update watched marks
            if self._row:
                QTimer.singleShot(500, lambda: self.load(self._row) if self._row else None)
        except Exception as exc:
            QMessageBox.warning(self, "播放失败", str(exc))


# ── Featured "continue watching" card ────────────────────────────

class _FeaturedCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("featured-card")
        self._row: AnimeRow | None = None
        self._on_continue = None
        self._on_open = None

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(16)

        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(110, 154)
        self.cover_lbl.setStyleSheet("border-radius: 6px; background: #333;")
        self.cover_lbl.setScaledContents(True)
        self.cover_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cover_lbl.mouseReleaseEvent = self._cover_clicked  # type: ignore
        h.addWidget(self.cover_lbl)

        col = QVBoxLayout()
        col.setSpacing(6)
        self.title_lbl = QLabel("—")
        self.title_lbl.setObjectName("featured-title")
        self.title_lbl.setWordWrap(True)
        col.addWidget(self.title_lbl)

        self.meta_lbl = QLabel()
        self.meta_lbl.setObjectName("featured-meta")
        col.addWidget(self.meta_lbl)

        col.addStretch(1)

        self.action_btn = QPushButton("▶ 继续观看")
        self.action_btn.setObjectName("hot-btn")
        self.action_btn.setMinimumWidth(180)
        self.action_btn.clicked.connect(self._action_clicked)
        col.addWidget(self.action_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        h.addLayout(col, stretch=1)

    def load(self, row: AnimeRow, on_continue, on_open) -> None:
        self._row = row
        self._on_continue = on_continue
        self._on_open = on_open
        self.title_lbl.setText(row.title)

        data = folder_cover_bytes(row.folder)
        if data:
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                self.cover_lbl.setPixmap(
                    pix.scaled(
                        110, 154,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                self.cover_lbl.clear()
        else:
            self.cover_lbl.clear()

        latest = row.latest_label
        self.meta_lbl.setText(
            f"共 {row.episode_count} 集  ·  已看 {row.watched_count} 集  ·  最新：{latest}"
        )

        # Find continue episode label
        if row.continue_path:
            cont_label = ""
            for ep in row.folder.sorted_episodes():
                if ep.file_path == row.continue_path:
                    cont_label = ep.episode_label
                    break
            self.action_btn.setText(f"▶ 继续观看  {cont_label}" if cont_label else "▶ 继续观看")
        else:
            self.action_btn.setText("👀 快看看我")

    def _cover_clicked(self, _event) -> None:
        if self._row and self._on_open:
            self._on_open(self._row)

    def _action_clicked(self) -> None:
        if self._row and self._on_continue:
            self._on_continue(self._row)


# ── Main page ───────────────────────────────────────────────────

class MediaLibraryPage(QWidget):
    def __init__(self, config: dict) -> None:
        super().__init__()
        self._cfg = config
        self._thread_pool = QThreadPool.globalInstance()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_async)
        self._rows: list[AnimeRow] = []
        self._active_workers: list = []
        self._build_ui()
        self.apply_config(config)
        self.refresh_async()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        # ── Page 0: grid view ──
        self.grid_page = QWidget()
        root = QVBoxLayout(self.grid_page)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        title_lbl = QLabel("🎬  媒体库")
        title_lbl.setObjectName("page-title")
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜索标题...")
        self.search_edit.setMinimumWidth(200)
        self.search_edit.textChanged.connect(self._render_rows)
        title_row.addWidget(self.search_edit)
        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh_async)
        title_row.addWidget(self.refresh_btn)
        root.addLayout(title_row)

        info_row = QHBoxLayout()
        self.path_label = QLabel("媒体目录：—")
        self.path_label.setObjectName("hint-text")
        info_row.addWidget(self.path_label)
        info_row.addStretch(1)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("status-text")
        info_row.addWidget(self.status_label)
        root.addLayout(info_row)

        # Featured continue-watching card
        self.featured_card = _FeaturedCard()
        root.addWidget(self.featured_card)
        self.featured_card.setVisible(False)

        # Grid scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(self.scroll.Shape.NoFrame)
        self.cards_host = QWidget()
        self.cards_host.setStyleSheet("background: transparent;")
        self.cards_grid = QGridLayout(self.cards_host)
        self.cards_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.cards_grid.setSpacing(10)
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(self.cards_host)
        root.addWidget(self.scroll, stretch=1)

        self.stack.addWidget(self.grid_page)

        # ── Page 1: detail view ──
        self.detail_page = EpisodeDetailPage(self)
        self.stack.addWidget(self.detail_page)

        self.stack.setCurrentIndex(0)

    def apply_config(self, config: dict) -> None:
        self._cfg = config
        media_path = config.get("qbittorrent", {}).get("save_path", "")
        self.path_label.setText(f"媒体目录：{media_path or '（未配置）'}")
        auto = bool(config.get("ui", {}).get("auto_refresh_enabled", False))
        self._reset_timer(auto, int(config.get("ui", {}).get("auto_refresh_seconds", 30) or 30))

    def _reset_timer(self, enabled: bool, seconds: int) -> None:
        self._refresh_timer.stop()
        if enabled:
            self._refresh_timer.start(max(5, min(seconds, 3600)) * 1000)

    def _clear_cards(self) -> None:
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _calc_cols(self) -> int:
        available = self.scroll.viewport().width() - 10
        return max(2, available // 170)

    def refresh_async(self) -> None:
        media_path = self._cfg.get("qbittorrent", {}).get("save_path", "").strip().strip('"').strip("'")
        if not media_path:
            self.status_label.setText("未配置媒体目录，请前往「⚙️ 设置」配置 qBittorrent 下载路径。")
            return
        if not Path(media_path).exists():
            self.status_label.setText(f"媒体目录不存在：{media_path}")
            return

        self.refresh_btn.setEnabled(False)
        self.status_label.setText("扫描媒体库中...")
        worker = Worker(build_media_rows, media_path)
        self._active_workers.append(worker)
        worker.signals.result.connect(self._on_rows_loaded)
        worker.signals.error.connect(self._on_refresh_error)
        worker.signals.finished.connect(lambda w=worker: (
            self.refresh_btn.setEnabled(True),
            self._active_workers.remove(w) if w in self._active_workers else None,
        ))
        self._thread_pool.start(worker)

    def _on_refresh_error(self, text: str) -> None:
        self.status_label.setText("扫描失败")
        QMessageBox.critical(self, "扫描失败", text)

    def _on_rows_loaded(self, rows: list[AnimeRow]) -> None:
        self._rows = rows
        self._render_rows()
        total_eps = sum(r.episode_count for r in rows)
        self.status_label.setText(f"共 {len(rows)} 部番剧  ·  {total_eps} 个文件")
        # If currently in detail view and the row still exists, reload it
        if self.stack.currentIndex() == 1 and self.detail_page._row:
            old_title = self.detail_page._row.title
            for r in rows:
                if r.title == old_title:
                    self.detail_page.load(r)
                    break

    def _filtered_rows(self) -> list[AnimeRow]:
        kw = self.search_edit.text().strip().lower()
        return [r for r in self._rows if kw in r.title.lower()] if kw else list(self._rows)

    def _pick_featured(self, rows: list[AnimeRow]) -> AnimeRow | None:
        """Best row to feature: latest in-progress > most recently updated."""
        in_progress = [r for r in rows if r.continue_path is not None]
        if in_progress:
            in_progress.sort(key=lambda r: r.folder.latest_mtime, reverse=True)
            return in_progress[0]
        if rows:
            return max(rows, key=lambda r: r.folder.latest_mtime)
        return None

    def _render_rows(self) -> None:
        self._clear_cards()
        rows = self._filtered_rows()

        featured = self._pick_featured(rows)
        if featured:
            self.featured_card.load(featured, self._continue_play_row, self._show_detail)
            self.featured_card.setVisible(True)
        else:
            self.featured_card.setVisible(False)

        cols = self._calc_cols()
        for i, row in enumerate(rows):
            has_progress = row.continue_path is not None
            action_text = "继续看我 ▶" if has_progress else "快看看我 👀"
            subtitle = f"{row.watched_count}/{row.episode_count} 集  ·  最新 {row.latest_label}"
            cover = bytes_to_pixmap(folder_cover_bytes(row.folder))
            card = CoverCard(
                title=row.title,
                subtitle=subtitle,
                pixmap=cover,
                action_text=action_text,
                action_enabled=True,
            )
            card.cover_clicked.connect(lambda _r=row: self._show_detail(_r))
            card.action_clicked.connect(
                lambda _r=row: self._continue_play_row(_r)
            )
            self.cards_grid.addWidget(card, i // cols, i % cols)

    def _continue_play_row(self, row: AnimeRow) -> None:
        if row.continue_path:
            self._continue_play(row.continue_path)
        else:
            # never watched → start from first episode
            eps = row.folder.sorted_episodes()
            if eps:
                self._continue_play(eps[0].file_path)
            else:
                self._show_detail(row)

    def _show_detail(self, row: AnimeRow) -> None:
        self.detail_page.load(row)
        self.stack.setCurrentIndex(1)

    def show_grid(self) -> None:
        self.stack.setCurrentIndex(0)
        self.refresh_async()

    def _continue_play(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            record_played(path)
            os.startfile(str(path))  # type: ignore[attr-defined]
            QTimer.singleShot(800, self.refresh_async)
        except Exception as exc:
            QMessageBox.warning(self, "播放失败", str(exc))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._rows:
            QTimer.singleShot(120, self._render_rows)
