from __future__ import annotations

import traceback
from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot


class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(object)


class Worker(QRunnable):
    """在 QThreadPool 中运行任意函数，通过信号回传结果。

    注意：必须让 Worker 自身持有 signals 引用，并设置 setAutoDelete(False)
    以防止 QThreadPool 在任务完成时提前释放 C++ 对象（导致信号失效）。
    调用方需在 result/error/finished 槽处理完后手动调用 worker.signals 即可，
    Python GC 会在 Worker 离开作用域后自然回收。
    """

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()
        # 不让 QThreadPool 自动 delete，由 Python 负责生命周期
        self.setAutoDelete(False)

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.signals.result.emit(result)
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()
