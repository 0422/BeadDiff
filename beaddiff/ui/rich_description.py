# 2026-10-11：本次修改原因：提供妙手式图文详情编辑，静态 HTML 与异步远程图片预览分开处理。
from __future__ import annotations

# from PySide6.QtCore import Qt, QUrl
# 2026-10-11：本次修改原因：图文详情支持本地素材加载及对其中单图请求 AI 修改。
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QFont, QImage, QPainter, QTextCharFormat, QTextDocument, QTextListFormat
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QDialog, QHBoxLayout, QInputDialog, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

from ..content import clean_description
from ..content import description_images
from ..assets import local_asset_path, valid_media_url
from ..models import valid_url
from .widgets import button, label


class RemoteDescriptionEdit(QTextEdit):
    def __init__(self, network: QNetworkAccessManager):
        super().__init__()
        self.network = network
        self.cache: dict[str, QImage] = {}
        self.pending: dict[str, tuple[QNetworkReply, bytearray]] = {}
        self.waiting: set[str] = set()
        self.setAcceptRichText(True)
        self.setMinimumHeight(360)
        self.setPlaceholderText("编辑商品文字，或插入详情图片")
        self.placeholder_image = QImage(640, 96, QImage.Format.Format_RGB32)
        self.placeholder_image.fill(Qt.GlobalColor.white)
        painter = QPainter(self.placeholder_image)
        painter.setPen(Qt.GlobalColor.gray)
        painter.drawText(self.placeholder_image.rect(), Qt.AlignmentFlag.AlignCenter, "详情图片 · 正在加载或暂不可用")
        painter.end()

    def loadResource(self, resource_type, url):
        if resource_type == QTextDocument.ResourceType.ImageResource.value:
            address = url.toString()
            # 2026-10-11：本次修改原因：仅加载受管理的本地图片，拒绝任意本地文件链接。
            local = local_asset_path(address)
            if local:
                image = QImage(str(local))
                return image.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation) if not image.isNull() else self.placeholder_image
            if not valid_url(address):
                return self.placeholder_image
            if address in self.cache:
                return self.cache[address]
            self.waiting.add(address)
            if self.isVisible():
                self._fetch()
            return self.placeholder_image
        return super().loadResource(resource_type, url)

    def _fetch(self) -> None:
        while self.waiting and len(self.pending) < 4:
            address = self.waiting.pop()
            if address in self.cache or address in self.pending:
                continue
            request = QNetworkRequest(QUrl(address))
            request.setTransferTimeout(8000)
            request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                                 QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
            reply = self.network.get(request)
            reply.setParent(self)
            self.pending[address] = (reply, bytearray())
            reply.readyRead.connect(lambda address=address, reply=reply: self._read(address, reply))
            reply.finished.connect(lambda address=address, reply=reply: self._finish(address, reply))

    def _read(self, address: str, reply: QNetworkReply) -> None:
        current = self.pending.get(address)
        if current is None or current[0] is not reply:
            return
        current[1].extend(bytes(reply.readAll()))
        if len(current[1]) > 8 * 1024 * 1024:
            reply.abort()

    def _finish(self, address: str, reply: QNetworkReply) -> None:
        current = self.pending.get(address)
        if current is None or current[0] is not reply:
            reply.deleteLater()
            return
        self._read(address, reply)
        bitmap = QImage()
        if reply.error() != QNetworkReply.NetworkError.NoError or not bitmap.loadFromData(bytes(current[1])):
            bitmap = self.placeholder_image
        else:
            bitmap = bitmap.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation)
        self.pending.pop(address)
        self.cache[address] = bitmap
        blocked = self.blockSignals(True)
        self.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(address), bitmap)
        self.document().markContentsDirty(0, self.document().characterCount())
        self.blockSignals(blocked)
        self.viewport().update()
        reply.deleteLater()
        self._fetch()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fetch()


