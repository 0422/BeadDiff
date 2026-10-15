# 2026-10-12：本次修改原因：统一编辑表格的行高、行号、输入框几何和完整内容查看，避免高 DPI 下裁字及边框重叠。
from __future__ import annotations

# from PySide6.QtCore import Qt
# 2026-10-13：本次修改原因：表格自适应高度在布局后计算，背景覆盖整个表格及行号空白区。
# from PySide6.QtCore import Qt, QTimer
# from PySide6.QtGui import QColor, QPalette
# 2026-10-15：本次修改原因：表格尾行、尾列边缘使用悬停入口，随滚动和尺寸变化更新位置。
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLineEdit, QMenu,
    QPlainTextEdit, QSizePolicy, QStyledItemDelegate, QVBoxLayout, QFrame,
)

from .widgets import button, label
# 2026-10-15：本次修改原因：边缘新增控件复用表格容器，支持鼠标悬停和键盘聚焦。
# from PySide6.QtWidgets import QSizePolicy, QToolButton, QWidget
# 2026-10-15：本次修改原因：QSizePolicy 已由统一表格导入，边缘控件仅补充其余类型，避免重复导入。
from PySide6.QtWidgets import QToolButton, QWidget


# 2026-10-15：本次修改原因：将新增行、列入口收至实际内容边缘，保留滚动条及最后一格的完整点击区域。
class TableEdgeActions(QWidget):
    def __init__(self, table, add_row, add_column, parent=None):
        super().__init__(parent)
        self.table = table
        self.edge_size = 26
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, self.edge_size, self.edge_size)
        layout.setSpacing(0)
        layout.addWidget(table)
        self.row_action = QToolButton(self)
        self.column_action = QToolButton(self)
        for control, title, callback in (
                (self.row_action, "新增字段行", add_row),
                (self.column_action, "新增属性列", add_column)):
            control.setObjectName("tableEdgeAdd")
            control.setText("＋")
            control.setToolTip(title)
            control.setAccessibleName(title)
            control.setCursor(Qt.CursorShape.PointingHandCursor)
            control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            control.setProperty("edgeActive", False)
            control.setMouseTracking(True)
            control.clicked.connect(callback)
            control.hide()
        self.position_timer = QTimer(self)
        self.position_timer.setSingleShot(True)
        self.position_timer.timeout.connect(self._position_actions)
        for surface in (table, table.viewport(), table.horizontalHeader(), table.verticalHeader(),
                        self.row_action, self.column_action):
            surface.setMouseTracking(True)
            surface.installEventFilter(self)
        for bar in (table.horizontalScrollBar(), table.verticalScrollBar()):
            bar.valueChanged.connect(self._schedule_position)
            bar.rangeChanged.connect(self._schedule_position)
        for header in (table.horizontalHeader(), table.verticalHeader()):
            header.sectionResized.connect(self._schedule_position)
            header.geometriesChanged.connect(self._schedule_position)
        for signal in (table.model().rowsInserted, table.model().rowsRemoved,
                       table.model().columnsInserted, table.model().columnsRemoved,
                       table.model().modelReset):
            signal.connect(self._schedule_position)
        self._schedule_position()

    def _schedule_position(self, *_args):
        self.position_timer.start(0)

    def _position_actions(self):
        viewport = self.table.viewport()
        origin = viewport.mapTo(self, viewport.rect().topLeft())
        width, height = viewport.width(), viewport.height()
        row_header, column_header = self.table.verticalHeader(), self.table.horizontalHeader()
        last_row, last_column = self.table.rowCount() - 1, self.table.columnCount() - 1
        row_end = row_header.sectionViewportPosition(last_row) + row_header.sectionSize(last_row) if last_row >= 0 else 0
        column_end = column_header.sectionViewportPosition(last_column) + column_header.sectionSize(last_column) if last_column >= 0 else 0
        # 2026-10-15：本次修改原因：只在滚动到尾行、尾列时开放对应新增边缘；空白视口内紧贴内容边界。
        row_visible = height > 0 and 0 <= row_end <= height + 1
        column_visible = width > 0 and 0 <= column_end <= width + 1
        row_y = origin.y() + row_end if row_end + self.edge_size < height else self.table.geometry().bottom() + 1
        column_x = origin.x() + column_end if column_end + self.edge_size < width else self.table.geometry().right() + 1
        # 2026-10-15：本次修改原因：悬停感应跨过边缘与滚动条之间的间隙，移动到加号时保持新增提示。
        self.row_hover_reach = max(6, row_y - origin.y() - row_end + 6)
        self.column_hover_reach = max(6, column_x - origin.x() - column_end + 6)
        self.row_action.setGeometry(origin.x(), row_y, width, self.edge_size)
        self.column_action.setGeometry(column_x, self.table.y(), self.edge_size,
                                       max(0, origin.y() + height - self.table.y()))
        self.row_action.setVisible(row_visible)
        self.column_action.setVisible(column_visible)
        self.row_action.raise_()
        self.column_action.raise_()
        self._update_hover()

    def _update_hover(self):
        position = self.mapFromGlobal(QCursor.pos())
        # for control in (self.row_action, self.column_action):
        #     active = control.isVisible() and control.geometry().adjusted(-6, -6, 6, 6).contains(position)
        # 2026-10-15：本次修改原因：只扩大边缘的感应区，保留滚动条和原单元格自身的点击区域。
        for control, left, top in (
                (self.row_action, 6, getattr(self, "row_hover_reach", 6)),
                (self.column_action, getattr(self, "column_hover_reach", 6), 6)):
            active = control.isVisible() and control.geometry().adjusted(-left, -top, 6, 6).contains(position)
            if control.property("edgeActive") != active:
                control.setProperty("edgeActive", active)
                control.style().unpolish(control)
                control.style().polish(control)
                control.update()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
            self._schedule_position()
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.Enter, QEvent.Type.Leave,
                            QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._update_hover()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_position()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_position()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._update_hover()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._update_hover()


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
