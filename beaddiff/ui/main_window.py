# 2026-10-12：本次修改原因：统一三条商品来源、加工审核与 ERP 回传，移除表格导出路线。
from __future__ import annotations

import json
# 2026-10-12：本次修改原因：本机清理失败统一反馈 SQLite 错误，保留现有列表。
import sqlite3
from datetime import datetime
# from pathlib import Path
# 2026-10-12：本次修改原因：表格路径处理已移除，原始材料路径读取交给采集记录页。

# from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl
# 2026-10-10：本次修改原因：使用显式 Qt 槽接收跨线程任务信号。
# from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, Slot
# 2026-10-12：本次修改原因：后台回传阶段通过 Qt 信号更新主线程界面。
# from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, Slot, Signal
# 2026-10-13：本次修改原因：商品列显示偏好在本机持久化，替代右侧速览的固定展示。
from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, Slot, Signal, QSettings
# 2026-10-13：本次修改原因：导航图标响应主题事件，使用 Qt 事件枚举统一处理。
from PySide6.QtCore import QEvent
# 2026-10-13：本次修改原因：页面式编辑返回后按商品 ID 恢复列表多行选择，不依赖易变的行号。
from PySide6.QtCore import QItemSelectionModel
# from PySide6.QtGui import QColor, QDesktopServices
# 2026-10-13：本次修改原因：快捷键复用现有搜索、编辑和移除按钮，不新增业务操作。
from PySide6.QtGui import QColor, QDesktopServices, QShortcut, QKeySequence
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit, QMainWindow,
    # QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
    # 2026-10-13：本次修改原因：商品加工改为全宽列表，不再创建左右分栏，逐行工具使用菜单。
    QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QStackedWidget, QMenu,
    # QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    # 2026-10-11：本次修改原因：在设置中提供插件连接与 AI 模型两个页面。
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
    # 2026-10-12：本次修改原因：底部使用实际同步进度，速览使用可折叠次要操作。
    QProgressBar, QToolButton,
)

from ..config import Settings
# 2026-10-11：本次修改原因：商品库与设置复用回传方式、回执服务及任务状态。
# from ..erp import ERPService, MODE_LABELS, STATE_LABELS
# 2026-10-12：本次修改原因：结果标签由回传记录页使用，主窗口只负责调度。
from ..erp import ERPService, MODE_LABELS
from ..models import Product, valid_url
from ..receiver import LocalReceiver
from ..service import CaptureService
from ..storage import Repository
from .editor import ProductEditor
# from .widgets import ImagePreview, Task, button, card, icon, label
# 2026-10-13：本次修改原因：列表缩略图由委托按可见行绘制，移除单独的商品速览图片控件。
from .widgets import Task, button, card, icon, label
# 2026-10-12：本次修改原因：工作列表和编辑表格共享安全行高与完整内容查看。
from .table_support import configure_table
# 2026-10-13：本次修改原因：商品字段、缩略图及逐行操作集中到全宽列表。
# from .product_table import PRODUCT_COLUMNS, PRODUCT_COL, IMAGE_ROLE, ProductTable, ProductThumbnailDelegate, ProductActionsDelegate, price_summary
# 2026-10-13：本次修改原因：列表统一状态委托及 Model/View，业务回调保留。
from .product_table import PRODUCT_COLUMNS, PRODUCT_COL, IMAGE_ROLE, ProductTable, ProductThumbnailDelegate, ProductActionsDelegate, ProductRowDelegate, StatusBadgeDelegate, price_summary
# from .layout_support import PersistentSplitter, Panel, save_splitters
# 2026-10-13：本次修改原因：操作说明移到状态栏，页面仅保留有效操作和内容区域。
from .layout_support import PersistentSplitter, Panel, StatusFeedback, save_splitters
# from .theme import apply_theme
# 2026-10-13：本次修改原因：导航图标随浅/深主题更新，避免侧栏换色后图标对比不足。
from .theme import apply_theme, theme_tokens
# 2026-10-13：本次修改原因：主窗口采用参考图的紧凑无文字顶栏，窗口操作与业务关闭保护保持不变。
from .window_chrome import DesktopWindow, WindowBar
# 2026-10-11：本次修改原因：两条商品路线共用本机模型配置、素材、任务与 AI 服务。
from ..ai.config import ModelConfigStore
from ..ai.service import AIService
from ..assets import AssetStore
from ..image_hosting import GitHubImageHosting, ImageHostingStore
from .ai_runner import TaskHub
from .model_settings import ModelSettingsPage
# from .product_creation import ProductCreation
# 2026-10-14：本次修改原因：接入白底图配置与错误处理位置。
from .product_creation import ProductCreation
from ..listing import ListingDefaultsStore
from .listing_settings import ListingSettingsPage
from ..validation_guidance import explain_errors, explain_issue
# 2026-10-11：本次修改原因：商品编辑和两条建档路线共用官方公共采集箱适配器与独立凭证配置。
from ..miaoshou import MiaoshouAdapter
from ..miaoshou_config import MiaoshouConfigStore
from .miaoshou_binding import MiaoshouBindingDialog
from .miaoshou_settings import MiaoshouSettingsPage
# 2026-10-11：本次修改原因：核对未知回传时允许填写经人工在妙手找到的目标商品 ID。
from PySide6.QtWidgets import QInputDialog
# 2026-10-12：本次修改原因：商品库直接导入官方采集箱数据，插件接收及文件导入保持独立可用。
from .miaoshou_import import MiaoshouImportDialog
# 2026-10-12：本次修改原因：采集、回传和帮助独立成页，来源与回传状态共用业务规则。
# from .workflow_pages import AcquisitionRecordsPage, ERPRecordsPage, HelpPage
# 2026-10-13：本次修改原因：采集与回传嵌入统一日志页，帮助归入设置，复用原记录页面及业务回调。
from .workflow_pages import AcquisitionRecordsPage, ERPRecordsPage, HelpPage, LogRecordsPage
# 2026-10-13：本次修改原因：回收站独立成页，所有删除来源都可进入查看和选择恢复。
from .recycle_bin import RecycleBinPage
from .image_hosting import ImageHostingConfigPage, ImageHostingPage
from ..workflow import ROUTE_LABELS, TARGET_LABEL, local_picture_count, transfer_status


def readable_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%m-%d %H:%M")
    except ValueError:
        return value


def table(headers: list[str]) -> QTableWidget:
    result = QTableWidget(0, len(headers))
    result.setHorizontalHeaderLabels(headers)
    result.setShowGrid(False)
    result.setAlternatingRowColors(True)
    result.verticalHeader().hide()
    result.verticalHeader().setDefaultSectionSize(58)
    result.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    result.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    result.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    result.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    result.horizontalHeader().setStretchLastSection(True)
    return result