class RichDescription(QWidget):
    # 2026-10-11：本次修改原因：详情中的图片复用公共 AI 改图面板。
    aiRequested = Signal(str)
    def __init__(self, network: QNetworkAccessManager, html: str):
        super().__init__()
        self.original_html = clean_description(html)
        self.changed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.editor = RemoteDescriptionEdit(network)
        toolbar.addWidget(button("加粗", self.bold))
        toolbar.addWidget(button("斜体", self.italic))
        toolbar.addWidget(button("下划线", self.underline))
        toolbar.addWidget(button("列表", self.make_list))
        toolbar.addWidget(button("插入图片", self.insert_image))
        toolbar.addWidget(button("链接", self.insert_link))
        toolbar.addWidget(button("HTML", self.edit_html))
        # 2026-10-11：本次修改原因：保持字段旁入口，并允许在图文详情内选择具体图片处理。
        toolbar.addWidget(button("AI 改详情图", self.request_ai))
        toolbar.addStretch()
        layout.addLayout(toolbar)
        layout.addWidget(self.editor)
        layout.addWidget(label("可直接编辑文字、图片顺序与格式；图片通过网络加载，原始链接保存在描述中。", "hint", True))
        self.editor.setHtml(self.original_html)
        self.editor.document().setModified(False)
        self.editor.textChanged.connect(self.mark_changed)

    def mark_changed(self) -> None:
        self.changed = True

    def html(self) -> str:
        return clean_description(self.editor.toHtml()) if self.changed else self.original_html

    def set_html(self, html: str) -> None:
        self.original_html = clean_description(html)
        self.editor.setHtml(self.original_html)
        self.changed = True

    def bold(self) -> None:
        self.editor.setFontWeight(QFont.Weight.Normal if self.editor.fontWeight() >= QFont.Weight.Bold else QFont.Weight.Bold)
        self.editor.setFocus()

    def italic(self) -> None:
        self.editor.setFontItalic(not self.editor.fontItalic())
        self.editor.setFocus()

    def underline(self) -> None:
        self.editor.setFontUnderline(not self.editor.fontUnderline())
        self.editor.setFocus()

    def make_list(self) -> None:
        self.editor.textCursor().createList(QTextListFormat.Style.ListDisc)
        self.editor.setFocus()

    def insert_image(self) -> None:
        address, accepted = QInputDialog.getText(self, "插入详情图片", "HTTP/HTTPS 图片链接：")
        # if accepted and valid_url(address.strip()):
        # 2026-10-11：本次修改原因：已上传本机素材也可插入图文详情。
        if accepted and valid_media_url(address.strip()):
            from ..content import detail_html
            self.editor.textCursor().insertHtml(detail_html("", [address.strip()]))

    def insert_link(self) -> None:
        address, accepted = QInputDialog.getText(self, "插入链接", "HTTP/HTTPS 地址：")
        if accepted and valid_url(address.strip()):
            cursor = self.editor.textCursor()
            formatting = QTextCharFormat()
            formatting.setAnchor(True)
            formatting.setAnchorHref(address.strip())
            cursor.insertText(cursor.selectedText() or address.strip(), formatting)

    def edit_html(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑详细描述 HTML")
        dialog.resize(820, 520)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(self.html())
        layout.addWidget(editor)
        layout.addWidget(button("应用", dialog.accept, primary=True))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_html(editor.toPlainText())

    # 2026-10-11：本次修改原因：优先使用光标所在图片，否则从当前详情图中选择。
    def request_ai(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        cursor = self.editor.textCursor()
        formatting = cursor.charFormat()
        current = formatting.toImageFormat().name() if formatting.isImageFormat() else ""
        images = description_images(self.html())
        if current and current in images:
            self.aiRequested.emit(current)
        elif images:
            selected, accepted = QInputDialog.getItem(self, "AI 修改详情图片", "选择需要修改的图片：", images, editable=False)
            if accepted:
                self.aiRequested.emit(selected)
        else:
            QMessageBox.information(self, "没有详情图片", "请先插入图片，再使用 AI 改图。")
