from __future__ import annotations

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui.qt.workers import Worker
from gui.services.config_service import ConfigService
from src.qbt.client import QBTClient


class OnboardingDialog(QDialog):
    """首次使用快速设置向导。

    仅在 config.yaml 不存在（或 save_path 为空）时由 MainWindow 弹出。
    完成后写入 config.yaml，向导不会再次出现。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("欢迎使用 — 快速设置")
        self.setMinimumWidth(480)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._cfg = ConfigService.load()
        self._thread_pool = QThreadPool.globalInstance()
        self._test_worker: Worker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(24, 20, 24, 20)

        # ── 欢迎标题 ──
        welcome = QLabel("🎌  欢迎使用番剧自动订阅管理")
        welcome.setObjectName("page-title")
        root.addWidget(welcome)

        hint = QLabel(
            "只需填写下面几项基本信息，即可开始使用。\n"
            "所有设置之后都可以在「⚙️ 设置」页面随时修改。"
        )
        hint.setObjectName("hint-text")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ── qBittorrent 连接 ──
        qbt_group = QGroupBox("qBittorrent 连接信息")
        qbt_form = QFormLayout(qbt_group)
        qbt_form.setSpacing(10)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("127.0.0.1")
        self.host_edit.setToolTip("qBittorrent Web UI 的 IP 地址，本机通常填 127.0.0.1")
        qbt_cfg = self._cfg.get("qbittorrent", {})
        self.host_edit.setText(str(qbt_cfg.get("host", "127.0.0.1")))
        host_label = QLabel("Host 地址")
        host_label.setToolTip("qBittorrent Web UI 的 IP 地址，本机通常填 127.0.0.1")
        qbt_form.addRow(host_label, self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(qbt_cfg.get("port", 8080)))
        self.port_spin.setToolTip("qBittorrent Web UI 端口，默认 8080（可在 qBittorrent 设置→Web UI 中查看）")
        port_label = QLabel("端口")
        port_label.setToolTip("qBittorrent Web UI 端口，默认 8080")
        qbt_form.addRow(port_label, self.port_spin)

        self.user_edit = QLineEdit()
        self.user_edit.setText(str(qbt_cfg.get("username", "admin")))
        self.user_edit.setToolTip("qBittorrent Web UI 登录用户名，默认 admin")
        user_label = QLabel("用户名")
        user_label.setToolTip("qBittorrent Web UI 登录用户名，默认 admin")
        qbt_form.addRow(user_label, self.user_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("请输入密码")
        self.pass_edit.setToolTip("qBittorrent Web UI 登录密码")
        pass_label = QLabel("密码")
        pass_label.setToolTip("qBittorrent Web UI 登录密码")
        qbt_form.addRow(pass_label, self.pass_edit)

        self.save_path_edit = QLineEdit()
        self.save_path_edit.setPlaceholderText("例如：D:/Anime 或 E:/Downloads/Anime")
        self.save_path_edit.setToolTip(
            "番剧的下载保存目录。\n"
            "qBittorrent 会把文件下载到这里，媒体库页面也会从这里扫描番剧。\n"
            "建议使用英文路径，避免中文或特殊字符。"
        )
        save_path_label = QLabel("下载保存路径")
        save_path_label.setToolTip("番剧下载到哪个文件夹，同时也是媒体库的扫描目录")
        qbt_form.addRow(save_path_label, self.save_path_edit)

        root.addWidget(qbt_group)

        # ── 测试连接按钮 ──
        test_row = QHBoxLayout()
        self.test_btn = QPushButton("🔌  测试连接")
        self.test_btn.setToolTip("点击验证 qBittorrent 是否可以连接")
        self.test_btn.clicked.connect(self._test_connection)
        self.test_status = QLabel("尚未测试")
        self.test_status.setObjectName("test-status")
        self.test_status.setProperty("status", "idle")
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_status)
        test_row.addStretch(1)
        root.addLayout(test_row)

        # ── 提示信息 ──
        tip = QLabel(
            "💡 如果不确定 qBittorrent 设置，请先打开 qBittorrent → 工具 → 设置 → Web UI，\n"
            "确认已勾选「启用 Web 用户界面」并记下端口号。"
        )
        tip.setObjectName("hint-text")
        tip.setWordWrap(True)
        root.addWidget(tip)

        # ── 底部按钮 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.skip_btn = QPushButton("稍后设置")
        self.skip_btn.setToolTip("跳过向导，稍后在「⚙️ 设置」页面填写")
        self.skip_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton("💾  保存并开始使用")
        self.ok_btn.setMinimumWidth(140)
        self.ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(self.skip_btn)
        btn_row.addWidget(self.ok_btn)
        root.addLayout(btn_row)

    def _test_connection(self) -> None:
        self.test_status.setText("连接中...")
        self.test_btn.setEnabled(False)
        qbt_cfg = {
            "host": self.host_edit.text().strip() or "127.0.0.1",
            "port": int(self.port_spin.value()),
            "username": self.user_edit.text().strip(),
            "password": self.pass_edit.text(),
        }
        self._test_worker = Worker(self._do_test_connection, qbt_cfg)
        self._test_worker.signals.result.connect(self._on_test_done)
        self._test_worker.signals.finished.connect(lambda: self.test_btn.setEnabled(True))
        self._thread_pool.start(self._test_worker)

    @staticmethod
    def _do_test_connection(qbt_cfg: dict) -> tuple[bool, str]:
        return QBTClient(
            host=qbt_cfg["host"],
            port=qbt_cfg["port"],
            username=qbt_cfg["username"],
            password=qbt_cfg["password"],
        ).test_connection()

    def _on_test_done(self, result: tuple[bool, str]) -> None:
        ok, msg = result
        from gui.themes import repolish
        self.test_status.setText(f"{'✅' if ok else '❌'} {msg}")
        self.test_status.setProperty("status", "ok" if ok else "error")
        repolish(self.test_status)

    def _on_ok(self) -> None:
        save_path = self.save_path_edit.text().strip().strip('"').strip("'")
        if not save_path:
            ret = QMessageBox.question(
                self,
                "下载路径未填",
                "还没有填写下载保存路径，媒体库功能将不可用。\n\n现在继续保存，还是返回填写？",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if ret != QMessageBox.StandardButton.Save:
                return

        self._cfg["qbittorrent"] = {
            "host": self.host_edit.text().strip() or "127.0.0.1",
            "port": int(self.port_spin.value()),
            "username": self.user_edit.text().strip(),
            "password": self.pass_edit.text(),
            "save_path": save_path,
        }
        ConfigService.save(self._cfg)
        self.accept()

    def saved_config(self) -> dict:
        return self._cfg