# class MainWindow(QMainWindow):
# 2026-10-13：本次修改原因：隐藏系统标题栏中的重复软件图标/文本，使用独立的窗口操作区。
class MainWindow(DesktopWindow):
    # 2026-10-13：本次修改原因：使用明确的页面编号，导航合并后避免设置、日志及回收站跳错页。
    PAGE_PRODUCTS = 0
    PAGE_LOGS = 1
    PAGE_SETTINGS = 2
    PAGE_RECYCLE = 3
    # 2026-10-13：本次修改原因：追加页面编号保持旧跳转稳定，导航顺序独立于堆栈编号。
    PAGE_REFERENCES = 4
    PAGE_TRACKING = 5
    PAGE_HOSTING = 6
    SETTINGS_HOSTING = 4
    # SETTINGS_HELP = 5
    # 2026-10-14：本次修改原因：追加白底图设置编号，不改变既有帮助、图床和系统跳转。
    SETTINGS_HELP = 5
    SETTINGS_LISTING = 7
    # 2026-10-12：本次修改原因：后台阶段提示只在主线程更新界面。
    transfer_progress = Signal(str)
    def __init__(self, settings: Settings, repository: Repository, service: CaptureService, receiver: LocalReceiver):
        super().__init__()
        self.settings, self.repository, self.service, self.receiver = settings, repository, service, receiver
        self.network = QNetworkAccessManager(self)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        # 2026-10-11：本次修改原因：启动时加载独立模型配置文件，所有编辑入口复用同一服务。
        self.model_config = ModelConfigStore(settings.data_dir)
        # self.assets = AssetStore(settings.data_dir)
        # 2026-10-14：本次修改原因：所有白底图建档读取同一设置。
        self.assets = AssetStore(settings.data_dir)
        self.listing_defaults_store = ListingDefaultsStore(settings.data_dir)
        self.ai_service = AIService(self.model_config, self.assets)
        # 2026-10-14：本次修改原因：图床凭证只在设置页配置，商品页和同步页直接复用，不重复弹模型或图床设置。
        self.image_hosting_store = ImageHostingStore(settings.data_dir)
        self.image_hosting_service = GitHubImageHosting(self.image_hosting_store, self.assets)
        # 2026-10-13：本次修改原因：独立爆款方案库与商品 AI 页共享本地存储。
        from ..ai.references import ReferenceStore
        self.reference_store = ReferenceStore(settings.data_dir)
        # 2026-10-11：本次修改原因：两条商品路线保存后共用妙手回传适配层。
        # self.erp_service = ERPService(repository)
        # 2026-10-11：本次修改原因：加载本地开放平台凭证并注入真实公共采集箱适配器。
        self.miaoshou_config = MiaoshouConfigStore(settings.data_dir)
        self.miaoshou_adapter = MiaoshouAdapter(self.miaoshou_config, hosting=self.image_hosting_service)
        self.erp_service = ERPService(repository, self.miaoshou_adapter)
        self.ai_hub = TaskHub(self)
        self._tasks: set[Task] = set()
        self._products: list[Product] = []
        # 2026-10-12：本次修改原因：刷新时统一载入回执，商品状态与回传记录保持一致。
        self._erp_records: list[dict] = []
        self.transfer_progress.connect(self.transfer_stage, Qt.ConnectionType.QueuedConnection)
        self.checked_ids: set[str] = set()
        self.active_filter = "全部"
        # 2026-10-13：本次修改原因：列表按采集商品/白底图商品切换展示，仅是界面筛选，不改变获取路线或存储。
        self.product_source = "capture"
        self.current_product: Product | None = None
        # 2026-10-13：本次修改原因：商品编辑共用主窗口页面栈，保留列表实例及进入前的显示状态。
        self.product_editor: ProductEditor | None = None
        # self.setWindowTitle("BeadDiff · 商品工作台")
        # 2026-10-12：本次修改原因：统一商品加工入口、来源和反馈链路。
        self.setWindowTitle("BeadDiff · 商品加工")
        self.resize(1500, 930)
        self.setMinimumSize(1180, 760)
        self.setWindowIcon(icon("products", "#138b78"))
        container = QWidget()
        self.setCentralWidget(container)
        # root = QHBoxLayout(container)
        # 2026-10-13：本次修改原因：顶栏与左右工作区统一布局，去除原标题栏及工作区重复的顶部空白。
        container.setObjectName("desktopShell")
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # self.window_bar = WindowBar(self)
        # root.addWidget(self.window_bar)
        # 2026-10-13：本次修改原因：侧栏直接顶到窗口上沿，窗口操作栏迁到右侧，不再在侧栏上方占用 30px。
        # root.addWidget(self._sidebar())
        # 2026-10-13：本次修改原因：侧栏与工作区可拖动调整宽度，六个导航入口全部保留。
        self.root_splitter = PersistentSplitter(Qt.Orientation.Horizontal, "ui/main/root_splitter_v1", [210, 1230], container, live=True)
        # 2026-10-13：本次修改原因：侧栏与内容以留白分隔，保持原有拖拽和持久化。
        self.root_splitter.setHandleWidth(8)
        self.root_splitter.addWidget(self._sidebar())
        root.addWidget(self.root_splitter, 1)
        # 2026-10-13：本次修改原因：右侧独立容纳窗口操作栏与页面，侧栏和工作区仍使用原分隔条持久化。
        workspace_column = QWidget()
        workspace_column.setObjectName("workspaceColumn")
        column_layout = QVBoxLayout(workspace_column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)
        self.window_bar = WindowBar(self)
        column_layout.addWidget(self.window_bar)
        workspace = QWidget()
        workspace.setObjectName("workspace")
        self.workspace_layout = QVBoxLayout(workspace)
        # self.workspace_layout.setContentsMargins(28, 26, 28, 18)
        # self.workspace_layout.setSpacing(18)
        # 2026-10-13：本次修改原因：内容紧贴紧凑顶栏，统一左右页边距，避免顶端出现第二条空白带。
        self.workspace_layout.setContentsMargins(12, 4, 16, 12)
        self.workspace_layout.setSpacing(12)
        # root.addWidget(workspace, 1)
        # self.root_splitter.addWidget(workspace)
        # 2026-10-13：本次修改原因：右侧操作栏只占右侧高度；保持既有 workspace_layout 与页面实例不变。
        column_layout.addWidget(workspace, 1)
        self.root_splitter.addWidget(workspace_column)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._products_page())
        # self.stack.addWidget(self._captures_page())
        # 2026-10-12：本次修改原因：表格路线撤下后，第三项导航改为 ERP 回传记录。
        # self.stack.addWidget(self._erp_records_page())
        # 2026-10-13：本次修改原因：侧栏只保留一个日志入口，采集/回传通过日志页的两类标签切换。
        self.stack.addWidget(self._logs_page())
        self.stack.addWidget(self._settings_page())
        # 2026-10-12：本次修改原因：在软件内提供可回到具体页面的操作帮助。
        # self.stack.addWidget(HelpPage(self))
        self.recycle_bin_page = RecycleBinPage(self)
        self.stack.addWidget(self.recycle_bin_page)
        # 2026-10-13：本次修改原因：增加爆款方案管理和包裹追踪占位入口，现有业务页面不变。
        from .reference_analysis import ReferenceAnalysisPage, PackageTrackingPage
        self.reference_analysis_page = ReferenceAnalysisPage(self.ai_service, self.ai_hub, self.reference_store, self)
        self.stack.addWidget(self.reference_analysis_page)
        self.stack.addWidget(PackageTrackingPage(self))
        # 2026-10-14：本次修改原因：独立展示已托管图片及公网链接，候选图仍留在商品编辑草稿中。
        self.image_hosting_page = ImageHostingPage(self.image_hosting_store, self.image_hosting_service, self.ai_hub, self)
        self.stack.addWidget(self.image_hosting_page)
        self.workspace_layout.addWidget(self.stack, 1)
        # self.statusBar().showMessage("就绪 · 原始材料与编辑版本保存在本机")
        # 2026-10-13：本次修改原因：无边框窗口用边缘拖拽缩放，撤下右下角单独尺寸柄。
        self.statusBar().setSizeGripEnabled(False)
        # 2026-10-12：本次修改原因：统一底部任务反馈，完成和失败都明确退出忙碌状态。
        self.task_progress_text = label("", "hint")
        self.task_progress_text.setMinimumWidth(0)
        self.task_progress = QProgressBar()
        self.task_progress.setFixedWidth(160)
        self.task_progress.setFixedHeight(16)
        self.task_progress.hide()
        # self.statusBar().addPermanentWidget(self.task_progress_text, 1)
        # self.statusBar().addPermanentWidget(self.task_progress)
        # 2026-10-13：本次修改原因：连接状态移至底部信息栏，顶部只保留统计和获取商品操作。
        # self.statusBar().addPermanentWidget(self.receiver_badge)
        # 2026-10-13：本次修改原因：撤下底部常驻状态栏；仅在操作时于当前页面上方显示反馈和真实进度。
        self.statusBar().hide()
        self.receiver_badge.setParent(self)
        self.receiver_badge.hide()
        self.feedback_row = QWidget()
        feedback_layout = QHBoxLayout(self.feedback_row)
        feedback_layout.setContentsMargins(4, 0, 4, 0)
        feedback_layout.setSpacing(12)
        self.task_progress_text.setWordWrap(True)
        feedback_layout.addWidget(self.task_progress_text, 1)
        feedback_layout.addWidget(self.task_progress)
        self.workspace_layout.insertWidget(0, self.feedback_row)
        self.feedback_row.hide()
        self.feedback_timer = QTimer(self)
        self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(lambda: self.feedback_row.setVisible(bool(self._tasks)))
        self.statusBar().messageChanged.connect(self.show_operation_feedback)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(300)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh()
        # 2026-10-13：本次修改原因：键盘入口点击现有按钮，仍遵守现有禁用及二次确认。
        self.shortcuts = []
        for sequence, callback, owner in (("Ctrl+F", self.focus_search, self),
                                           ("F2", self.edit_button.click, self.product_table),
                                           ("Delete", self.delete_products_button.click, self.product_table)):
            shortcut = QShortcut(QKeySequence(sequence), owner)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut if owner is self else Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)

    # 2026-10-13：本次修改原因：兼容现有状态消息回调，反馈只在任务期间或操作后短暂占用页面空间。
    def show_operation_feedback(self, text: str) -> None:
        if text:
            self.task_progress_text.setText(text)
            self.feedback_row.show()
            if self._tasks:
                self.feedback_timer.stop()
            else:
                self.feedback_timer.start(8000)
        elif not self._tasks:
            self.feedback_row.hide()

    def focus_search(self):
        # search = self.search if self.stack.currentIndex() == 0 else (
        #     self.erp_records_page.search if self.stack.currentIndex() == 2 else None)
        # 2026-10-13：本次修改原因：Ctrl+F 只聚焦当前日志标签的原搜索框，避免跳入设置或隐藏页。
        search = self.search if self.stack.currentIndex() == self.PAGE_PRODUCTS else (
            self.erp_records_page.search if self.stack.currentIndex() == self.PAGE_LOGS
            and self.logs_page.is_transfer_tab() else None)
        # 2026-10-13：本次修改原因：新方案库沿用 Ctrl+F 搜索习惯。
        if self.stack.currentIndex() == self.PAGE_REFERENCES:
            search = self.reference_analysis_page.search
        if search:
            # 2026-10-13：本次修改原因：默认收起筛选后，Ctrl+F 先展开再聚焦，搜索入口保持可用。
            if search is self.search:
                self.product_filter_panel.set_expanded(True)
            search.setFocus()
            search.selectAll()

    def _sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        # sidebar.setFixedWidth(210)
        # 2026-10-13：本次修改原因：保证侧栏可调，保留品牌和完整导航文字。
        sidebar.setMinimumWidth(190)
        sidebar.setMaximumWidth(320)
        layout = QVBoxLayout(sidebar)
        # layout.setContentsMargins(18, 28, 18, 24)
        # 2026-10-13：本次修改原因：浅色侧栏收紧品牌与导航之间的空间，撤下无操作用途的说明文字。
        layout.setContentsMargins(14, 14, 14, 16)
        layout.setSpacing(8)
        brand = QHBoxLayout()
        badge = label("BD", "brandBadge")
        badge.setFixedSize(38, 38)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(badge)
        brand.addWidget(label("BeadDiff", "brand"))
        layout.addLayout(brand)
        # layout.addSpacing(34)
        # layout.addWidget(label("商品运营", "navCaption"))
        # layout.addSpacing(6)
        layout.addSpacing(20)
        self.navigation = QButtonGroup(self)
        # for index, (text, symbol) in enumerate([
            # 2026-10-11：本次修改原因：统一设置入口容纳插件连接与模型管理。
            # 2026-10-12：本次修改原因：导航按加工、获取记录、回传结果、设置和帮助排列。
            # ("商品加工", "products"), ("采集记录", "capture"), ("回传记录", "export"),
            # ("设置", "settings"), ("操作帮助", "capture"),
            # 2026-10-13：本次修改原因：将历史查询合成日志记录，帮助放入设置，减少侧栏入口数量。
        #     ("商品加工", "products"), ("日志记录", "capture"), ("设置", "settings"),
            # 2026-10-13：本次修改原因：回收站在侧栏始终可发现，补齐选择恢复及永久删除操作链路。
        #     ("回收站", "capture"),
        # ]):
        # 2026-10-13：本次修改原因：爆款参考与商品加工相邻，日志及配置保持集中，使用稳定页面编号。
        for index, text, symbol in [
            (self.PAGE_PRODUCTS, "商品加工", "products"),
            (self.PAGE_REFERENCES, "爆款分析", "analysis"),
            (self.PAGE_TRACKING, "包裹追踪", "tracking"),
            (self.PAGE_HOSTING, "图床", "hosting"),
        ]:
            item = button(text)
            item.setObjectName("navButton")
            item.setCheckable(True)
            # item.setIcon(icon(symbol, "#a2c4c1"))
            # 2026-10-13：本次修改原因：导航图标跟随浅/深主题，避免浅侧栏上沿用过浅的图标。
            item.setIcon(icon(symbol, theme_tokens()["muted"]))
            item.setProperty("navSymbol", symbol)
            self.navigation.addButton(item, index)
            layout.addWidget(item)
            if index == 0:
                item.setChecked(True)
        self.navigation.idClicked.connect(self.navigate)
        layout.addStretch()
        # 2026-10-14：本次修改原因：日志、设置、回收站属于低频系统入口，移到底部水平排列并仅保留图标。
        footer = QHBoxLayout()
        footer.setSpacing(4)
        for index, text, symbol in [
            (self.PAGE_LOGS, "日志记录", "logs"),
            (self.PAGE_SETTINGS, "设置", "settings"),
            (self.PAGE_RECYCLE, "回收站", "trash"),
        ]:
            item = button("")
            item.setObjectName("navButton")
            item.setCheckable(True)
            item.setProperty("iconOnly", True)
            item.setProperty("navSymbol", symbol)
            item.setToolTip(text)
            item.setAccessibleName(text)
            item.setFixedSize(42, 38)
            item.setIcon(icon(symbol, theme_tokens()["muted"]))
            self.navigation.addButton(item, index)
            footer.addWidget(item)
        footer.addStretch()
        layout.addLayout(footer)
        # layout.addWidget(label("LOCAL WORKSPACE", "navCaption"))
        # layout.addWidget(label("v0.1.0  /  本机桌面版", "navCaption"))
        # 2026-10-12：本次修改原因：统一商品加工入口、来源和反馈链路。
        # layout.addWidget(label("v0.2.0  /  本机桌面版", "navCaption"))
        # 2026-10-13：本次修改原因：撤下侧栏底部环境/版本说明，保留导航与品牌。
        return sidebar

    # 2026-10-13：本次修改原因：切换主题时只更新导航图标配色，窗口状态仍由无文字顶栏处理。
    def changeEvent(self, event):
        super().changeEvent(event)
        # 此处使用事件枚举，不改变页面、数据或主题配置。
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange) and hasattr(self, "navigation"):
            for item in self.navigation.buttons():
                item.setIcon(icon(item.property("navSymbol"), theme_tokens()["muted"]))

    def navigate(self, index: int) -> None:
        # 2026-10-13：本次修改原因：方案未保存或分析中切页也有保护，不丢弃用户输入。
        if self.stack.currentIndex() == self.PAGE_REFERENCES and index != self.PAGE_REFERENCES:
            if not self.reference_analysis_page.can_leave():
                self.navigation.button(self.PAGE_REFERENCES).setChecked(True)
                return
        # 2026-10-13：本次修改原因：切换导航同样检查未保存内容和 AI 任务，避免页面式编辑绕过原关闭保护。
        editor = getattr(self, "product_editor", None)
        if editor is not None and not editor.reject():
            self.navigation.button(self.PAGE_PRODUCTS).setChecked(True)
            return
        self.stack.setCurrentIndex(index)
        self.navigation.button(index).setChecked(True)
        # if index == 3:
        if index == self.PAGE_SETTINGS:
            self.update_connection()
            # 2026-10-11：本次修改原因：编辑窗口修改模型后，设置页展示最新配置。
            self.model_settings.refresh()
        # 2026-10-13：本次修改原因：进入回收站即展示最新已移除条目，不仅提供“全部恢复”。
        # if index == 5:
        if index == self.PAGE_RECYCLE:
            self.recycle_bin_page.refresh()
        # 2026-10-13：本次修改原因：进入方案库刷新列表与模型配置，不重置编辑草稿。
        if index == self.PAGE_REFERENCES:
            self.reference_analysis_page.refresh()
        # 2026-10-14：本次修改原因：每次进入图床页展示最新同步结果与手动上传记录。
        if index == self.PAGE_HOSTING:
            self.image_hosting_page.refresh()

    def _heading(self, title: str, subtitle: str) -> tuple[QHBoxLayout, QVBoxLayout]:
        row = QHBoxLayout()
        texts = QVBoxLayout()
        texts.setSpacing(7)
        texts.addWidget(label(title, "pageTitle"))
        texts.addWidget(label(subtitle, "muted"))
        row.addLayout(texts)
        row.addStretch()
        return row, texts

    def _products_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        # layout.setSpacing(18)
        # 2026-10-13：本次修改原因：移除重复页面标题后，顶部工具与内容保持紧凑留白。
        layout.setSpacing(12)
        # heading, _ = self._heading("商品工作台", "采集素材集中管理，完善商品后交给妙手导入")
        # 2026-10-12：本次修改原因：增加 ERP 数据入口后把建档操作移至独立一行，避免标题区挤压。
        # heading, _ = self._heading("商品工作台", "管理采集与上传商品，编辑后回传妙手公共采集箱")
        # 2026-10-12：本次修改原因：统一商品加工入口、来源和反馈链路。
        # heading, _ = self._heading("商品加工", "获取商品 → 手动 / AI 加工 → 保存并审核 → 传回 ERP")
        # 2026-10-12：本次修改原因：标题区容纳四个紧凑统计卡片，把垂直空间还给商品列表。
        # heading, texts = self._heading("商品加工", "获取 → 加工 → 审核 → 回传")
        # texts.itemAt(1).widget().setWordWrap(True)
        # 2026-10-13：本次修改原因：标题、横向统计和高频入口共用一行，减少工作台顶部占用高度。
        # heading = QHBoxLayout()
        # 2026-10-13：本次修改原因：较窄窗口或统计位数增多时保持顶部一行，通过横向滚动确保所有入口可达。
        heading_body = QWidget()
        heading = QHBoxLayout(heading_body)
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(10)
        # title = label("商品加工", "pageTitle")
        # title.setToolTip("获取 → 加工 → 审核 → 回传")
        # heading.addWidget(title)
        # 2026-10-13：本次修改原因：导航已说明页面归属，工具栏不再重复大标题。
        heading.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.receiver_badge = label("正在初始化", "statusBadge")
        # heading.addWidget(self.receiver_badge)
        # heading.addSpacing(8)
        # heading.addWidget(button("刷新", self.refresh))
        # 2026-10-11：本次修改原因：白底图路线直接建草稿并进入共用商品编辑页。
        # heading.addWidget(button("上传白底图建商品", self.create_from_photos, symbol="import"))
        self.import_button = button("导入采集文件", self.import_files, primary=True, symbol="import")
        # 2026-10-13：本次修改原因：保留原按钮和任务禁用状态，菜单通过同一个按钮调用文件导入。
        self.import_button.setParent(page)
        self.import_button.hide()
        # heading.addWidget(self.import_button)
        # layout.addLayout(heading)
        heading_scroll = QScrollArea()
        heading_scroll.setWidgetResizable(True)
        heading_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        heading_scroll.setMinimumWidth(0)
        # heading_scroll.setFixedHeight(max(64, title.fontMetrics().height() + 32))
        # 2026-10-13：本次修改原因：顶部只占一行操作高度，统计不再随容器被拉高。
        heading_scroll.setFixedHeight(max(52, self.fontMetrics().height() + 32))
        heading_scroll.setWidget(heading_body)
        layout.addWidget(heading_scroll)
        # 2026-10-12：本次修改原因：ERP 查询导入作为主要建档入口，另外两条本机素材路线仍可直接操作。
        # intake = QHBoxLayout()
        # self.erp_import_button = button("从妙手采集箱导入", self.import_miaoshou, primary=True, symbol="import")
        # 2026-10-12：本次修改原因：统一商品加工入口、来源和反馈链路。
        self.erp_import_button = button("同步妙手采集箱", self.import_miaoshou, primary=True, symbol="import")
        # intake.addWidget(self.erp_import_button)
        # intake.addWidget(button("上传白底图建商品", self.create_from_photos, symbol="import"))
        # intake.addWidget(self.import_button)
        # intake.addStretch()
        # 2026-10-12：本次修改原因：连接状态跟随获取入口，避免标题和统计卡片相互挤压。
        # intake.addWidget(self.receiver_badge)
        # 2026-10-12：本次修改原因：主操作区可直接查看当前路线及简明帮助。
        # intake.addWidget(button("采集路线设置", lambda: self.open_settings(0)))
        # intake.addWidget(button("操作帮助", lambda: self.navigate(4)))
        # layout.addLayout(intake)
        # self.operation_feedback = label("先获取商品，再双击加工。保存、审核和回传是独立步骤。", "hint", True)
        # layout.addWidget(self.operation_feedback)
        # 2026-10-13：本次修改原因：取消常驻流程解释，操作后的动态结果仍通过底部状态栏反馈。
        self.operation_feedback = StatusFeedback(self)
        metrics = QHBoxLayout()
        # metrics.setSpacing(14)
        # 2026-10-12：本次修改原因：紧凑统计卡片横向放入上部中间区域。
        metrics.setSpacing(8)
        self.count_labels = {}
        for key, title, hint in [
            ("全部", "商品总数", "采集素材沉淀为商品"), ("待完善", "待完善", "补充字段、规格及售价"),
            # 2026-10-12：本次修改原因：审核提示改为接口回传流程。
            ("待审核", "待审核", "核对当前版本后审核"), ("已审核", "已审核", "检查回传条件后传回 ERP"),
        ]:
            # frame, contents = card()
            # contents.setSpacing(5)
            # contents.setContentsMargins(12, 8, 12, 8)
            # frame.setMinimumWidth(84)
            # 2026-10-13：本次修改原因：统计改为标题和数字并排的紧凑标签，统计口径及更新方法保持原样。
            frame = QFrame()
            frame.setObjectName("metricChip")
            contents = QHBoxLayout(frame)
            contents.setSpacing(6)
            contents.setContentsMargins(8, 6, 8, 6)
            frame.setToolTip(hint)
            contents.addWidget(label(title, "hint"))
            # value = label("0", "count")
            value = label("0", "metricValue")
            contents.addWidget(value)
            # contents.addWidget(label(hint, "muted"))
            self.count_labels[key] = value
            # metrics.addWidget(frame)
            # 2026-10-13：本次修改原因：统计按自身内容高度居中，避免变成过高的装饰卡片。
            metrics.addWidget(frame, 0, Qt.AlignmentFlag.AlignVCenter)
        # layout.addLayout(metrics)
        # 2026-10-12：本次修改原因：复用标题中间留白，不再为统计独占整行。
        # heading.insertLayout(1, metrics, 1)
        # 2026-10-13：本次修改原因：用更多菜单承载原有低频入口，保留全部回调和任务状态。
        heading.addLayout(metrics)
        heading.addStretch(1)
        self.erp_import_button.setProperty("compact", True)
        # heading.addWidget(self.erp_import_button)
        # upload = button("上传白底图", self.create_from_photos, symbol="import")
        # upload.setToolTip("上传白底图建商品，进入商品编辑与 AI 加工。")
        # upload.setProperty("compact", True)
        # heading.addWidget(upload)
        # more = QToolButton()
        # more.setText("更多")
        # more.setProperty("compact", True)
        # menu = QMenu(more)
        # self.import_file_action = menu.addAction(icon("import"), "导入采集文件")
        # self.import_file_action.triggered.connect(self.import_button.click)
        # menu.aboutToShow.connect(lambda: self.import_file_action.setEnabled(self.import_button.isEnabled()))
        # menu.addSeparator()
        # menu.addAction("刷新").triggered.connect(self.refresh)
        # menu.addAction("采集路线设置").triggered.connect(lambda: self.open_settings(0))
        # menu.addAction("操作帮助").triggered.connect(lambda: self.navigate(4))
        # 2026-10-13：本次修改原因：保留快捷帮助入口，跳转到设置中的同一个帮助页面。
        # menu.addAction("操作帮助").triggered.connect(self.show_help)
        # more.setMenu(menu)
        # more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # heading.addWidget(more)
        # 2026-10-13：本次修改原因：撤下顶部更多及重复刷新；设置/帮助仍从侧栏设置进入，导入文件迁至采集切换区。
        self.product_upload_button = button("上传白底图", self.create_from_photos, primary=True, symbol="import")
        self.product_upload_button.setProperty("compact", True)
        self.product_upload_button.setToolTip("选择白底图创建商品，继续编辑或 AI 加工。")
        # splitter = QSplitter(Qt.Orientation.Horizontal)
        # splitter.setChildrenCollapsible(False)
        # 2026-10-13：本次修改原因：去掉右侧商品速览，将全部可用宽度交给商品列表。
        # catalog, catalog_layout = card()
        # 2026-10-13：本次修改原因：移除分区外的重复边框，筛选和列表独立成块，以间距区分。
        catalog = QWidget()
        catalog_layout = QVBoxLayout(catalog)
        # catalog_layout.setContentsMargins(0, 0, 0, 10)
        # 2026-10-13：本次修改原因：筛选可收起，商品表格仍保持全宽；批量操作不与筛选一起隐藏。
        catalog_outer = catalog_layout
        # catalog_outer.setContentsMargins(8, 8, 8, 8)
        catalog_outer.setContentsMargins(0, 0, 0, 0)
        filter_area = QWidget()
        # filter_layout = QVBoxLayout(filter_area)
        # 2026-10-13：本次修改原因：状态、搜索、来源及列设置合并成一行；窄窗口只横向滚动，不换行或挤压输入框。
        filter_layout = QHBoxLayout(filter_area)
        filter_layout.setSpacing(8)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        table_area = QWidget()
        catalog_layout = QVBoxLayout(table_area)
        catalog_layout.setContentsMargins(0, 0, 0, 0)
        catalog_layout.setSpacing(8)
        self.catalog_splitter = PersistentSplitter(Qt.Orientation.Vertical, "ui/products/filter_list_splitter_v1", [120, 640], catalog)
        # 2026-10-13：本次修改原因：分隔条常态留白，鼠标经过再显示拖拽反馈。
        self.catalog_splitter.setHandleWidth(12)
        # self.catalog_splitter.addWidget(Panel("商品筛选", filter_area))
        filter_scroll = QScrollArea()
        filter_scroll.setWidgetResizable(True)
        filter_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        filter_scroll.setMinimumWidth(0)
        filter_scroll.setMinimumHeight(max(58, self.fontMetrics().height() + 38))
        filter_scroll.setWidget(filter_area)
        self.product_filter_panel = Panel("商品筛选", filter_scroll)
        self.catalog_splitter.addWidget(self.product_filter_panel)
        # self.catalog_splitter.addWidget(Panel("商品列表", table_area, collapsible=False))
        # 2026-10-13：本次修改原因：总量紧邻列表标题显示，不占用表格底部空间。
        self.product_list_panel = Panel("商品列表", table_area, collapsible=False)
        self.product_summary = label("共 0 个商品", "muted")
        # self.product_list_panel.heading_layout.insertWidget(1, self.product_summary)
        # 2026-10-13：本次修改原因：来源切换和对应获取入口放在商品列表左上角，避免顶部多个并列按钮。
        self.product_list_panel.title_label.hide()
        source_switch = QFrame()
        source_switch.setObjectName("sourceSwitch")
        switch_layout = QHBoxLayout(source_switch)
        switch_layout.setContentsMargins(3, 3, 3, 3)
        switch_layout.setSpacing(2)
        self.product_sources = QButtonGroup(self)
        for index, text in enumerate(("采集商品", "白底图商品")):
            tab = button(text)
            tab.setObjectName("sourceTab")
            tab.setCheckable(True)
            tab.setChecked(index == 0)
            self.product_sources.addButton(tab, index)
            switch_layout.addWidget(tab)
        self.product_sources.idClicked.connect(self.change_product_source)
        self.product_list_panel.heading_layout.insertWidget(0, source_switch)
        self.product_list_panel.heading_layout.insertWidget(1, self.erp_import_button)
        self.product_list_panel.heading_layout.insertWidget(2, self.import_button)
        self.product_list_panel.heading_layout.insertWidget(3, self.product_upload_button)
        self.product_list_panel.heading_layout.addWidget(self.product_summary)
        self.update_product_intake()
        self.catalog_splitter.addWidget(self.product_list_panel)
        catalog_outer.addWidget(self.catalog_splitter, 1)
        filter_row = QHBoxLayout()
        # filter_row.setContentsMargins(16, 14, 16, 0)
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(2)
        self.filters = QButtonGroup(self)
        for index, title in enumerate(["全部", "待完善", "待审核", "已审核"]):
            item = button(title)
            item.setObjectName("filterTab")
            item.setCheckable(True)
            item.setChecked(index == 0)
            self.filters.addButton(item, index)
            filter_row.addWidget(item)
        self.filters.idClicked.connect(self.filter_changed)
        # filter_row.addStretch()
        # catalog_layout.addLayout(filter_row)
        filter_layout.addLayout(filter_row)
        # search_row = QHBoxLayout()
        # search_row.setContentsMargins(18, 0, 18, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索商品名称 / 商品编号 / SKU")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(190)
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.populate_products)
        # search_row.addWidget(self.search, 1)
        filter_layout.addWidget(self.search, 1)
        # 2026-10-12：本次修改原因：获取方式和货源平台分别筛选。
        self.acquisition_filter = QComboBox()
        self.acquisition_filter.addItem("全部获取方式", "")
        for route, caption in ROUTE_LABELS.items():
            self.acquisition_filter.addItem(caption, route)
        # self.acquisition_filter.currentIndexChanged.connect(self.populate_products)
        # 2026-10-13：本次修改原因：原获取方式筛选与新的来源标签联动，防止两个筛选互相冲突。
        self.acquisition_filter.currentIndexChanged.connect(self.acquisition_filter_changed)
        # search_row.addWidget(self.acquisition_filter)
        filter_layout.addWidget(self.acquisition_filter)
        self.source_filter = QComboBox()
        # self.source_filter.addItems(["全部来源", "temu"])
        # 2026-10-12：本次修改原因：统一商品加工入口、来源和反馈链路。
        self.source_filter.addItems(["全部平台", "temu"])
        self.source_filter.currentTextChanged.connect(self.populate_products)
        # search_row.addWidget(self.source_filter)
        filter_layout.addWidget(self.source_filter)
        # catalog_layout.addLayout(search_row)
        # filter_layout.addLayout(search_row)
        selection = QHBoxLayout()
        selection.setContentsMargins(18, 0, 18, 0)
        self.select_all = QCheckBox("本页全选")
        self.select_all.toggled.connect(self.check_all)
        selection.addWidget(self.select_all)
        self.selected_label = label("已选 0 项", "muted")
        # 2026-10-13：本次修改原因：说明视觉选行与批量勾选的原有区别，避免用户误判回传范围。
        self.selected_label.setToolTip("批量审核和回传以左侧复选框为准；行高亮用于查看或编辑当前商品。")
        selection.addWidget(self.selected_label)
        # selection.addWidget(button("清空", self.clear_selection))
        # 2026-10-12：本次修改原因：明确取消勾选与删除商品的区别，移除支持回收站恢复。
        selection.addWidget(button("取消勾选", self.clear_selection))
        self.delete_products_button = button("移除所选", self.remove_selected_products)
        selection.addWidget(self.delete_products_button)
        # self.restore_products_button = button("恢复回收站", lambda: self.restore_local_list("products"))
        # 2026-10-13：本次修改原因：按钮打开可浏览回收站，用户选择具体数据再恢复。
        self.restore_products_button = button("回收站", lambda: self.open_recycle_bin("products"))
        selection.addWidget(self.restore_products_button)
        # 2026-10-12：本次修改原因：清空按钮明确仅作用于当前筛选结果。
        selection.addWidget(button("清空当前结果", self.clear_visible_products))
        selection.addStretch()
        self.approve_button = button("批量审核", self.approve_selected)
        selection.addWidget(self.approve_button)
        catalog_layout.addLayout(selection)
        # 2026-10-11：本次修改原因：批量回传入口显示当前设置方式，并允许查看可追溯的回传记录。
        erp_actions = QHBoxLayout()
        erp_actions.setContentsMargins(18, 0, 18, 0)
        # 2026-10-13：本次修改原因：速览主操作迁移至列表工具栏，保留键盘选行后的编辑与单商品操作入口。
        self.edit_button = button("编辑 / AI 加工", self.edit_current)
        erp_actions.addWidget(self.edit_button)
        self.product_more_button = button("当前商品 · 更多", self.show_selected_product_menu)
        erp_actions.addWidget(self.product_more_button)
        self.erp_mode_hint = label("", "muted")
        erp_actions.addWidget(self.erp_mode_hint)
        erp_actions.addStretch()
        erp_actions.addWidget(button("回传记录", self.show_erp_records))
        self.erp_button = button("传回妙手 ERP", self.transfer_selected, primary=True, symbol="export")
        erp_actions.addWidget(self.erp_button)
        catalog_layout.addLayout(erp_actions)
        # self.product_table = table(["", "商品 / 主编号", "来源", "SKU", "状态", "更新"])
        # for col, width in enumerate([42, 310, 90, 60, 90, 105]):
        #     self.product_table.setColumnWidth(col, width)
        # 2026-10-11：本次修改原因：增加内容修改及当前内容是否已传回 ERP 两个独立状态列。
        # self.product_table = table(["", "商品 / 主编号", "来源", "SKU", "状态", "修改", "传回 ERP", "更新"])
        # for col, width in enumerate([42, 270, 70, 50, 78, 72, 90, 100]):
        # 2026-10-12：本次修改原因：统一商品加工入口、来源和反馈链路。
        # self.product_table = table(["", "商品 / 主编号", "获取方式", "平台", "SKU", "审核状态", "修改状态", "传回 ERP", "更新时间"])
        # 2026-10-13：本次修改原因：参考采集箱列表展示主图、平台/站点、SKU 售价和辅助字段，列可按需选择。
        self.product_table = ProductTable()
        configure_table(self.product_table, editable=False, multiline=True)
        # 2026-10-13：本次修改原因：列表所在分区已有圆角边框，内层表格不重复描边。
        self.product_table.setProperty("embeddedTable", True)
        # for col, width in enumerate([42, 260, 90, 65, 45, 82, 75, 85, 100]):
        for col, (_key, _title, width, _visible) in enumerate(PRODUCT_COLUMNS):
            self.product_table.setColumnWidth(col, width)
        self.product_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # self.product_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # 2026-10-13：本次修改原因：支持视觉多行选择；批量审核/回传仍只使用勾选 ID。
        self.product_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.product_table.verticalHeader().hide()
        self.product_table.verticalHeader().setDefaultSectionSize(max(78, self.product_table.fontMetrics().height() * 2 + 24))
        self.product_table.horizontalHeader().setStretchLastSection(False)
        self.product_table.horizontalHeader().setMinimumSectionSize(42)
        # self.product_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.product_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.product_table.horizontalHeader().setSectionResizeMode(PRODUCT_COL["selected"], QHeaderView.ResizeMode.Fixed)
        self.product_table.horizontalHeader().setSectionResizeMode(PRODUCT_COL["actions"], QHeaderView.ResizeMode.Fixed)
        # 2026-10-13：本次修改原因：绘制状态标签；固定列集合与行内业务入口保持不变。
        self.product_table.setItemDelegate(ProductRowDelegate(self.product_table))
        for key in ("review", "modified", "transfer"):
            self.product_table.setItemDelegateForColumn(PRODUCT_COL[key], StatusBadgeDelegate(self.product_table))
        self.product_table.setSortingEnabled(True)
        self.product_table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.product_table.restore_widths()
        self.product_thumbnails = ProductThumbnailDelegate(self.product_table, self.network)
        self.product_table.setItemDelegateForColumn(PRODUCT_COL["image"], self.product_thumbnails)
        self.product_row_actions = ProductActionsDelegate(self.product_table)
        self.product_table.setItemDelegateForColumn(PRODUCT_COL["actions"], self.product_row_actions)
        self.product_row_actions.editRequested.connect(self.edit_product_row)
        self.product_row_actions.moreRequested.connect(self.show_product_menu)
        self.product_column_settings = QSettings("BeadDiff", "BeadDiff")
        self.product_columns_menu = QMenu(self)
        self._configure_product_columns()
        self.product_column_button = QToolButton()
        self.product_column_button.setText("显示列")
        self.product_column_button.setMenu(self.product_columns_menu)
        self.product_column_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # filter_row.addWidget(self.product_column_button)
        # 2026-10-13：本次修改原因：显示列放在筛选行最右侧，与同一行的来源筛选一起呈现。
        filter_layout.addWidget(self.product_column_button)
        self.product_table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.product_table.horizontalHeader().customContextMenuRequested.connect(
            lambda point: self.product_columns_menu.exec(self.product_table.horizontalHeader().mapToGlobal(point)))
        self.product_table.itemChanged.connect(self.check_changed)
        self.product_table.itemSelectionChanged.connect(self.product_selected)
        # self.product_table.itemDoubleClicked.connect(lambda _item: self.edit_current())
        self.product_table.itemDoubleClicked.connect(lambda item: self.edit_product_row(item.data(Qt.ItemDataRole.UserRole))
            if item.column() not in {PRODUCT_COL["selected"], PRODUCT_COL["actions"]} else None)
        catalog_layout.addWidget(self.product_table, 1)
        # self.product_empty = label("还没有商品\n导入 pfti 请求 JSON / HAR，或在连接设置中配置插件转发。", "empty", True)
        # 2026-10-11：本次修改原因：为空商品库提供采集与上传两条可操作路线。
        # self.product_empty = label("还没有商品\n导入采集文件、配置插件同步，或上传白底图创建商品。", "empty", True)
        # 2026-10-12：本次修改原因：统一商品加工入口、来源和反馈链路。
        self.product_empty = label("还没有商品\n点击“同步妙手采集箱”或“上传白底图建商品”开始。", "empty", True)
        self.product_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        catalog_layout.addWidget(self.product_empty)
        # self.product_summary = label("共 0 个商品", "muted")
        # self.product_summary.setContentsMargins(18, 3, 18, 0)
        # catalog_layout.addWidget(self.product_summary)
        # splitter.addWidget(catalog)
        # splitter.addWidget(self._inspector())
        # splitter.setSizes([850, 300])
        # layout.addWidget(splitter, 1)
        layout.addWidget(catalog, 1)
        return page

    # 2026-10-13：本次修改原因：速览字段改为可选展示列，显示偏好仅保存在本机，下次启动自动读取。
    def _configure_product_columns(self) -> None:
        defaults = [key for key, _title, _width, visible in PRODUCT_COLUMNS if visible]
        stored = self.product_column_settings.value("products/visible_columns_v1", defaults)
        visible = set(stored if isinstance(stored, list) else defaults)
        self.product_column_actions = {}
        for key, title, _width, _default in PRODUCT_COLUMNS:
            column = PRODUCT_COL[key]
            # if key in {"selected", "product", "actions"}:
            # 2026-10-13：本次修改原因：撤下重复行内操作列，顶部编辑/更多及双击入口保留，旧列索引不变。
            if key == "actions":
                self.product_table.setColumnHidden(column, True)
                continue
            if key in {"selected", "product"}:
                self.product_table.setColumnHidden(column, False)
                continue
            action = self.product_columns_menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(key in visible)
            self.product_table.setColumnHidden(column, key not in visible)
            action.toggled.connect(lambda checked, key=key: self.toggle_product_column(key, checked))
            self.product_column_actions[key] = action
        self.product_columns_menu.addSeparator()
        self.product_columns_menu.addAction("恢复默认列", self.reset_product_columns)

    def toggle_product_column(self, key: str, visible: bool) -> None:
        self.product_table.setColumnHidden(PRODUCT_COL[key], not visible)
        current = [key for key, *_rest in PRODUCT_COLUMNS if not self.product_table.isColumnHidden(PRODUCT_COL[key])]
        self.product_column_settings.setValue("products/visible_columns_v1", current)
        self.product_table.fit_title()

    def reset_product_columns(self) -> None:
        for key, _title, width, visible in PRODUCT_COLUMNS:
            self.product_table.setColumnWidth(PRODUCT_COL[key], width)
            if key in self.product_column_actions:
                self.product_column_actions[key].setChecked(visible)
        self.product_table.fit_title()

    # 2026-10-13：本次修改原因：原速览问题清单迁移到审核/检查提示列及行内菜单，不丢失完整提示。
    @staticmethod
    def product_notice(product: Product, issues: list[str] | None = None) -> str:
        issues = product.review_issues() if issues is None else issues
        text = "待完善\n" + "\n".join("• " + issue for issue in issues) if issues else "必填信息已完善，请人工核对来源、售价和规格。"
        if product.warnings:
            text += "\n\n采集提示\n" + "\n".join("• " + warning.replace("实际导出售价", "实际售价") for warning in product.warnings)
        count = local_picture_count(product)
        if count:
            # text += f"\n\n素材待处理\n• {count} 张本机图片；写回涉及这些图片时需先替换为公网链接。"
            # 2026-10-14：本次修改原因：本机已采用图片在同步时自动托管，检查提示与真实操作一致。
            text += f"\n\n本机素材\n• {count} 张图片；同步 ERP 时自动上传图床并替换提交链接。"
        return text

    def show_product_notice(self) -> None:
        product = self.current_product
        if product:
            self.text_dialog("商品检查与提示", f"{product.title or product.main_code}\n当前版本 v{product.revision}\n\n" + self.product_notice(product))

    # 2026-10-13：本次修改原因：行内按钮冻结商品 ID，打开菜单后即使选择变化也只操作原商品。
    def invoke_product_action(self, product_id: str, callback) -> None:
        if self._tasks or self.ai_hub.busy:
            return
        product = next((item for item in self._products if item.id == product_id), None)
        if not product:
            self.operation_feedback.setText("商品已移除，请刷新列表后操作。")
            return
        for row in range(self.product_table.rowCount()):
            if self.product_table.item(row, PRODUCT_COL["selected"]).data(Qt.ItemDataRole.UserRole) == product_id:
                self.product_table.selectRow(row)
                break
        self.current_product = product
        callback()

    def edit_product_row(self, product_id: str) -> None:
        self.invoke_product_action(product_id, self.edit_current)

    def show_selected_product_menu(self) -> None:
        if self.current_product:
            self.show_product_menu(self.current_product.id,
                self.product_more_button.mapToGlobal(self.product_more_button.rect().bottomLeft()))

    def show_product_menu(self, product_id: str, position) -> None:
        if self._tasks or self.ai_hub.busy:
            return
        product = next((item for item in self._products if item.id == product_id), None)
        if not product:
            return
        menu = QMenu(self)
        scope = menu.addAction("仅操作此商品（不改变批量勾选）")
        scope.setEnabled(False)

        def add(text, callback, enabled=True):
            action = menu.addAction(text)
            action.setEnabled(enabled)
            action.triggered.connect(lambda _checked=False: self.invoke_product_action(product_id, callback))

        add("编辑 / AI 加工", self.edit_current)
        add("传回妙手 ERP · 此商品", self.transfer_current)
        add("查看检查与采集提示", self.show_product_notice)
        menu.addSeparator()
        add("打开货源页面", self.open_source, valid_url(product.source_url))
        add("查看妙手导入原始详情", self.show_miaoshou_snapshot, bool(product.erp_remote_snapshot))
        add("关联妙手原商品", self.bind_erp_current, not product.erp_imported)
        unknown = any(row["product_id"] == product_id and row["state"] == "unknown" for row in self._erp_records)
        add("核对未知回传（只读）", self.reconcile_erp_current, unknown)
        add("查看回传记录", self.show_erp_records)
        menu.exec(position)

    # def _inspector(self) -> QFrame:
    #     frame, contents = card()
    #     frame.setMinimumWidth(265)
    #     frame.setMaximumWidth(365)
    #     contents.addWidget(label("商品速览", "sectionTitle"))
    #     self.preview = ImagePreview(self.network, 190)
    #     contents.addWidget(self.preview)
    #     self.inspector_title = label("选择商品查看详情", "sectionTitle", True)
    #     contents.addWidget(self.inspector_title)
    #     self.inspector_meta = label("商品信息与待完善项将在此显示", "muted", True)
    #     contents.addWidget(self.inspector_meta)
    #     self.inspector_status = label("", "hint", True)
    #     contents.addWidget(self.inspector_status)
    #     scroll = QScrollArea()
    #     scroll.setWidgetResizable(True)
    #     self.inspector_issues = label("从采集记录可查看原始材料及解析结果。", "hint", True)
    #     self.inspector_issues.setAlignment(Qt.AlignmentFlag.AlignTop)
    #     scroll.setWidget(self.inspector_issues)
    #     contents.addWidget(scroll, 1)
    #     # self.edit_button = button("编辑商品与 SKU", self.edit_current, primary=True)
    #     # 2026-10-12：本次修改原因：统一商品加工入口、来源和反馈链路。
    #     self.edit_button = button("编辑 / AI 加工", self.edit_current, primary=True)
    #     self.source_button = button("打开货源页面", self.open_source)
    #     contents.addWidget(self.edit_button)
    #     # 2026-10-11：本次修改原因：速览提供当前单商品回传入口，与勾选批量操作共用业务逻辑。
    #     self.erp_current_button = button("传回妙手 ERP", self.transfer_current, symbol="export")
    #     contents.addWidget(self.erp_current_button)
    #     # 2026-10-11：本次修改原因：更新前先查询并人工确认原商品，避免误用平台商品 ID。
    #     self.erp_binding_hint = label("", "hint", True)
    #     contents.addWidget(self.erp_binding_hint)
    #     self.erp_bind_button = button("关联妙手原商品", self.bind_erp_current)
    #     contents.addWidget(self.erp_bind_button)
    #     # 2026-10-11：本次修改原因：超时后查询实际详情，不能直接重发新增或手动勾选已传。
    #     self.erp_reconcile_button = button("核对未知回传（只读）", self.reconcile_erp_current)
    #     contents.addWidget(self.erp_reconcile_button)
    #     # 2026-10-12：本次修改原因：本机商品提供留存的完整 ERP 导入详情查看入口，便于比较未展示的规格/附件字段。
    #     self.erp_snapshot_button = button("查看妙手导入原始详情", self.show_miaoshou_snapshot)
    #     contents.addWidget(self.erp_snapshot_button)
    #     contents.addWidget(self.source_button)
    #     return frame

    # 2026-10-13：本次修改原因：按用户要求移除商品速览，旧布局注释保留；字段和操作已迁移到商品列表。
    # def _inspector(self) -> QFrame:
    #     frame, contents = card()
    #     frame.setMinimumWidth(265)
    #     frame.setMaximumWidth(365)
    #     contents.setContentsMargins(16, 16, 16, 14)
    #     contents.addWidget(label("商品速览", "sectionTitle"))
    #     scroll = QScrollArea()
    #     scroll.setWidgetResizable(True)
    #     body = QWidget()
    #     # 2026-10-13：本次修改原因：速览滚动内容显式白底，不再出现灰色底板。
    #     body.setObjectName("inspectorBody")
    #     info = QVBoxLayout(body)
    #     info.setContentsMargins(0, 0, 4, 0)
    #     self.preview = ImagePreview(self.network, 170)
    #     info.addWidget(self.preview)
    #     self.inspector_title = label("选择商品查看详情", "sectionTitle", True)
    #     self.inspector_meta = label("商品信息与待完善项将在此显示", "muted", True)
    #     self.inspector_status = label("", "statusBadge", True)
    #     self.inspector_issues = label("从采集记录查看原始材料及解析结果。", "hint", True)
    #     # 2026-10-12：本次修改原因：速览字段按普通文本显示，商品标题中的符号不被误判为 HTML。
    #     for item in (self.inspector_title, self.inspector_meta, self.inspector_status, self.inspector_issues):
    #         item.setTextFormat(Qt.TextFormat.PlainText)
    #     self.inspector_issues.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    #     self.erp_binding_hint = label("", "hint", True)
    #     for item in (self.inspector_title, self.inspector_meta, self.inspector_status, self.inspector_issues, self.erp_binding_hint):
    #         info.addWidget(item)
    #     more = QToolButton()
    #     more.setText("来源与回传工具")
    #     more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    #     more.setArrowType(Qt.ArrowType.RightArrow)
    #     more.setCheckable(True)
    #     info.addWidget(more)
    #     extra = QWidget()
    #     actions = QVBoxLayout(extra)
    #     actions.setContentsMargins(0, 0, 0, 0)
    #     self.erp_bind_button = button("关联妙手原商品", self.bind_erp_current)
    #     self.erp_reconcile_button = button("核对未知回传（只读）", self.reconcile_erp_current)
    #     self.erp_snapshot_button = button("查看妙手导入原始详情", self.show_miaoshou_snapshot)
    #     self.source_button = button("打开货源页面", self.open_source)
    #     for item in (self.erp_bind_button, self.erp_reconcile_button, self.erp_snapshot_button, self.source_button):
    #         actions.addWidget(item)
    #     extra.hide()
    #     more.toggled.connect(extra.setVisible)
    #     more.toggled.connect(lambda checked: more.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow))
    #     info.addWidget(extra)
    #     info.addStretch()
    #     scroll.setWidget(body)
    #     contents.addWidget(scroll, 1)
    #     self.edit_button = button("编辑 / AI 加工", self.edit_current, primary=True)
    #     self.erp_current_button = button("传回妙手 ERP", self.transfer_current, symbol="export")
    #     contents.addWidget(self.edit_button)
    #     contents.addWidget(self.erp_current_button)
    #     return frame

    # def _captures_page(self) -> QWidget:
        # page = QWidget()
        # layout = QVBoxLayout(page)
        # layout.setContentsMargins(0, 0, 0, 0)
        # layout.setSpacing(18)
        # heading, _ = self._heading("采集记录", "每次接收独立留档，解析异常可追溯")
        # heading.addWidget(button("导入采集文件", self.import_files, primary=True, symbol="import"))
        # layout.addLayout(heading)
        # frame, contents = card()
        # actions = QHBoxLayout()
        # self.capture_count = label("共 0 条记录", "sectionTitle")
        # actions.addWidget(self.capture_count)
        # actions.addStretch()
        # actions.addWidget(button("查看原始材料", self.show_raw))
        # actions.addWidget(button("重新解析", self.reparse_selected))
        # contents.addLayout(actions)
        # self.capture_table = table(["接收时间", "来源 / 站点", "商品 ID", "结果", "说明"])
        # for col, width in enumerate([120, 140, 180, 110]):
            # self.capture_table.setColumnWidth(col, width)
        # self.capture_table.itemDoubleClicked.connect(lambda _item: self.show_raw())
        # contents.addWidget(self.capture_table, 1)
        # self.capture_empty = label("暂无采集记录。插件转发接通后，材料会自动出现在这里。", "empty", True)
        # contents.addWidget(self.capture_empty)
        # # contents.addWidget(label("重新解析只处理留档材料；已有商品及人工修改会保留。", "hint"))
        # # 2026-10-11：本次修改原因：重新解析可以补齐旧商品缺失字段，明确人工编辑保护和复审要求。
        # contents.addWidget(label("重新解析会补齐留档中的 SKU、属性与图片；保留人工编辑、主动清空及移除的 SKU。更新后需重新审核。", "hint", True))
        # layout.addWidget(frame, 1)
        # return page
    # 2026-10-12：本次修改原因：采集记录支持接口和插件历史切换及进入加工。
    # def _captures_page(self) -> QWidget:
    #     self.capture_records_page = AcquisitionRecordsPage(self)
    # 2026-10-13：本次修改原因：原采集页面嵌入日志时省去重复大标题，控件、筛选和任务状态保持原实例。
    def _captures_page(self, *, embedded=False) -> QWidget:
        self.capture_records_page = AcquisitionRecordsPage(self, embedded=embedded)
        return self.capture_records_page


    # 2026-10-12：本次修改原因：接口回传记录承接结果核查，撤下表格导出页面。
    # def _erp_records_page(self) -> QWidget:
    #     self.erp_records_page = ERPRecordsPage(self)
    # 2026-10-13：本次修改原因：回传记录嵌入日志，左右回执布局和未知结果保护保留。
    def _erp_records_page(self, *, embedded=False) -> QWidget:
        self.erp_records_page = ERPRecordsPage(self, embedded=embedded)
        return self.erp_records_page

    # 2026-10-13：本次修改原因：两个原记录页面由同一日志容器承载，不合并不同含义的记录字段。
    def _logs_page(self) -> QWidget:
        self.logs_page = LogRecordsPage(self, self._captures_page(embedded=True),
                                       self._erp_records_page(embedded=True))
        return self.logs_page

    # def _settings_page(self) -> QWidget:
        # # 2026-10-11：本次修改原因：模型配置放入独立可点击设置页面，保留插件连接功能。
        # page = QWidget()
        # layout = QVBoxLayout(page)
        # layout.setContentsMargins(0, 0, 0, 0)
        # # heading, _ = self._heading("设置", "管理插件连接与当前使用的 AI 模型")
        # # 2026-10-11：本次修改原因：设置页增加独立的妙手回传栏目，避免开关隐藏在插件接收设置内。
        # heading, _ = self._heading("设置", "管理插件连接、AI 模型与妙手回传方式")
        # layout.addLayout(heading)
        # tabs = QTabWidget()
        # tabs.addTab(self._connection_settings_page(), "插件连接")
        # self.model_settings = ModelSettingsPage(self.model_config, self.assets, self.ai_hub, self)
        # tabs.addTab(self.model_settings, "AI 模型")
        # tabs.addTab(self._erp_settings_page(), "妙手回传")
        # layout.addWidget(tabs, 1)
        # return page
    # 2026-10-12：本次修改原因：默认接口路线，凭证和模型分别配置，插件连接集中为备用。
    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        # heading, _ = self._heading("设置", "选择获取路线，配置妙手读写接口与文本 / 图片模型")
        # 2026-10-13：本次修改原因：设置页提供全应用主题选择，仅保存显示偏好。
        # self.theme_choice = QComboBox()
        # self.theme_choice.addItem("浅色主题", "light")
        # self.theme_choice.addItem("深色主题", "dark")
        # self.theme_choice.setCurrentIndex(self.theme_choice.findData(QApplication.instance().property("beaddiffTheme") or "light"))
        # self.theme_choice.currentIndexChanged.connect(lambda _: apply_theme(QApplication.instance(), self.theme_choice.currentData()))
        # self.theme_choice.setToolTip("仅切换界面主题，业务配置保持不变")
        # heading.addWidget(self.theme_choice)
        # layout.addLayout(heading)
        # 2026-10-13：本次修改原因：导航已说明当前页面，撤下顶部标题和说明，主题归入系统。
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName("settingsTabs")
        self.settings_tabs.addTab(self._route_settings_page(), "采集路线")
        self.settings_tabs.addTab(self._erp_settings_page(), "妙手 ERP")
        self.model_settings = ModelSettingsPage(self.model_config, self.assets, self.ai_hub, self)
        # 2026-10-14：本次修改原因：图床凭证集中在设置页维护，其他页面只显示状态和执行同步。
        self.image_hosting_settings = ImageHostingConfigPage(
            self.image_hosting_store, self.image_hosting_service, self.ai_hub, self)
        # self.settings_tabs.addTab(self.image_hosting_settings, "图床")
        # 2026-10-14：本次修改原因：保留现有 AI 模型和插件连接标签索引，图床设置排在连接设置之后。
        self.settings_tabs.addTab(self.model_settings, "AI 模型")
        self.settings_tabs.addTab(self._connection_settings_page(), "插件连接（备用）")
        self.settings_tabs.addTab(self.image_hosting_settings, "图床")
        # 2026-10-13：本次修改原因：操作帮助放入设置末尾，原四组设置索引保持不变。
        self.help_page = HelpPage(self)
        self.settings_tabs.addTab(self.help_page, "操作帮助")
        # 2026-10-13：本次修改原因：系统追加在操作帮助之后，保留所有既有分组索引和跳转。
        # self.settings_tabs.addTab(self._system_settings_page(), "系统")
        # 2026-10-14：本次修改原因：新增类目、生成方案与建档预设设置页，保持旧编号。
        self.settings_tabs.addTab(self._system_settings_page(), "系统")
        self.listing_settings = ListingSettingsPage(self.listing_defaults_store, self)
        self.settings_tabs.addTab(self.listing_settings, "白底图 Listing")
        # layout.addWidget(self.settings_tabs, 1)
        # 2026-10-13：本次修改原因：设置分组固定在左侧，内容分栏可拖动，原四个标签与跳转索引保持一致。
        from PySide6.QtWidgets import QListWidget
        settings_navigation = QListWidget()
        # 2026-10-13：本次修改原因：设置导航与内容各一层圆角边框，内层列表取消重复描边。
        settings_navigation.setObjectName("settingsNavigation")
        settings_navigation.setMinimumWidth(140)
        # settings_navigation.setMaximumWidth(260)
        settings_navigation.addItems([self.settings_tabs.tabText(i) for i in range(self.settings_tabs.count())])
        self.settings_tabs.tabBar().hide()
        settings_navigation.currentRowChanged.connect(self.settings_tabs.setCurrentIndex)
        self.settings_tabs.currentChanged.connect(settings_navigation.setCurrentRow)
        settings_navigation.setCurrentRow(0)
        settings_splitter = PersistentSplitter(Qt.Orientation.Horizontal, "ui/settings/navigation_splitter_v1", [180, 940], page, live=True)
        # settings_splitter.addWidget(settings_navigation)
        # settings_splitter.addWidget(self.settings_tabs)
        # 2026-10-13：本次修改原因：两侧独立成块，分隔条用留白区分，保留可拖拽调整宽度。
        navigation_frame, navigation_layout = card()
        navigation_layout.setContentsMargins(8, 8, 8, 8)
        navigation_frame.setMinimumWidth(156)
        navigation_frame.setMaximumWidth(280)
        navigation_layout.addWidget(settings_navigation)
        content_frame, content_layout = card()
        content_frame.setObjectName("settingsContentFrame")
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_frame.setMinimumWidth(480)
        content_layout.addWidget(self.settings_tabs)
        settings_splitter.setHandleWidth(14)
        settings_splitter.addWidget(navigation_frame)
        settings_splitter.addWidget(content_frame)
        layout.addWidget(settings_splitter, 1)
        return page

    # 2026-10-13：本次修改原因：主题与实际文件存储路径集中到系统设置，只展示目录，不改变存储或迁移数据。
    def _system_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        appearance, contents = card()
        contents.addWidget(label("界面主题", "sectionTitle"))
        self.theme_choice = QComboBox()
        self.theme_choice.addItem("浅色主题", "light")
        self.theme_choice.addItem("深色主题", "dark")
        self.theme_choice.setCurrentIndex(self.theme_choice.findData(QApplication.instance().property("beaddiffTheme") or "light"))
        self.theme_choice.currentIndexChanged.connect(lambda _: apply_theme(QApplication.instance(), self.theme_choice.currentData()))
        self.theme_choice.setMaximumWidth(240)
        contents.addWidget(self.theme_choice)
        layout.addWidget(appearance)
        storage, contents = card()
        contents.addWidget(label("文件存储目录", "sectionTitle"))
        directory_row = QHBoxLayout()
        self.storage_directory = QLineEdit(str(self.settings.data_dir))
        self.storage_directory.setReadOnly(True)
        self.storage_directory.setToolTip("当前商品、配置、原始材料和日志的存储目录，可选中文字复制。")
        directory_row.addWidget(self.storage_directory, 1)
        directory_row.addWidget(button("打开数据目录", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.settings.data_dir)))))
        contents.addLayout(directory_row)
        layout.addWidget(storage)
        layout.addStretch()
        return page

    def _route_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        frame, contents = card()
        contents.addWidget(label("默认获取方式", "sectionTitle"))
        self.capture_route = QComboBox()
        self.capture_route.addItem("妙手 ERP 接口（推荐）", "miaoshou")
        self.capture_route.addItem("插件同步到本机（备用）", "plugin")
        self.capture_route.setCurrentIndex(self.capture_route.findData(self.settings.capture_route))
        contents.addWidget(self.capture_route)
        contents.addWidget(label("妙手接口：原插件先采集到妙手，再点击“同步妙手采集箱”查询、勾选并导入 ERP 已解析的商品。\n"
                                 "插件同步：加载随附扩展，另发一份原始材料到本机解析；选择此路线才启用接收服务。\n"
                                 "上传白底图始终可用。切换获取路线保留全部历史商品、编辑内容及记录。", "hint", True))
        self.capture_route_save = button("保存采集路线", self.save_capture_route, primary=True)
        contents.addWidget(self.capture_route_save)
        actions = QHBoxLayout()
        actions.addWidget(button("配置妙手接口", lambda: self.open_settings(1)))
        actions.addWidget(button("配置备用插件", lambda: self.open_settings(3)))
        # actions.addWidget(button("操作帮助", lambda: self.navigate(4)))
        # 2026-10-13：本次修改原因：采集路线中的帮助按钮同步跳到设置帮助分组。
        actions.addWidget(button("操作帮助", self.show_help))
        contents.addLayout(actions)
        layout.addWidget(frame)
        layout.addStretch()
        return page

    def open_settings(self, tab_index: int = 0) -> None:
        # self.navigate(3)
        # 2026-10-13：本次修改原因：设置移到第三个主导航位置，使用命名编号保持所有配置跳转一致。
        self.navigate(self.PAGE_SETTINGS)
        self.settings_tabs.setCurrentIndex(tab_index)

    # 2026-10-13：本次修改原因：帮助与采集日志深层跳转集中管理，原按钮直接定位正确分组。
    def show_help(self) -> None:
        self.open_settings(self.SETTINGS_HELP)

    # def show_capture_records(self, route_index: int | None = None) -> None:
    # 2026-10-13：本次修改原因：来源参数只允许按名称传入，避免按钮 clicked 的布尔值误切换采集来源。
    def show_capture_records(self, *, route_index: int | None = None) -> None:
        if route_index is not None:
            self.capture_records_page.routes.button(route_index).setChecked(True)
            self.capture_records_page.change_route(route_index)
        else:
            self.capture_records_page.refresh()
        self.logs_page.show_capture_tab()
        self.navigate(self.PAGE_LOGS)

    def save_capture_route(self) -> None:
        if self._tasks:
            QMessageBox.information(self, "任务正在进行", "请等待同步、回传或核对完成后切换路线。")
            return
        try:
            content = json.loads((self.settings.data_dir / "settings.json").read_text(encoding="utf-8"))
            route = str(self.capture_route.currentData())
            saved = Settings(self.settings.data_dir, self.settings.token, int(content.get("port", self.settings.port)),
                             self.settings.erp_transfer_mode, route)
            saved.save()
            self.settings.capture_route = route
            if route == "plugin":
                self.receiver.start()
            else:
                self.receiver.stop()
            self.capture_records_page.route = route
            self.capture_records_page.routes.button(0 if route == "miaoshou" else 1).setChecked(True)
            self.refresh()
            message = f"已切换为{ROUTE_LABELS[route]}。历史商品与加工内容已保留。"
            if route == "plugin" and self.receiver.error:
                message += "\n接收服务启动失败：" + self.receiver.error + "。请检查端口后重启。"
            QMessageBox.information(self, "采集路线已保存", message)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "未能保存路线", str(error))


    # 2026-10-11：本次修改原因：配置新增或更新开关，默认新增，并明确真实接口接通状态。
    def _erp_settings_page(self) -> QWidget:
        # page = QWidget()
        # layout = QVBoxLayout(page)
        # layout.setContentsMargins(18, 18, 18, 18)
        # 2026-10-13：本次修改原因：全部 ERP 设置卡片由一个外层滚动区承载，不再只滚动中间凭证区域。
        page = QScrollArea()
        page.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("settingsBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)
        frame, contents = card()
        # 2026-10-12：本次修改原因：明确当前写回位置，未适配的店铺选项禁用并说明原因。
        contents.addWidget(label("写回位置与方式", "sectionTitle"))
        self.erp_target = QComboBox()
        self.erp_target.addItem("公共采集箱", "public")
        self.erp_target.addItem("授权店铺采集箱 · 暂未开放", "shop")
        self.erp_target.model().item(1).setEnabled(False)
        self.erp_target.setToolTip("当前接口只适配公共采集箱，店铺接口、授权与字段规范尚待核实。")
        contents.addWidget(self.erp_target)
        contents.addWidget(label("公共采集箱回传成功后，请在妙手认领并发布；店铺采集箱暂未接通。", "hint", True))
        contents.addWidget(label("设置决定下一次回传的处理方式；已创建的回传记录保留各自的方式。", "hint", True))
        self.erp_mode = QComboBox()
        self.erp_mode.addItem("新增一份加工后的商品（保留原采集商品）", "create")
        # self.erp_mode.addItem("更新妙手采集箱中的原商品", "update")
        # 2026-10-11：本次修改原因：当前实现明确写入公共采集箱，不等同于直接保存 Temu 平台采集箱。
        self.erp_mode.addItem("更新妙手公共采集箱中的原商品", "update")
        self.erp_mode.setCurrentIndex(self.erp_mode.findData(self.settings.erp_transfer_mode))
        contents.addWidget(self.erp_mode)
        contents.addWidget(label("更新原商品需要可靠关联妙手商品 ID。来源平台商品 ID 不能直接代替；上传白底图创建的商品首次回传请选择新增。", "hint", True))
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("保存回传方式", self.save_erp_mode, primary=True))
        contents.addLayout(actions)
        layout.addWidget(frame)
        # frame, contents = card()
        # contents.addWidget(label("回传连接", "sectionTitle"))
        # contents.addWidget(label(self.erp_service.unavailable_reason or "已接通经过验证的妙手回传适配器。", "warning", True))
        # contents.addWidget(button("查看回传记录", self.show_erp_records))
        # layout.addWidget(frame)
        # layout.addStretch()
        # 2026-10-11：本次修改原因：用可编辑的凭证设置及只读测试替代静态“未接通”提示。
        self.miaoshou_settings = MiaoshouSettingsPage(self.miaoshou_config, self.miaoshou_adapter,
                                                     self.run_task, self.refresh, self)
        # layout.addWidget(self.miaoshou_settings, 1)
        # layout.addWidget(button("查看回传记录", self.show_erp_records))
        # 2026-10-13：本次修改原因：凭证与图片缓存按内容高度展示，撤下设置底部重复的回传记录跳转。
        layout.addWidget(self.miaoshou_settings)
        layout.addStretch()
        page.setWidget(body)
        return page

    # def _settings_page(self) -> QWidget:
    # 2026-10-11：本次修改原因：将原连接页作为设置子页面使用。
    def _connection_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        # heading, _ = self._heading("连接设置", "让浏览器插件把采集材料同步到本机工作台")
        # layout.addLayout(heading)
        # 2026-10-13：本次修改原因：分组导航已明确插件连接归属，不重复展示大标题与流程说明。
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 8, 0)
        body_layout.setSpacing(18)
        connection, contents = card()
        contents.addWidget(label("本机接收服务", "sectionTitle"))
        self.connection_state = label("", "hint", True)
        contents.addWidget(self.connection_state)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(label("接收地址"), 0, 0)
        self.endpoint = QLineEdit(self.settings.endpoint)
        self.endpoint.setReadOnly(True)
        grid.addWidget(self.endpoint, 0, 1)
        grid.addWidget(button("复制", lambda: self.copy_text(self.endpoint.text())), 0, 2)
        grid.addWidget(label("接入密钥"), 1, 0)
        self.token = QLineEdit(self.settings.token)
        self.token.setReadOnly(True)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(self.token, 1, 1)
        grid.addWidget(button("复制", lambda: self.copy_text(self.settings.token)), 1, 2)
        grid.addWidget(label("监听端口"), 2, 0)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(self.settings.port)
        grid.addWidget(self.port, 2, 1)
        grid.addWidget(button("保存端口", self.save_port), 2, 2)
        contents.addLayout(grid)
        # contents.addWidget(label("服务仅监听 127.0.0.1。修改端口后重启软件生效，插件端也需更新地址。", "hint", True))
        # 2026-10-12：本次修改原因：说明接口路线与备用扩展分支的停用关系。
        contents.addWidget(label("服务仅监听 127.0.0.1，选择插件路线才启用。接口路线可在扩展选项关闭“启用采集同步”；修改端口后重启软件并更新扩展地址。", "hint", True))
        body_layout.addWidget(connection)
        integration, contents = card()
        contents.addWidget(label("插件接入说明", "sectionTitle"))
        # contents.addWidget(label("当前安装的妙手插件尚未修改。仅启动 BeadDiff 不会自动取得浏览器里的商品。", "warning", True))
        # contents.addWidget(label("1  在插件后台捕获 pfti 上传前的 pageContent、itemId、source、site 和 afterUrl。\n\n"
        #                          "2  使用这里的地址与密钥，从扩展后台另发一份 JSON；妙手原有上传流程保持独立。\n\n"
        #                          "3  接收成功后，商品出现在商品库；未识别字段会保留原始材料并提示补充。", "hint", True))
        # 2026-10-11：本次修改原因：更新为可操作的开发版插件加载与连接设置指引。
        contents.addWidget(label("请在浏览器加载项目中的 browser_extension/unpacked 插件目录，再配置同步。", "warning", True))
        contents.addWidget(label("1  浏览器扩展管理页开启开发者模式，停用旧版，加载项目里的开发版插件。\n\n"
                                 "2  打开开发版插件的“扩展选项”，粘贴上方地址与密钥，勾选“启用采集同步”并保存、测试连接。\n\n"
                                 "3  刷新 Temu 商品页并重新采集，商品将在本软件出现；本机关闭时材料会暂存到扩展队列。", "hint", True))
        contents.addWidget(button("查看接入协议", self.show_protocol))
        body_layout.addWidget(integration)
        # storage, contents = card()
        # contents.addWidget(label("本机数据", "sectionTitle"))
        # contents.addWidget(label(str(self.settings.data_dir), "hint", True))
        # contents.addWidget(label("商品库、原始采集文件、编辑版本和日志均保存在 data 目录；备份时请先关闭软件。", "hint", True))
        # 2026-10-12：本次修改原因：数据说明采用当前页面名称。
        # contents.addWidget(label("商品加工、原始材料、编辑版本和日志均保存在数据目录；备份时请先关闭软件。", "hint", True))
        # contents.addWidget(button("打开数据目录", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.settings.data_dir)))))
        # body_layout.addWidget(storage)
        # 2026-10-13：本次修改原因：目录展示和打开目录的原入口迁至系统设置，避免在插件分组重复。
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        return page

    @Slot()
    def schedule_refresh(self) -> None:
        self.refresh_timer.start()

    def refresh(self) -> None:
        self._products = self.repository.products()
        # 2026-10-12：本次修改原因：列表及回传记录显示同一组最新回执。
        self._erp_records = self.repository.erp_transfers()
        existing = {product.id for product in self._products}
        self.checked_ids.intersection_update(existing)
        for key, widget in self.count_labels.items():
            widget.setText(str(len(self._products) if key == "全部" else sum(product.status == key for product in self._products)))
        source = self.source_filter.currentText()
        self.source_filter.blockSignals(True)
        self.source_filter.clear()
        # self.source_filter.addItems(["全部来源"] + sorted({"temu"} | {product.source for product in self._products}))
        # 2026-10-12：本次修改原因：平台筛选不再混入白底图的获取方式。
        self.source_filter.addItems(["全部平台"] + sorted({product.source for product in self._products if product.source != "upload"}))
        self.source_filter.setCurrentText(source)
        self.source_filter.blockSignals(False)
        self.populate_products()
        # captures = self.repository.captures()
        # self.capture_count.setText(f"共 {len(captures)} 条记录")
        # self.capture_empty.setVisible(not captures)
        # self.capture_table.setRowCount(len(captures))
        # for row, capture in enumerate(captures):
            # values = [readable_time(capture["received_at"]), f"{capture['source'].upper()} / {capture['site'] or '—'}",
                      # capture["source_id"], capture["state"], capture["message"]]
            # for col, value in enumerate(values):
                # item = QTableWidgetItem(value)
                # item.setToolTip(value)
                # item.setData(Qt.ItemDataRole.UserRole, capture["id"])
                # if col == 3:
                    # item.setForeground(QColor("#b56936" if value in {"解析失败", "待补充"} else "#168371"))
                # self.capture_table.setItem(row, col, item)
        # 2026-10-12：本次修改原因：刷新两类采集记录及回传页面。
        self.capture_records_page.refresh()
        self.erp_records_page.refresh()
        # 2026-10-13：本次修改原因：移除、恢复或永久删除后更新回收站数量及入口。
        self.recycle_bin_page.refresh()
        self.restore_products_button.setText(f"回收站（{len(self.repository.hidden_local_ids('products'))}）")
        self.update_connection()

    # 2026-10-13：本次修改原因：来源标签只筛选本机列表，按钮继续调用原同步/建档功能，不自动发起请求。
    def update_product_intake(self) -> None:
        capture = self.product_source == "capture"
        plugin = self.settings.capture_route == "plugin"
        self.erp_import_button.setVisible(capture and not plugin)
        self.import_button.setVisible(capture and plugin)
        self.product_upload_button.setVisible(not capture)

    def change_product_source(self, index: int, *, reset_filters: bool = True, render: bool = True) -> None:
        self.product_source = "upload" if index == 1 else "capture"
        self.product_sources.button(index).setChecked(True)
        if reset_filters:
            for widget in (self.acquisition_filter, self.source_filter):
                widget.blockSignals(True)
                widget.setCurrentIndex(0)
                widget.blockSignals(False)
        self.update_product_intake()
        if render:
            self.populate_products()

    def acquisition_filter_changed(self, *_args) -> None:
        route = self.acquisition_filter.currentData()
        if route:
            self.change_product_source(1 if route == "upload" else 0, reset_filters=False, render=False)
            if route == "upload":
                self.source_filter.blockSignals(True)
                self.source_filter.setCurrentIndex(0)
                self.source_filter.blockSignals(False)
        self.populate_products()

    def filter_changed(self, index: int) -> None:
        self.active_filter = ["全部", "待完善", "待审核", "已审核"][index]
        self.populate_products()

    # 2026-10-13：本次修改原因：旧列表填充代码注释保留，改用统一字段列表。
    # def populate_products(self, *_args) -> None:
    #     query = self.search.text().strip().casefold()
    #     source = self.source_filter.currentText()
    #     # filtered = [product for product in self._products
    #                 # if (self.active_filter == "全部" or product.status == self.active_filter)
    #                 # and (source == "全部来源" or product.source == source)
    #     # 2026-10-12：本次修改原因：获取方式与平台独立筛选。
    #     route = self.acquisition_filter.currentData()
    #     filtered = [product for product in self._products
    #                 if (self.active_filter == "全部" or product.status == self.active_filter)
    #                 and (source == "全部平台" or product.source == source)
    #                 and (not route or product.acquisition_route == route)
    #                 and (not query or query in " ".join([product.title, product.main_code, product.source_id]
    #                      + [sku.platform_sku for sku in product.skus]).casefold())]
    #     # 2026-10-12：本次修改原因：批量操作只作用于当前筛选中可见的勾选商品。
    #     self.checked_ids.intersection_update(product.id for product in filtered)
    #     previous = self.current_product.id if self.current_product else ""
    #     self.product_table.blockSignals(True)
    #     self.product_table.setRowCount(len(filtered))
    #     selected_row = 0
    #     for row, product in enumerate(filtered):
    #         check = QTableWidgetItem()
    #         check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
    #         check.setCheckState(Qt.CheckState.Checked if product.id in self.checked_ids else Qt.CheckState.Unchecked)
    #         check.setData(Qt.ItemDataRole.UserRole, product.id)
    #         self.product_table.setItem(row, 0, check)
    #         # values = [f"{product.title or '未识别标题 · 请完善'}\n{product.main_code}", product.source.upper(),
    #         #           str(len(product.skus)), product.status, readable_time(product.updated_at)]
    #         # 2026-10-11：本次修改原因：列表显示保存的内容修改与可信回执对应状态。
    #         # values = [f"{product.title or '未识别标题 · 请完善'}\n{product.main_code}", product.source.upper(),
    #                   # # str(len(product.skus)), product.status, product.modification_status, product.erp_status,
    #                   # # 2026-10-11：本次修改原因：账号变化后不能把旧账号的成功回执显示为当前账号已传。
    #                   # str(len(product.skus)), product.status, product.modification_status, self.erp_display_status(product),
    #                   # readable_time(product.updated_at)]
    #         # 2026-10-12：本次修改原因：商品行分别显示获取方式、平台、审核和回传状态。
    #         values = [f"{product.title or '未识别标题 · 请完善'}\n{product.main_code}", product.acquisition_label,
    #                   product.source.upper() if product.source != "upload" else "—", str(len(product.skus)),
    #                   product.status, product.modification_status, self.erp_display_status(product),
    #                   readable_time(product.updated_at)]
    #         for col, value in enumerate(values, 1):
    #             item = QTableWidgetItem(value)
    #             item.setToolTip(value)
    #             # 2026-10-12：本次修改原因：新增获取方式列后同步状态列位置。
    #             if col == 5:
    #                 item.setForeground(QColor({"待完善": "#b87a2c", "待审核": "#4282ad", "已审核": "#168371"}[product.status]))
    #             # 2026-10-11：本次修改原因：通过颜色和说明区分修改状态以及内容是否已回传。
    #             if col == 6:
    #                 item.setForeground(QColor("#4282ad" if product.content_modified else "#70888d"))
    #                 item.setToolTip("商品内容已修改并保存" if product.content_modified else "尚无已保存的内容修改")
    #             if col == 7:
    #                 # item.setForeground(QColor("#168371" if value == "已传" else "#70888d"))
    #                 # 2026-10-12：本次修改原因：失败、待核对和需重传分别着色，列表即可识别处理优先级。
    #                 colors = {"已传": "#168371", "需重传": "#4282ad", "回传中": "#4282ad",
    #                           "失败": "#b56936", "待核对": "#b56936", "未发送": "#b56936"}
    #                 item.setForeground(QColor(colors.get(value, "#70888d")))
    #                 hint = "当前内容尚未取得妙手成功回执。"
    #                 if product.erp_transferred_at:
    #                     hint = f"最近成功回传：{readable_time(product.erp_transferred_at)}\n方式：{MODE_LABELS.get(product.erp_transfer_mode, product.erp_transfer_mode)}\n妙手目标 ID：{product.erp_target_id}"
    #                     # if value == "未传":
    #                     # 2026-10-12：本次修改原因：已传内容再次改动时明确提示需要重传。
    #                     if value == "需重传":
    #                         hint += "\n当前内容与上次已传内容不同，需重新回传。"
    #                 item.setToolTip(hint)
    #             self.product_table.setItem(row, col, item)
    #         if product.id == previous:
    #             selected_row = row
    #     self.product_table.blockSignals(False)
    #     self.product_empty.setVisible(not filtered)
    #     # self.product_empty.setText("没有符合筛选条件的商品。" if self._products else
    #     #                            "还没有商品\n导入 pfti 请求 JSON / HAR，或在连接设置中配置插件转发。")
    #     # 2026-10-11：本次修改原因：刷新后仍展示采集与白底图两条路线。
    #     # self.product_empty.setText("没有符合筛选条件的商品。" if self._products else
    #                                # "还没有商品\n导入采集文件、配置插件同步，或上传白底图创建商品。")
    #     # 2026-10-12：本次修改原因：空列表说明获取入口或筛选原因。
    #     self.product_empty.setText("没有符合筛选条件的商品，请调整获取方式、平台或审核筛选。" if self._products else
    #                                "还没有商品\n点击上方同步采集箱或上传白底图开始。")
    #     # self.product_summary.setText(f"当前 {len(filtered)} 个商品  /  商品库共 {len(self._products)} 个    ·    双击编辑")
    #     # 2026-10-12：本次修改原因：列表摘要说明统一加工入口。
    #     self.product_summary.setText(f"当前 {len(filtered)} 个 / 共 {len(self._products)} 个商品    ·    双击进行编辑 / AI 加工")
    #     if filtered:
    #         self.product_table.selectRow(selected_row)
    #     self.product_selected()
    #     self.update_selection()

    # 2026-10-13：本次修改原因：商品速览字段直接进入列表，所有状态和操作使用命名列索引，避免增列后错位。
    # 2026-10-13：本次修改原因：旧逐单元格重建保留注释，当前使用轻量数据行，不改变筛选和状态规则。
    # def populate_products(self, *_args) -> None:
        # query = self.search.text().strip().casefold()
        # source = self.source_filter.currentText()
        # route = self.acquisition_filter.currentData()
        # filtered = [product for product in self._products
                    # if (self.active_filter == "全部" or product.status == self.active_filter)
                    # and (source == "全部平台" or product.source == source)
                    # and (not route or product.acquisition_route == route)
                    # and (not query or query in " ".join([product.title, product.main_code, product.source_id,
                         # product.erp_original_id, product.erp_target_id] + [sku.platform_sku for sku in product.skus]).casefold())]
        # self.checked_ids.intersection_update(product.id for product in filtered)
        # previous = self.current_product.id if self.current_product else ""
        # self.product_table.blockSignals(True)
        # self.product_table.setRowCount(len(filtered))
        # selected_row = 0
        # for row, product in enumerate(filtered):
            # check = QTableWidgetItem()
            # check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            # check.setCheckState(Qt.CheckState.Checked if product.id in self.checked_ids else Qt.CheckState.Unchecked)
            # check.setData(Qt.ItemDataRole.UserRole, product.id)
            # self.product_table.setItem(row, PRODUCT_COL["selected"], check)
            # price, price_hint = price_summary(product)
            # issues = product.review_issues()
            # notice = self.product_notice(product, issues)
            # status = product.status
            # transferred = self.erp_display_status(product)
            # material = f"主图 {len(product.images)} · 详情 {len(product.detail_images)}\n视频：{'有' if product.video else '无'}"
            # values = {
                # "image": "",
                # "product": f"{product.title or '未识别标题 · 请完善'}\n{product.main_code or '主编号未填写'}",
                # "platform": f"{product.source.upper() if product.source != 'upload' else '—'}\n{product.site or '—'}",
                # "route": product.acquisition_label,
                # "sku": f"{len(product.skus)} 个 SKU\n{len(product.attributes)} 项属性",
                # "price": price,
                # "materials": material,
                # "review": status,
                # "modified": product.modification_status,
                # "transfer": transferred,
                # "updated": readable_time(product.updated_at),
                # "source_id": product.source_id or "—",
                # "erp_id": f"原：{product.erp_original_id or '未关联'}\n回传：{product.erp_target_id or '尚无'}",
                # "revision": f"v{product.revision}",
                # "issues": (f"待完善 {len(issues)} 项" if issues else "必填已完善")
                    # + (" · 有提示" if product.warnings or local_picture_count(product) else ""),
                # "actions": "",
            # }
            # hints = {
                # "image": (product.images[0] if product.images else "暂无主图") + "\n双击商品进入图片编辑",
                # "product": values["product"] + f"\n货源 ID：{product.source_id or '—'}\n当前版本：v{product.revision}\n" + material,
                # "price": price_hint,
                # "materials": material + ("\n视频：" + product.video if product.video else ""),
                # "review": notice,
                # "issues": notice,
                # "modified": "商品内容已修改并保存" if product.content_modified else "尚无已保存的内容修改",
                # "erp_id": values["erp_id"] + "\n来源平台商品 ID 不能代替妙手原商品 ID。",
                # "actions": "编辑 / AI：加工当前商品；更多：单条回传、货源、关联、原始详情、检查提示。",
            # }
            # transfer_hint = "当前内容尚未取得妙手成功回执。"
            # if product.erp_transferred_at:
                # transfer_hint = (f"最近成功回传：{readable_time(product.erp_transferred_at)}\n"
                    # f"方式：{MODE_LABELS.get(product.erp_transfer_mode, product.erp_transfer_mode)}\n"
                    # f"妙手目标 ID：{product.erp_target_id}")
                # if transferred == "需重传":
                    # transfer_hint += "\n当前内容与上次已传内容不同，需重新回传。"
            # hints["transfer"] = transfer_hint
            # for key, _title, _width, _visible in PRODUCT_COLUMNS[1:]:
                # item = QTableWidgetItem(values[key])
                # item.setData(Qt.ItemDataRole.UserRole, product.id)
                # item.setToolTip(hints.get(key, values[key]))
                # if key == "image":
                    # item.setData(IMAGE_ROLE, product.images[0] if product.images else "")
                # if key == "review":
                    # item.setForeground(QColor({"待完善": "#b87a2c", "待审核": "#4282ad", "已审核": "#168371"}[status]))
                # elif key == "modified":
                    # item.setForeground(QColor("#4282ad" if product.content_modified else "#70888d"))
                # elif key == "transfer":
                    # colors = {"已传": "#168371", "需重传": "#4282ad", "回传中": "#4282ad",
                              # "失败": "#b56936", "待核对": "#b56936", "未发送": "#b56936"}
                    # item.setForeground(QColor(colors.get(transferred, "#70888d")))
                # elif key == "issues":
                    # item.setForeground(QColor("#b87a2c" if issues else "#70888d"))
                # if key in {"route", "review", "modified", "transfer", "revision"}:
                    # item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # elif key == "price":
                    # item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                # self.product_table.setItem(row, PRODUCT_COL[key], item)
            # if product.id == previous:
                # selected_row = row
        # self.product_table.blockSignals(False)
        # self.product_empty.setVisible(not filtered)
        # self.product_empty.setText("没有符合筛选条件的商品，请调整获取方式、平台或审核筛选。" if self._products else
                                   # "还没有商品\n点击上方同步采集箱或上传白底图开始。")
        # self.product_summary.setText(f"当前 {len(filtered)} 个 / 共 {len(self._products)} 个商品"
            # "    ·    双击或点击行内编辑 / AI    ·    显示列可展开素材、编号、版本和检查提示")
        # if filtered:
            # self.product_table.selectRow(selected_row)
        # else:
            # self.product_table.setCurrentCell(-1, -1)
        # self.product_selected()
        # self.update_selection()


    def populate_products(self, *_args) -> None:
        query = self.search.text().strip().casefold()
        source = self.source_filter.currentText()
        route = self.acquisition_filter.currentData()
        filtered = [product for product in self._products
                    if (self.active_filter == "全部" or product.status == self.active_filter)
                    # 2026-10-13：本次修改原因：采集标签含接口/插件商品，白底图标签只展示自上传；业务状态规则不变。
                    and ((product.acquisition_route == "upload") == (self.product_source == "upload"))
                    and (source == "全部平台" or product.source == source)
                    and (not route or product.acquisition_route == route)
                    and (not query or query in " ".join([product.title, product.main_code, product.source_id,
                         product.erp_original_id, product.erp_target_id] + [sku.platform_sku for sku in product.skus]).casefold())]
        self.checked_ids.intersection_update(product.id for product in filtered)
        previous = self.current_product.id if self.current_product else ""
        self.product_table.blockSignals(True)
        rows = []
        for row, product in enumerate(filtered):
            price, price_hint = price_summary(product)
            issues = product.review_issues()
            notice = self.product_notice(product, issues)
            status = product.status
            transferred = self.erp_display_status(product)
            material = f"主图 {len(product.images)} · 详情 {len(product.detail_images)}\n视频：{'有' if product.video else '无'}"
            values = {
                "image": "",
                "product": f"{product.title or '未识别标题 · 请完善'}\n{product.main_code or '主编号未填写'}",
                "platform": f"{product.source.upper() if product.source != 'upload' else '—'}\n{product.site or '—'}",
                "route": product.acquisition_label,
                "sku": f"{len(product.skus)} 个 SKU\n{len(product.attributes)} 项属性",
                "price": price,
                "materials": material,
                "review": status,
                "modified": product.modification_status,
                "transfer": transferred,
                "updated": readable_time(product.updated_at),
                "source_id": product.source_id or "—",
                "erp_id": f"原：{product.erp_original_id or '未关联'}\n回传：{product.erp_target_id or '尚无'}",
                "revision": f"v{product.revision}",
                "issues": (f"待完善 {len(issues)} 项" if issues else "必填已完善")
                    + (" · 有提示" if product.warnings or local_picture_count(product) else ""),
                "actions": "",
            }
            hints = {
                "image": (product.images[0] if product.images else "暂无主图") + "\n双击商品进入图片编辑",
                "product": values["product"] + f"\n货源 ID：{product.source_id or '—'}\n当前版本：v{product.revision}\n" + material,
                "price": price_hint,
                "materials": material + ("\n视频：" + product.video if product.video else ""),
                "review": notice,
                "issues": notice,
                "modified": "商品内容已修改并保存" if product.content_modified else "尚无已保存的内容修改",
                "erp_id": values["erp_id"] + "\n来源平台商品 ID 不能代替妙手原商品 ID。",
                "actions": "编辑 / AI：加工当前商品；更多：单条回传、货源、关联、原始详情、检查提示。",
            }
            transfer_hint = "当前内容尚未取得妙手成功回执。"
            if product.erp_transferred_at:
                transfer_hint = (f"最近成功回传：{readable_time(product.erp_transferred_at)}\n"
                    f"方式：{MODE_LABELS.get(product.erp_transfer_mode, product.erp_transfer_mode)}\n"
                    f"妙手目标 ID：{product.erp_target_id}")
                if transferred == "需重传":
                    transfer_hint += "\n当前内容与上次已传内容不同，需重新回传。"
            hints["transfer"] = transfer_hint
            rows.append({"id": product.id, "checked": product.id in self.checked_ids,
                         "values": values, "hints": hints, "image_url": product.images[0] if product.images else "",
                         "sort": {"updated": product.updated_at, "revision": product.revision, "sku": len(product.skus)}})
        self.product_table.set_rows(rows)
        self.product_table.blockSignals(False)
        self.product_empty.setVisible(not filtered)
        # self.product_empty.setText("没有符合筛选条件的商品，请调整获取方式、平台或审核筛选。" if self._products else
        #                            "还没有商品\n点击上方同步采集箱或上传白底图开始。")
        # 2026-10-13：本次修改原因：空状态和数量按当前来源显示，避免白底图列表为空却提示同步妙手。
        source_count = sum((product.acquisition_route == "upload") == (self.product_source == "upload")
                           for product in self._products)
        start_action = "上传白底图" if self.product_source == "upload" else (
            "导入采集文件" if self.settings.capture_route == "plugin" else "同步妙手采集箱")
        self.product_empty.setText("没有符合筛选条件的商品。调整筛选或清空搜索。" if source_count else
                                   f"暂无{'白底图' if self.product_source == 'upload' else '采集'}商品\n点击左上方“{start_action}”开始。")
        # self.product_summary.setText(f"当前 {len(filtered)} 个 / 共 {len(self._products)} 个商品"
        #     "    ·    双击或点击行内编辑 / AI    ·    显示列可展开素材、编号、版本和检查提示")
        # 2026-10-13：本次修改原因：数量迁至列表标题旁，撤下重复的常驻操作说明。
        # self.product_summary.setText(f"当前 {len(filtered)} 个 / 共 {len(self._products)} 个")
        self.product_summary.setText(f"当前 {len(filtered)} 个 / 共 {source_count} 个")
        if filtered:
            selected_row = next((row for row in range(self.product_table.rowCount())
                if self.product_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == previous), 0)
            self.product_table.selectRow(selected_row)
        else:
            self.product_table.setCurrentCell(-1, -1)
        self.product_selected()
        self.update_selection()

    # 2026-10-13：本次修改原因：旧速览刷新代码注释保留，页面已改为全宽列表。
    # def product_selected(self) -> None:
    #     row = self.product_table.currentRow()
    #     item = self.product_table.item(row, 0) if row >= 0 else None
    #     product_id = item.data(Qt.ItemDataRole.UserRole) if item else None
    #     product = next((value for value in self._products if value.id == product_id), None)
    #     previous_url = self.current_product.images[0] if self.current_product and self.current_product.images else ""
    #     self.current_product = product
    #     self.edit_button.setEnabled(product is not None)
    #     self.erp_current_button.setEnabled(product is not None and not self._tasks)
    #     # 2026-10-11：本次修改原因：查询、发送期间锁住关联和凭证编辑，保持同一账号的任务快照。
    #     self.erp_bind_button.setEnabled(product is not None and not self._tasks)
    #     # 2026-10-12：本次修改原因：API 商品已有稳定原商品关联，不使用按平台规格猜测的重新关联流程。
    #     if product and product.erp_imported:
    #         self.erp_bind_button.setEnabled(False)
    #     # 2026-10-11：本次修改原因：只读核对复用后台任务状态。
    #     self.erp_reconcile_button.setEnabled(product is not None and not self._tasks)
    #     # 2026-10-12：本次修改原因：仅 API 导入商品具有远端快照，插件原始材料仍从采集记录查看。
    #     self.erp_snapshot_button.setEnabled(bool(product and product.erp_remote_snapshot))
    #     self.miaoshou_settings.set_busy(bool(self._tasks))
    #     self.erp_mode.setEnabled(not self._tasks)
    #     self.erp_binding_hint.setText(
    #         (f"公共采集箱原商品 ID：{product.erp_original_id}" if product.erp_original_id else "更新前请先关联妙手原商品")
    #         if product else "")
    #     self.source_button.setEnabled(bool(product and valid_url(product.source_url)))
    #     if not product:
    #         self.inspector_title.setText("选择商品查看详情")
    #         self.inspector_meta.setText("商品信息与待完善项将在此显示")
    #         self.inspector_status.setText("")
    #         self.inspector_issues.setText("从采集记录可查看原始材料及解析结果。")
    #         self.preview.set_url("")
    #         return
    #     current_url = product.images[0] if product.images else ""
    #     if current_url != previous_url:
    #         self.preview.set_url(current_url)
    #     self.inspector_title.setText(product.title or "未识别标题")
    #     # self.inspector_meta.setText(f"{product.source.upper()} · {product.site or '站点未提供'}\n{product.source_id}\n{len(product.skus)} 个 SKU  ·  v{product.revision}")
    #     # 2026-10-11：本次修改原因：商品速览显示素材数量，便于对比妙手采集结果。
    #     self.inspector_meta.setText(
    #         f"{product.source.upper()} · {product.site or '站点未提供'}\n{product.source_id}\n"
    #         f"{len(product.skus)} 个 SKU  ·  {len(product.attributes)} 项属性  ·  v{product.revision}\n"
    #         f"主图 {len(product.images)} 张  ·  详情图 {len(product.detail_images)} 张"
    #         + ("  ·  有视频" if product.video else ""))
    #     # 2026-10-12：本次修改原因：商品库区分 API 导入与原始插件接收，并提供完整远端快照查看入口。
    #     # if product.erp_imported:
    #         # self.inspector_meta.setText(self.inspector_meta.text() + "\n数据来源：妙手 API 导入")
    #     # 2026-10-12：本次修改原因：速览与列表统一展示获取方式。
    #     self.inspector_meta.setText(self.inspector_meta.text() + "\n获取方式：" + product.acquisition_label)
    #     # self.inspector_status.setText(f"{product.status}  ·  售价币种 {product.currency or '待确认'}")
    #     # 2026-10-11：本次修改原因：速览与商品列表展示相同的修改和回传状态。
    #     self.inspector_status.setText(f"{product.status}  ·  售价币种 {product.currency or '待确认'}\n"
    #                                   # f"{product.modification_status}  ·  传回 ERP：{product.erp_status}")
    #                                   # 2026-10-11：本次修改原因：速览与列表一致按当前账号展示回传状态。
    #                                   f"{product.modification_status}  ·  传回 ERP：{self.erp_display_status(product)}")
    #     # issues = product.issues()
    #     # 2026-10-12：本次修改原因：速览问题清单与 API 原商品增量审核保持一致。
    #     issues = product.review_issues()
    #     text = "待完善\n" + "\n".join(f"• {issue}" for issue in issues[:14]) if issues else "必填信息已完善，请人工核对来源、售价和规格。"
    #     if product.warnings:
    #         # text += "\n\n采集提示\n" + "\n".join(f"• {warning}" for warning in product.warnings)
    #         # 2026-10-12：本次修改原因：旧材料价格提示与当前接口流程一致。
    #         text += "\n\n采集提示\n" + "\n".join(f"• {warning.replace('实际导出售价', '实际售价')}" for warning in product.warnings)
    #     # 2026-10-12：本次修改原因：本机素材在加工阶段提前提醒，减少直到回传才发现不能上传。
    #     local_count = local_picture_count(product)
    #     if local_count:
    #         text += f"\n\n素材待处理\n• {local_count} 张本机图片；写回涉及这些图片时需先替换为公网链接。"
    #     self.inspector_issues.setText(text)

    # 2026-10-13：本次修改原因：选中商品只更新列表工具栏状态，移除全部速览控件刷新及图片请求。
    def product_selected(self) -> None:
        row = self.product_table.currentRow()
        item = self.product_table.item(row, PRODUCT_COL["selected"]) if row >= 0 else None
        product_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.current_product = next((value for value in self._products if value.id == product_id), None)
        busy = bool(self._tasks) or self.ai_hub.busy
        self.edit_button.setEnabled(self.current_product is not None and not busy)
        self.product_more_button.setEnabled(self.current_product is not None and not busy)
        self.product_row_actions.busy = busy
        self.product_table.viewport().update()
        self.miaoshou_settings.set_busy(bool(self._tasks))
        self.erp_mode.setEnabled(not self._tasks)

    def check_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        product_id = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self.checked_ids.add(product_id)
        else:
            self.checked_ids.discard(product_id)
        self.update_selection()

    def update_selection(self) -> None:
        self.selected_label.setText(f"已选 {len(self.checked_ids)} 项")
        # 2026-10-11：本次修改原因：回传期间禁止重复点击，当前配置方式直接展示在商品操作区。
        self.erp_button.setEnabled(bool(self.checked_ids) and not self._tasks)
        # self.erp_mode_hint.setText("回传方式：" + MODE_LABELS[self.settings.erp_transfer_mode])
        # 2026-10-12：本次修改原因：统一商品加工入口、来源和反馈链路。
        self.erp_mode_hint.setText(TARGET_LABEL + " · " + MODE_LABELS[self.settings.erp_transfer_mode])
        # self.approve_button.setEnabled(bool(self.checked_ids))
        # 2026-10-12：本次修改原因：统一商品加工入口、来源和反馈链路。
        self.approve_button.setEnabled(bool(self.checked_ids) and not self._tasks)
        checked = self.product_table.rowCount() > 0 and all(
            self.product_table.item(row, 0).checkState() == Qt.CheckState.Checked for row in range(self.product_table.rowCount()))
        self.select_all.blockSignals(True)
        self.select_all.setChecked(checked)
        self.select_all.blockSignals(False)

    # 2026-10-13：本次修改原因：全选只更新当前显示商品，合并界面刷新，避免逐行触发全表计数。
    # def check_all(self, checked: bool) -> None:
        # for row in range(self.product_table.rowCount()):
            # self.product_table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def check_all(self, checked: bool) -> None:
        visible_ids = {self.product_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                       for row in range(self.product_table.rowCount())}
        blocked = self.product_table.blockSignals(True)
        for row in range(self.product_table.rowCount()):
            self.product_table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.product_table.blockSignals(blocked)
        if checked:
            self.checked_ids.update(visible_ids)
        else:
            self.checked_ids.difference_update(visible_ids)
        self.update_selection()

    def clear_selection(self) -> None:
        self.checked_ids.clear()
        self.populate_products()

    # 2026-10-12：本次修改原因：商品清理只处理勾选或当前筛选结果，保留回收站及远端商品。
    def remove_selected_products(self) -> None:
        self.clean_local_list("products", list(self.checked_ids))

    def clear_visible_products(self) -> None:
        self.clean_local_list("products", [self.product_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in range(self.product_table.rowCount())])

    # 2026-10-12：本次修改原因：各页面共用可恢复的本机清理确认，未确认回传仍保留，不调用 ERP 删除接口。
    def clean_local_list(self, kind: str, ids: list[str]) -> None:
        if self._tasks or self.ai_hub.busy:
            QMessageBox.information(self, "请等待任务结束", "当前仍有任务运行，结束后再清理。")
            return
        if not ids:
            QMessageBox.information(self, "请选择条目", "先勾选商品或选中记录；清空仅作用于当前筛选结果。")
            return
        explanation = "商品移入本机回收站，版本和去重身份保留。" if kind == "products" else "记录从列表移除，原始材料、商品及回传证据保留。"
        if not self._confirm_transfer("清理本机列表", f"本次涉及 {len(set(ids))} 条。\n{explanation}\n可点击恢复找回；不会删除妙手商品。回传中或结果未知的条目会保留。", "确认移除"):
            return
        try:
            result = self.repository.hide_local_items(kind, ids)
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "清理未完成", str(error))
            return
        self.refresh()
        # text = f"已移除 {result['hidden']} 条，可恢复。"
        # 2026-10-13：本次修改原因：清理成功反馈指向实际回收站入口，避免用户找不到已移除内容。
        text = f"已移除 {result['hidden']} 条，可从侧栏“回收站”选择恢复或永久删除。"
        if result["blocked"]:
            text += f" {result['blocked']} 条仍在处理或待核对，已保留。"
        self.operation_feedback.setText(text)
        self.statusBar().showMessage(text, 10000)
        self.task_progress_text.setText(text)

    # 2026-10-12：本次修改原因：恢复仅撤销本机隐藏标记，不重新采集或写入妙手。
    # def restore_local_list(self, kind: str) -> None:
    #     if self._tasks or self.ai_hub.busy:
    #         return
    #     if not self._confirm_transfer("恢复本机列表", "恢复此类列表中全部已移除条目？不会请求妙手接口。", "确认恢复"):
    #         return
    #     try:
    #         count = self.repository.restore_local_items(kind)
    #     except (OSError, ValueError, sqlite3.Error) as error:
    #         QMessageBox.warning(self, "恢复未完成", str(error))
    #         return
    #     self.refresh()
    #     text = f"已恢复 {count} 条；可调整筛选查看。"
    #     self.operation_feedback.setText(text)
    #     self.task_progress_text.setText(text)
    #     self.statusBar().showMessage(text, 10000)

    # 2026-10-13：本次修改原因：用具体回收站页面替代隐藏的“同类全部恢复”，入口可选类型。
    def open_recycle_bin(self, kind: str = "products") -> None:
        self.recycle_bin_page.open_kind(kind)
        # self.navigate(5)
        # 2026-10-13：本次修改原因：回收站随主导航收敛后使用新的明确编号。
        self.navigate(self.PAGE_RECYCLE)

    def edit_current(self) -> None:
        if self.current_product:
            product = self.repository.product(self.current_product.id)
            # if product and ProductEditor(self.repository, product, self.network, self).exec() == QDialog.DialogCode.Accepted:
            # 2026-10-11：本次修改原因：采集商品编辑调用共用 AI 服务，表单应用后再由用户保存。
            # if product and ProductEditor(self.repository, product, self.network, self,
            #                              ai_service=self.ai_service, ai_hub=self.ai_hub).exec() == QDialog.DialogCode.Accepted:
            #     self.refresh()
            #     saved = self.repository.product(product.id)
            #     self.operation_feedback.setText(
            #         "商品已保存并审核，可检查并回传 ERP。" if saved and saved.status == "已审核"
            #         else "修改已保存。补齐待完善项并审核当前版本后，再传回 ERP。")
            #     self.statusBar().showMessage("商品已保存，编辑版本已记录", 6000)
            # 2026-10-13：本次修改原因：采集商品在主窗口内编辑，保存结果由页面关闭回调统一反馈。
            if product:
                self.open_product_editor(product)

    # 2026-10-13：本次修改原因：两条编辑入口共用内嵌页面，筛选/来源/排序控件留在原列表页，不重复创建。
    def open_product_editor(self, product: Product) -> None:
        if getattr(self, "product_editor", None) is not None:
            self.stack.setCurrentWidget(self.product_editor)
            return
        table = self.product_table
        context = {
            "current_id": self.current_product.id if self.current_product else product.id,
            "column": max(0, table.currentIndex().column()),
            "selected_ids": {index.data(Qt.ItemDataRole.UserRole)
                             for index in table.selectionModel().selectedRows()},
            "checked_ids": set(self.checked_ids),
            "horizontal": table.horizontalScrollBar().value(),
            "vertical": table.verticalScrollBar().value(),
        }
        # editor = ProductEditor(self.repository, product, self.network, self,
        #                        ai_service=self.ai_service, ai_hub=self.ai_hub)
        # 2026-10-13：本次修改原因：采集/白底图商品共用统一 AI 页与已保存爆款方案库。
        editor = ProductEditor(self.repository, product, self.network, self,
                               ai_service=self.ai_service, ai_hub=self.ai_hub, reference_store=self.reference_store)
        self.product_editor = editor
        editor.closed.connect(lambda result: self.finish_product_edit(editor, result, context))
        self.stack.addWidget(editor)
        self.stack.setCurrentWidget(editor)
        self.navigation.button(self.PAGE_PRODUCTS).setChecked(True)
        editor.back_button.setFocus()

    # 2026-10-13：本次修改原因：保存沿用原刷新/审核反馈；返回复用列表控件，恢复勾选及滚动位置。
    def finish_product_edit(self, editor: ProductEditor, result: int, context: dict) -> None:
        if editor is not getattr(self, "product_editor", None):
            return
        self.product_editor = None
        self.stack.setCurrentIndex(self.PAGE_PRODUCTS)
        self.navigation.button(self.PAGE_PRODUCTS).setChecked(True)
        self.stack.removeWidget(editor)
        editor.hide()
        editor.deleteLater()
        self.checked_ids = set(context["checked_ids"])
        if result == QDialog.DialogCode.Accepted:
            self.refresh()
            saved = self.repository.product(editor.product.id)
            self.operation_feedback.setText(
                "商品已保存并审核，可检查并回传 ERP。" if saved and saved.status == "已审核"
                else "修改已保存。补齐待完善项并审核当前版本后，再传回 ERP。")
            self.statusBar().showMessage("商品已保存，编辑版本已记录", 6000)
        else:
            # 接收服务可能在编辑期间更新了隐藏列表；按原勾选集合重新绘制，不改动商品数据。
            self.populate_products()
        self.restore_product_list_context(context)
        # 页面切回后的布局可能重算滚动范围，下一轮事件再次恢复最终位置。
        QTimer.singleShot(0, lambda: self.restore_product_list_context(context)
                          if self.product_editor is None else None)

    # 2026-10-13：本次修改原因：刷新可能改变行号，按稳定商品 ID 恢复当前行/多选；已不符合筛选的商品不强行显示。
    def restore_product_list_context(self, context: dict) -> None:
        table = self.product_table
        selection = table.selectionModel()
        selection.clearSelection()
        for row in range(table.rowCount()):
            index = table.model().index(row, context["column"])
            product_id = index.data(Qt.ItemDataRole.UserRole)
            if product_id == context["current_id"]:
                selection.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
            if product_id in context["selected_ids"]:
                selection.select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        table.horizontalScrollBar().setValue(context["horizontal"])
        table.verticalScrollBar().setValue(context["vertical"])
        self.product_selected()

    # 2026-10-12：本次修改原因：API 导入自动关联原商品，返回商品库定位最后导入项，编辑与 AI 不需要另写流程。
    def import_miaoshou(self) -> None:
        if self._tasks:
            return
        if self.erp_service.unavailable_reason:
            # QMessageBox.information(self, "请先配置妙手接口", self.erp_service.unavailable_reason + "\n请进入设置 → 妙手回传填写凭证。")
            # 2026-10-12：本次修改原因：缺少凭证时直接定位妙手接口设置。
            QMessageBox.information(self, "请先配置妙手接口", self.erp_service.unavailable_reason)
            self.open_settings(1)
            return
        # dialog = MiaoshouImportDialog(self.repository, self.miaoshou_adapter, self.run_task, self)
        # 2026-10-12：本次修改原因：同步查询和导入使用明确任务名称，失败反馈与入口一致。
        # dialog = MiaoshouImportDialog(self.repository, self.miaoshou_adapter,
        #     lambda work, done: self.run_task(work, done, "同步妙手采集箱"), self)
        # 2026-10-12：本次修改原因：同步窗口区分查询、查看和导入任务，并接收真实进度。
        dialog = MiaoshouImportDialog(self.repository, self.miaoshou_adapter, self.run_task, self)
        # dialog.exec()
        # if dialog.last_product_id:
        # 2026-10-12：本次修改原因：进入加工按钮明确返回接受状态。
        result = dialog.exec()
        if dialog.last_product_id:
            self.active_filter = "全部"
            self.filters.button(0).setChecked(True)
            # self.source_filter.setCurrentText("全部来源")
            # 2026-10-12：本次修改原因：同步完成清除来源筛选并定位商品。
            self.source_filter.setCurrentIndex(0)
            self.acquisition_filter.setCurrentIndex(0)
            self.search.clear()
            # self.current_product = self.repository.product(dialog.last_product_id)
        # self.refresh()
            # 2026-10-12：本次修改原因：从同步窗口进入加工时定位商品并更新图片。
            self.current_product = self.repository.product(dialog.last_product_id)
            # 2026-10-13：本次修改原因：同步结果定位采集列表，避免导入成功后仍停留在白底图列表。
            self.change_product_source(0, reset_filters=False, render=False)
            # if self.current_product:
            #     self.preview.set_url(self.current_product.images[0] if self.current_product.images else "")
            # 2026-10-13：本次修改原因：列表负责主图缩略图，ERP 同步结束不再访问已移除的速览控件。
        self.refresh()
        if result == QDialog.DialogCode.Accepted and dialog.last_product_id:
            self.focus_product(dialog.last_product_id, edit=True)

    # 2026-10-12：本次修改原因：查看首次导入的全部字段不发起网络请求，也不覆盖本机工作内容。
    def show_miaoshou_snapshot(self) -> None:
        if self.current_product and self.current_product.erp_remote_snapshot:
            self.text_dialog("妙手 API 原始详情（首次导入快照）",
                             json.dumps(self.current_product.erp_remote_snapshot, ensure_ascii=False, indent=2))

    # 2026-10-11：本次修改原因：上传商品与采集商品共用编辑、版本和 AI 处理流程。
    def create_from_photos(self) -> None:
        # creation = ProductCreation(self.repository, self.assets, self)
        # 2026-10-14：本次修改原因：上传前读取配置并检查模型，失败不创建半成品。
        creation = ProductCreation(self.repository, self.assets, self,
            defaults_store=self.listing_defaults_store, ai_service=self.ai_service)
        if creation.exec() != QDialog.DialogCode.Accepted or not creation.created_product:
            return
        # self.current_product = creation.created_product
        self.active_filter = "全部"
        self.filters.button(0).setChecked(True)
        # self.source_filter.setCurrentText("全部来源")
        # 2026-10-12：本次修改原因：白底图建档后清除筛选并定位草稿。
        self.source_filter.setCurrentIndex(0)
        self.acquisition_filter.setCurrentIndex(0)
        self.search.clear()
        # 2026-10-11：本次修改原因：筛选刷新可能切换选中项，最后重新定位新草稿并更新速览图。
        self.current_product = creation.created_product
        # 2026-10-13：本次修改原因：自上传建档后定位白底图列表，继续使用原编辑和保存流程。
        self.change_product_source(1, reset_filters=False, render=False)
        # self.preview.set_url(creation.created_product.images[0])
        # 2026-10-13：本次修改原因：自上传商品通过列表定位和缩略图显示，不再访问右侧速览。
        self.refresh()
        product = creation.created_product
        # editor = ProductEditor(self.repository, product, self.network, self,
        #                        ai_service=self.ai_service, ai_hub=self.ai_hub)
        # editor.exec()
        # self.refresh()
        # 2026-10-13：本次修改原因：自上传商品与采集商品进入同一编辑页面，返回仍定位白底图列表。
        # self.open_product_editor(product)
        # # self.statusBar().showMessage("上传商品草稿已保存在商品库", 6000)
        # 2026-10-14：本次修改原因：仅明确点击创建并生成时自动启动；普通商品编辑不调用模型。
        self.open_product_editor(product)
        if creation.generate_listing:
            self.product_editor.start_white_listing(creation.defaults)
        # 2026-10-12：本次修改原因：自上传路线明确草稿和公网素材要求。
        # self.operation_feedback.setText("自上传商品已建档，可继续 AI 加工。白底图及生成图回传前需转换为公网链接。")
        # 2026-10-14：本次修改原因：已采用的本机图片在同步 ERP 时自动托管，提示与实际操作保持一致。
        self.operation_feedback.setText("自上传商品已建档，可继续 AI 加工。保存并审核后，同步 ERP 时会自动托管已采用的本机图片。")
        self.statusBar().showMessage("上传商品草稿已保存在商品加工", 6000)

    def open_source(self) -> None:
        if self.current_product and valid_url(self.current_product.source_url):
            QDesktopServices.openUrl(QUrl(self.current_product.source_url))

    # def run_task(self, work, callback) -> None:
    # 2026-10-12：本次修改原因：后台任务携带操作名称，错误反馈可理解。
    # def run_task(self, work, callback, description: str = "处理") -> None:
    #     task = Task(work)
    # 2026-10-12：本次修改原因：任务进度跨线程投递；普通查询保持兼容，批量同步按实际件数更新。
    def run_task(self, work, callback, description: str = "处理", *, with_progress: bool = False) -> None:
        task = Task(lambda: work(lambda value: task.signals.progress.emit(task, value))) if with_progress else Task(work)
        task.last_progress = {}
        task.signals.progress.connect(self.task_progressed, Qt.ConnectionType.QueuedConnection)
        task.callback = callback
        # 2026-10-12：本次修改原因：保存任务说明用于开始、完成及失败反馈。
        task.description = description
        self._tasks.add(task)
        self.import_button.setEnabled(False)
        # 2026-10-12：本次修改原因：查询导入与回传共用任务锁，处理期间不允许启动第二个 ERP 导入窗口。
        self.erp_import_button.setEnabled(False)
        # 2026-10-11：本次修改原因：后台任务运行时禁用回传按钮，避免重复发起同一批商品。
        self.erp_button.setEnabled(False)
        # self.erp_current_button.setEnabled(False)
        # 2026-10-11：本次修改原因：后台任务运行期间禁止换账号或重新绑定，避免查询和发送账号不一致。
        # self.erp_bind_button.setEnabled(False)
        # 2026-10-11：本次修改原因：防止同一未知记录被同时核对。
        # self.erp_reconcile_button.setEnabled(False)
        # 2026-10-13：本次修改原因：任务锁同步覆盖迁移后的行内操作和工具栏入口。
        self.edit_button.setEnabled(False)
        self.product_more_button.setEnabled(False)
        self.product_row_actions.busy = True
        self.product_table.viewport().update()
        self.miaoshou_settings.set_busy(True)
        self.erp_mode.setEnabled(False)
        # self.statusBar().showMessage("正在处理，请稍候…")
        # 2026-10-12：本次修改原因：任务期间锁住获取路线及重复操作并显示具体阶段。
        self.capture_route_save.setEnabled(False)
        self.capture_records_page.sync.setEnabled(False)
        self.capture_records_page.files.setEnabled(False)
        self.capture_records_page.reparse.setEnabled(False)
        self.erp_records_page.reconcile.setEnabled(False)
        self.operation_feedback.setText(description + "中，请稍候…")
        self.statusBar().showMessage(description + "中，请稍候…")
        # 2026-10-12：本次修改原因：底部信息栏和同步窗口共享任务状态，不使用虚假百分比。
        self.statusBar().clearMessage()
        self.task_progress_text.setText(description + "中，请稍候…")
        self.task_progress.setRange(0, 0)
        self.task_progress.show()
        self.delete_products_button.setEnabled(False)
        self.restore_products_button.setEnabled(False)
        self.capture_records_page.set_cleanup_busy(True)
        self.erp_records_page.set_cleanup_busy(True)
        self.recycle_bin_page.update_actions()
        for dialog in self.findChildren(MiaoshouImportDialog):
            dialog.set_busy(True)

        # def finish(result) -> None:
        #     self._tasks.discard(task)
        #     self.import_button.setEnabled(not self._tasks)
        #     self.refresh()
        #     callback(result)
        # def fail(message: str) -> None:
        #     self._tasks.discard(task)
        #     self.import_button.setEnabled(not self._tasks)
        #     self.refresh()
        #     self.statusBar().showMessage("处理失败，详细原因已写入日志", 6000)
        #     QMessageBox.warning(self, "处理失败", message)
        # task.signals.finished.connect(finish)
        # task.signals.failed.connect(fail)
        # 2026-10-10：本次修改原因：使用带主线程上下文的槽，保证 UI 操作不会落在工作线程。
        task.signals.finished.connect(self.task_finished, Qt.ConnectionType.QueuedConnection)
        task.signals.failed.connect(self.task_failed, Qt.ConnectionType.QueuedConnection)
        self.pool.start(task)

    @Slot(object, object)
    def task_finished(self, task, result) -> None:
        self._tasks.discard(task)
        self.import_button.setEnabled(not self._tasks)
        # 2026-10-12：本次修改原因：任务结束恢复 ERP 导入入口。
        self.erp_import_button.setEnabled(not self._tasks)
        self.refresh()
        # 2026-10-12：本次修改原因：完成反馈明确操作结束，具体结果由各入口继续展示。
        self.operation_feedback.setText(task.description + "已完成，请查看结果。")
        # 2026-10-12：本次修改原因：结束时复位进度及同步窗口，忽略后续旧进度信号。
        self.finish_task_feedback(task, failed=False)
        task.callback(result)

    @Slot(object, str)
    def task_failed(self, task, message: str) -> None:
        self._tasks.discard(task)
        self.import_button.setEnabled(not self._tasks)
        # 2026-10-12：本次修改原因：查询或导入失败后同样恢复 ERP 导入入口。
        self.erp_import_button.setEnabled(not self._tasks)
        self.refresh()
        # 2026-10-11：本次修改原因：连接测试失败后不让状态标签继续显示正在查询。
        if self.miaoshou_settings.status.text().startswith("正在查询"):
            self.miaoshou_settings.status.setText("连接测试失败：" + message)
        # self.statusBar().showMessage("处理失败，详细原因已写入日志", 6000)
        # QMessageBox.warning(self, "处理失败", message)
        # 2026-10-12：本次修改原因：失败后不残留处理中提示。
        self.operation_feedback.setText(task.description + "未完成：" + message)
        self.statusBar().showMessage(task.description + "未完成，查看提示后处理", 6000)
        # 2026-10-12：本次修改原因：异常也要停止进度动画并恢复清理/查询入口。
        self.finish_task_feedback(task, failed=True)
        for dialog in self.findChildren(MiaoshouImportDialog):
            dialog.status.setText("操作未完成：" + message)
        QMessageBox.warning(self, task.description + "未完成", message)

    # 2026-10-12：本次修改原因：真实进度仅由其所属的活动任务更新，避免完成后残留“请稍候”。
    @Slot(object, dict)
    def task_progressed(self, task, value: dict) -> None:
        if task not in self._tasks:
            return
        task.last_progress = value
        total, completed = value.get("total", 0), value.get("completed", 0)
        self.task_progress.setRange(0, max(1, total))
        self.task_progress.setValue(completed)
        text = (f"同步 {completed}/{total} · 新导入 {value.get('imported', 0)} · "
                f"已导入跳过 {value.get('existing', 0)} · 失败 {value.get('failed', 0)}")
        self.task_progress_text.setText(text)
        self.operation_feedback.setText(text)
        for dialog in self.findChildren(MiaoshouImportDialog):
            dialog.show_progress(value)

    # 2026-10-12：本次修改原因：所有终态都关闭忙碌动画；同步有部分失败时仍准确显示已完成件数。
    def finish_task_feedback(self, task, failed: bool) -> None:
        self.task_progress.setRange(0, 1)
        self.task_progress.setValue(0 if failed else 1)
        # 2026-10-13：本次修改原因：任务结束撤下进度条，保留短暂结果反馈，避免页面常驻空进度区域。
        self.task_progress.setVisible(bool(self._tasks))
        prefix = task.description + ("未完成" if failed else "已完成")
        counts = task.last_progress
        if counts:
            prefix += (f" · 导入 {counts.get('imported', 0)} · 跳过 {counts.get('existing', 0)}"
                       f" · 失败 {counts.get('failed', 0)}")
        self.task_progress_text.setText(prefix)
        self.statusBar().showMessage(prefix, 8000)
        self.delete_products_button.setEnabled(not self._tasks)
        self.restore_products_button.setEnabled(not self._tasks)
        self.capture_records_page.set_cleanup_busy(bool(self._tasks))
        self.erp_records_page.set_cleanup_busy(bool(self._tasks))
        self.recycle_bin_page.update_actions()
        for dialog in self.findChildren(MiaoshouImportDialog):
            dialog.set_busy(bool(self._tasks))

    def import_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择采集材料", "", "采集材料 (*.json *.har *.txt);;所有文件 (*)")
        if not paths:
            return

        def done(result: dict) -> None:
            rows = result["results"]
            failed = sum(row.get("state") == "解析失败" for row in rows)
            duplicates = sum(bool(row.get("duplicate")) or row.get("state") == "重复商品" for row in rows)
            text = f"已接收 {len(rows)} 条材料；重复 {duplicates} 条；解析失败 {failed} 条。"
            if result["errors"]:
                text += "\n\n" + "\n".join(result["errors"][:12])
            # text += "\n\n缺失字段和解析原因可在商品库 / 采集记录中查看。"
            # 2026-10-12：本次修改原因：文件接收结果指向新的加工入口。
            text += "\n\n缺失字段和解析原因可在商品加工 / 采集记录中查看。"
            QMessageBox.information(self, "导入结果", text)
            self.statusBar().showMessage("文件导入结束", 6000)

        # self.run_task(lambda: self.service.import_files(paths), done)
        # 2026-10-12：本次修改原因：文件处理提示明确接收来源，避免显示泛化的处理中。
        self.run_task(lambda: self.service.import_files(paths), done, "导入采集材料")

    def approve_selected(self) -> None:
        products = [self.repository.product(product_id) for product_id in self.checked_ids]
        # invalid = [product for product in products if product and product.issues()]
        # 2026-10-12：本次修改原因：批量审核也允许原商品未改动的物流占位，不能与单条审核规则不一致。
        invalid = [product for product in products if product and product.review_issues()]
        if invalid:
            # QMessageBox.warning(self, "请先完善商品", "以下商品尚不能审核：\n" + "\n".join(
            #     f"{product.title or product.source_id}：{product.review_issues()[0]}" for product in invalid[:12]))
            # 2026-10-12：本次修改原因：批量审核汇总所有已知问题，长清单放详情而不是只显示每件商品第一个错误。
            details = "\n\n".join(f"{product.title or product.source_id}：\n" + "\n".join(
                # f"• {issue}" for issue in product.review_issues()) for product in invalid)
                # 2026-10-14：本次修改原因：批量审核错误也能定位补充字段。
                "• " + explain_issue(issue) for issue in product.review_issues()) for product in invalid)
            notice = QMessageBox(self)
            notice.setIcon(QMessageBox.Icon.Warning)
            notice.setWindowTitle("请先完善商品")
            notice.setText(f"所选商品中有 {len(invalid)} 件存在字段格式、数量或必填问题，尚不能审核。")
            notice.setInformativeText("\n".join(details.splitlines()[:12]) + "\n完整问题清单请展开详情查看。")
            notice.setDetailedText(details)
            notice.exec()
            return
        if QMessageBox.question(self, "批量审核", f"确认已核对所选 {len(products)} 个商品的售价、币种、图片与 SKU？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for product in products:
            try:
                if product and not product.approved:
                    self.repository.save_product(product, approve=True)
            except Exception as error:
                errors.append(str(error))
        self.refresh()
        if errors:
            QMessageBox.warning(self, "部分商品未审核", "\n".join(errors[:12]))
        else:
            # 2026-10-12：本次修改原因：审核后指向接口回传及其独立条件检查。
            self.operation_feedback.setText("所选商品已审核。点击“传回妙手 ERP”，检查方式与目标后提交。")
            self.statusBar().showMessage("所选商品已审核，可以检查并回传", 6000)

    # 2026-10-11：本次修改原因：当前商品与勾选批量回传共用入口，冻结操作开始时选用的方式。
    def transfer_current(self) -> None:
        if self.current_product:
            self._transfer_products([self.current_product.id])

    def transfer_selected(self) -> None:
        self._transfer_products(list(self.checked_ids))

    # 2026-10-11：本次修改原因：统一中文确认按钮，避免英文 Yes/No 让用户误以为已经开始妙手回传。
    def _confirm_transfer(self, title: str, message: str, accept_text: str) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText(accept_text)
        dialog.button(QMessageBox.StandardButton.No).setText("取消")
        # 2026-10-13：本次修改原因：回传、覆盖、清空等确认默认取消，避免回车误操作。
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.setEscapeButton(QMessageBox.StandardButton.No)
        return dialog.exec() == QMessageBox.StandardButton.Yes

    # def _transfer_products(self, product_ids: list[str]) -> None:
        # if not product_ids or self._tasks:
            # return
        # mode = self.settings.erp_transfer_mode
        # if self.erp_service.unavailable_reason:
            # # 未接通时记录检查结果，不向用户展示“正在发送”的假状态。
            # notice = self.erp_service.unavailable_reason + "\n\n本次不会向妙手发送，只记录未发送原因，商品保持“未传”。"
            # if not self._confirm_transfer("回传尚未接通", notice + "\n\n是否继续记录？", "继续记录"):
                # return
        # elif not self._confirm_transfer(
                # # "确认传回妙手 ERP",
                # # f"将按“{MODE_LABELS[mode]}”处理 {len(product_ids)} 个商品。\n"
                # # "结果未知时请先到妙手核对。是否继续？",
                # # 2026-10-11：本次修改原因：实际发送前清楚说明目标为公共采集箱和操作方式。
                # "确认回传公共采集箱",
                # f"将按“{MODE_LABELS[mode]}”向妙手公共采集箱写入 {len(product_ids)} 个商品。\n"
                # "更新只合并本机修改过的字段。结果未知时请先到妙手核对。是否继续？",
                # "继续回传"):
            # return

        # def done(results: list[dict]) -> None:
            # counts = {state: sum(row.get("state") == state for row in results)
                      # for state in ("succeeded", "blocked", "failed", "unknown")}
            # message = (f"成功 {counts['succeeded']} 个 · 未发送 {counts['blocked']} 个 · "
                       # f"失败 {counts['failed']} 个 · 结果未知 {counts['unknown']} 个")
            # failures = [row for row in results if row.get("state") != "succeeded"]
            # if failures:
                # message += "\n\n" + "\n\n".join(row["message"] for row in failures[:3])
                # message += "\n\n完整原因见“回传记录”。"
            # QMessageBox.information(self, "回传处理结果", message)

        # self.run_task(lambda: self.erp_service.transfer(product_ids, mode), done)
    # 2026-10-12：本次修改原因：回传前统一检查并提供处理入口，回传后以记录和下一步承接结果。
    def _transfer_products(self, product_ids: list[str]) -> None:
        if not product_ids or self._tasks:
            return
        mode = self.settings.erp_transfer_mode
        if self.erp_service.unavailable_reason:
            # QMessageBox.information(self, "请先配置妙手 ERP", self.erp_service.unavailable_reason)
            # 2026-10-14：本次修改原因：未配凭证明确设置栏目。
            QMessageBox.information(self, "请先配置妙手 ERP", explain_errors(self.erp_service.unavailable_reason))
            self.open_settings(1)
            return
        problems = []
        for product_id in dict.fromkeys(product_ids):
            product = self.repository.product(product_id)
            # issues = self.erp_service.issues(product, mode) if product else ["商品不存在，请刷新。"]
            # 2026-10-14：本次修改原因：回传问题清单指向字段、配置及日志具体位置。
            issues = [explain_issue(issue) for issue in self.erp_service.issues(product, mode)] if product else ["商品不存在，请刷新。"]
            if any(row["product_id"] == product_id and row["state"] in {"sending", "unknown"} for row in self._erp_records):
                issues.append("已有回传进行中或结果未知，请先到回传记录核对。")
            if issues:
                problems.append((product_id, (product.title or product.main_code) if product else product_id, issues))
        if problems:
            # 2026-10-12：本次修改原因：检查失败留本机记录，不发送商品。
            record_errors = self.erp_service.record_preflight(
                [(product_id, issues) for product_id, _, issues in problems], mode,
                self.miaoshou_config.config.account_id)
            self.refresh()
            notice = QMessageBox(self)
            notice.setIcon(QMessageBox.Icon.Warning)
            notice.setWindowTitle("回传检查未通过")
            notice.setText(f"{len(problems)} 个商品需要处理，本次未向妙手发送。")
            details = "\n\n".join(title + "：\n" + "\n".join("• " + issue for issue in issues)
                                    for _, title, issues in problems)
            # 2026-10-12：本次修改原因：本机记录保存失败不能误报已留档。
            if record_errors:
                details += "\n\n回传记录未能完整保存：\n" + "\n".join(record_errors)
            # notice.setInformativeText("\n".join(details.splitlines()[:10]) + "\n完整问题可展开详情查看。")
            # 2026-10-14：本次修改原因：首屏显示具体补充位置，完整问题保留在详情。
            notice.setInformativeText("\n".join(details.splitlines()[:16]) + "\n完整问题和处理位置可展开详情查看。")
            notice.setDetailedText(details)
            process = notice.addButton("进入商品加工", QMessageBox.ButtonRole.ActionRole)
            records = notice.addButton("查看回传记录", QMessageBox.ButtonRole.ActionRole)
            notice.addButton("返回", QMessageBox.ButtonRole.RejectRole)
            notice.exec()
            self.operation_feedback.setText("回传检查未通过，本次未发送。请处理字段、素材、审核或待核对记录。")
            if notice.clickedButton() == process:
                self.focus_product(problems[0][0], edit=True)
            elif notice.clickedButton() == records:
                self.show_erp_records()
            return
        account = self.miaoshou_config.config.account_id[:8]
        if not self._confirm_transfer("确认传回妙手 ERP",
                f"目标账号：{account}\n写回位置：{TARGET_LABEL}\n"
                f"处理方式：{MODE_LABELS[mode]}\n商品数量：{len(product_ids)}\n"
                "字段检查已通过。更新只合并本机改动；保存成功后仍需在妙手完成发布。",
                "确认回传"):
            return

        def done(results: list[dict]) -> None:
            counts = {state: sum(row.get("state") == state for row in results)
                      for state in ("succeeded", "blocked", "failed", "unknown")}
            summary = (f"成功 {counts['succeeded']} 个 · 未发送 {counts['blocked']} 个 · "
                       f"失败 {counts['failed']} 个 · 待核对 {counts['unknown']} 个")
            self.operation_feedback.setText(summary + "。完整原因及下一步见回传记录。")
            notice = QMessageBox(self)
            notice.setWindowTitle("回传处理结果")
            notice.setText(summary)
            notice.setInformativeText("成功商品已写入公共采集箱。失败请查看原因；待核对商品不要重复新增。")
            view = notice.addButton("查看回传记录", QMessageBox.ButtonRole.ActionRole)
            notice.addButton("返回商品加工", QMessageBox.ButtonRole.RejectRole)
            notice.exec()
            if notice.clickedButton() == view:
                self.show_erp_records()

        self.run_task(lambda: self.erp_service.transfer(product_ids, mode, self.transfer_progress.emit),
                      done, "回传妙手 ERP")


    # 2026-10-11：本次修改原因：查看原始发送快照之外的任务摘要，说明失败原因和对应商品版本。
    # def show_erp_records(self) -> None:
        # records = self.repository.erp_transfers()
        # titles = {product.id: product.title or product.main_code for product in self._products}
        # lines = []
        # for record in records:
            # lines.append(
                # f"{readable_time(record['created_at'])}  {titles.get(record['product_id'], record['product_id'])}\n"
                # f"方式：{MODE_LABELS.get(record['mode'], record['mode'])}  ·  v{record['revision']}  ·  "
                # f"{STATE_LABELS.get(record['state'], record['state'])}\n"
                # f"记录：{record['id']}\n妙手目标：{record['target_id'] or '尚无'}\n{record['message']}"
                # # 2026-10-11：本次修改原因：显示真实接口响应以便核对错误码，服务层已剥离凭证和签名。
                # + "\n回执：" + json.dumps(json.loads(record["receipt"]), ensure_ascii=False, indent=2)
            # )
        # self.text_dialog("妙手回传记录", "\n\n".join(lines) or "暂无回传记录。")
    # 2026-10-12：本次修改原因：回传结果改为独立可筛选页面。
    def show_erp_records(self) -> None:
        self._erp_records = self.repository.erp_transfers()
        self.erp_records_page.refresh()
        # self.navigate(2)
        # 2026-10-13：本次修改原因：全部回传结果入口直接定位日志记录中的回传标签。
        self.logs_page.show_transfer_tab()
        self.navigate(self.PAGE_LOGS)


    # def selected_capture(self) -> dict | None:
        # row = self.capture_table.currentRow()
        # item = self.capture_table.item(row, 0) if row >= 0 else None
        # if not item:
            # QMessageBox.information(self, "选择记录", "请先选择一条采集记录。")
            # return None
        # return self.repository.capture(item.data(Qt.ItemDataRole.UserRole))

    # def show_raw(self) -> None:
        # record = self.selected_capture()
        # if not record:
            # return
        # try:
            # text = Path(record["raw_path"]).read_text(encoding="utf-8")
            # truncated = len(text) > 300_000
            # self.text_dialog("原始采集材料", text[:300_000] + ("\n\n【显示已截断，完整文件保存在下方路径】" if truncated else ""), record["raw_path"])
        # except OSError as error:
            # QMessageBox.warning(self, "读取失败", str(error))

    # def reparse_selected(self) -> None:
        # record = self.selected_capture()
        # if record:
            # # self.run_task(lambda: self.service.reparse(record["id"]),
            # #               lambda result: QMessageBox.information(self, "解析结果", f"结果：{result['state']}\n已有商品编辑会保留。"))
            # # 2026-10-11：本次修改原因：将补齐数量或失败原因直接反馈给用户。
            # self.run_task(lambda: self.service.reparse(record["id"]),
                          # lambda result: QMessageBox.information(
                              # self, "解析结果", f"结果：{result['state']}\n\n{result.get('message', '')}"))
    # 2026-10-12：本次修改原因：原始材料与重新解析入口已由采集记录页面接管，旧方法注释留存。

    # def update_connection(self) -> None:
        # running = self.receiver.server is not None and not self.receiver.error
        # self.receiver_badge.setText("● 本机接收运行中" if running else "● 本机接收未启动")
        # self.receiver_badge.setToolTip(self.receiver.error or self.settings.endpoint)
        # # self.connection_state.setText(f"运行中 · 127.0.0.1:{self.receiver.settings.port} · 插件尚需配置转发" if running else
        # #                               "启动失败：" + (self.receiver.error or "尚未启动") + "。仍可使用文件导入。")
        # # 2026-10-11：本次修改原因：仅展示本机实际状态，不推断浏览器是否已加载或配置插件。
        # self.connection_state.setText(f"运行中 · 127.0.0.1:{self.receiver.settings.port} · 请在扩展选项中测试连接" if running else
                                      # "启动失败：" + (self.receiver.error or "尚未启动") + "。仍可使用文件导入。")
    # 2026-10-12：本次修改原因：主界面展示当前获取路线，并支持记录直接定位商品与回传阶段。
    def update_connection(self) -> None:
        running = self.receiver.server is not None and not self.receiver.error
        plugin = self.settings.capture_route == "plugin"
        # self.import_button.setVisible(plugin)
        # 2026-10-13：本次修改原因：文件导入迁入更多菜单后，仍按原采集路线控制入口显隐。
        # self.import_file_action.setVisible(plugin)
        # self.erp_import_button.setVisible(not plugin)
        # 2026-10-13：本次修改原因：文件导入迁出顶部菜单，获取按钮随列表来源和原采集路线显示。
        self.update_product_intake()
        self.capture_route_save.setEnabled(not self._tasks)
        if plugin:
            self.receiver_badge.setText("● 插件同步运行中" if running else "● 插件同步未接通")
            self.receiver_badge.setToolTip(self.receiver.error or self.settings.endpoint)
        else:
            self.receiver_badge.setText("● 妙手接口待配置" if self.miaoshou_adapter.unavailable_reason else "● 妙手接口已配置")
            self.receiver_badge.setToolTip("点击同步采集箱查询商品；已配置不代表已验证全部接口权限。")
        self.connection_state.setText(
            (f"运行中 · 127.0.0.1:{self.receiver.settings.port} · 请在扩展选项测试连接" if running else
             "未启动：" + (self.receiver.error or "请检查监听端口")) if plugin else
            "备用插件同步已暂停。使用时在设置 → 采集路线选择插件同步并保存。")

    @Slot(str)
    def transfer_stage(self, message: str) -> None:
        if self._tasks:
            self.operation_feedback.setText(message)
            self.statusBar().showMessage(message)
            self._erp_records = self.repository.erp_transfers()
            self.populate_products()
            self.erp_records_page.refresh()

    def focus_product(self, product_id: str, edit: bool = False) -> None:
        # 2026-10-12：本次修改原因：历史记录关联的已移除商品先引导恢复，不悄悄重建。
        if product_id in self.repository.hidden_local_ids("products"):
            # QMessageBox.information(self, "商品在回收站", "请到商品加工点击“恢复回收站”后继续操作。")
            # 2026-10-13：本次修改原因：历史记录指向已移除商品时直接打开回收站，用户勾选恢复。
            QMessageBox.information(self, "商品在回收站", "即将打开回收站，勾选此商品后点击“恢复所选”。")
            self.open_recycle_bin("products")
            return
        product = self.repository.product(product_id)
        if not product:
            QMessageBox.information(self, "商品不存在", "该记录关联的商品不存在，请检查数据目录。")
            return
        self.active_filter = "全部"
        self.filters.button(0).setChecked(True)
        self.source_filter.setCurrentIndex(0)
        self.acquisition_filter.setCurrentIndex(0)
        self.search.clear()
        # self.current_product = product
        # self.refresh()
        # self.navigate(0)
        # 2026-10-12：本次修改原因：记录跳转后商品速览图片与选中商品一致。
        self.current_product = product
        # 2026-10-13：本次修改原因：日志跳转时切换到商品所属来源，只调整列表定位。
        self.change_product_source(1 if product.acquisition_route == "upload" else 0, reset_filters=False, render=False)
        # self.preview.set_url(product.images[0] if product.images else "")
        # 2026-10-13：本次修改原因：记录跳转后只定位商品行，主图由列表委托加载。
        self.refresh()
        self.navigate(0)
        if edit:
            self.edit_current()


    def copy_text(self, value: str) -> None:
        QApplication.clipboard().setText(value)
        self.statusBar().showMessage("已复制到剪贴板", 4000)

    def save_port(self) -> None:
        try:
            # saved = Settings(self.settings.data_dir, self.settings.token, self.port.value())
            # 2026-10-11：本次修改原因：保存端口时保留 ERP 回传方式；仅下一次启动应用新端口。
            # saved = Settings(self.settings.data_dir, self.settings.token, self.port.value(), self.settings.erp_transfer_mode)
            # 2026-10-12：本次修改原因：保存端口保留采集路线。
            saved = Settings(self.settings.data_dir, self.settings.token, self.port.value(), self.settings.erp_transfer_mode, self.settings.capture_route)
            saved.save()
            QMessageBox.information(self, "设置已保存", f"端口 {saved.port} 将在重启后生效。当前接收地址保持显示实际运行端口。")
        except OSError as error:
            QMessageBox.warning(self, "保存失败", str(error))

    # 2026-10-11：本次修改原因：回传方式保存后立即生效，并保留用户已保存但尚未重启的端口设置。
    def save_erp_mode(self) -> None:
        # 2026-10-11：本次修改原因：发送过程中保存按钮不应切换当前任务方式。
        if self._tasks:
            return
        try:
            target = self.settings.data_dir / "settings.json"
            content = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
            mode = str(self.erp_mode.currentData())
            # saved = Settings(self.settings.data_dir, self.settings.token, int(content.get("port", self.settings.port)), mode)
            # 2026-10-12：本次修改原因：保存回传方式保留采集路线及待重启端口。
            saved = Settings(self.settings.data_dir, self.settings.token, int(content.get("port", self.settings.port)), mode, self.settings.capture_route)
            saved.save()
            self.settings.erp_transfer_mode = mode
            self.update_selection()
            QMessageBox.information(self, "回传方式已保存", f"当前方式：{MODE_LABELS[mode]}。下一次回传立即使用。")
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "保存失败", str(error))

    def show_protocol(self) -> None:
        sample = {
            "eventId": "每次采集生成一个 UUID，重试沿用同一个值",
            "requestUrl": "https://kuajing-plw.happyporsche.com/open/fetch/pfti",
            "payload": {"source": "temu", "site": "US", "itemId": "实际商品 ID", "afterUrl": "实际商品 URL",
                        "pageContent": "压缩前的完整 HTML 字符串", "productExtInfo": '{"sizeChatInfo":null}'},
        }
        self.text_dialog("本机采集接入协议", "POST " + self.settings.endpoint + "\nContent-Type: application/json\n"
                         "Authorization: Bearer <连接设置中的接入密钥>\n\n" + json.dumps(sample, ensure_ascii=False, indent=2)
                         + "\n\nHTTP 200 + accepted:true 表示材料已留档，state 表示解析状态。"
                         "\n解析失败也会留档；传输失败应由插件独立重试，不阻断妙手上传。")

    # 2026-10-11：本次修改原因：显示回执时绑定当前配置账号，保留旧记录供核查。
    def erp_display_status(self, product: Product) -> str:
        # account = self.miaoshou_config.config.account_id
        # return product.erp_status if account and product.erp_account_id == account else "未传"
        # 2026-10-12：本次修改原因：回传列显示未发送、失败、待核对及需重传。
        return transfer_status(product, self.miaoshou_config.config.account_id, self._erp_records)

    # 2026-10-11：本次修改原因：关联对话框只读查询妙手，人工确认后写本地关联信息。
    def bind_erp_current(self) -> None:
        if self._tasks or not self.current_product:
            return
        if self.erp_service.unavailable_reason:
            QMessageBox.information(self, "请先配置妙手回传", self.erp_service.unavailable_reason)
            return
        product = self.repository.product(self.current_product.id)
        if product and MiaoshouBindingDialog(self.repository, product, self.miaoshou_adapter,
                                            self.run_task, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.statusBar().showMessage("已关联妙手公共采集箱原商品。关联没有修改妙手商品。", 6000)

    # 2026-10-11：本次修改原因：用户先在妙手确定候选目标，再读取详情精确核对，不自动猜测新增 ID。
    # def reconcile_erp_current(self) -> None:
        # if self._tasks or not self.current_product:
            # return
        # record = next((row for row in self.repository.erp_transfers(self.current_product.id) if row["state"] == "unknown"), None)
        # if not record:
            # QMessageBox.information(self, "无需核对", "当前商品没有结果未知的回传记录。")
            # return
        # snapshot = json.loads(record["snapshot"])
        # target, ok = QInputDialog.getText(self, "只读核对未知回传",
            # "请先在妙手公共采集箱核对标题、来源和发送时间。\n填写确认属于这次回传的妙手商品 ID；程序只读取详情，字段一致才确认成功。",
            # text=snapshot.get("erp_original_id", "") if record["mode"] == "update" else "")
        # if ok and target.strip():
            # self.run_task(lambda: self.erp_service.reconcile(record["id"], target.strip()),
                          # lambda message: QMessageBox.information(self, "核对结果", message))
    # 2026-10-12：本次修改原因：回传记录按所选的确切未知任务核对，避免误核另一条记录。
    def reconcile_erp_current(self) -> None:
        if self._tasks or not self.current_product:
            return
        record = next((row for row in self._erp_records
                       if row["product_id"] == self.current_product.id and row["state"] == "unknown"), None)
        if record:
            self.reconcile_erp_record(record)
        else:
            QMessageBox.information(self, "无需核对", "当前商品没有结果未知的回传记录。")

    def reconcile_erp_record(self, record: dict) -> None:
        if self._tasks or record["state"] != "unknown":
            return
        snapshot = json.loads(record["snapshot"])
        target, ok = QInputDialog.getText(self, "只读核对未知回传",
            "请先在妙手公共采集箱核对标题、来源和发送时间。\n填写属于该次回传的妙手商品 ID；字段一致才确认成功。",
            text=snapshot.get("erp_original_id", "") if record["mode"] == "update" else "")
        if ok and target.strip():
            self.run_task(lambda: self.erp_service.reconcile(record["id"], target.strip()),
                          lambda message: QMessageBox.information(self, "核对结果", message),
                          "只读核对回传")


    def text_dialog(self, title: str, text: str, path: str = "") -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(950, 670)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.addWidget(label(title, "sectionTitle"))
        viewer = QPlainTextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText(text)
        layout.addWidget(viewer, 1)
        if path:
            layout.addWidget(label(path, "muted", True))
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("关闭", dialog.accept, primary=True))
        layout.addLayout(actions)
        dialog.exec()

    def closeEvent(self, event) -> None:
        # if self._tasks:
        # 2026-10-11：本次修改原因：AI 任务进行中保护候选和素材留档。
        if self._tasks or self.ai_hub.busy:
            # 2026-10-12：本次修改原因：关闭提示覆盖同步、回传、核对及 AI 任务。
            QMessageBox.information(self, "任务正在进行", "请等待当前同步、回传、核对或 AI 任务完成后再关闭。")
            event.ignore()
            return
        # 2026-10-13：本次修改原因：关闭主窗口也须确认编辑页未保存内容，不因移除弹窗而丢失保护。
        editor = getattr(self, "product_editor", None)
        if editor is not None and not editor.reject():
            event.ignore()
            return
        # 2026-10-13：本次修改原因：关闭应用前同样保护独立爆款方案的未保存编辑。
        if not self.reference_analysis_page.can_leave():
            event.ignore()
            return
        # 2026-10-13：本次修改原因：退出前保存正常布局和列宽，不保存临时最大化状态。
        save_splitters(self)
        self.product_table.save_widths()
        super().closeEvent(event)
