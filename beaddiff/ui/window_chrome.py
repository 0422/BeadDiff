# 2026-10-13：本次修改原因：主窗口去掉重复标题栏，采用紧凑窗口操作区；保留系统拖动、缩放和关闭流程。
from __future__ import annotations

# 2026-10-13：本次修改原因：整窗外轮廓优先使用 Windows 原生圆角，旧系统及非 Windows 控件验证用裁剪兜底。
import ctypes
import sys
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMainWindow, QToolButton, QWidget
# 2026-10-13：本次修改原因：动态页面控件被释放后不再还原其光标，避免悬停引用触发已删除对象错误。
from shiboken6 import isValid

from .theme import theme_tokens


class WindowControl(QToolButton):
    """窗口符号用矢量绘制，避免高 DPI 模糊及额外资源路径。"""
    def __init__(self, mode: str, callback, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.setObjectName("windowClose" if mode == "close" else "windowControl")
        self.setFixedSize(44, 30)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(callback)
        self.update_mode(mode)

    def update_mode(self, mode: str):
        self.mode = mode
        text = {"minimize": "最小化", "maximize": "最大化", "restore": "还原", "close": "关闭"}[mode]
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = "#FFFFFF" if self.mode == "close" and self.underMouse() else theme_tokens()["text"]
        painter.setPen(QPen(QColor(color), 1.2))
        x, y = self.width() / 2, self.height() / 2
        if self.mode == "minimize":
            painter.drawLine(QPointF(x - 5, y + 1), QPointF(x + 5, y + 1))
        elif self.mode == "maximize":
            painter.drawRect(int(x - 5), int(y - 5), 10, 10)
        elif self.mode == "restore":
            painter.drawRect(int(x - 5), int(y - 2), 8, 8)
            painter.drawLine(QPointF(x - 2, y - 5), QPointF(x + 6, y - 5))
            painter.drawLine(QPointF(x + 6, y - 5), QPointF(x + 6, y + 3))
        else:
            painter.drawLine(QPointF(x - 4, y - 4), QPointF(x + 4, y + 4))
            painter.drawLine(QPointF(x + 4, y - 4), QPointF(x - 4, y + 4))


class WindowBar(QFrame):
    def __init__(self, owner):
        super().__init__(owner)
        self.setObjectName("windowBar")
        self.setFixedHeight(30)
        self.setMouseTracking(True)
        self.setAccessibleName("窗口拖动区域")
        self.owner = owner
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 4, 0)
        row.setSpacing(0)
        row.addStretch()
        row.addWidget(WindowControl("minimize", owner.showMinimized, self))
        self.maximize = WindowControl("maximize", self.toggle_maximized, self)
        row.addWidget(self.maximize)
        # 调用原窗口 close()，任务中的关闭保护仍由 MainWindow.closeEvent 决定。
        row.addWidget(WindowControl("close", owner.close, self))

    def toggle_maximized(self):
        self.owner.showNormal() if self.owner.isMaximized() else self.owner.showMaximized()

    def sync_state(self):
        self.maximize.update_mode("restore" if self.owner.isMaximized() else "maximize")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner.windowHandle():
            if self.owner.windowHandle().startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class DesktopWindow(QMainWindow):
    """只替换窗口外观；使用 Qt 的系统移动/缩放保持 Windows 桌面操作习惯。"""
    def __init__(self):
        super().__init__()
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        # 2026-10-13：本次修改原因：圆角作用于整个窗口（包含顶栏、侧栏及状态栏），不启用透明子窗口。
        self._corner_radius = 12
        self._native_rounding = False
        self._edge_widget = None
        self._edge_cursor = None
        QApplication.instance().installEventFilter(self)

    # 2026-10-13：本次修改原因：Windows 11 原生圆角具有平滑边缘；不支持时保留下面的窗口区域裁剪。
    def enable_native_rounding(self) -> bool:
        if sys.platform != "win32" or QApplication.platformName() != "windows":
            return False
        try:
            self.clearMask()
            setter = ctypes.windll.dwmapi.DwmSetWindowAttribute
            setter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
            setter.restype = ctypes.c_long
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33，DWMWCP_ROUND = 2。
            preference = ctypes.c_int(2)
            return setter(int(self.winId()), 33, ctypes.byref(preference), ctypes.sizeof(preference)) == 0
        except (AttributeError, OSError):
            return False

    def update_window_outline(self):
        # 最大化/全屏贴合屏幕，不为四角预留透明缺口；还原后恢复圆角。
        if self.isMaximized() or self.isFullScreen() or getattr(self, "_native_rounding", False):
            self.clearMask()
            return
        path = QPainterPath()
        radius = getattr(self, "_corner_radius", 12)
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def showEvent(self, event):
        super().showEvent(event)
        self._native_rounding = self.enable_native_rounding()
        self.update_window_outline()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_window_outline()

    def resize_edges(self, global_position):
        if self.isMaximized() or self.isFullScreen():
            return Qt.Edge(0)
        point = self.mapFromGlobal(global_position)
        if not self.rect().contains(point):
            return Qt.Edge(0)
        edges = Qt.Edge(0)
        if point.x() < 6:
            edges |= Qt.Edge.LeftEdge
        elif point.x() >= self.width() - 6:
            edges |= Qt.Edge.RightEdge
        if point.y() < 6:
            edges |= Qt.Edge.TopEdge
        elif point.y() >= self.height() - 6:
            edges |= Qt.Edge.BottomEdge
        return edges

    def restore_edge_cursor(self):
        # if self._edge_widget is not None:
        if self._edge_widget is not None and isValid(self._edge_widget):
            self._edge_widget.setCursor(self._edge_cursor)
        self._edge_widget = None
        self._edge_cursor = None

    def eventFilter(self, target, event):
        if isinstance(target, QWidget) and target.window() is self:
            if event.type() == QEvent.Type.MouseMove:
                edges = self.resize_edges(event.globalPosition().toPoint())
                if edges:
                    if self._edge_widget is not target:
                        self.restore_edge_cursor()
                        self._edge_widget, self._edge_cursor = target, target.cursor()
                    horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
                    vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
                    if horizontal and vertical:
                        diagonal = bool(edges & Qt.Edge.LeftEdge) == bool(edges & Qt.Edge.TopEdge)
                        cursor = Qt.CursorShape.SizeFDiagCursor if diagonal else Qt.CursorShape.SizeBDiagCursor
                    else:
                        cursor = Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor
                    target.setCursor(cursor)
                else:
                    self.restore_edge_cursor()
            elif event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                edges = self.resize_edges(event.globalPosition().toPoint())
                handle = self.windowHandle()
                if edges and handle and handle.startSystemResize(edges):
                    return True
            elif event.type() == QEvent.Type.Leave and target is self._edge_widget:
                self.restore_edge_cursor()
        return super().eventFilter(target, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        # if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "window_bar"):
        #     self.restore_edge_cursor()
        #     self.window_bar.sync_state()
        # 2026-10-13：本次修改原因：最大化/还原同时更新整窗轮廓，按钮状态与原窗口操作一致。
        if event.type() == QEvent.Type.WindowStateChange:
            self.update_window_outline()
            self.restore_edge_cursor()
            if hasattr(self, "window_bar"):
                self.window_bar.sync_state()
