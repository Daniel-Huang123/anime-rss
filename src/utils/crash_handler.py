"""Global crash handling for PyQt desktop app."""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QtMsgType, pyqtSignal, qInstallMessageHandler
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QMessageBox

from src.utils.runtime_paths import DATA_ROOT

logger = logging.getLogger(__name__)
CRASH_LOG_FILE = DATA_ROOT / "crash.log"

_INSTALLED = False
_DIALOG_OPEN = False
_PREV_EXCEPTHOOK: Callable | None = None
_PREV_THREAD_EXCEPTHOOK: Callable | None = None


class _CrashBridge(QObject):
    show_dialog = pyqtSignal(str, str)


_BRIDGE: _CrashBridge | None = None


def _append_crash_log(title: str, detail: str) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = (
        f"\n{'=' * 80}\n"
        f"[{ts}] {title}\n"
        f"{'-' * 80}\n"
        f"{detail.rstrip()}\n"
    )
    CRASH_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CRASH_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(block)
    return CRASH_LOG_FILE


def _show_crash_dialog(title: str, detail: str) -> None:
    global _DIALOG_OPEN
    if _DIALOG_OPEN:
        return
    _DIALOG_OPEN = True
    try:
        log_path = CRASH_LOG_FILE
        if not log_path.exists():
            log_path = _append_crash_log(title, detail)
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("程序异常")
        msg.setText(f"出错了，错误日志已写入：\n{log_path}")
        msg.setInformativeText("可点击“复制错误详情”后反馈。")
        copy_btn = msg.addButton("复制错误详情", QMessageBox.ButtonRole.ActionRole)
        msg.addButton(QMessageBox.StandardButton.Close)
        msg.exec()
        if msg.clickedButton() == copy_btn:
            QGuiApplication.clipboard().setText(detail)
    except Exception:
        logger.exception("显示崩溃对话框失败")
    finally:
        _DIALOG_OPEN = False


def _emit_dialog(title: str, detail: str) -> None:
    if _BRIDGE is not None:
        _BRIDGE.show_dialog.emit(title, detail)
    else:
        _show_crash_dialog(title, detail)


def report_background_exception(detail: str, title: str = "后台任务异常") -> None:
    """Report worker/thread exceptions that would otherwise be swallowed."""
    try:
        _append_crash_log(title, detail)
        _emit_dialog(title, detail)
    except Exception:
        logger.exception("上报后台异常失败")


def _handle_python_exception(exc_type, exc_value, exc_traceback, origin: str) -> None:
    detail = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    title = f"{origin}: {exc_type.__name__}"
    _append_crash_log(title, detail)
    _emit_dialog(title, detail)


def _python_excepthook(exc_type, exc_value, exc_traceback) -> None:
    _handle_python_exception(exc_type, exc_value, exc_traceback, "未捕获 Python 异常")
    if _PREV_EXCEPTHOOK:
        _PREV_EXCEPTHOOK(exc_type, exc_value, exc_traceback)


def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
    origin = f"线程异常({getattr(args.thread, 'name', 'unknown')})"
    _handle_python_exception(args.exc_type, args.exc_value, args.exc_traceback, origin)
    if _PREV_THREAD_EXCEPTHOOK:
        _PREV_THREAD_EXCEPTHOOK(args)


def _qt_message_handler(mode, context, message) -> None:
    mode_map = {
        QtMsgType.QtDebugMsg: "DEBUG",
        QtMsgType.QtInfoMsg: "INFO",
        QtMsgType.QtWarningMsg: "WARNING",
        QtMsgType.QtCriticalMsg: "CRITICAL",
        QtMsgType.QtFatalMsg: "FATAL",
    }
    level = mode_map.get(mode, "QT")
    where = f"{context.file}:{context.line}" if context and context.file else "<unknown>"
    detail = f"[{level}] {where}\n{message}"
    if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        _append_crash_log("Qt 内部消息", detail)
        if mode == QtMsgType.QtFatalMsg:
            _emit_dialog("Qt 致命错误", detail)


def install_global_crash_handlers() -> None:
    """Install global crash hooks once."""
    global _INSTALLED, _BRIDGE, _PREV_EXCEPTHOOK, _PREV_THREAD_EXCEPTHOOK
    if _INSTALLED:
        return
    _INSTALLED = True

    _BRIDGE = _CrashBridge()
    _BRIDGE.show_dialog.connect(_show_crash_dialog)

    _PREV_EXCEPTHOOK = sys.excepthook
    sys.excepthook = _python_excepthook

    _PREV_THREAD_EXCEPTHOOK = threading.excepthook
    threading.excepthook = _thread_excepthook

    qInstallMessageHandler(_qt_message_handler)
