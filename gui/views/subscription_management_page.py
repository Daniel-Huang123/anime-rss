from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from src.utils.state import get_all_subscriptions_flat, remove_subscription


class SubscriptionManagementPage(QWidget):
    def __init__(self, config: dict) -> None:
        super().__init__()
        self._cfg = config
        self._all_subs: list[dict] = []
        self._build_ui()
        self.refresh()

    def apply_config(self, config: dict) -> None:
        self._cfg = config
        self.refresh()

    def showEvent(self, event) -> None:
        # 每次切到本页都重读 state，反映媒体库同步刚补上的字幕组/封面元数据
        super().showEvent(event)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # 标题
        title_row = QHBoxLayout()
        title_lbl = QLabel("📋  订阅管理")
        title_lbl.setObjectName("page-title")
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)
        self.count_lbl = QLabel("0 条")
        self.count_lbl.setObjectName("status-text")
        title_row.addWidget(self.count_lbl)
        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        title_row.addWidget(self.refresh_btn)
        root.addLayout(title_row)

        # 订阅表格
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["季度", "番剧", "字幕组", "订阅日期", "RSS URL"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, stretch=1)

        # 删除区
        del_label = QLabel("🗑️  删除订阅")
        del_label.setObjectName("section-header")
        root.addWidget(del_label)

        del_box = QHBoxLayout()
        del_box.addWidget(QLabel("季度"))
        self.q_combo = QComboBox()
        self.q_combo.setMinimumWidth(100)
        self.q_combo.currentIndexChanged.connect(self._refresh_titles_combo)
        del_box.addWidget(self.q_combo)
        del_box.addWidget(QLabel("番剧"))
        self.title_combo = QComboBox()
        self.title_combo.setMinimumWidth(200)
        del_box.addWidget(self.title_combo, stretch=1)
        self.delete_qbt = QCheckBox("同时删除 qBittorrent RSS/种子/目录")
        self.delete_qbt.setChecked(True)
        del_box.addWidget(self.delete_qbt)
        self.del_btn = QPushButton("🗑️  删除")
        self.del_btn.clicked.connect(self._delete_selected)
        del_box.addWidget(self.del_btn)
        root.addLayout(del_box)

    def refresh(self) -> None:
        self._all_subs = get_all_subscriptions_flat()
        self._all_subs.sort(key=lambda x: (x.get("quarter", ""), x.get("title", "")), reverse=True)
        self.table.setRowCount(len(self._all_subs))
        for i, s in enumerate(self._all_subs):
            self.table.setItem(i, 0, QTableWidgetItem(s.get("quarter", "")))
            self.table.setItem(i, 1, QTableWidgetItem(s.get("title", "")))
            self.table.setItem(i, 2, QTableWidgetItem(s.get("subgroup_name", "")))
            self.table.setItem(i, 3, QTableWidgetItem(s.get("added_at", "")))
            self.table.setItem(i, 4, QTableWidgetItem(s.get("rss_url", "")))
        self.table.resizeColumnsToContents()
        self.count_lbl.setText(f"共 {len(self._all_subs)} 条")

        quarters = sorted({s["quarter"] for s in self._all_subs}, reverse=True)
        current_q = self.q_combo.currentText()
        self.q_combo.blockSignals(True)
        self.q_combo.clear()
        self.q_combo.addItems(quarters)
        if current_q:
            idx = self.q_combo.findText(current_q)
            if idx >= 0:
                self.q_combo.setCurrentIndex(idx)
        self.q_combo.blockSignals(False)
        self._refresh_titles_combo()

    def _refresh_titles_combo(self) -> None:
        q = self.q_combo.currentText()
        titles = [s["title"] for s in self._all_subs if s["quarter"] == q]
        self.title_combo.clear()
        self.title_combo.addItems(titles)

    def _delete_selected(self) -> None:
        quarter = self.q_combo.currentText().strip()
        title = self.title_combo.currentText().strip()
        if not quarter or not title:
            return

        ret = QMessageBox.question(
            self,
            "确认删除",
            f"确认删除订阅：\n{quarter} / {title}",
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        if self.delete_qbt.isChecked():
            qbt_cfg = self._cfg.get("qbittorrent", {})
            qbt_save_path = qbt_cfg.get("save_path", "").strip().strip('"').strip("'")
            try:
                qbt = QBTClient(
                    host=qbt_cfg["host"],
                    port=qbt_cfg["port"],
                    username=qbt_cfg["username"],
                    password=qbt_cfg["password"],
                )
                feed_path = f"{quarter}/{title}"
                save_path = f"{qbt_save_path}/{quarter}/{title}" if qbt_save_path else ""
                ok, msg = qbt.unsubscribe(feed_path=feed_path, save_path=save_path)
                if not ok:
                    QMessageBox.warning(self, "qBittorrent 警告", f"qBit 删除失败（可能已不存在）:\n{msg}")
            except Exception as exc:
                QMessageBox.warning(self, "qBittorrent 错误", str(exc))

        removed = remove_subscription(quarter, title)
        if removed:
            QMessageBox.information(self, "完成", f"✅ 已删除 {quarter} / {title}")
            self.refresh()
        else:
            QMessageBox.warning(self, "失败", "未找到该订阅记录")
