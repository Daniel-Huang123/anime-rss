from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.qt.workers import Worker
from gui.themes import repolish
from src.qbt.client import QBTClient
from src.utils.file_parser import scan_media_directory
from src.utils.season import current_quarter
from src.utils.state import get_all_subscriptions_flat, get_quarters_to_cleanup


class _MetricCard(QFrame):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metric-card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(90)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self.label_lbl = QLabel(label)
        self.label_lbl.setObjectName("metric-label")
        layout.addWidget(self.label_lbl)

        self.value_lbl = QLabel("—")
        self.value_lbl.setObjectName("metric-value")
        self.value_lbl.setProperty("warn", "false")
        layout.addWidget(self.value_lbl)

    def set_value(self, value: str, warn: bool = False) -> None:
        self.value_lbl.setText(value)
        self.value_lbl.setProperty("warn", "true" if warn else "false")
        repolish(self.value_lbl)


class DashboardPage(QWidget):
    def __init__(self, config: dict) -> None:
        super().__init__()
        self._cfg = config
        self._thread_pool = QThreadPool.globalInstance()
        self._active_workers: list = []
        self._build_ui()
        self.refresh()

    def apply_config(self, config: dict) -> None:
        self._cfg = config
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setSpacing(16)
        root.setContentsMargins(20, 20, 20, 20)

        # 标题栏
        title_row = QHBoxLayout()
        title_lbl = QLabel("🎌  番剧自动订阅管理")
        title_lbl.setObjectName("page-title")
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)
        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        title_row.addWidget(self.refresh_btn)
        root.addLayout(title_row)

        # qBittorrent 状态
        self.qbt_status_lbl = QLabel("qBittorrent：检测中...")
        self.qbt_status_lbl.setObjectName("qbt-status")
        self.qbt_status_lbl.setProperty("status", "loading")
        self.qbt_status_lbl.setToolTip("qBittorrent Web UI 连接状态")
        root.addWidget(self.qbt_status_lbl)

        # 概览卡片
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self.card_quarter = _MetricCard("当前季度")
        self.card_total   = _MetricCard("总订阅数")
        self.card_cross   = _MetricCard("已跨季度")
        self.card_clean   = _MetricCard("待清理季度")
        for card in (self.card_quarter, self.card_total, self.card_cross, self.card_clean):
            cards_row.addWidget(card)
        root.addLayout(cards_row)

        # 当前季度订阅列表
        self.sub_header = QLabel("📋 当前季度订阅列表")
        self.sub_header.setObjectName("section-header")
        root.addWidget(self.sub_header)

        self.sub_table = QTableWidget(0, 4)
        self.sub_table.setHorizontalHeaderLabels(["番剧", "字幕组", "订阅日期", "RSS URL"])
        self.sub_table.horizontalHeader().setStretchLastSection(True)
        self.sub_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sub_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sub_table.verticalHeader().setVisible(False)
        self.sub_table.setAlternatingRowColors(True)
        self.sub_table.setMinimumHeight(160)
        root.addWidget(self.sub_table)

        # 最近更新媒体库
        media_lbl = QLabel("🎬  最近更新媒体")
        media_lbl.setObjectName("section-header")
        root.addWidget(media_lbl)

        self.media_table = QTableWidget(0, 3)
        self.media_table.setHorizontalHeaderLabels(["番剧", "集数", "最新集"])
        self.media_table.horizontalHeader().setStretchLastSection(True)
        self.media_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.media_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.media_table.verticalHeader().setVisible(False)
        self.media_table.setAlternatingRowColors(True)
        self.media_table.setMinimumHeight(160)
        root.addWidget(self.media_table)

        # 使用指引
        guide_lbl = QLabel("📖  使用指引")
        guide_lbl.setObjectName("section-header")
        root.addWidget(guide_lbl)

        guide_text = QLabel(
            "1. <b>首次使用</b>：前往「⚙️ 设置」填写 qBittorrent 账密并测试连接<br>"
            "2. <b>每季度初</b>：前往「📺 季度订阅」加载番单，勾选想看的，点击订阅<br>"
            "3. <b>日常管理</b>：「📋 订阅管理」页面可查看 / 删除单个订阅<br>"
            "4. <b>季度清理</b>：「🗑️ 季度清理」页面删除超过保留期的旧资源<br>"
            "5. <b>看番</b>：「🎬 媒体库」页面查看剧集，点击用本地播放器播放"
        )
        guide_text.setObjectName("hint-text")
        guide_text.setWordWrap(True)
        root.addWidget(guide_text)
        root.addStretch(1)

    def refresh(self) -> None:
        self._check_qbt_async()
        subs = get_all_subscriptions_flat()
        cur_q = current_quarter()
        self.card_quarter.set_value(cur_q)
        self.card_total.set_value(str(len(subs)))
        self.card_cross.set_value(str(len({s["quarter"] for s in subs})))

        keep = int(self._cfg.get("cleanup", {}).get("keep_quarters", 2))
        to_clean = get_quarters_to_cleanup(keep)
        self.card_clean.set_value(str(len(to_clean)), warn=bool(to_clean))

        self.sub_header.setText(f"📋  {cur_q} 订阅列表")
        cur_rows = [s for s in subs if s.get("quarter") == cur_q]
        self.sub_table.setRowCount(len(cur_rows))
        for i, s in enumerate(cur_rows):
            self.sub_table.setItem(i, 0, QTableWidgetItem(s.get("title", "")))
            self.sub_table.setItem(i, 1, QTableWidgetItem(s.get("subgroup_name", "")))
            self.sub_table.setItem(i, 2, QTableWidgetItem(s.get("added_at", "")))
            self.sub_table.setItem(i, 3, QTableWidgetItem(s.get("rss_url", "")))
        self.sub_table.resizeColumnsToContents()

        media_path = self._cfg.get("qbittorrent", {}).get("save_path", "").strip().strip('"').strip("'")
        rows = []
        if media_path and Path(media_path).exists():
            folders = scan_media_directory(media_path)
            recent = sorted(folders, key=lambda f: f.latest_mtime, reverse=True)[:12]
            for f in recent:
                latest = f.latest_episode.episode_label if f.latest_episode else "—"
                rows.append((f.title, str(f.episode_count), latest))

        self.media_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                self.media_table.setItem(i, j, QTableWidgetItem(value))
        self.media_table.resizeColumnsToContents()

    def _check_qbt_async(self) -> None:
        qbt_cfg = self._cfg.get("qbittorrent", {})
        host = str(qbt_cfg.get("host", "")).strip()
        if not host:
            self.qbt_status_lbl.setText("qBittorrent：未配置连接信息，请前往「⚙️ 设置」填写")
            self.qbt_status_lbl.setProperty("status", "unconfigured")
            repolish(self.qbt_status_lbl)
            return
        self.qbt_status_lbl.setText("qBittorrent：检测中...")
        self.qbt_status_lbl.setProperty("status", "loading")
        repolish(self.qbt_status_lbl)

        worker = Worker(self._do_qbt_check, qbt_cfg)
        self._active_workers.append(worker)
        worker.signals.result.connect(self._on_qbt_check_done)
        worker.signals.finished.connect(lambda w=worker: (
            self._active_workers.remove(w) if w in self._active_workers else None,
        ))
        self._thread_pool.start(worker)

    @staticmethod
    def _do_qbt_check(qbt_cfg: dict) -> tuple[bool, str]:
        try:
            return QBTClient(
                host=str(qbt_cfg.get("host", "127.0.0.1")),
                port=int(qbt_cfg.get("port", 8080)),
                username=str(qbt_cfg.get("username", "admin")),
                password=str(qbt_cfg.get("password", "")),
            ).test_connection()
        except Exception as exc:
            return False, str(exc)

    def _on_qbt_check_done(self, result: tuple[bool, str]) -> None:
        ok, msg = result
        if ok:
            self.qbt_status_lbl.setText(f"qBittorrent：✅ 已连接  ·  {msg}")
            self.qbt_status_lbl.setProperty("status", "ok")
        else:
            host = self._cfg.get("qbittorrent", {}).get("host", "")
            port = self._cfg.get("qbittorrent", {}).get("port", 8080)
            self.qbt_status_lbl.setText(
                f"qBittorrent：⚠️ 无法连接到 {host}:{port}  —  "
                f"请确认 qBittorrent 已启动并开启 Web UI，或前往「⚙️ 设置」检查"
            )
            self.qbt_status_lbl.setProperty("status", "error")
        repolish(self.qbt_status_lbl)
