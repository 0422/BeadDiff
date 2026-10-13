# 2026-10-13：本次修改原因：界面分区可拖拽并记住布局，仅保存显示偏好，不读写业务数据。
from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings, QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSplitter, QSplitterHandle, QToolButton, QVBoxLayout, QWidget


class ResetHandle(QSplitterHandle):
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.splitter().reset_layout()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class PersistentSplitter(QSplitter):
    """只在首次显示时还原；拖拽结束防抖保存，不在 resizeEvent 中反复写设置。"""
    def __init__(self, orientation, key: str, defaults: list[int], parent=None, *, live=False):
        super().__init__(orientation, parent)
        self.key, self.defaults = key, defaults
        self.settings = QSettings("BeadDiff", "BeadDiff")
        self.restored = False
        self.transient = False
        # 2026-10-13：本次修改原因：撤下区域放大入口，只保留拖拽和必要的折叠，旧代码注释保留。
        # self.normal_sizes = None
        self.setHandleWidth(7)
        self.setChildrenCollapsible(False)
        self.setOpaqueResize(live)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(250)
        self.save_timer.timeout.connect(self.save_layout)
        self.splitterMoved.connect(lambda *_: self.save_timer.start())

    def createHandle(self):
        handle = ResetHandle(self.orientation(), self)
        handle.setToolTip("拖动调整区域 · 双击恢复默认布局")
        return handle

    def showEvent(self, event):
        super().showEvent(event)
        if not self.restored:
            self.restored = True
            state = self.settings.value(self.key)
            if not isinstance(state, QByteArray) or not self.restoreState(state) or min(self.sizes()) <= 0:
                self.setSizes(self.defaults)

    def save_layout(self):
        if self.restored and not self.transient:
            self.settings.setValue(self.key, self.saveState())

    def reset_layout(self):
        for index in range(self.count()):
            self.widget(index).show()
            if isinstance(self.widget(index), Panel):
                # self.widget(index).body.show()
                # self.widget(index).collapse.setText("收起")
                # self.widget(index).maximize.setText("放大")
                # self.settings.setValue(self.key + "/collapsed/" + str(index), False)
                # 2026-10-13：本次修改原因：双击复位遵循辅助区默认收起，不把所有内容强制展开。
                panel = self.widget(index)
                panel.expanded_size = None
                panel.set_expanded(not panel.default_collapsed, persist=False)
        self.transient = False
        # self.normal_sizes = None
        self.setSizes(self.defaults)
        self.save_layout()

    # 2026-10-13：本次修改原因：取消隐藏同级区域的放大逻辑，避免增加不必要的显示状态。
    # def focus_region(self, widget):
    #     if not self.transient:
    #         self.normal_sizes = self.sizes()
    #         self.save_layout()
    #         self.transient = True
    #         for index in range(self.count()):
    #             self.widget(index).setVisible(self.widget(index) is widget)
    #     else:
    #         for index in range(self.count()):
    #             self.widget(index).show()
    #         self.transient = False
    #         self.setSizes(self.normal_sizes or self.defaults)
    #         self.normal_sizes = None


