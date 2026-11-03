"""把耗时计算放到 QThread，避免界面卡死。

用法：
    self._worker = FunctionWorker(lambda: heavy())
    self._worker.succeeded.connect(self._on_done)
    self._worker.failed.connect(self._on_error)
    self._worker.start()

注意：页面必须持有 worker 的引用（self._worker），否则 QThread 对象
可能在运行中被 Python 回收，导致 Qt 直接崩溃。
"""

from __future__ import annotations

import traceback
from collections.abc import Callable

from PySide6.QtCore import QThread, Signal


class FunctionWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, function: Callable, parent=None):
        super().__init__(parent)
        self._function = function

    def run(self) -> None:  # noqa: D401 - Qt 回调
        try:
            result = self._function()
        except Exception as exc:  # 后台线程的异常必须带回 UI 线程展示
            traceback.print_exc()
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.succeeded.emit(result)


def stop_worker(worker: FunctionWorker | None, wait_ms: int = 2000) -> None:
    """窗口关闭时停掉后台线程，避免 QThread 在运行中被销毁导致崩溃。

    正常任务很快结束；如果正在等 LLM 的 60 秒超时，等待 wait_ms 后
    强制终止。terminate() 不优雅，但只发生在退出路径上，
    比 Qt 直接 abort 安全。
    """
    if worker is None or not worker.isRunning():
        return
    worker.requestInterruption()
    if not worker.wait(wait_ms):
        worker.terminate()
        worker.wait(500)
