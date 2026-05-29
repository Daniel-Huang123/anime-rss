from __future__ import annotations

from PyQt6.QtCore import QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
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
    QVBoxLayout,
    QWidget,
)

from gui.qt.workers import Worker
from gui.services.config_service import ConfigService
from gui.themes import THEMES, repolish
from gui.views.widgets.priority_list import PriorityListEditor
from src.qbt.client import QBTClient


class SettingsPage(QWidget):
    config_saved = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._cfg = ConfigService.load()
        self._thread_pool = QThreadPool.globalInstance()
        self._test_worker: Worker | None = None
        self._build_ui()
        self._load_to_form()

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
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        title_lbl = QLabel("⚙️  设置")
        title_lbl.setObjectName("page-title")
        root.addWidget(title_lbl)

        # ── 主题 ──
        theme_group = QGroupBox("🎨  外观主题")
        theme_form = QFormLayout(theme_group)
        self.theme_combo = QComboBox()
        for key, meta in THEMES.items():
            self.theme_combo.addItem(meta["label"], key)
        self.theme_combo.setToolTip("切换界面配色，保存后立即生效")
        theme_form.addRow(QLabel("主题"), self.theme_combo)
        root.addWidget(theme_group)

        # ── qBittorrent ──
        qbt_group = QGroupBox("🖥️  qBittorrent 连接")
        qbt_form = QFormLayout(qbt_group)
        qbt_form.setSpacing(8)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("127.0.0.1")
        self.host_edit.setToolTip("qBittorrent Web UI 的 IP 地址，本机填 127.0.0.1")
        qbt_form.addRow(QLabel("Host 地址"), self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        qbt_form.addRow(QLabel("端口"), self.port_spin)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("admin")
        qbt_form.addRow(QLabel("用户名"), self.user_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("请输入密码")
        qbt_form.addRow(QLabel("密码"), self.pass_edit)

        self.save_path_edit = QLineEdit()
        self.save_path_edit.setPlaceholderText("例如：D:/Anime")
        self.save_path_edit.setToolTip("番剧下载根目录，同时也是媒体库扫描根目录")
        save_path_row = QHBoxLayout()
        save_path_row.setContentsMargins(0, 0, 0, 0)
        save_path_row.addWidget(self.save_path_edit, stretch=1)
        browse_btn = QPushButton("📂 浏览")
        browse_btn.setToolTip("选择下载保存文件夹")
        browse_btn.clicked.connect(self._browse_save_path)
        save_path_row.addWidget(browse_btn)
        save_path_wrap = QWidget()
        save_path_wrap.setLayout(save_path_row)
        qbt_form.addRow(QLabel("下载保存路径"), save_path_wrap)
        root.addWidget(qbt_group)

        test_row = QHBoxLayout()
        self.test_btn = QPushButton("🔌 测试连接")
        self.test_btn.clicked.connect(self._test_connection)
        self.test_status_lbl = QLabel("")
        self.test_status_lbl.setObjectName("test-status")
        self.test_status_lbl.setProperty("status", "idle")
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_status_lbl)
        test_row.addStretch(1)
        root.addLayout(test_row)

        # ── 字幕组优先级 ──
        sub_group = QGroupBox("🎬  字幕组优先级")
        sub_lay = QVBoxLayout(sub_group)
        self.priority_editor = PriorityListEditor()
        sub_lay.addWidget(self.priority_editor)
        root.addWidget(sub_group)

        # ── 资源与清理 ──
        opts_group = QGroupBox("🔍  资源与清理")
        opts_form = QFormLayout(opts_group)
        opts_form.setSpacing(8)

        self.recent_weeks_spin = QSpinBox()
        self.recent_weeks_spin.setRange(1, 12)
        self.recent_weeks_spin.setToolTip("判断字幕组是否还在活跃更新的时间窗口，建议 4 周")
        opts_form.addRow(QLabel("「有资源」时间窗口（周）"), self.recent_weeks_spin)

        self.keep_quarters_spin = QSpinBox()
        self.keep_quarters_spin.setRange(1, 8)
        opts_form.addRow(QLabel("保留季度数"), self.keep_quarters_spin)

        self.delete_files_check = QCheckBox("清理时删除下载文件")
        opts_form.addRow(self.delete_files_check)
        root.addWidget(opts_group)

        # ── 高级 ──
        adv_group = QGroupBox("🔧  高级选项")
        adv_form = QFormLayout(adv_group)
        adv_form.setSpacing(8)

        self.use_mirror_check = QCheckBox("使用 mikanime.tv 镜像")
        self.use_mirror_check.setToolTip("mikanani.me 访问不稳定时启用")
        adv_form.addRow(self.use_mirror_check)

        self.request_delay_spin = QDoubleSpinBox()
        self.request_delay_spin.setRange(0.5, 10.0)
        self.request_delay_spin.setSingleStep(0.5)
        adv_form.addRow(QLabel("批量订阅请求间隔（秒）"), self.request_delay_spin)

        self.auto_refresh_check = QCheckBox("媒体库自动刷新")
        adv_form.addRow(self.auto_refresh_check)

        self.auto_refresh_seconds = QSpinBox()
        self.auto_refresh_seconds.setRange(5, 3600)
        self.auto_refresh_seconds.setSingleStep(5)
        adv_form.addRow(QLabel("自动刷新间隔（秒）"), self.auto_refresh_seconds)
        root.addWidget(adv_group)

        # 保存
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.save_btn = QPushButton("💾  保存配置")
        self.save_btn.setMinimumWidth(120)
        self.save_btn.clicked.connect(self._on_save_clicked)
        btn_row.addWidget(self.save_btn)
        root.addLayout(btn_row)
        root.addStretch(1)

    def _load_to_form(self) -> None:
        qbt = self._cfg.get("qbittorrent", {})
        ui = self._cfg.get("ui", {})

        theme_key = ui.get("theme", "night")
        idx = self.theme_combo.findData(theme_key)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)

        self.host_edit.setText(str(qbt.get("host", "127.0.0.1")))
        self.port_spin.setValue(int(qbt.get("port", 8080)))
        self.user_edit.setText(str(qbt.get("username", "admin")))
        self.pass_edit.setText(str(qbt.get("password", "")))
        self.save_path_edit.setText(str(qbt.get("save_path", "")))
        self.priority_editor.set_items(self._cfg.get("subtitle_priorities", ["ANi", "kirara"]))
        self.recent_weeks_spin.setValue(int(self._cfg.get("resource_check", {}).get("recent_weeks", 4)))
        self.keep_quarters_spin.setValue(int(self._cfg.get("cleanup", {}).get("keep_quarters", 2)))
        self.delete_files_check.setChecked(bool(self._cfg.get("cleanup", {}).get("delete_files", True)))
        self.use_mirror_check.setChecked(bool(self._cfg.get("advanced", {}).get("use_mirror", False)))
        self.request_delay_spin.setValue(float(self._cfg.get("advanced", {}).get("request_delay", 1.0)))
        self.auto_refresh_check.setChecked(bool(ui.get("auto_refresh_enabled", False)))
        self.auto_refresh_seconds.setValue(int(ui.get("auto_refresh_seconds", 30)))

    def _browse_save_path(self) -> None:
        start = self.save_path_edit.text().strip().strip('"').strip("'")
        path = QFileDialog.getExistingDirectory(self, "选择下载保存文件夹", start or "")
        if path:
            self.save_path_edit.setText(path.replace("/", "\\"))

    def _test_connection(self) -> None:
        self.test_status_lbl.setText("连接中...")
        self.test_status_lbl.setProperty("status", "idle")
        repolish(self.test_status_lbl)
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
        return QBTClient(**qbt_cfg).test_connection()

    def _on_test_done(self, result: tuple[bool, str]) -> None:
        ok, msg = result
        self.test_status_lbl.setText(f"{'✅' if ok else '❌'} {msg}")
        self.test_status_lbl.setProperty("status", "ok" if ok else "error")
        repolish(self.test_status_lbl)

    def _on_save_clicked(self) -> None:
        priorities = self.priority_editor.items()
        if not priorities:
            QMessageBox.warning(self, "字幕组未设置", "至少需要一个字幕组关键词，例如「ANi」")
            return

        self._cfg = {
            "qbittorrent": {
                "host": self.host_edit.text().strip(),
                "port": int(self.port_spin.value()),
                "username": self.user_edit.text().strip(),
                "password": self.pass_edit.text(),
                "save_path": self.save_path_edit.text().strip().strip('"').strip("'"),
            },
            "subtitle_priorities": priorities,
            "resource_check": {"recent_weeks": int(self.recent_weeks_spin.value())},
            "cleanup": {
                "keep_quarters": int(self.keep_quarters_spin.value()),
                "delete_files": bool(self.delete_files_check.isChecked()),
            },
            "advanced": {
                "use_mirror": bool(self.use_mirror_check.isChecked()),
                "request_delay": float(self.request_delay_spin.value()),
            },
            "ui": {
                "theme": self.theme_combo.currentData(),
                "auto_refresh_enabled": bool(self.auto_refresh_check.isChecked()),
                "auto_refresh_seconds": int(self.auto_refresh_seconds.value()),
            },
        }
        ConfigService.save(self._cfg)
        QMessageBox.information(self, "保存成功", "✅ 配置已保存！")
        self.config_saved.emit(self._cfg)

    @property
    def config(self) -> dict:
        return self._cfg
