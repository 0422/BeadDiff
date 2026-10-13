# 2026-10-12：本次修改原因：统一编辑表格的行高、行号、输入框几何和完整内容查看，避免高 DPI 下裁字及边框重叠。
from __future__ import annotations

# from PySide6.QtCore import Qt
# 2026-10-13：本次修改原因：表格自适应高度在布局后计算，背景覆盖整个表格及行号空白区。
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLineEdit, QMenu,
    QPlainTextEdit, QSizePolicy, QStyledItemDelegate, QVBoxLayout, QFrame,
)

from .widgets import button, label


class CellEditorDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            # editor.setStyleSheet("QLineEdit { padding: 2px 5px; min-height: 0px; border: 1px solid #36a893; border-radius: 3px; }")
            # 2026-10-13：本次修改原因：单元格输入框跟随当前主题，避免局部白底及高 DPI 裁字。
            editor.setProperty("cellEditor", True)
            editor.setMinimumHeight(0)
            editor.setFrame(False)
        return editor

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(1, 1, -1, -1))


def configure_table(table, *, editable: bool = True, multiline: bool = False) -> None:
    height = max(42, table.fontMetrics().height() * (2 if multiline else 1) + 18)
    table.verticalHeader().setMinimumSectionSize(height)
    table.verticalHeader().setDefaultSectionSize(height)
    table.verticalHeader().setMinimumWidth(max(38, table.fontMetrics().horizontalAdvance("9999") + 16))
    table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setMinimumHeight(max(36, table.fontMetrics().height() + 16))
    table.horizontalHeader().setMinimumSectionSize(48)
    # table.setStyleSheet("QTableWidget::item { padding: 4px 7px; } QHeaderView::section { padding: 6px 8px; }")
    # 2026-10-13：本次修改原因：行号区、空白视口及表角统一白底，完整外边框收住灰白错位，弱化网格。
    table.setFrameShape(QFrame.Shape.StyledPanel)
    # table.setStyleSheet("""
        # QTableWidget { background: #ffffff; border: 1px solid #dde7eb; border-radius: 6px;
            # alternate-background-color: #fafcfd; selection-background-color: #e8f5f1; }
        # QTableWidget::item { padding: 5px 10px; border: none; border-bottom: 1px solid #edf2f4; }
        # QTableWidget::item:selected { background: #e8f5f1; color: #163e37; }
        # QHeaderView { background: #ffffff; }
        # QHeaderView::section { background: #f5f8fa; color: #607780; border: none;
            # border-bottom: 1px solid #dde7eb; padding: 8px 10px; font-weight: 500; }
        # QHeaderView#rowNumbers::section { background: #ffffff; color: #8a9aa1;
            # padding: 4px; border-right: 1px solid #edf2f4; }
        # QTableCornerButton::section { background: #f5f8fa; border: none; border-bottom: 1px solid #dde7eb; }
    # """)
    # palette = table.palette()
    # palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    # palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
    # palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#fafcfd"))
    # table.setPalette(palette)
    # # 2026-10-13：本次修改原因：显式标记数据视口，空白区使用和表格相同的白色背景。
    # table.viewport().setObjectName("tableViewport")
    # table.viewport().setPalette(palette)
    # table.viewport().setAutoFillBackground(True)
    # for header in (table.horizontalHeader(), table.verticalHeader()):
        # header.setPalette(palette)
        # header.setAutoFillBackground(True)
    # 2026-10-13：本次修改原因：表格背景交给全局主题，移除局部固定调色板，主题切换无需重建表格。
    table.viewport().setObjectName("tableViewport")
    table.setMouseTracking(True)
    table.verticalHeader().setObjectName("rowNumbers")
    table.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
    # 2026-10-13：本次修改原因：表头可拖动列宽，长表不扫描所有行计算列宽。
    table.horizontalHeader().setResizeContentsPrecision(100)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    table.setMinimumWidth(0)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setItemDelegate(CellEditorDelegate(table))
    if not editable:
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def tooltip(item):
        if item.toolTip() != item.text():
            # 2026-10-12：本次修改原因：仅更新提示不能重复触发业务 itemChanged 或把预览视为修改。
            blocked = table.blockSignals(True)
            item.setToolTip(item.text())
            table.blockSignals(blocked)
    table.itemChanged.connect(tooltip)
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def show_content(position):
        item = table.itemAt(position)
        if item is None:
            return
        can_edit = editable and bool(item.flags() & Qt.ItemFlag.ItemIsEditable)
        menu = QMenu(table)
        action = menu.addAction("编辑完整内容…" if can_edit else "查看完整内容…")
        if menu.exec(table.viewport().mapToGlobal(position)) != action:
            return
        dialog = QDialog(table)
        dialog.setWindowTitle("完整单元格内容")
        dialog.resize(680, 350)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("长文本或链接可在此完整查看；普通单元格双击直接编辑。", "hint", True))
        editor = QPlainTextEdit(item.text())
        editor.setReadOnly(not can_edit)
        layout.addWidget(editor, 1)
        controls = QHBoxLayout()
        controls.addStretch()
        controls.addWidget(button("取消" if can_edit else "关闭", dialog.reject))
        if can_edit:
            controls.addWidget(button("应用", dialog.accept, primary=True))
        layout.addLayout(controls)
        if dialog.exec() == QDialog.DialogCode.Accepted and can_edit:
            item.setText(editor.toPlainText())
    table.customContextMenuRequested.connect(show_content)


# 2026-10-13：本次修改原因：表单中的短表按实际行数收起底部空白，长表达到行数上限后独立滚动。
# def fit_table_rows(table, *, maximum_rows: int = 8) -> None:
# 2026-10-13：本次修改原因：设置页短表可按全部行展开，由外层整页滚动；其他表格默认上限不变。
def fit_table_rows(table, *, maximum_rows: int | None = 8) -> None:
    timer = QTimer(table)
    timer.setSingleShot(True)
    timer.setInterval(0)

    def resize_height():
        # count = min(maximum_rows, max(1, table.rowCount()))
        count = max(1, table.rowCount()) if maximum_rows is None else min(maximum_rows, max(1, table.rowCount()))
        rows = sum(table.rowHeight(row) for row in range(min(count, table.rowCount())))
        if not table.rowCount():
            rows = table.verticalHeader().defaultSectionSize()
        header = max(table.horizontalHeader().minimumHeight(), table.horizontalHeader().sizeHint().height())
        horizontal = table.horizontalScrollBar().sizeHint().height()
        table.setFixedHeight(header + rows + horizontal + table.frameWidth() * 2 + 2)
        table.updateGeometry()

    def schedule(*_args):
        timer.start()
    timer.timeout.connect(resize_height)
    table.model().rowsInserted.connect(schedule)
    table.model().rowsRemoved.connect(schedule)
    table.model().modelReset.connect(schedule)
    table.verticalHeader().sectionResized.connect(schedule)
    table.horizontalHeader().sectionResized.connect(schedule)
    schedule()
