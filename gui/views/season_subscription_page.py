from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from PyQt6.QtCore import QThreadPool, QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.qt.workers import Worker
from gui.services.config_service import ConfigService
from gui.services.cover_service import bytes_to_pixmap, fetch_cover_bytes
from gui.services.subscription_service import (
    SeasonAnimeItem,
    SeasonDataset,
    apply_bgm_map,
    build_season_grid,
    build_season_index_and_map,
    clear_season_caches,
    subscribe_title,
    unsubscribe_title,
)
from gui.themes import SEASON_LABELS
from gui.views.widgets.cover_card import CoverCard
from src.utils.season import current_quarter, list_season_options

_DAY_ORDER = ["周一", "周二", "周三", "周四", "周五", "周六", "周日", "其他"]
_CARD_W = 170  # 160px card + 10px spacing


def _quarter_label(q: str) -> str:
    year, s = q[:4], int(q[5])
    return f"{year} {SEASON_LABELS[s]}"


class SeasonSubscriptionPage(QWidget):
    # 订阅/取消订阅成功后发出，供媒体库重新解析封面
    subscription_changed = pyqtSignal()

    def __init__(self, config: dict) -> None:
        super().__init__()
        self._cfg = config
        self._thread_pool = QThreadPool.globalInstance()
        self._quarter_timer = QTimer(self)
        self._quarter_timer.timeout.connect(self._rebuild_quarter_menu)
        self._quarter_timer.start(10 * 60 * 1000)
        self._dataset: SeasonDataset | None = None
        self._failed_titles: set[str] = set()
        self._grid_rendered: bool = False
        self._silent_load: bool = False
        self._active_workers: list[Worker] = []
        self._loading: bool = False
        self._current_quarter: str = self._initial_quarter()
        self._last_cols: int = 0
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(self._on_resize_stable)
        # 加载进度（模拟进度条 + 预计时间）
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(200)
        self._progress_timer.timeout.connect(self._tick_progress)
        self._load_elapsed_ms = 0
        self._load_est_ms = 38000  # 首次未缓存约 30-40s，命中缓存会提前结束
        self._build_ui()
        self._rebuild_quarter_menu()  # also refreshes button text + current-season button state
        # 启动即后台预加载番单，不必等用户点进本页才开始（失败静默，访问时再报错）
        QTimer.singleShot(0, self._preload)

    def _preload(self) -> None:
        if self._dataset is not None or self._loading:
            return
        self._silent_load = True
        self.refresh_async()

    def apply_config(self, config: dict) -> None:
        self._cfg = config

    # ── 上次季度记忆 ──────────────────────────────────────────

    def _initial_quarter(self) -> str:
        """启动时优先恢复上次停留的季度，否则回到当前季度。"""
        saved = (self._cfg.get("ui") or {}).get("last_quarter")
        if (
            isinstance(saved, str)
            and len(saved) == 6
            and saved[:4].isdigit()
            and saved[4] == "Q"
            and saved[5].isdigit()
        ):
            return saved
        return current_quarter()

    def _persist_last_quarter(self, quarter: str) -> None:
        """把当前季度写入配置，下次启动恢复（写盘失败不影响 UI）。"""
        try:
            self._cfg.setdefault("ui", {})["last_quarter"] = quarter
            ConfigService.save(self._cfg)
        except Exception:
            pass

    # ── 季度选择器（年份级联菜单）────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        title_lbl = QLabel("📺  季度订阅")
        title_lbl.setObjectName("page-title")
        root.addWidget(title_lbl)

        # 控制栏
        top = QHBoxLayout()
        self.quarter_btn = QToolButton()
        self.quarter_btn.setMinimumWidth(140)
        self.quarter_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.quarter_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        top.addWidget(self.quarter_btn)

        self.current_season_btn = QPushButton("⟲ 回到当前季度")
        self.current_season_btn.setToolTip("跳转到当前最新季度番单")
        self.current_season_btn.clicked.connect(self._jump_to_current)
        top.addWidget(self.current_season_btn)

        self.refresh_cache_btn = QPushButton("🗑 刷新缓存")
        self.refresh_cache_btn.setToolTip("清除 yuc.wiki 番单和蜜柑索引缓存，重新爬取并加载")
        self.refresh_cache_btn.clicked.connect(self._refresh_cache)
        top.addWidget(self.refresh_cache_btn)
        top.addStretch(1)
        root.addLayout(top)

        # 筛选
        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 输入关键词搜索...")
        self.search_edit.textChanged.connect(self._render_cards)
        self.hide_subbed = QCheckBox("隐藏已订阅")
        self.hide_subbed.toggled.connect(self._render_cards)
        filters.addWidget(self.search_edit, stretch=1)
        filters.addWidget(self.hide_subbed)
        root.addLayout(filters)

        self.status_lbl = QLabel("加载中…")
        self.status_lbl.setObjectName("status-text")
        root.addWidget(self.status_lbl)

        # 通知栏（默认隐藏）
        self.notif_frame = QFrame()
        self.notif_frame.setObjectName("notif-bar")
        notif_row = QHBoxLayout(self.notif_frame)
        notif_row.setContentsMargins(10, 6, 10, 6)
        self.notif_lbl = QLabel()
        self.notif_lbl.setObjectName("notif-text")
        self.notif_retry_btn = QPushButton("重新加载")
        self.notif_retry_btn.clicked.connect(self.refresh_async)
        self.notif_close_btn = QPushButton("✕")
        self.notif_close_btn.setFixedWidth(28)
        self.notif_close_btn.clicked.connect(lambda: self.notif_frame.setVisible(False))
        notif_row.addWidget(self.notif_lbl, stretch=1)
        notif_row.addWidget(self.notif_retry_btn)
        notif_row.addWidget(self.notif_close_btn)
        self.notif_frame.setVisible(False)
        root.addWidget(self.notif_frame)

        # 加载提示（含进度条 + 预计时间，默认隐藏）
        self.loading_frame = QFrame()
        self.loading_frame.setObjectName("loading-frame")
        load_box = QVBoxLayout(self.loading_frame)
        load_box.setContentsMargins(20, 28, 20, 28)
        load_box.setSpacing(12)
        load_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_msg = QLabel("🐾  追番姬正在努力加载中，耐心等待下喵~")
        self.loading_msg.setObjectName("loading-msg")
        self.loading_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        load_box.addWidget(self.loading_msg)
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 100)
        self.loading_bar.setValue(0)
        self.loading_bar.setFixedWidth(360)
        load_box.addWidget(self.loading_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        self.loading_eta = QLabel("")
        self.loading_eta.setObjectName("loading-eta")
        self.loading_eta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        load_box.addWidget(self.loading_eta)
        self.loading_frame.setVisible(False)
        root.addWidget(self.loading_frame)

        # 卡片区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(self.scroll.Shape.NoFrame)
        self.cards_host = QWidget()
        self.cards_host.setStyleSheet("background: transparent;")
        self.cards_vbox = QVBoxLayout(self.cards_host)
        self.cards_vbox.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.cards_vbox.setSpacing(4)
        self.cards_vbox.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(self.cards_host)
        root.addWidget(self.scroll, stretch=1)

    def _rebuild_quarter_menu(self) -> None:
        menu = QMenu(self)
        quarters = list_season_options(20)
        cur_q = current_quarter()
        cur_year = cur_q[:4]
        by_year: dict[str, list[str]] = defaultdict(list)
        for q in quarters:
            by_year[q[:4]].append(q)
        for year in sorted(by_year.keys(), reverse=True):
            label = f"{year}  ●" if year == cur_year else year
            year_menu = QMenu(label, self)
            for q in sorted(by_year[year], key=lambda x: int(x[5])):
                s = int(q[5])
                suffix = "  ●" if q == cur_q else ""
                action = year_menu.addAction(f"{SEASON_LABELS[s]}番组{suffix}")
                action.setData(q)
                action.triggered.connect(partial(self._select_quarter, q))
            menu.addMenu(year_menu)
        # Top-level shortcut to current quarter
        menu.addSeparator()
        jump = menu.addAction(f"⟲  跳到当前季度（{_quarter_label(cur_q)}）")
        jump.triggered.connect(self._jump_to_current)
        self.quarter_btn.setMenu(menu)
        self._update_quarter_btn_text()

    def _update_quarter_btn_text(self) -> None:
        cur_q = current_quarter()
        on_current = self._current_quarter == cur_q
        if on_current:
            self.quarter_btn.setText(f"📅  {_quarter_label(self._current_quarter)}  ●  ▾")
        else:
            self.quarter_btn.setText(f"📅  {_quarter_label(self._current_quarter)}  ▾")
        # 已在当前季度（或正在加载）时禁用「回到当前季度」按钮
        if hasattr(self, "current_season_btn"):
            self.current_season_btn.setEnabled(not on_current and not self._loading)

    def _select_quarter(self, q: str) -> None:
        self._current_quarter = q
        self._update_quarter_btn_text()
        self._persist_last_quarter(q)
        self.refresh_async()  # 切换季度后自动加载

    def _sync_to_current(self) -> None:
        self._current_quarter = current_quarter()
        self._update_quarter_btn_text()
        self._persist_last_quarter(self._current_quarter)

    def _jump_to_current(self) -> None:
        """回到当前季度并自动加载。"""
        self._sync_to_current()
        self.refresh_async()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 首次显示（或缓存清空后）自动加载，免去手动「加载番单」
        if self._dataset is None and not self._loading:
            QTimer.singleShot(0, self.refresh_async)

    def _set_busy(self, busy: bool) -> None:
        """加载/订阅期间禁用交互控件，防止并发请求。"""
        self._loading = busy
        self.quarter_btn.setEnabled(not busy)
        self.refresh_cache_btn.setEnabled(not busy)
        self.current_season_btn.setEnabled(
            not busy and self._current_quarter != current_quarter()
        )

    # ── 加载提示 / 模拟进度 ────────────────────────────────────

    def _start_loading_ui(self) -> None:
        """清屏并展示「追番姬加载中」提示 + 进度条。"""
        self._clear_cards()
        self._grid_rendered = False
        self._load_elapsed_ms = 0
        self.loading_bar.setValue(0)
        self.loading_eta.setText(
            f"预计还需 ~{self._load_est_ms // 1000} 秒（首次较慢，之后走缓存秒开）"
        )
        self.loading_frame.setVisible(True)
        self._progress_timer.start()

    def _tick_progress(self) -> None:
        self._load_elapsed_ms += self._progress_timer.interval()
        pct = min(95, int(self._load_elapsed_ms / self._load_est_ms * 100))
        self.loading_bar.setValue(pct)
        if self._load_elapsed_ms >= self._load_est_ms:
            self.loading_eta.setText("就快好了喵~ 马上就来")
        else:
            remain = (self._load_est_ms - self._load_elapsed_ms) // 1000
            self.loading_eta.setText(f"预计还需 ~{remain} 秒")

    def _stop_loading_ui(self) -> None:
        self._progress_timer.stop()
        self.loading_bar.setValue(100)
        self.loading_frame.setVisible(False)

    # ── 缓存刷新 ──────────────────────────────────────────────

    def _refresh_cache(self) -> None:
        self._set_busy(True)
        self.status_lbl.setText("清理缓存中...")
        worker = Worker(clear_season_caches)
        self._active_workers.append(worker)
        worker.signals.finished.connect(lambda w=worker: (
            self._on_cache_cleared(),
            self._active_workers.remove(w) if w in self._active_workers else None,
        ))
        self._thread_pool.start(worker)

    def _on_cache_cleared(self) -> None:
        self._set_busy(False)
        self.status_lbl.setText("缓存已清除，正在重新加载…")
        self._dataset = None
        self._failed_titles.clear()
        self._clear_cards()
        self.refresh_async()  # 自动重新加载

    # ── 数据加载 ──────────────────────────────────────────────

    def refresh_async(self) -> None:
        quarter = self._current_quarter
        if not quarter or self._loading:
            return
        self._set_busy(True)
        self.notif_frame.setVisible(False)
        self._start_loading_ui()
        self.status_lbl.setText(f"正在加载 {quarter} 番单...")
        # 快路径：只抓 yuc.wiki 番单即可渲染网格；蜜柑索引随后后台构建
        worker = Worker(build_season_grid, self._cfg, quarter)
        self._active_workers.append(worker)
        worker.signals.result.connect(self._on_grid_loaded)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(lambda w=worker: (
            self._set_busy(False),
            self._active_workers.remove(w) if w in self._active_workers else None,
        ))
        self._thread_pool.start(worker)

    def _on_grid_loaded(self, dataset: SeasonDataset) -> None:
        self._silent_load = False  # 加载成功，后续失败正常弹窗
        self._dataset = dataset
        self._failed_titles.clear()
        n_subbed = sum(1 for it in dataset.items if it.subscribed)
        self.status_lbl.setText(
            f"{dataset.quarter}  共 {len(dataset.items)} 部  ·  已订阅 {n_subbed} 部  ·  封面加载中..."
        )
        # Check pending notifications
        self._check_pending_notifications(dataset.quarter)

        uncached = [it.cover_url for it in dataset.items if it.cover_url]
        if uncached:
            prefetch_worker = Worker(self._prefetch_covers_sync, uncached)
            self._active_workers.append(prefetch_worker)
            prefetch_worker.signals.error.connect(lambda _: None)
            prefetch_worker.signals.finished.connect(lambda w=prefetch_worker: (
                self._finish_render(),
                self._active_workers.remove(w) if w in self._active_workers else None,
            ))
            self._thread_pool.start(prefetch_worker)
        else:
            self._finish_render()

        # 后台构建蜜柑索引（不阻塞网格交互）：完成后回填 bgm 链接并启用精准订阅
        self._start_index_build(dataset.quarter)

    def _start_index_build(self, quarter: str) -> None:
        idx_worker = Worker(build_season_index_and_map, self._cfg, quarter)
        self._active_workers.append(idx_worker)
        idx_worker.signals.result.connect(partial(self._on_index_ready, quarter))
        idx_worker.signals.error.connect(lambda _: None)  # 索引失败不影响网格
        idx_worker.signals.finished.connect(lambda w=idx_worker: (
            self._active_workers.remove(w) if w in self._active_workers else None,
        ))
        self._thread_pool.start(idx_worker)

    def _on_index_ready(self, quarter: str, result: tuple[dict[int, int], dict[str, int]]) -> None:
        # 用户可能已切换季度——只回填仍匹配的 dataset
        if not self._dataset or self._dataset.quarter != quarter:
            return
        season_index, yuc_bgm_map = result
        self._dataset.season_index = season_index
        self._dataset.yuc_bgm_map = yuc_bgm_map
        apply_bgm_map(self._dataset, yuc_bgm_map)
        # 首屏（封面预抓）还没渲染完时，不要抢先出网格——bgm_map 已写入 dataset，
        # 交给 _finish_render 一次性渲染（否则会出现"番单已出但加载条还在"）。
        if not self._grid_rendered:
            return
        # 轻量重渲染：封面已缓存，主要为让卡片封面点击跳转 bgm 链接生效
        self._render_cards()
        n_subbed = sum(1 for it in self._dataset.items if it.subscribed)
        self.status_lbl.setText(
            f"{self._dataset.quarter}  共 {len(self._dataset.items)} 部  ·  已订阅 {n_subbed} 部  ·  索引就绪"
        )

    def _check_pending_notifications(self, quarter: str) -> None:
        from gui.services.subscription_service import get_pending_checks
        pending = get_pending_checks().get(quarter, [])
        if pending:
            self.notif_lbl.setText(
                f"💡  上次有 {len(pending)} 部番剧未能匹配到资源（"
                + "、".join(pending[:3])
                + ("…" if len(pending) > 3 else "")
                + "），点击「重新加载」可再次尝试匹配"
            )
            self.notif_frame.setVisible(True)

    @staticmethod
    def _prefetch_covers_sync(urls: list[str]) -> None:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(fetch_cover_bytes, urls))

    def _finish_render(self) -> None:
        self._stop_loading_ui()
        if not self._dataset:
            return
        n_subbed = sum(1 for it in self._dataset.items if it.subscribed)
        self.status_lbl.setText(
            f"{self._dataset.quarter}  共 {len(self._dataset.items)} 部  ·  已订阅 {n_subbed} 部"
        )
        self._render_cards()
        self._grid_rendered = True

    def _on_error(self, text: str) -> None:
        self._stop_loading_ui()
        self._set_busy(False)
        if self._silent_load:
            # 启动预加载失败：不打扰，留待用户进入本页时再加载/报错
            self._silent_load = False
            self.status_lbl.setText("番单待加载（点开本页或「重新加载」重试）")
            return
        QMessageBox.critical(self, "加载失败", text)
        self.status_lbl.setText("加载失败")

    # ── 卡片渲染 ──────────────────────────────────────────────

    def _calc_cols(self) -> int:
        available = self.scroll.viewport().width() - 10
        return max(2, available // _CARD_W)

    def _iter_filtered_items(self) -> list[SeasonAnimeItem]:
        if not self._dataset:
            return []
        items = list(self._dataset.items)
        kw = self.search_edit.text().strip().lower()
        if kw:
            items = [it for it in items if kw in it.title.lower()]
        if self.hide_subbed.isChecked():
            items = [it for it in items if not it.subscribed]
        return items

    def _clear_cards(self) -> None:
        while self.cards_vbox.count():
            child = self.cards_vbox.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()

    def _render_cards(self) -> None:
        self._clear_cards()
        if not self._dataset:
            return
        items = self._iter_filtered_items()
        cols = self._calc_cols()
        self._last_cols = cols

        day_groups: defaultdict[str, list[SeasonAnimeItem]] = defaultdict(list)
        for it in items:
            day_groups[it.day].append(it)

        ordered_days = [d for d in _DAY_ORDER if d in day_groups] + \
                       [d for d in day_groups if d not in _DAY_ORDER]

        for day in ordered_days:
            day_items = day_groups[day]
            n_sub = sum(1 for it in day_items if it.subscribed)
            hint = f"  ·  ✓ {n_sub}" if n_sub else ""

            day_lbl = QLabel(f"{day}  {len(day_items)} 部{hint}")
            day_lbl.setObjectName("day-header")
            self.cards_vbox.addWidget(day_lbl)

            section = QWidget()
            section.setStyleSheet("background: transparent;")
            grid = QGridLayout(section)
            grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            grid.setSpacing(10)
            grid.setContentsMargins(0, 4, 0, 8)

            for idx, it in enumerate(day_items):
                cover = bytes_to_pixmap(fetch_cover_bytes(it.cover_url))
                subtitle = f"{it.broadcast_time}\n{it.episodes}"

                if it.title in self._failed_titles:
                    action_text = "❌ 重试"
                elif it.subscribed:
                    action_text = "✓ 已订阅"
                else:
                    action_text = "＋ 订阅"

                card = CoverCard(
                    title=it.title,
                    subtitle=subtitle,
                    pixmap=cover,
                    action_text=action_text,
                    action_enabled=True,
                )
                if it.bgm_url:
                    card.cover_clicked.connect(partial(self._open_url, it.bgm_url))
                if it.title in self._failed_titles:
                    card.action_clicked.connect(partial(self._retry_subscribe_async, it))
                else:
                    card.action_clicked.connect(partial(self._toggle_subscribe_async, it))

                grid.addWidget(card, idx // cols, idx % cols)

            self.cards_vbox.addWidget(section)

        self.cards_vbox.addStretch(1)

    def _open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._dataset:
            self._resize_timer.start()

    def _on_resize_stable(self) -> None:
        new_cols = self._calc_cols()
        if new_cols != self._last_cols:
            self._render_cards()

    # ── 订阅操作 ──────────────────────────────────────────────

    def _toggle_subscribe_async(self, item: SeasonAnimeItem) -> None:
        if not self._dataset:
            return
        quarter = self._dataset.quarter

        if item.subscribed:
            ret = QMessageBox.question(
                self,
                "确认取消订阅",
                f"取消订阅《{item.title}》？\n\n取消后将停止自动下载新集数（不会删除已下载文件）。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        self.status_lbl.setText(f"{'取消订阅' if item.subscribed else '订阅'}中：{item.title}")
        self._set_busy(True)

        if item.subscribed:
            worker = Worker(unsubscribe_title, self._cfg, quarter, item.title, True)
        else:
            worker = Worker(
                subscribe_title,
                self._cfg, quarter, item.title, item.cover_url, self._dataset.season_index,
            )
        self._active_workers.append(worker)
        worker.signals.result.connect(partial(self._on_toggle_done, item))
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(lambda w=worker: (
            self._set_busy(False),
            self._active_workers.remove(w) if w in self._active_workers else None,
        ))
        self._thread_pool.start(worker)

    def _retry_subscribe_async(self, item: SeasonAnimeItem) -> None:
        if not self._dataset:
            return
        text, ok = QInputDialog.getText(
            self,
            "自定义搜索词重试",
            f"《{item.title}》在蜜柑计划未找到资源。\n请输入自定义搜索词（留空取消）：",
            text=item.title,
        )
        if not ok or not text.strip():
            return

        search_term = text.strip()
        self.status_lbl.setText(f"重试订阅中：{item.title}（搜索词：{search_term}）")
        self._set_busy(True)

        worker = Worker(
            subscribe_title,
            self._cfg, self._dataset.quarter, item.title,
            item.cover_url, self._dataset.season_index, search_term,
        )
        self._active_workers.append(worker)
        worker.signals.result.connect(partial(self._on_toggle_done, item))
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(lambda w=worker: (
            self._set_busy(False),
            self._active_workers.remove(w) if w in self._active_workers else None,
        ))
        self._thread_pool.start(worker)

    def _on_toggle_done(self, item: SeasonAnimeItem, result: tuple[bool, str]) -> None:
        ok, msg = result
        if ok:
            item.subscribed = not item.subscribed
            self._failed_titles.discard(item.title)
            # Remove from pending if successfully subscribed
            if item.subscribed and self._dataset:
                from gui.services.subscription_service import remove_pending_check
                remove_pending_check(self._dataset.quarter, item.title)
            self._render_cards()
            self.subscription_changed.emit()
        else:
            if "未找到可用RSS" in msg:
                self._failed_titles.add(item.title)
                # Save to persistent pending list
                if self._dataset:
                    from gui.services.subscription_service import add_pending_check
                    add_pending_check(self._dataset.quarter, item.title)
                self._render_cards()
            else:
                QMessageBox.warning(self, "操作失败", msg)
        self.status_lbl.setText(msg)
