# 2026-10-10：本次修改原因：提供复用卡片、任务信号和异步图片预览，避免下载图片阻塞界面。
from __future__ import annotations

import logging
from typing import Callable

# 2026-10-11：本次修改原因：缩略图读取本地素材，图库发出单图 AI 操作信号。
from ..assets import local_asset_path, valid_media_url

from PySide6.QtCore import QObject, QRunnable, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
# from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout
# 2026-10-11：本次修改原因：增加分页缩略图，便于核对主图和详情图数量及内容。
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


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
    # 2026-10-11：本次修改原因：图片加载后提供真实像素尺寸，支持商品图片尺寸核对。
    dimensionsLoaded = Signal(int, int)

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
        # if self._reply:
        #     self._reply.abort()
        # 2026-10-11：本次修改原因：先解除旧请求关联，避免取消请求的回调影响新图片。
        previous = self._reply
        self._reply = None
        if previous:
            previous.abort()
        self._pixmap = None
        self.clear()
        self.setToolTip(url)
        if not url:
            self.setText("暂无图片")
            return
        # 2026-10-11：本次修改原因：本地生成图直接加载，避免当作远程 HTTP 链接请求。
        local = local_asset_path(url)
        if local:
            pixmap = QPixmap(str(local))
            if not pixmap.isNull():
                self._pixmap = pixmap
                self.dimensionsLoaded.emit(pixmap.width(), pixmap.height())
                self._fit()
            else:
                self.setText("本地图片无法解码")
            return
        self.setText("正在加载图片…")
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(8000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        self._buffer = bytearray()
        reply = self.network.get(request)
        # 2026-10-11：本次修改原因：预览控件销毁时一并销毁请求，避免缩略图关闭后回调已销毁的控件。
        reply.setParent(self)
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
                self.dimensionsLoaded.emit(pixmap.width(), pixmap.height())
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


# 2026-10-11：本次修改原因：分组展示采集图片，进入页签才加载，每页六张控制并发和界面长度。
class ImageGallery(QFrame):
    PAGE_SIZE = 6
    # 2026-10-11：本次修改原因：图库把真实图片尺寸传给对应图片列表，补齐材料缺少的像素信息。
    sizeLoaded = Signal(str, int, int)

    # 2026-10-11：本次修改原因：每张图片提供就地 AI 改图入口。
    aiRequested = Signal(str)

    def __init__(self, network: QNetworkAccessManager):
        super().__init__()
        self.network = network
        self.urls: list[str] = []
        self.page = 0
        self.loaded = False
        self.previews: list[ImagePreview] = []
        self.enable_ai = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        self.count = label("共 0 张", "hint")
        actions.addWidget(self.count)
        actions.addStretch()
        self.previous = button("上一页", lambda: self.move_page(-1))
        self.next = button("下一页", lambda: self.move_page(1))
        actions.addWidget(self.previous)
        actions.addWidget(self.next)
        layout.addLayout(actions)
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        layout.addLayout(self.grid)
        self.set_urls([])

    def set_urls(self, urls: list[str]) -> None:
        unique = list(dict.fromkeys(url for url in urls if url))
        if unique == self.urls and self.loaded:
            return
        self.urls = unique
        self.page = 0
        self.loaded = False
        self._counts()
        if self.isVisible():
            self._render()

    def _counts(self) -> None:
        pages = max(1, (len(self.urls) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.count.setText(f"共 {len(self.urls)} 张  ·  第 {self.page + 1}/{pages} 页")
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(self.page + 1 < pages)

    def move_page(self, step: int) -> None:
        pages = max(1, (len(self.urls) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.page = max(0, min(pages - 1, self.page + step))
        self._render()

    def _render(self) -> None:
        # from ..models import valid_url
        # 2026-10-11：本次修改原因：图库复用统一素材地址判断。

        for preview in self.previews:
            preview.set_url("")
        self.previews.clear()
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        start = self.page * self.PAGE_SIZE
        for index, url in enumerate(self.urls[start:start + self.PAGE_SIZE]):
            tile = QFrame()
            contents = QVBoxLayout(tile)
            contents.setContentsMargins(0, 0, 0, 0)
            preview = ImagePreview(self.network, 125)
            # preview.set_url(url if valid_url(url) else "")
            # 2026-10-11：本次修改原因：本地与远程图片使用相同的预览入口。
            # preview.set_url(url if valid_media_url(url) else "")
            self.previews.append(preview)
            contents.addWidget(preview)
            caption = label(f"第 {start + index + 1} 张", "muted")
            # 2026-10-11：本次修改原因：缩略图加载后显示像素尺寸，而非只显示序号。
            preview.dimensionsLoaded.connect(
                lambda width, height, caption=caption, number=start + index + 1, url=url:
                self._image_size(caption, number, url, width, height))
            caption.setToolTip(url)
            # 2026-10-11：本次修改原因：本地图片同步返回尺寸，必须先连接信号再读取。
            preview.set_url(url if valid_media_url(url) else "")
            contents.addWidget(caption)
            # 2026-10-11：本次修改原因：商品图库的 AI 入口携带准确的当前图片地址。
            if self.enable_ai:
                contents.addWidget(button("AI 改图", lambda _checked=False, address=url: self.aiRequested.emit(address)))
            self.grid.addWidget(tile, index // 3, index % 3)
        self.loaded = True
        self._counts()

    # 2026-10-11：本次修改原因：像素尺寸只来自实际解码的图片，不作为物流尺寸。
    def _image_size(self, caption: QLabel, number: int, url: str, width: int, height: int) -> None:
        caption.setText(f"第 {number} 张 · {width} × {height}")
        self.sizeLoaded.emit(url, width, height)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.loaded:
            self._render()
