# 2026-10-10：本次修改原因：组织桌面程序启动、单实例锁、日志和本地接收服务生命周期。
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication, QMessageBox

from .config import Settings
from .receiver import LocalReceiver
from .service import CaptureService
from .storage import Repository
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


class EventBridge(QObject):
    capture_received = Signal()


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("BeadDiff")
    application.setOrganizationName("BeadDiff")
    apply_theme(application)
    QImageReader.setAllocationLimit(64)
    try:
        settings = Settings.load()
        instance_lock = QLockFile(str(settings.data_dir / "beaddiff.lock"))
        instance_lock.setStaleLockTime(0)
        if not instance_lock.tryLock(0):
            QMessageBox.information(None, "BeadDiff 已在运行", "该数据目录已有一个 BeadDiff 实例，请切换到已打开的窗口。")
            return 0
        log_dir = settings.data_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        handler = RotatingFileHandler(log_dir / "beaddiff.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
        # 2026-10-11：本次修改原因：不把模型或签名图片 URL 的查询参数记录到 HTTP 请求日志。
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        repository = Repository(settings.data_dir)
        service = CaptureService(repository)
        bridge = EventBridge()
        receiver = LocalReceiver(settings, service, bridge.capture_received.emit)
        window = MainWindow(settings, repository, service, receiver)
        bridge.capture_received.connect(window.schedule_refresh)
        receiver.start()
        window.update_connection()
        application.aboutToQuit.connect(receiver.stop)
        window.show()
        code = application.exec()
        instance_lock.unlock()
        return code
    except Exception as error:
        logging.exception("BeadDiff 启动失败")
        QMessageBox.critical(None, "启动失败", f"无法启动 BeadDiff：\n{error}\n\n请确认使用 learner 环境运行项目根目录的 main.py。")
        return 1
