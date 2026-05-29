from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout


class CoverCard(QFrame):
    cover_clicked  = pyqtSignal()
    action_clicked = pyqtSignal()

    def __init__(
        self,
        title: str,
        subtitle: str,
        pixmap: QPixmap,
        action_text: str = "",
        action_enabled: bool = True,
    ) -> None:
        super().__init__()
        self.setObjectName("cover-card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedWidth(160)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.cover_btn = QPushButton()
        self.cover_btn.setObjectName("cover-btn")
        self.cover_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cover_btn.setFixedSize(144, 200)
        self.set_cover_pixmap(pixmap)
        self.cover_btn.clicked.connect(self.cover_clicked.emit)
        root.addWidget(self.cover_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("card-title")
        self.title_lbl.setWordWrap(True)
        root.addWidget(self.title_lbl)

        self.sub_lbl = QLabel(subtitle)
        self.sub_lbl.setObjectName("card-subtitle")
        self.sub_lbl.setWordWrap(True)
        root.addWidget(self.sub_lbl)

        if action_text:
            self.action_btn = QPushButton(action_text)
            self.action_btn.setEnabled(action_enabled)
            self.action_btn.clicked.connect(self.action_clicked.emit)
            root.addWidget(self.action_btn)

    def set_cover_pixmap(self, pixmap: QPixmap) -> None:
        self.cover_btn.setIcon(QIcon(pixmap))
        self.cover_btn.setIconSize(self.cover_btn.size())
