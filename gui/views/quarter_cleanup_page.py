from __future__ import annotations

from gui.themes import repolish
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.qbt.client import QBTClient
from src.utils.state import (
    get_cleanup_log,
    get_quarters_to_cleanup,
    get_subscriptions,
    log_cleanup,
    remove_subscription,
)


class QuarterCleanupPage(QWidget):
    def __init__(self, config: dict) -> None:
        super().__init__()
        self._cfg = config
        self._build_ui()
        self.refresh()

    def apply_config(self, config: dict) -> None:
        self._cfg = config
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # 标题
        title_row = QHBoxLayout()
        title_lbl = QLabel("🗑️  季度清理")
        title_lbl.setObjectName("page-title")
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)
        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        title_row.addWidget(self.refresh_btn)
        root.addLayout(title_row)

        self.info_lbl = QLabel("")
        self.info_lbl.setObjectName("hint-text")
        root.addWidget(self.info_lbl)

        self.summary_lbl = QLabel("待清理季度: —")
        self.summary_lbl.setObjectName("summary-text")
        self.summary_lbl.setProperty("status", "warn")
        root.addWidget(self.summary_lbl)

        # 操作选项
        opts = QHBoxLayout()
        self.delete_files_check = QCheckBox("同时删除下载文件")
        self.delete_rss_check = QCheckBox("同时删除 qBittorrent RSS 订阅")
        self.delete_rss_check.setChecked(True)
        opts.addWidget(self.delete_files_check)
        opts.addWidget(self.delete_rss_check)
        opts.addStretch(1)
        self.cleanup_btn = QPushButton("🗑️  确认清理")
        self.cleanup_btn.clicked.connect(self._cleanup)
        opts.addWidget(self.cleanup_btn)
        root.addLayout(opts)

        # 待清理列表
        pending_lbl = QLabel("待清理订阅")
        pending_lbl.setObjectName("section-header")
        root.addWidget(pending_lbl)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["季度", "番剧", "字幕组", "RSS路径"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, stretch=1)

        # 清理历史
        log_lbl = QLabel("📜  清理历史")
        log_lbl.setObjectName("section-header")
        root.addWidget(log_lbl)

        self.log_table = QTableWidget(0, 3)
        self.log_table.setHorizontalHeaderLabels(["季度", "清理日期", "条数"])
        self.log_table.horizontalHeader().setStretchLastSection(True)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setMaximumHeight(180)
        root.addWidget(self.log_table)

    def refresh(self) -> None:
        cleanup_cfg = self._cfg.get("cleanup", {})
        keep_quarters = int(cleanup_cfg.get("keep_quarters", 2))
        delete_files_default = bool(cleanup_cfg.get("delete_files", True))
        self.delete_files_check.setChecked(delete_files_default)
        self.info_lbl.setText(f"当前配置：保留最近 {keep_quarters} 个季度的资源，超过则列为待清理。")

        to_clean = get_quarters_to_cleanup(keep_quarters)
        if to_clean:
            self.summary_lbl.setText(f"待清理季度：{', '.join(to_clean)}")
            self.summary_lbl.setProperty("status", "warn")
            self.cleanup_btn.setEnabled(True)
        else:
            self.summary_lbl.setText("✅ 没有需要清理的季度，一切整洁！")
            self.summary_lbl.setProperty("status", "ok")
            self.cleanup_btn.setEnabled(False)
        repolish(self.summary_lbl)

        rows = []
        for q in to_clean:
            for s in get_subscriptions(q).get(q, []):
                rows.append((q, s["title"], s.get("subgroup_name", ""), s.get("qbt_feed_path", "")))
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                self.table.setItem(i, j, QTableWidgetItem(str(value)))

        logs = list(reversed(get_cleanup_log()))
        self.log_table.setRowCount(len(logs))
        for i, entry in enumerate(logs):
            self.log_table.setItem(i, 0, QTableWidgetItem(entry.get("quarter", "")))
            self.log_table.setItem(i, 1, QTableWidgetItem(entry.get("cleaned_at", "")))
            self.log_table.setItem(i, 2, QTableWidgetItem(str(entry.get("count", 0))))

    def _cleanup(self) -> None:
        cleanup_cfg = self._cfg.get("cleanup", {})
        keep_quarters = int(cleanup_cfg.get("keep_quarters", 2))
        to_clean = get_quarters_to_cleanup(keep_quarters)
        if not to_clean:
            QMessageBox.information(self, "提示", "没有需要清理的季度")
            return

        ret = QMessageBox.question(
            self,
            "确认清理",
            f"将清理以下季度：\n{', '.join(to_clean)}\n\n⚠️ 此操作不可撤销，是否继续？",
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        qbt_cfg = self._cfg.get("qbittorrent", {})
        try:
            qbt = QBTClient(
                host=qbt_cfg["host"],
                port=qbt_cfg["port"],
                username=qbt_cfg["username"],
                password=qbt_cfg["password"],
            )
        except Exception as exc:
            QMessageBox.warning(self, "qBittorrent 连接失败", str(exc))
            return

        delete_files = self.delete_files_check.isChecked()
        delete_rss = self.delete_rss_check.isChecked()

        cleaned_subs = 0
        cleaned_torrents = 0
        errors: list[str] = []
        for q in to_clean:
            subs = get_subscriptions(q).get(q, [])
            for s in subs:
                if delete_rss:
                    ok, msg = qbt.remove_rss_feed(s["qbt_feed_path"])
                    if not ok:
                        errors.append(f"{s['qbt_feed_path']}: {msg}")
                if delete_files:
                    count, _msg = qbt.delete_torrents_by_tag(q, delete_files=True)
                    cleaned_torrents += count
                remove_subscription(q, s["title"])
                cleaned_subs += 1
            log_cleanup(q, len(subs))

        tip = f"✅ 已清理订阅 {cleaned_subs} 条，种子 {cleaned_torrents} 个。"
        if errors:
            tip += "\n\n部分错误:\n" + "\n".join(errors[:10])
        QMessageBox.information(self, "清理完成", tip)
        self.refresh()
