"""字幕组优先级编辑控件 — 拖拽排序 + 行内删除 + 输入框添加。"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PriorityListEditor(QWidget):
    """Reorderable list with add/remove. Order = priority (high→low)."""

    def __init__(self, items: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.set_items(items or [])

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # Add row
        add_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入字幕组关键词，回车或点「添加」")
        self.input.returnPressed.connect(self._add_from_input)
        add_btn = QPushButton("＋ 添加")
        add_btn.clicked.connect(self._add_from_input)
        add_row.addWidget(self.input, stretch=1)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        # List
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setUniformItemSizes(False)
        self.list.setFixedHeight(150)
        root.addWidget(self.list)

        # Hint
        hint = QLabel("拖动调整顺序（顶部优先级最高）  ·  点 ✕ 删除")
        hint.setObjectName("hint-text")
        root.addWidget(hint)

    def _add_item_widget(self, text: str) -> None:
        item = QListWidgetItem()
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 4, 4, 4)
        h.setSpacing(8)
        grip = QLabel("⋮⋮")
        grip.setStyleSheet("color: #888;")
        lbl = QLabel(text)
        lbl.setProperty("priority_text", text)
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(24, 24)
        del_btn.setToolTip("删除")
        del_btn.clicked.connect(lambda: self._remove_item(item))
        h.addWidget(grip)
        h.addWidget(lbl, stretch=1)
        h.addWidget(del_btn)
        item.setSizeHint(row.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, text)
        self.list.addItem(item)
        self.list.setItemWidget(item, row)

    def _add_from_input(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        existing = self.items()
        if text in existing:
            self.input.clear()
            return
        self._add_item_widget(text)
        self.input.clear()

    def _remove_item(self, item: QListWidgetItem) -> None:
        row = self.list.row(item)
        if row >= 0:
            self.list.takeItem(row)

    def set_items(self, items: list[str]) -> None:
        self.list.clear()
        for it in items:
            if it.strip():
                self._add_item_widget(it.strip())

    def items(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            text = item.data(Qt.ItemDataRole.UserRole)
            if text:
                out.append(text)
        return out
