# 2026-10-11：本次修改原因：AI 网络任务在后台执行，结果与进度统一通过 Qt 槽回到主线程，不记录敏感请求。
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class WorkerSignals(QObject):
    finished = Signal(object, object)
    failed = Signal(object, str)
    progress = Signal(object, str)


class AIWorker(QRunnable):
    def __init__(self, work: Callable):
        super().__init__()
        self.work = work
        self.signals = WorkerSignals()

    def run(self):
        try:
            value = self.work(lambda message: self.signals.progress.emit(self, message))
            self.signals.finished.emit(self, value)
        except Exception as error:
            self.signals.failed.emit(self, str(error))


class TaskHub(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.callbacks: dict[AIWorker, tuple] = {}

    @property
    def busy(self) -> bool:
        return bool(self.callbacks)

    def submit(self, work: Callable, done: Callable, failed: Callable, progress: Callable | None = None):
        worker = AIWorker(work)
        self.callbacks[worker] = (done, failed, progress)
        worker.signals.finished.connect(self.finished)
        worker.signals.failed.connect(self.failed)
        worker.signals.progress.connect(self.progress)
        self.pool.start(worker)

    @Slot(object, object)
    def finished(self, worker, value):
        callbacks = self.callbacks.pop(worker, None)
        if callbacks:
            callbacks[0](value)

    @Slot(object, str)
    def failed(self, worker, message):
        callbacks = self.callbacks.pop(worker, None)
        if callbacks:
            callbacks[1](message)

    @Slot(object, str)
    def progress(self, worker, message):
        callbacks = self.callbacks.get(worker)
        if callbacks and callbacks[2]:
            callbacks[2](message)
