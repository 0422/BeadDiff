# 2026-10-11：本次修改原因：图片列表提供新增、批量粘贴、移除和排序，符合商品图片维护习惯。
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
# from PySide6.QtWidgets import QDialog, QHBoxLayout, QHeaderView, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
# 2026-10-11：本次修改原因：允许从本机上传图片并请求 AI 处理当前图片。
from pathlib import Path
# from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QHeaderView, QMessageBox, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
# 2026-10-12：本次修改原因：图片操作改为网格工具栏，不再依赖单行水平布局。
from PySide6.QtWidgets import QDialog, QFileDialog, QGridLayout, QHeaderView, QMessageBox, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ..assets import AssetStore

# from .widgets import button
# 2026-10-12：本次修改原因：图片列表实时展示当前张数及超限提醒。
from .widgets import button, label
# 2026-10-12：本次修改原因：所有图片列表共享安全行高及完整链接查看入口。
# from .table_support import configure_table
# 2026-10-13：本次修改原因：图片列表按完整行数调整高度，不再固定区间截出半行或留下大块空白。
from .table_support import configure_table, fit_table_rows


class MediaList(QWidget):
    textChanged = Signal()
    # 2026-10-11：本次修改原因：图片操作与模型调用解耦，由商品编辑器接收当前图片。
    aiRequested = Signal(str)

    # def __init__(self, urls: list[str], sizes: dict[str, str]):
    # 2026-10-11：本次修改原因：同一图片列表支持商品素材和爆款参考素材上传。
    # def __init__(self, urls: list[str], sizes: dict[str, str], assets: AssetStore | None = None, enable_ai: bool = False):
    # 2026-10-12：本次修改原因：可选上限仅用于主图等有明确数量规则的列表，详情图和爆款参考图不强加主图限制。
    def __init__(self, urls: list[str], sizes: dict[str, str], assets: AssetStore | None = None, enable_ai: bool = False,
                 maximum: int | None = None):
        super().__init__()
        # self.sizes = sizes
        # 2026-10-11：本次修改原因：预览取得的尺寸仅更新编辑副本，取消编辑不改原商品。
        self.sizes = dict(sizes)
        self.assets = assets
        # 2026-10-12：本次修改原因：保留采集到的完整列表，只提示上限，不静默裁剪图片。
        self.maximum = maximum
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 2)
        # self.table.setHorizontalHeaderLabels(["图片链接（按行排序）", "像素尺寸"])
        # 2026-10-11：本次修改原因：列表同时存放链接和本地素材地址。
        self.table.setHorizontalHeaderLabels(["图片地址（按行排序）", "像素尺寸"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 130)
        # self.table.setMinimumHeight(155)
        # self.table.setMaximumHeight(230)
        self.table.setAlternatingRowColors(True)
        configure_table(self.table)
        fit_table_rows(self.table, maximum_rows=6)
        layout.addWidget(self.table)
        # actions = QHBoxLayout()
        # 2026-10-12：本次修改原因：图片工具栏按两行排列，避免窄窗口将表格和所在表单撑出边界。
        actions = QGridLayout()
        # 2026-10-13：本次修改原因：图片操作按钮按内容宽度靠左排列，不再拉伸为三列大矩形。
        actions.setAlignment(Qt.AlignmentFlag.AlignLeft)
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        action_buttons = []
        # actions.addWidget(button("新增 / 批量粘贴", self.add_urls))
        action_buttons.append(button("新增 / 批量粘贴", self.add_urls))
        # 2026-10-11：本次修改原因：白底图和参考图直接上传，不需要先取得网络链接。
        if assets:
            # actions.addWidget(button("上传图片", self.upload))
            action_buttons.append(button("上传图片", self.upload))
        if enable_ai:
            # actions.addWidget(button("AI 改选中图", self.request_ai))
            action_buttons.append(button("AI 改选中图", self.request_ai))
        # actions.addWidget(button("移除选中", self.remove_selected))
        # actions.addWidget(button("上移", lambda: self.move(-1)))
        # actions.addWidget(button("下移", lambda: self.move(1)))
        # actions.addStretch()
        action_buttons += [button("移除选中", self.remove_selected), button("上移", lambda: self.move(-1)), button("下移", lambda: self.move(1))]
        for index, action in enumerate(action_buttons):
            actions.addWidget(action, index // 3, index % 3)
        layout.addLayout(actions)
        # 2026-10-12：本次修改原因：打开编辑器即检查已有超限图片，新增、移除、AI 应用后跟随刷新。
        self.count_hint = label("", "hint", True)
        layout.addWidget(self.count_hint)
        self.textChanged.connect(self.update_count)
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
        # 2026-10-12：本次修改原因：程序化设置和 AI 套图替换同样即时刷新数量，且不把初始化当作人工改动。
        self.update_count()

    # 2026-10-12：本次修改原因：按最终保存时的去重规则计数，超限显示差额而不自动删图。
    def update_count(self) -> None:
        count = len(set(self.toPlainText().splitlines()))
        text = f"共 {count} 张图片"
        over_limit = self.maximum is not None and count > self.maximum
        if self.maximum is not None:
            text = f"{count} / {self.maximum} 张图片"
            if over_limit:
                text += f" · 超出 {count - self.maximum} 张，请移除或调整用途后保存"
        self.count_hint.setText(text)
        self.count_hint.setObjectName("warning" if over_limit else "hint")
        self.count_hint.style().unpolish(self.count_hint)
        self.count_hint.style().polish(self.count_hint)

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

    # 2026-10-11：本次修改原因：上传图片先复制到管理目录，原始文件移动后商品仍能使用。
    def upload(self) -> None:
        if not self.assets:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "上传商品 / 参考图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.gif)")
        imported = []
        errors = []
        for value in paths:
            try:
                asset = self.assets.import_file(Path(value))
                imported.append(asset.uri)
                self.sizes[asset.uri] = f"{asset.width} × {asset.height}"
            except (ValueError, OSError) as error:
                errors.append(f"{Path(value).name}：{error}")
        if imported:
            self.set_urls(self.toPlainText().splitlines() + imported)
            self.textChanged.emit()
        if errors:
            QMessageBox.warning(self, "部分图片未能上传", "\n".join(errors))

    def request_ai(self) -> None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        if item and item.text().strip():
            self.aiRequested.emit(item.text().strip())
        else:
            QMessageBox.information(self, "请选择图片", "先选中需要修改的图片，再点击 AI。")