class Panel(QWidget):
    # 2026-10-13：本次修改原因：区域标题只提供必要的收起/展开，不再堆叠放大按钮。
    """折叠只改变呈现，内部字段与操作保持原实例。"""
    # def __init__(self, title, body, parent=None, *, collapsible=True):
    # 2026-10-13：本次修改原因：辅助分区每次创建默认收起，操作中的主区域可显式保持展开。
    def __init__(self, title, body, parent=None, *, collapsible=True, default_collapsed=True):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.body = body
        self.collapsible = collapsible
        self.default_collapsed = bool(collapsible and default_collapsed)
        self.collapse_restored = False
        self.expanded_size = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        # heading.addWidget(QLabel(title), 1)
        # 2026-10-13：本次修改原因：标题与数量相邻展示，留白撑开操作区，避免再增加一行页脚。
        self.heading_layout = heading
        self.title_label = QLabel(title)
        self.title_label.setObjectName("panelTitle")
        heading.addWidget(self.title_label)
        heading.addStretch(1)
        self.collapse = QToolButton()
        # self.collapse.setText("收起")
        self.collapse.setText("展开" if self.default_collapsed else "收起")
        self.collapse.setToolTip("折叠当前区域，内容保留")
        self.collapse.setVisible(collapsible)
        self.collapse.clicked.connect(self.toggle_body)
        heading.addWidget(self.collapse)
        # 2026-10-13：本次修改原因：所有分区撤下放大/恢复按钮，简化界面。
        # self.maximize = QToolButton()
        # self.maximize.setText("放大")
        # self.maximize.setToolTip("放大当前区域，再点一次恢复")
        # self.maximize.clicked.connect(self.toggle_focus)
        # heading.addWidget(self.maximize)
        layout.addLayout(heading)
        layout.addWidget(body, 1)
        # 2026-10-13：本次修改原因：首次布局前隐藏辅助内容，避免启动时先展开再跳动。
        body.setVisible(not self.default_collapsed)

    # 2026-10-13：本次修改原因：查看按钮与快捷键复用同一个展开方法，确保分隔条尺寸和按钮文字同步。
    # def toggle_body(self):
    #     visible = self.body.isHidden()
    def set_expanded(self, visible: bool, *, persist=True):
        if not self.collapsible:
            return
        parent = self.parentWidget()
        sizes = parent.sizes() if isinstance(parent, PersistentSplitter) else None
        # 2026-10-13：本次修改原因：已展开时切换记录不重新分配宽度，保留用户拖拽后的左右比例。
        changed = self.body.isHidden() == visible
        # if sizes and not visible:
        if sizes and not visible and not self.body.isHidden():
            self.expanded_size = sizes[parent.indexOf(self)]
        self.body.setVisible(visible)
        self.collapse.setText("收起" if visible else "展开")
        if isinstance(parent, PersistentSplitter):
            # parent.settings.setValue(parent.key + "/collapsed/" + str(parent.indexOf(self)), not visible)
            # 2026-10-13：本次修改原因：收起后只保留标题栏，消除隐藏内容后仍占大片空白的问题。
            vertical = parent.orientation() == Qt.Orientation.Vertical
            limit = 16777215 if visible else (
                self.minimumSizeHint().height() if vertical else self.minimumSizeHint().width())
            if vertical:
                self.setMaximumHeight(limit)
            else:
                self.setMaximumWidth(limit)
            # if sizes and not parent.transient:
            if sizes and changed and not parent.transient:
                index = parent.indexOf(self)
                sizes[index] = (self.expanded_size or parent.defaults[index]) if visible else (
                    self.minimumSizeHint().height() if parent.orientation() == Qt.Orientation.Vertical else self.minimumSizeHint().width())
                parent.setSizes(sizes)
                # parent.save_layout()
                if persist:
                    parent.save_layout()

    def toggle_body(self):
        self.set_expanded(self.body.isHidden())

    def showEvent(self, event):
        super().showEvent(event)
        if self.collapsible and not self.collapse_restored:
            self.collapse_restored = True
            # parent = self.parentWidget()
            # if isinstance(parent, PersistentSplitter):
            #     value = parent.settings.value(parent.key + "/collapsed/" + str(parent.indexOf(self)), False)
            #     if value is True or value == "true":
            #         self.body.hide()
            #         self.collapse.setText("展开")
            # 2026-10-13：本次修改原因：旧版展开偏好不覆盖本次默认收起；启动后点击才展开，拖拽比例继续保存。
            self.set_expanded(not self.body.isHidden(), persist=False)

    # 2026-10-13：本次修改原因：放大按钮撤下后停用其回调，拖拽和双击复位仍有效。
    # def toggle_focus(self):
    #     parent = self.parentWidget()
    #     if isinstance(parent, PersistentSplitter):
    #         self.body.show()
    #         self.collapse.setText("收起")
    #         parent.focus_region(self)
    #         self.maximize.setText("恢复" if parent.transient else "放大")


# 2026-10-13：本次修改原因：撤下工作区常驻说明后，将原反馈标签的更新转交底部状态栏，保留全部业务回调。
class StatusFeedback(QLabel):
    """兼容原 setText 调用，仅在操作发生时显示反馈，不占页面布局。"""
    def __init__(self, owner):
        super().__init__("", owner)
        self.owner = owner
        self.hide()

    def setText(self, text):
        super().setText(text)
        if text:
            self.owner.statusBar().setToolTip(text)
            self.owner.statusBar().showMessage(text, 10000)


def save_splitters(owner):
    for splitter in owner.findChildren(PersistentSplitter):
        splitter.save_layout()
