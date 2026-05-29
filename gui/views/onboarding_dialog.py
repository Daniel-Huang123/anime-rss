from __future__ import annotations

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.qt.workers import Worker
from gui.services.config_service import ConfigService
from src.qbt.client import QBTClient
from src.utils.runtime_paths import APP_ROOT


class OnboardingDialog(QDialog):
    """首次使用快速设置向导。

    仅在 config.yaml 不存在（或 save_path 为空）时由 MainWindow 弹出。
    完成后写入 config.yaml，向导不会再次出现。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("欢迎使用 — 快速设置")
        self.setMinimumWidth(640)
        self.setMinimumHeight(560)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._cfg = ConfigService.load()
        self._thread_pool = QThreadPool.globalInstance()
        self._test_worker: Worker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.stack.addWidget(self._build_form_page())   # page 0：填信息
        self.stack.addWidget(self._build_guide_page())  # page 1：图文指引
        self.stack.setCurrentIndex(0)

        # 端口探测随输入实时刷新
        self.host_edit.textChanged.connect(self._update_qbt_probe_status)
        self.port_spin.valueChanged.connect(lambda _v: self._update_qbt_probe_status())
        self._update_qbt_probe_status()

    def _build_form_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setSpacing(14)
        root.setContentsMargins(24, 20, 24, 20)

        # ── 欢迎标题 ──
        welcome = QLabel("🎌  欢迎使用追番姬")
        welcome.setObjectName("page-title")
        root.addWidget(welcome)

        hint = QLabel(
            "填好 qBittorrent 连接信息即可开始使用，所有设置之后都能在「⚙️ 设置」里改。"
        )
        hint.setObjectName("hint-text")
        hint.setWordWrap(True)
        root.addWidget(hint)

        from gui.themes import current
        accent = current()["accent"]
        guide_link = QLabel(
            f'<a href="#guide" style="color:{accent};text-decoration:none;font-weight:600;">'
            "🐾 不知道怎么做？来看看指引喵~</a>"
        )
        guide_link.setObjectName("hint-text")
        guide_link.linkActivated.connect(lambda _: self.stack.setCurrentIndex(1))
        root.addWidget(guide_link)

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
        save_path_row = QHBoxLayout()
        save_path_row.setContentsMargins(0, 0, 0, 0)
        save_path_row.addWidget(self.save_path_edit, stretch=1)
        browse_btn = QPushButton("📂 浏览")
        browse_btn.setToolTip("选择下载保存文件夹")
        browse_btn.clicked.connect(self._browse_save_path)
        save_path_row.addWidget(browse_btn)
        save_path_wrap = QWidget()
        save_path_wrap.setLayout(save_path_row)
        qbt_form.addRow(save_path_label, save_path_wrap)

        root.addWidget(qbt_group)

        self.qbt_probe_lbl = QLabel("qBittorrent 运行状态：检测中...")
        self.qbt_probe_lbl.setObjectName("hint-text")
        self.qbt_probe_lbl.setWordWrap(True)
        root.addWidget(self.qbt_probe_lbl)

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
        return page

    def _build_guide_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setSpacing(12)
        root.setContentsMargins(24, 20, 24, 20)

        title = QLabel("📖  qBittorrent 配置指引")
        title.setObjectName("page-title")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(body)
        bl.setSpacing(10)
        bl.setContentsMargins(0, 0, 0, 0)

        steps = QLabel(
            "1. 打开 qBittorrent → 工具 → 选项 → Web UI\n"
            "2. 勾选「启用 Web 用户界面（远程控制）」\n"
            "3. 记下端口（默认 8080）、用户名、密码\n"
            "4. 返回上一页填入这些信息，点「测试连接」确认\n\n"
            "还没装 qBittorrent？"
        )
        steps.setObjectName("hint-text")
        steps.setWordWrap(True)
        bl.addWidget(steps)

        from gui.themes import current
        accent = current()["accent"]
        dl = QLabel(
            f'<a href="https://www.qbittorrent.org/download" style="color:{accent};font-weight:600;">'
            "⬇️ 点这里下载 qBittorrent</a>"
        )
        dl.setObjectName("hint-text")
        dl.setOpenExternalLinks(True)
        bl.addWidget(dl)

        # 截图（打包未含图时静默跳过）
        for img in ("qbt-main-entry-step.png", "qbt-webui-step.png"):
            p = APP_ROOT / "docs" / "images" / img
            if not p.exists():
                continue
            pix = QPixmap(str(p))
            if pix.isNull():
                continue
            shot = QLabel()
            shot.setPixmap(pix.scaledToWidth(580, Qt.TransformationMode.SmoothTransformation))
            bl.addWidget(shot)
            zoom = QLabel(
                f'<a href="{p.as_uri()}" style="color:{accent};">🔍 看不清？点这里看高清大图</a>'
            )
            zoom.setObjectName("hint-text")
            zoom.setOpenExternalLinks(True)
            bl.addWidget(zoom)

        bl.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        back_btn = QPushButton("← 我填好了，返回填写")
        back_btn.setObjectName("back-btn")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        root.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        return page

    def _browse_save_path(self) -> None:
        start = self.save_path_edit.text().strip().strip('"').strip("'")
        path = QFileDialog.getExistingDirectory(self, "选择下载保存文件夹", start or "")
        if path:
            self.save_path_edit.setText(path.replace("/", "\\"))

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

    def _update_qbt_probe_status(self) -> None:
        host = self.host_edit.text().strip() or "127.0.0.1"
        port = int(self.port_spin.value())
        if QBTClient.is_webui_port_open(host, port):
            self.qbt_probe_lbl.setText(f"qBittorrent 运行状态：✅ 已检测到 {host}:{port}")
            return
        self.qbt_probe_lbl.setText(
            "qBittorrent 运行状态：⚠️ 未检测到 Web UI 端口。"
            "请先启动 qBittorrent，并在 Web UI 设置里开启监听端口。"
        )

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
