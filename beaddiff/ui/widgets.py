# 2026-10-10：本次修改原因：提供复用卡片、任务信号和异步图片预览，避免下载图片阻塞界面。
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout


def icon(name: str, color: str = "#70888d") -> QIcon:
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if name == "products":
        painter.drawRoundedRect(4, 4, 6, 6, 1, 1)
        painter.drawRoundedRect(14, 4, 6, 6, 1, 1)
        painter.drawRoundedRect(4, 14, 6, 6, 1, 1)
        painter.drawRoundedRect(14, 14, 6, 6, 1, 1)
    elif name == "capture":
        painter.drawRoundedRect(4, 6, 16, 14, 2, 2)
        painter.drawLine(8, 3, 8, 9)
        painter.drawLine(16, 3, 16, 9)
        painter.drawLine(8, 13, 16, 13)
        painter.drawLine(8, 17, 13, 17)
    elif name in {"import", "export"}:
        painter.drawLine(4, 15, 4, 20)
        painter.drawLine(4, 20, 20, 20)
        painter.drawLine(20, 20, 20, 15)
        painter.drawLine(12, 3, 12, 15)
        end, start = (3, 7) if name == "export" else (15, 11)
        painter.drawLine(8, start, 12, end)
        painter.drawLine(12, end, 16, start)
    elif name == "settings":
        for x, y in ((6, 8), (12, 15), (18, 10)):
            painter.drawLine(x, 3, x, y - 3)
            painter.drawEllipse(x - 2, y - 2, 4, 4)
            painter.drawLine(x, y + 3, x, 21)
    elif name == "search":
        painter.drawEllipse(4, 3, 12, 12)
        painter.drawLine(14, 14, 21, 21)
    else:
        painter.drawLine(5, 12, 10, 17)
        painter.drawLine(10, 17, 20, 6)
    painter.end()
    return QIcon(pixmap)


def button(text: str, callback: Callable | None = None, primary: bool = False, symbol: str = "") -> QPushButton:
    result = QPushButton(text)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        result.setObjectName("primary")
    if symbol:
        result.setIcon(icon(symbol, "#ffffff" if primary else "#6b8389"))
    if callback:
        result.clicked.connect(callback)
    return result


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    return frame, layout


class TaskSignals(QObject):
    # finished = Signal(object)
    # failed = Signal(str)
    # 2026-10-10：本次修改原因：携带任务标识，将后台完成事件明确交由主窗口的 Qt 槽处理。
    finished = Signal(object, object)
    failed = Signal(object, str)


class Task(QRunnable):
    def __init__(self, work: Callable):
        super().__init__()
        self.work = work
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            # self.signals.finished.emit(self.work())
            # 2026-10-10：本次修改原因：把任务结果路由到主线程，避免后台线程直接更新界面。
            self.signals.finished.emit(self, self.work())
        except Exception as error:
            logging.exception("后台任务失败")
            # self.signals.failed.emit(str(error))
            self.signals.failed.emit(self, str(error))


class ImagePreview(QLabel):
    def __init__(self, network: QNetworkAccessManager, height: int = 195):
        super().__init__("暂无图片")
        self.network = network
        self.setObjectName("imagePreview")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(160)
        self.setFixedHeight(height)
        self._pixmap: QPixmap | None = None
        self._reply: QNetworkReply | None = None
        self._buffer = bytearray()

    def set_url(self, url: str) -> None:
        if self._reply:
            self._reply.abort()
        self._reply = None
        self._pixmap = None
        self.clear()
        self.setToolTip(url)
        if not url:
            self.setText("暂无图片")
            return
        self.setText("正在加载图片…")
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(8000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        self._buffer = bytearray()
        reply = self.network.get(request)
        self._reply = reply
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._finish(reply))

    def _read(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            return
        self._buffer.extend(bytes(reply.readAll()))
        if len(self._buffer) > 8 * 1024 * 1024:
            reply.abort()

    def _finish(self, reply: QNetworkReply) -> None:
        if reply is self._reply:
            self._read(reply)
            pixmap = QPixmap()
            if reply.error() == QNetworkReply.NetworkError.NoError and pixmap.loadFromData(bytes(self._buffer)):
                self._pixmap = pixmap
                self._fit()
            else:
                self.setText("图片暂时无法加载\n可在编辑页核对链接")
            self._reply = None
            self._buffer = bytearray()
        reply.deleteLater()

    def _fit(self) -> None:
        if self._pixmap:
            self.setPixmap(self._pixmap.scaled(self.width() - 18, self.height() - 18,
                                             Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()
