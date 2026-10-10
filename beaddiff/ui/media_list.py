# 2026-10-11：本次修改原因：图片列表提供新增、批量粘贴、移除和排序，符合商品图片维护习惯。
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QHeaderView, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from .widgets import button


class MediaList(QWidget):
    textChanged = Signal()

    def __init__(self, urls: list[str], sizes: dict[str, str]):
        super().__init__()
        # self.sizes = sizes
        # 2026-10-11：本次修改原因：预览取得的尺寸仅更新编辑副本，取消编辑不改原商品。
        self.sizes = dict(sizes)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["图片链接（按行排序）", "像素尺寸"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 130)
        self.table.setMinimumHeight(155)
        self.table.setMaximumHeight(230)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        actions.addWidget(button("新增 / 批量粘贴", self.add_urls))
        actions.addWidget(button("移除选中", self.remove_selected))
        actions.addWidget(button("上移", lambda: self.move(-1)))
        actions.addWidget(button("下移", lambda: self.move(1)))
        actions.addStretch()
        layout.addLayout(actions)
        self.set_urls(urls)
        self.table.itemChanged.connect(self.item_changed)

    def toPlainText(self) -> str:
        return "\n".join(self.table.item(row, 0).text().strip() for row in range(self.table.rowCount())
                         if self.table.item(row, 0) and self.table.item(row, 0).text().strip())

    def set_urls(self, urls: list[str]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for address in dict.fromkeys(url.strip() for url in urls if url.strip()):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(address))
            size = QTableWidgetItem(self.sizes.get(address, "未提供"))
            size.setFlags(size.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, size)
        self.table.blockSignals(False)

    def item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self.table.blockSignals(True)
            self.table.item(item.row(), 1).setText(self.sizes.get(item.text().strip(), "未提供"))
            self.table.blockSignals(False)
            self.textChanged.emit()

    # 2026-10-11：本次修改原因：显示异步预览解码出的尺寸，不将自动元数据更新当作人工编辑。
    def update_size(self, address: str, width: int, height: int) -> None:
        value = f"{width} × {height}"
        self.sizes[address] = value
        blocked = self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text().strip() == address:
                self.table.item(row, 1).setText(value)
        self.table.blockSignals(blocked)

    def add_urls(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("添加图片 · 每行一个链接")
        dialog.resize(670, 340)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setPlaceholderText("每行粘贴一个 HTTP/HTTPS 图片链接")
        layout.addWidget(editor)
        layout.addWidget(button("添加", dialog.accept, primary=True))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_urls(self.toPlainText().splitlines() + editor.toPlainText().splitlines())
            self.textChanged.emit()

    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        if rows:
            self.textChanged.emit()

    def move(self, step: int) -> None:
        row = self.table.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.table.rowCount():
            return
        urls = [self.table.item(index, 0).text() for index in range(self.table.rowCount())]
        urls[row], urls[target] = urls[target], urls[row]
        self.set_urls(urls)
        self.table.selectRow(target)
        self.textChanged.emit()
