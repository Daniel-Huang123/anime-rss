from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QThreadPool, QTimer, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
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
from gui.services.config_service import ConfigService
from gui.services.cover_service import (
    batch_folder_cover_bytes,
    bytes_to_pixmap,
    invalidate_miss_cache,
)
from gui.services.cover_sync_service import (
    plan_cover_sync,
    sync_other_quarters_covers,
    sync_titles_covers,
)
from gui.services.media_service import AnimeRow, build_media_rows
from gui.themes import repolish
from gui.views.widgets.cover_card import CoverCard
from src.utils.file_parser import AnimeFolder
from src.utils.potplayer import detect_potplayer, play_media
from src.utils.watch_progress import (
    get_recently_played,
    get_watch_status,
    record_played,
    resume_episode,
)


def _scale_cover(data: bytes | None, width: int, height: int) -> QPixmap:
    return bytes_to_pixmap(data, width=width, height=height)


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

        # cover (only from cache; async updater fills later)
        cover_data = self._parent._cover_bytes_by_title.get(row.title)
        self.set_cover_bytes(cover_data)

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

    def set_cover_bytes(self, data: bytes | None) -> None:
        if data:
            self.cover_lbl.setPixmap(_scale_cover(data, 180, 252))
        else:
            self.cover_lbl.clear()

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
            play_media(path, self._parent._cfg)
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

    def load(
        self,
        row: AnimeRow,
        on_continue: Callable[[AnimeRow], None],
        on_open: Callable[[AnimeRow], None],
        cover_data: bytes | None = None,
    ) -> None:
        self._row = row
        self._on_continue = on_continue
        self._on_open = on_open
        self.title_lbl.setText(row.title)
        self.set_cover_bytes(cover_data)

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

    def set_cover_bytes(self, data: bytes | None) -> None:
        if data:
            self.cover_lbl.setPixmap(_scale_cover(data, 110, 154))
        else:
            self.cover_lbl.clear()

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
        self._cover_bytes_by_title: dict[str, bytes] = {}
        self._cards_by_title: dict[str, list[CoverCard]] = {}
        self._scan_running = False
        self._pending_refresh = False
        self._scan_seq = 0
        self._cover_seq = 0
        self._sync_seq = 0
        self._cover_synced_paths: set[str] = set()
        self._backfilled_paths: set[str] = set()
        self._current_media_path = ""
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

        # ── PotPlayer 缺失提示（行内展开，默认隐藏）──
        self.pp_hint = QFrame()
        self.pp_hint.setObjectName("pp-hint")
        pp_v = QVBoxLayout(self.pp_hint)
        pp_v.setContentsMargins(12, 8, 12, 8)
        pp_v.setSpacing(8)
        self.pp_hint_btn = QPushButton(self._pp_hint_text(False))
        self.pp_hint_btn.setObjectName("pp-hint-btn")
        self.pp_hint_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pp_hint_btn.clicked.connect(self._toggle_pp_detail)
        pp_v.addWidget(self.pp_hint_btn)

        self.pp_detail = QWidget()
        pp_d = QVBoxLayout(self.pp_detail)
        pp_d.setContentsMargins(0, 0, 0, 0)
        pp_d.setSpacing(8)
        pp_desc = QLabel("进度追踪需要 PotPlayer 写入播放记录。定位到 PotPlayer.exe 后即可正常追踪。")
        pp_desc.setObjectName("hint-text")
        pp_desc.setWordWrap(True)
        pp_d.addWidget(pp_desc)
        pp_actions = QHBoxLayout()
        self.pp_locate_btn = QPushButton("📂 定位 PotPlayer.exe")
        self.pp_locate_btn.clicked.connect(self._locate_potplayer)
        self.pp_download_btn = QPushButton("⬇️ 下载 PotPlayer")
        self.pp_download_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://potplayer.tv/"))
        )
        self.pp_guide_btn = QPushButton("📖 查看教程")
        self.pp_guide_btn.clicked.connect(self._show_pp_guide)
        pp_actions.addWidget(self.pp_locate_btn)
        pp_actions.addWidget(self.pp_download_btn)
        pp_actions.addWidget(self.pp_guide_btn)
        pp_actions.addStretch(1)
        pp_d.addLayout(pp_actions)
        self.pp_detail.setVisible(False)
        pp_v.addWidget(self.pp_detail)

        self.pp_hint.setVisible(False)
        root.addWidget(self.pp_hint)

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
        self._check_potplayer()

    # ── PotPlayer 缺失提示 ────────────────────────────────────

    def _pp_hint_text(self, expanded: bool) -> str:
        return f"🐾 追番姬找不到 PotPlayer，媒体库功能会受限哦~ 点我更新路径  {'▴' if expanded else '▾'}"

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._check_potplayer()

    def _check_potplayer(self) -> None:
        """打开媒体库时检测 PotPlayer，找不到则显示底部提示条。"""
        found = detect_potplayer(self._cfg) is not None
        self.pp_hint.setVisible(not found)
        if found:
            self.pp_detail.setVisible(False)
            self.pp_hint_btn.setText(self._pp_hint_text(False))

    def _toggle_pp_detail(self) -> None:
        show = not self.pp_detail.isVisible()
        self.pp_detail.setVisible(show)
        self.pp_hint_btn.setText(self._pp_hint_text(show))

    def _locate_potplayer(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "定位 PotPlayer.exe", "",
            "PotPlayer (PotPlayer*.exe);;可执行文件 (*.exe)",
        )
        if not path:
            return
        self._cfg.setdefault("ui", {})["potplayer_path"] = path
        try:
            ConfigService.save(self._cfg)
        except Exception:
            pass
        self._check_potplayer()
        self.status_label.setText("已设置 PotPlayer 路径 ✓")

    def _show_pp_guide(self) -> None:
        QMessageBox.information(
            self, "配置 PotPlayer",
            "1. 安装 PotPlayer（64 位）：potplayer.tv\n"
            "2. 打开 PotPlayer → 选项 → 播放 → 播放列表 →\n"
            "   勾选「保存最近播放记录」\n"
            "3. 回到这里点「📂 定位 PotPlayer.exe」，选择安装目录下的\n"
            "   PotPlayerMini64.exe\n\n"
            "之后从媒体库点击播放，追番姬就能自动追踪你的观看进度喵~",
        )

    def _reset_timer(self, enabled: bool, seconds: int) -> None:
        self._refresh_timer.stop()
        if enabled:
            self._refresh_timer.start(max(5, min(seconds, 3600)) * 1000)

    def _clear_cards(self) -> None:
        self._cards_by_title = {}
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _calc_cols(self) -> int:
        available = self.scroll.viewport().width() - 10
        return max(2, available // 170)

    def _update_visible_covers(self) -> None:
        for title, cards in self._cards_by_title.items():
            data = self._cover_bytes_by_title.get(title)
            if not data:
                continue
            pixmap = _scale_cover(data, 140, 196)
            for card in cards:
                card.set_cover_pixmap(pixmap)

        featured = self._pick_featured(self._filtered_rows())
        if featured:
            self.featured_card.set_cover_bytes(self._cover_bytes_by_title.get(featured.title))

        if self.stack.currentIndex() == 1 and self.detail_page._row:
            self.detail_page.set_cover_bytes(self._cover_bytes_by_title.get(self.detail_page._row.title))

    def refresh_async(self) -> None:
        if self._scan_running:
            self._pending_refresh = True
            self.status_label.setText("扫描进行中，完成后会自动刷新…")
            return

        media_path = self._cfg.get("qbittorrent", {}).get("save_path", "").strip().strip('"').strip("'")
        if not media_path:
            self.status_label.setText("未配置媒体目录，请前往「⚙️ 设置」配置 qBittorrent 下载路径。")
            return
        if not Path(media_path).exists():
            self.status_label.setText(f"媒体目录不存在：{media_path}")
            return

        if media_path != self._current_media_path:
            self._current_media_path = media_path
            self._cover_bytes_by_title = {}

        need_backfill = media_path not in self._backfilled_paths
        self._scan_running = True
        self._scan_seq += 1
        scan_seq = self._scan_seq

        self.refresh_btn.setEnabled(False)
        self.status_label.setText("扫描媒体库中...")
        worker = Worker(build_media_rows, media_path, self._cfg.get("qbittorrent", {}), need_backfill)
        self._active_workers.append(worker)
        worker.signals.result.connect(
            lambda rows, seq=scan_seq, path=media_path, backfill=need_backfill: self._on_rows_loaded(
                rows, seq, path, backfill
            )
        )
        worker.signals.error.connect(lambda text, seq=scan_seq: self._on_refresh_error(text, seq))
        worker.signals.finished.connect(lambda w=worker, seq=scan_seq: self._on_scan_finished(w, seq))
        self._thread_pool.start(worker)

    def _on_scan_finished(self, worker: Worker, seq: int) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        if seq != self._scan_seq:
            return
        self._scan_running = False
        self.refresh_btn.setEnabled(True)
        if self._pending_refresh:
            self._pending_refresh = False
            QTimer.singleShot(0, self.refresh_async)

    def _on_refresh_error(self, text: str, seq: int) -> None:
        if seq != self._scan_seq:
            return
        self.status_label.setText("扫描失败")
        QMessageBox.critical(self, "扫描失败", text)

    def _on_rows_loaded(self, rows: list[AnimeRow], seq: int, media_path: str, backfill: bool) -> None:
        if seq != self._scan_seq:
            return
        if backfill:
            self._backfilled_paths.add(media_path)
        self._rows = rows
        self._render_rows()
        total_eps = sum(r.episode_count for r in rows)
        self.status_label.setText(f"共 {len(rows)} 部番剧  ·  {total_eps} 个文件")
        self._start_cover_loading(rows)
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

    def _start_cover_loading(self, rows: list[AnimeRow]) -> None:
        if not rows:
            return
        self._cover_seq += 1
        cover_seq = self._cover_seq
        folders = [r.folder for r in rows]
        worker = Worker(batch_folder_cover_bytes, folders, allow_network=True)
        self._active_workers.append(worker)
        worker.signals.result.connect(lambda cover_map, seq=cover_seq: self._on_covers_loaded(cover_map, seq))
        worker.signals.error.connect(lambda text, seq=cover_seq: self._on_cover_error(text, seq))
        worker.signals.finished.connect(
            lambda w=worker: self._active_workers.remove(w) if w in self._active_workers else None
        )
        self._thread_pool.start(worker)

    def _on_cover_error(self, _text: str, seq: int) -> None:
        if seq != self._cover_seq:
            return
        # 封面失败不影响主流程，保持当前状态文本，等待下次刷新重试
        return

    def _on_covers_loaded(self, cover_map: dict[str, bytes], seq: int) -> None:
        if seq != self._cover_seq:
            return
        if cover_map:
            self._cover_bytes_by_title.update(cover_map)
            self._update_visible_covers()
        # 第一次读完媒体库后：对仍缺封面的作品做封面同步（先当季，再其他季度）
        missing = [r.title for r in self._rows if r.title not in self._cover_bytes_by_title]
        if missing:
            self._start_cover_sync(missing)

    # ── 封面同步（缺封面作品：当季 → 其他季度）──────────────────

    def _start_cover_sync(self, missing_titles: list[str]) -> None:
        # 每个媒体路径每个会话只同步一次；命中结果已写回 state + 封面缓存，
        # 后续刷新/重启走普通封面解析直接命中缓存。
        path = self._current_media_path
        if not missing_titles or path in self._cover_synced_paths:
            return
        self._cover_synced_paths.add(path)
        self._sync_seq += 1
        sync_seq = self._sync_seq

        _cur_q, cur_titles, others = plan_cover_sync(missing_titles)
        if cur_titles:
            worker = Worker(sync_titles_covers, self._cfg, cur_titles, _cur_q)
            self._active_workers.append(worker)
            worker.signals.result.connect(
                lambda cover_map, seq=sync_seq: self._on_sync_covers(cover_map, seq)
            )
            worker.signals.error.connect(lambda _text: None)
            worker.signals.finished.connect(
                lambda w=worker, o=others, seq=sync_seq: self._after_current_sync(w, o, seq)
            )
            self._thread_pool.start(worker)
        elif others:
            self._start_other_quarter_sync(others, sync_seq)

    def _after_current_sync(self, worker: Worker, others: dict, seq: int) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        if seq != self._sync_seq:
            return
        if others:
            self._start_other_quarter_sync(others, seq)

    def _start_other_quarter_sync(self, others: dict, seq: int) -> None:
        worker = Worker(sync_other_quarters_covers, self._cfg, others)
        self._active_workers.append(worker)
        worker.signals.result.connect(
            lambda cover_map, s=seq: self._on_sync_covers(cover_map, s)
        )
        worker.signals.error.connect(lambda _text: None)
        worker.signals.finished.connect(
            lambda w=worker: self._active_workers.remove(w) if w in self._active_workers else None
        )
        self._thread_pool.start(worker)

    def _on_sync_covers(self, cover_map: dict[str, bytes], seq: int) -> None:
        if seq != self._sync_seq:
            return
        if not cover_map:
            return
        self._cover_bytes_by_title.update(cover_map)
        self._update_visible_covers()

    def resync_covers(self) -> None:
        """外部订阅变化后重新解析封面（不重扫媒体目录）。

        允许对当前路径再触发一次同步：新订阅的封面通常已缓存，普通批量加载即可命中；
        若仍缺，则放行一次同步补齐。
        """
        invalidate_miss_cache()
        self._cover_synced_paths.discard(self._current_media_path)
        if self._rows:
            self._start_cover_loading(self._rows)

    def _render_rows(self) -> None:
        self._clear_cards()
        rows = self._filtered_rows()

        featured = self._pick_featured(rows)
        if featured:
            self.featured_card.load(
                featured,
                self._continue_play_row,
                self._show_detail,
                self._cover_bytes_by_title.get(featured.title),
            )
            self.featured_card.setVisible(True)
        else:
            self.featured_card.setVisible(False)

        cols = self._calc_cols()
        for i, row in enumerate(rows):
            has_progress = row.continue_path is not None
            action_text = "继续看我 ▶" if has_progress else "快看看我 👀"
            subtitle = f"{row.watched_count}/{row.episode_count} 集  ·  最新 {row.latest_label}"
            cover = _scale_cover(self._cover_bytes_by_title.get(row.title), 140, 196)
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
            self._cards_by_title.setdefault(row.title, []).append(card)

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

    def _continue_play(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            record_played(path)
            play_media(path, self._cfg)
            QTimer.singleShot(800, self.refresh_async)
        except Exception as exc:
            QMessageBox.warning(self, "播放失败", str(exc))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._rows:
            QTimer.singleShot(120, self._render_rows)
