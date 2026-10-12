# 2026-10-10：本次修改原因：实现围绕商品库、采集记录、导出记录和本机连接的电商桌面工作台。
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl
# 2026-10-10：本次修改原因：使用显式 Qt 槽接收跨线程任务信号。
from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, Slot
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
    # QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    # 2026-10-11：本次修改原因：在设置中提供插件连接与 AI 模型两个页面。
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..config import Settings
from ..exporter import export_products
# 2026-10-11：本次修改原因：商品库与设置复用回传方式、回执服务及任务状态。
from ..erp import ERPService, MODE_LABELS, STATE_LABELS
from ..models import Product, valid_url
from ..receiver import LocalReceiver
from ..service import CaptureService
from ..storage import Repository
from .editor import ProductEditor
from .widgets import ImagePreview, Task, button, card, icon, label
# 2026-10-11：本次修改原因：两条商品路线共用本机模型配置、素材、任务与 AI 服务。
from ..ai.config import ModelConfigStore
from ..ai.service import AIService
from ..assets import AssetStore
from .ai_runner import TaskHub
from .model_settings import ModelSettingsPage
from .product_creation import ProductCreation
# 2026-10-11：本次修改原因：商品编辑和两条建档路线共用官方公共采集箱适配器与独立凭证配置。
from ..miaoshou import MiaoshouAdapter
from ..miaoshou_config import MiaoshouConfigStore
from .miaoshou_binding import MiaoshouBindingDialog
from .miaoshou_settings import MiaoshouSettingsPage
# 2026-10-11：本次修改原因：核对未知回传时允许填写经人工在妙手找到的目标商品 ID。
from PySide6.QtWidgets import QInputDialog
# 2026-10-12：本次修改原因：商品库直接导入官方采集箱数据，插件接收及文件导入保持独立可用。
from .miaoshou_import import MiaoshouImportDialog


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


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, repository: Repository, service: CaptureService, receiver: LocalReceiver):
        super().__init__()
        self.settings, self.repository, self.service, self.receiver = settings, repository, service, receiver
        self.network = QNetworkAccessManager(self)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        # 2026-10-11：本次修改原因：启动时加载独立模型配置文件，所有编辑入口复用同一服务。
        self.model_config = ModelConfigStore(settings.data_dir)
        self.assets = AssetStore(settings.data_dir)
        self.ai_service = AIService(self.model_config, self.assets)
        # 2026-10-11：本次修改原因：两条商品路线保存后共用妙手回传适配层。
        # self.erp_service = ERPService(repository)
        # 2026-10-11：本次修改原因：加载本地开放平台凭证并注入真实公共采集箱适配器。
        self.miaoshou_config = MiaoshouConfigStore(settings.data_dir)
        self.miaoshou_adapter = MiaoshouAdapter(self.miaoshou_config)
        self.erp_service = ERPService(repository, self.miaoshou_adapter)
        self.ai_hub = TaskHub(self)
        self._tasks: set[Task] = set()
        self._products: list[Product] = []
        self.checked_ids: set[str] = set()
        self.active_filter = "全部"
        self.current_product: Product | None = None
        self.setWindowTitle("BeadDiff · 商品工作台")
        self.resize(1500, 930)
        self.setMinimumSize(1180, 760)
        self.setWindowIcon(icon("products", "#138b78"))
        container = QWidget()
        self.setCentralWidget(container)
        root = QHBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())
        workspace = QWidget()
        workspace.setObjectName("workspace")
        self.workspace_layout = QVBoxLayout(workspace)
        self.workspace_layout.setContentsMargins(28, 26, 28, 18)
        self.workspace_layout.setSpacing(18)
        root.addWidget(workspace, 1)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._products_page())
        self.stack.addWidget(self._captures_page())
        self.stack.addWidget(self._exports_page())
        self.stack.addWidget(self._settings_page())
        self.workspace_layout.addWidget(self.stack, 1)
        self.statusBar().showMessage("就绪 · 原始材料与编辑版本保存在本机")
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(300)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh()

    def _sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 28, 18, 24)
        layout.setSpacing(8)
        brand = QHBoxLayout()
        badge = label("BD", "brandBadge")
        badge.setFixedSize(38, 38)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(badge)
        brand.addWidget(label("BeadDiff", "brand"))
        layout.addLayout(brand)
        layout.addSpacing(34)
        layout.addWidget(label("商品运营", "navCaption"))
        layout.addSpacing(6)
        self.navigation = QButtonGroup(self)
        for index, (text, symbol) in enumerate([
            # ("商品库", "products"), ("采集记录", "capture"), ("导出记录", "export"), ("连接设置", "settings"),
            # 2026-10-11：本次修改原因：统一设置入口容纳插件连接与模型管理。
            ("商品库", "products"), ("采集记录", "capture"), ("导出记录", "export"), ("设置", "settings"),
        ]):
            item = button(text)
            item.setObjectName("navButton")
            item.setCheckable(True)
            item.setIcon(icon(symbol, "#a2c4c1"))
            self.navigation.addButton(item, index)
            layout.addWidget(item)
            if index == 0:
                item.setChecked(True)
        self.navigation.idClicked.connect(self.navigate)
        layout.addStretch()
        layout.addWidget(label("LOCAL WORKSPACE", "navCaption"))
        layout.addWidget(label("v0.1.0  /  本机桌面版", "navCaption"))
        return sidebar

    def navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.navigation.button(index).setChecked(True)
        if index == 3:
            self.update_connection()
            # 2026-10-11：本次修改原因：编辑窗口修改模型后，设置页展示最新配置。
            self.model_settings.refresh()

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
        layout.setSpacing(18)
        # heading, _ = self._heading("商品工作台", "采集素材集中管理，完善商品后交给妙手导入")
        # 2026-10-12：本次修改原因：增加 ERP 数据入口后把建档操作移至独立一行，避免标题区挤压。
        heading, _ = self._heading("商品工作台", "管理采集与上传商品，编辑后回传妙手公共采集箱")
        self.receiver_badge = label("正在初始化", "statusBadge")
        heading.addWidget(self.receiver_badge)
        heading.addSpacing(8)
        heading.addWidget(button("刷新", self.refresh))
        # 2026-10-11：本次修改原因：白底图路线直接建草稿并进入共用商品编辑页。
        # heading.addWidget(button("上传白底图建商品", self.create_from_photos, symbol="import"))
        self.import_button = button("导入采集文件", self.import_files, primary=True, symbol="import")
        # heading.addWidget(self.import_button)
        layout.addLayout(heading)
        # 2026-10-12：本次修改原因：ERP 查询导入作为主要建档入口，另外两条本机素材路线仍可直接操作。
        intake = QHBoxLayout()
        self.erp_import_button = button("从妙手采集箱导入", self.import_miaoshou, primary=True, symbol="import")
        intake.addWidget(self.erp_import_button)
        intake.addWidget(button("上传白底图建商品", self.create_from_photos, symbol="import"))
        intake.addWidget(self.import_button)
        intake.addStretch()
        layout.addLayout(intake)
        metrics = QHBoxLayout()
        metrics.setSpacing(14)
        self.count_labels = {}
        for key, title, hint in [
            ("全部", "商品总数", "采集素材沉淀为商品"), ("待完善", "待完善", "补充字段、规格及售价"),
            ("待审核", "待审核", "人工确认后方可导出"), ("已审核", "已审核", "可选择导出妙手表格"),
        ]:
            frame, contents = card()
            contents.setSpacing(5)
            contents.addWidget(label(title, "hint"))
            value = label("0", "count")
            contents.addWidget(value)
            contents.addWidget(label(hint, "muted"))
            self.count_labels[key] = value
            metrics.addWidget(frame)
        layout.addLayout(metrics)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        catalog, catalog_layout = card()
        catalog_layout.setContentsMargins(0, 0, 0, 10)
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(16, 14, 16, 0)
        self.filters = QButtonGroup(self)
        for index, title in enumerate(["全部", "待完善", "待审核", "已审核"]):
            item = button(title)
            item.setObjectName("filterTab")
            item.setCheckable(True)
            item.setChecked(index == 0)
            self.filters.addButton(item, index)
            filter_row.addWidget(item)
        self.filters.idClicked.connect(self.filter_changed)
        filter_row.addStretch()
        catalog_layout.addLayout(filter_row)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(18, 0, 18, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索商品名称 / 商品编号 / SKU")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.populate_products)
        search_row.addWidget(self.search, 1)
        self.source_filter = QComboBox()
        self.source_filter.addItems(["全部来源", "temu"])
        self.source_filter.currentTextChanged.connect(self.populate_products)
        search_row.addWidget(self.source_filter)
        catalog_layout.addLayout(search_row)
        selection = QHBoxLayout()
        selection.setContentsMargins(18, 0, 18, 0)
        self.select_all = QCheckBox("本页全选")
        self.select_all.toggled.connect(self.check_all)
        selection.addWidget(self.select_all)
        self.selected_label = label("已选 0 项", "muted")
        selection.addWidget(self.selected_label)
        selection.addWidget(button("清空", self.clear_selection))
        selection.addStretch()
        self.approve_button = button("批量审核", self.approve_selected)
        selection.addWidget(self.approve_button)
        # self.export_button = button("导出妙手表格", self.export_selected, primary=True, symbol="export")
        # 2026-10-11：本次修改原因：表格导出与回传分开；批量回传单独放在下一行，避免挤压列表工具栏。
        self.export_button = button("导出妙手表格", self.export_selected, symbol="export")
        selection.addWidget(self.export_button)
        catalog_layout.addLayout(selection)
        # 2026-10-11：本次修改原因：批量回传入口显示当前设置方式，并允许查看可追溯的回传记录。
        erp_actions = QHBoxLayout()
        erp_actions.setContentsMargins(18, 0, 18, 0)
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
        self.product_table = table(["", "商品 / 主编号", "来源", "SKU", "状态", "修改", "传回 ERP", "更新"])
        for col, width in enumerate([42, 270, 70, 50, 78, 72, 90, 100]):
            self.product_table.setColumnWidth(col, width)
        self.product_table.horizontalHeader().setStretchLastSection(False)
        self.product_table.horizontalHeader().setMinimumSectionSize(42)
        self.product_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.product_table.itemChanged.connect(self.check_changed)
        self.product_table.itemSelectionChanged.connect(self.product_selected)
        self.product_table.itemDoubleClicked.connect(lambda _item: self.edit_current())
        catalog_layout.addWidget(self.product_table, 1)
        # self.product_empty = label("还没有商品\n导入 pfti 请求 JSON / HAR，或在连接设置中配置插件转发。", "empty", True)
        # 2026-10-11：本次修改原因：为空商品库提供采集与上传两条可操作路线。
        self.product_empty = label("还没有商品\n导入采集文件、配置插件同步，或上传白底图创建商品。", "empty", True)
        self.product_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        catalog_layout.addWidget(self.product_empty)
        self.product_summary = label("共 0 个商品", "muted")
        self.product_summary.setContentsMargins(18, 3, 18, 0)
        catalog_layout.addWidget(self.product_summary)
        splitter.addWidget(catalog)
        splitter.addWidget(self._inspector())
        splitter.setSizes([850, 300])
        layout.addWidget(splitter, 1)
        return page

    def _inspector(self) -> QFrame:
        frame, contents = card()
        frame.setMinimumWidth(265)
        frame.setMaximumWidth(365)
        contents.addWidget(label("商品速览", "sectionTitle"))
        self.preview = ImagePreview(self.network, 190)
        contents.addWidget(self.preview)
        self.inspector_title = label("选择商品查看详情", "sectionTitle", True)
        contents.addWidget(self.inspector_title)
        self.inspector_meta = label("商品信息与待完善项将在此显示", "muted", True)
        contents.addWidget(self.inspector_meta)
        self.inspector_status = label("", "hint", True)
        contents.addWidget(self.inspector_status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.inspector_issues = label("从采集记录可查看原始材料及解析结果。", "hint", True)
        self.inspector_issues.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.inspector_issues)
        contents.addWidget(scroll, 1)
        self.edit_button = button("编辑商品与 SKU", self.edit_current, primary=True)
        self.source_button = button("打开货源页面", self.open_source)
        contents.addWidget(self.edit_button)
        # 2026-10-11：本次修改原因：速览提供当前单商品回传入口，与勾选批量操作共用业务逻辑。
        self.erp_current_button = button("传回妙手 ERP", self.transfer_current, symbol="export")
        contents.addWidget(self.erp_current_button)
        # 2026-10-11：本次修改原因：更新前先查询并人工确认原商品，避免误用平台商品 ID。
        self.erp_binding_hint = label("", "hint", True)
        contents.addWidget(self.erp_binding_hint)
        self.erp_bind_button = button("关联妙手原商品", self.bind_erp_current)
        contents.addWidget(self.erp_bind_button)
        # 2026-10-11：本次修改原因：超时后查询实际详情，不能直接重发新增或手动勾选已传。
        self.erp_reconcile_button = button("核对未知回传（只读）", self.reconcile_erp_current)
        contents.addWidget(self.erp_reconcile_button)
        # 2026-10-12：本次修改原因：本机商品提供留存的完整 ERP 导入详情查看入口，便于比较未展示的规格/附件字段。
        self.erp_snapshot_button = button("查看妙手导入原始详情", self.show_miaoshou_snapshot)
        contents.addWidget(self.erp_snapshot_button)
        contents.addWidget(self.source_button)
        return frame

    def _captures_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        heading, _ = self._heading("采集记录", "每次接收独立留档，解析异常可追溯")
        heading.addWidget(button("导入采集文件", self.import_files, primary=True, symbol="import"))
        layout.addLayout(heading)
        frame, contents = card()
        actions = QHBoxLayout()
        self.capture_count = label("共 0 条记录", "sectionTitle")
        actions.addWidget(self.capture_count)
        actions.addStretch()
        actions.addWidget(button("查看原始材料", self.show_raw))
        actions.addWidget(button("重新解析", self.reparse_selected))
        contents.addLayout(actions)
        self.capture_table = table(["接收时间", "来源 / 站点", "商品 ID", "结果", "说明"])
        for col, width in enumerate([120, 140, 180, 110]):
            self.capture_table.setColumnWidth(col, width)
        self.capture_table.itemDoubleClicked.connect(lambda _item: self.show_raw())
        contents.addWidget(self.capture_table, 1)
        self.capture_empty = label("暂无采集记录。插件转发接通后，材料会自动出现在这里。", "empty", True)
        contents.addWidget(self.capture_empty)
        # contents.addWidget(label("重新解析只处理留档材料；已有商品及人工修改会保留。", "hint"))
        # 2026-10-11：本次修改原因：重新解析可以补齐旧商品缺失字段，明确人工编辑保护和复审要求。
        contents.addWidget(label("重新解析会补齐留档中的 SKU、属性与图片；保留人工编辑、主动清空及移除的 SKU。更新后需重新审核。", "hint", True))
        layout.addWidget(frame, 1)
        return page

    def _exports_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        heading, _ = self._heading("导出记录", "追踪导出文件、商品数量与对应编辑版本")
        heading.addWidget(button("前往商品库", lambda: self.navigate(0), primary=True))
        layout.addLayout(heading)
        layout.addWidget(label("本版按妙手模板字段生成 .xlsx，需先在妙手验证导入兼容性。发布操作仍在妙手完成。", "warning", True))
        frame, contents = card()
        actions = QHBoxLayout()
        self.export_count = label("共 0 次导出", "sectionTitle")
        actions.addWidget(self.export_count)
        actions.addStretch()
        actions.addWidget(button("打开文件", self.open_export))
        actions.addWidget(button("打开所在目录", lambda: self.open_export(True)))
        contents.addLayout(actions)
        self.export_table = table(["导出时间", "文件名", "商品数", "SKU 数", "保存位置"])
        for col, width in enumerate([130, 240, 90, 90]):
            self.export_table.setColumnWidth(col, width)
        self.export_table.itemDoubleClicked.connect(lambda _item: self.open_export())
        contents.addWidget(self.export_table, 1)
        self.export_empty = label("暂无导出记录。请在商品库勾选已审核商品，再导出妙手表格。", "empty", True)
        contents.addWidget(self.export_empty)
        layout.addWidget(frame, 1)
        return page

    def _settings_page(self) -> QWidget:
        # 2026-10-11：本次修改原因：模型配置放入独立可点击设置页面，保留插件连接功能。
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        # heading, _ = self._heading("设置", "管理插件连接与当前使用的 AI 模型")
        # 2026-10-11：本次修改原因：设置页增加独立的妙手回传栏目，避免开关隐藏在插件接收设置内。
        heading, _ = self._heading("设置", "管理插件连接、AI 模型与妙手回传方式")
        layout.addLayout(heading)
        tabs = QTabWidget()
        tabs.addTab(self._connection_settings_page(), "插件连接")
        self.model_settings = ModelSettingsPage(self.model_config, self.assets, self.ai_hub, self)
        tabs.addTab(self.model_settings, "AI 模型")
        tabs.addTab(self._erp_settings_page(), "妙手回传")
        layout.addWidget(tabs, 1)
        return page

    # 2026-10-11：本次修改原因：配置新增或更新开关，默认新增，并明确真实接口接通状态。
    def _erp_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        frame, contents = card()
        contents.addWidget(label("回传目标", "sectionTitle"))
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
        # contents.addWidget(label("只有妙手确认保存成功才显示“已传”。导出表格、原采集提交及 AI 生成完成不会改变回传状态；发布仍在妙手完成。", "hint", True))
        # contents.addWidget(button("查看回传记录", self.show_erp_records))
        # layout.addWidget(frame)
        # layout.addStretch()
        # 2026-10-11：本次修改原因：用可编辑的凭证设置及只读测试替代静态“未接通”提示。
        self.miaoshou_settings = MiaoshouSettingsPage(self.miaoshou_config, self.miaoshou_adapter,
                                                     self.run_task, self.refresh, self)
        layout.addWidget(self.miaoshou_settings, 1)
        layout.addWidget(button("查看回传记录", self.show_erp_records))
        return page

    # def _settings_page(self) -> QWidget:
    # 2026-10-11：本次修改原因：将原连接页作为设置子页面使用。
    def _connection_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        heading, _ = self._heading("连接设置", "让浏览器插件把采集材料同步到本机工作台")
        layout.addLayout(heading)
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
        contents.addWidget(label("服务仅监听 127.0.0.1。修改端口后重启软件生效，插件端也需更新地址。", "hint", True))
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
        storage, contents = card()
        contents.addWidget(label("本机数据", "sectionTitle"))
        contents.addWidget(label(str(self.settings.data_dir), "hint", True))
        contents.addWidget(label("商品库、原始采集文件、编辑版本和日志均保存在 data 目录；备份时请先关闭软件。", "hint", True))
        contents.addWidget(button("打开数据目录", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.settings.data_dir)))))
        body_layout.addWidget(storage)
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        return page

    @Slot()
    def schedule_refresh(self) -> None:
        self.refresh_timer.start()

    def refresh(self) -> None:
        self._products = self.repository.products()
        existing = {product.id for product in self._products}
        self.checked_ids.intersection_update(existing)
        for key, widget in self.count_labels.items():
            widget.setText(str(len(self._products) if key == "全部" else sum(product.status == key for product in self._products)))
        source = self.source_filter.currentText()
        self.source_filter.blockSignals(True)
        self.source_filter.clear()
        self.source_filter.addItems(["全部来源"] + sorted({"temu"} | {product.source for product in self._products}))
        self.source_filter.setCurrentText(source)
        self.source_filter.blockSignals(False)
        self.populate_products()
        captures = self.repository.captures()
        self.capture_count.setText(f"共 {len(captures)} 条记录")
        self.capture_empty.setVisible(not captures)
        self.capture_table.setRowCount(len(captures))
        for row, capture in enumerate(captures):
            values = [readable_time(capture["received_at"]), f"{capture['source'].upper()} / {capture['site'] or '—'}",
                      capture["source_id"], capture["state"], capture["message"]]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                item.setData(Qt.ItemDataRole.UserRole, capture["id"])
                if col == 3:
                    item.setForeground(QColor("#b56936" if value in {"解析失败", "待补充"} else "#168371"))
                self.capture_table.setItem(row, col, item)
        exports = self.repository.exports()
        self.export_count.setText(f"共 {len(exports)} 次导出")
        self.export_empty.setVisible(not exports)
        self.export_table.setRowCount(len(exports))
        for row, record in enumerate(exports):
            values = [readable_time(record["created_at"]), Path(record["path"]).name,
                      str(record["product_count"]), str(record["sku_count"]), record["path"]]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                item.setData(Qt.ItemDataRole.UserRole, record["path"])
                self.export_table.setItem(row, col, item)
        self.update_connection()

    def filter_changed(self, index: int) -> None:
        self.active_filter = ["全部", "待完善", "待审核", "已审核"][index]
        self.populate_products()

    def populate_products(self, *_args) -> None:
        query = self.search.text().strip().casefold()
        source = self.source_filter.currentText()
        filtered = [product for product in self._products
                    if (self.active_filter == "全部" or product.status == self.active_filter)
                    and (source == "全部来源" or product.source == source)
                    and (not query or query in " ".join([product.title, product.main_code, product.source_id]
                         + [sku.platform_sku for sku in product.skus]).casefold())]
        previous = self.current_product.id if self.current_product else ""
        self.product_table.blockSignals(True)
        self.product_table.setRowCount(len(filtered))
        selected_row = 0
        for row, product in enumerate(filtered):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Checked if product.id in self.checked_ids else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, product.id)
            self.product_table.setItem(row, 0, check)
            # values = [f"{product.title or '未识别标题 · 请完善'}\n{product.main_code}", product.source.upper(),
            #           str(len(product.skus)), product.status, readable_time(product.updated_at)]
            # 2026-10-11：本次修改原因：列表显示保存的内容修改与可信回执对应状态。
            values = [f"{product.title or '未识别标题 · 请完善'}\n{product.main_code}", product.source.upper(),
                      # str(len(product.skus)), product.status, product.modification_status, product.erp_status,
                      # 2026-10-11：本次修改原因：账号变化后不能把旧账号的成功回执显示为当前账号已传。
                      str(len(product.skus)), product.status, product.modification_status, self.erp_display_status(product),
                      readable_time(product.updated_at)]
            for col, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if col == 4:
                    item.setForeground(QColor({"待完善": "#b87a2c", "待审核": "#4282ad", "已审核": "#168371"}[product.status]))
                # 2026-10-11：本次修改原因：通过颜色和说明区分修改状态以及内容是否已回传。
                if col == 5:
                    item.setForeground(QColor("#4282ad" if product.content_modified else "#70888d"))
                    item.setToolTip("商品内容已修改并保存" if product.content_modified else "尚无已保存的内容修改")
                if col == 6:
                    item.setForeground(QColor("#168371" if value == "已传" else "#70888d"))
                    hint = "当前内容尚未取得妙手成功回执。"
                    if product.erp_transferred_at:
                        hint = f"最近成功回传：{readable_time(product.erp_transferred_at)}\n方式：{MODE_LABELS.get(product.erp_transfer_mode, product.erp_transfer_mode)}\n妙手目标 ID：{product.erp_target_id}"
                        if value == "未传":
                            hint += "\n当前内容与上次已传内容不同，需重新回传。"
                    item.setToolTip(hint)
                self.product_table.setItem(row, col, item)
            if product.id == previous:
                selected_row = row
        self.product_table.blockSignals(False)
        self.product_empty.setVisible(not filtered)
        # self.product_empty.setText("没有符合筛选条件的商品。" if self._products else
        #                            "还没有商品\n导入 pfti 请求 JSON / HAR，或在连接设置中配置插件转发。")
        # 2026-10-11：本次修改原因：刷新后仍展示采集与白底图两条路线。
        self.product_empty.setText("没有符合筛选条件的商品。" if self._products else
                                   "还没有商品\n导入采集文件、配置插件同步，或上传白底图创建商品。")
        self.product_summary.setText(f"当前 {len(filtered)} 个商品  /  商品库共 {len(self._products)} 个    ·    双击编辑")
        if filtered:
            self.product_table.selectRow(selected_row)
        self.product_selected()
        self.update_selection()

    def product_selected(self) -> None:
        row = self.product_table.currentRow()
        item = self.product_table.item(row, 0) if row >= 0 else None
        product_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        product = next((value for value in self._products if value.id == product_id), None)
        previous_url = self.current_product.images[0] if self.current_product and self.current_product.images else ""
        self.current_product = product
        self.edit_button.setEnabled(product is not None)
        self.erp_current_button.setEnabled(product is not None and not self._tasks)
        # 2026-10-11：本次修改原因：查询、发送期间锁住关联和凭证编辑，保持同一账号的任务快照。
        self.erp_bind_button.setEnabled(product is not None and not self._tasks)
        # 2026-10-12：本次修改原因：API 商品已有稳定原商品关联，不使用按平台规格猜测的重新关联流程。
        if product and product.erp_imported:
            self.erp_bind_button.setEnabled(False)
        # 2026-10-11：本次修改原因：只读核对复用后台任务状态。
        self.erp_reconcile_button.setEnabled(product is not None and not self._tasks)
        # 2026-10-12：本次修改原因：仅 API 导入商品具有远端快照，插件原始材料仍从采集记录查看。
        self.erp_snapshot_button.setEnabled(bool(product and product.erp_remote_snapshot))
        self.miaoshou_settings.set_busy(bool(self._tasks))
        self.erp_mode.setEnabled(not self._tasks)
        self.erp_binding_hint.setText(
            (f"公共采集箱原商品 ID：{product.erp_original_id}" if product.erp_original_id else "更新前请先关联妙手原商品")
            if product else "")
        self.source_button.setEnabled(bool(product and valid_url(product.source_url)))
        if not product:
            self.inspector_title.setText("选择商品查看详情")
            self.inspector_meta.setText("商品信息与待完善项将在此显示")
            self.inspector_status.setText("")
            self.inspector_issues.setText("从采集记录可查看原始材料及解析结果。")
            self.preview.set_url("")
            return
        current_url = product.images[0] if product.images else ""
        if current_url != previous_url:
            self.preview.set_url(current_url)
        self.inspector_title.setText(product.title or "未识别标题")
        # self.inspector_meta.setText(f"{product.source.upper()} · {product.site or '站点未提供'}\n{product.source_id}\n{len(product.skus)} 个 SKU  ·  v{product.revision}")
        # 2026-10-11：本次修改原因：商品速览显示素材数量，便于对比妙手采集结果。
        self.inspector_meta.setText(
            f"{product.source.upper()} · {product.site or '站点未提供'}\n{product.source_id}\n"
            f"{len(product.skus)} 个 SKU  ·  {len(product.attributes)} 项属性  ·  v{product.revision}\n"
            f"主图 {len(product.images)} 张  ·  详情图 {len(product.detail_images)} 张"
            + ("  ·  有视频" if product.video else ""))
        # 2026-10-12：本次修改原因：商品库区分 API 导入与原始插件接收，并提供完整远端快照查看入口。
        if product.erp_imported:
            self.inspector_meta.setText(self.inspector_meta.text() + "\n数据来源：妙手 API 导入")
        # self.inspector_status.setText(f"{product.status}  ·  售价币种 {product.currency or '待确认'}")
        # 2026-10-11：本次修改原因：速览与商品列表展示相同的修改和回传状态。
        self.inspector_status.setText(f"{product.status}  ·  售价币种 {product.currency or '待确认'}\n"
                                      # f"{product.modification_status}  ·  传回 ERP：{product.erp_status}")
                                      # 2026-10-11：本次修改原因：速览与列表一致按当前账号展示回传状态。
                                      f"{product.modification_status}  ·  传回 ERP：{self.erp_display_status(product)}")
        # issues = product.issues()
        # 2026-10-12：本次修改原因：速览问题清单与 API 原商品增量审核保持一致。
        issues = product.review_issues()
        text = "待完善\n" + "\n".join(f"• {issue}" for issue in issues[:14]) if issues else "必填信息已完善，请人工核对来源、售价和规格。"
        if product.warnings:
            text += "\n\n采集提示\n" + "\n".join(f"• {warning}" for warning in product.warnings)
        self.inspector_issues.setText(text)

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
        self.erp_mode_hint.setText("回传方式：" + MODE_LABELS[self.settings.erp_transfer_mode])
        self.approve_button.setEnabled(bool(self.checked_ids))
        self.export_button.setEnabled(bool(self.checked_ids))
        checked = self.product_table.rowCount() > 0 and all(
            self.product_table.item(row, 0).checkState() == Qt.CheckState.Checked for row in range(self.product_table.rowCount()))
        self.select_all.blockSignals(True)
        self.select_all.setChecked(checked)
        self.select_all.blockSignals(False)

    def check_all(self, checked: bool) -> None:
        for row in range(self.product_table.rowCount()):
            self.product_table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def clear_selection(self) -> None:
        self.checked_ids.clear()
        self.populate_products()

    def edit_current(self) -> None:
        if self.current_product:
            product = self.repository.product(self.current_product.id)
            # if product and ProductEditor(self.repository, product, self.network, self).exec() == QDialog.DialogCode.Accepted:
            # 2026-10-11：本次修改原因：采集商品编辑调用共用 AI 服务，表单应用后再由用户保存。
            if product and ProductEditor(self.repository, product, self.network, self,
                                         ai_service=self.ai_service, ai_hub=self.ai_hub).exec() == QDialog.DialogCode.Accepted:
                self.refresh()
                self.statusBar().showMessage("商品已保存，编辑版本已记录", 6000)

    # 2026-10-12：本次修改原因：API 导入自动关联原商品，返回商品库定位最后导入项，编辑与 AI 不需要另写流程。
    def import_miaoshou(self) -> None:
        if self._tasks:
            return
        if self.erp_service.unavailable_reason:
            QMessageBox.information(self, "请先配置妙手接口", self.erp_service.unavailable_reason + "\n请进入设置 → 妙手回传填写凭证。")
            return
        dialog = MiaoshouImportDialog(self.repository, self.miaoshou_adapter, self.run_task, self)
        dialog.exec()
        if dialog.last_product_id:
            self.active_filter = "全部"
            self.filters.button(0).setChecked(True)
            self.source_filter.setCurrentText("全部来源")
            self.search.clear()
            self.current_product = self.repository.product(dialog.last_product_id)
        self.refresh()

    # 2026-10-12：本次修改原因：查看首次导入的全部字段不发起网络请求，也不覆盖本机工作内容。
    def show_miaoshou_snapshot(self) -> None:
        if self.current_product and self.current_product.erp_remote_snapshot:
            self.text_dialog("妙手 API 原始详情（首次导入快照）",
                             json.dumps(self.current_product.erp_remote_snapshot, ensure_ascii=False, indent=2))

    # 2026-10-11：本次修改原因：上传商品与采集商品共用编辑、版本和 AI 处理流程。
    def create_from_photos(self) -> None:
        creation = ProductCreation(self.repository, self.assets, self)
        if creation.exec() != QDialog.DialogCode.Accepted or not creation.created_product:
            return
        # self.current_product = creation.created_product
        self.active_filter = "全部"
        self.filters.button(0).setChecked(True)
        self.source_filter.setCurrentText("全部来源")
        self.search.clear()
        # 2026-10-11：本次修改原因：筛选刷新可能切换选中项，最后重新定位新草稿并更新速览图。
        self.current_product = creation.created_product
        self.preview.set_url(creation.created_product.images[0])
        self.refresh()
        product = creation.created_product
        editor = ProductEditor(self.repository, product, self.network, self,
                               ai_service=self.ai_service, ai_hub=self.ai_hub)
        editor.exec()
        self.refresh()
        self.statusBar().showMessage("上传商品草稿已保存在商品库", 6000)

    def open_source(self) -> None:
        if self.current_product and valid_url(self.current_product.source_url):
            QDesktopServices.openUrl(QUrl(self.current_product.source_url))

    def run_task(self, work, callback) -> None:
        task = Task(work)
        task.callback = callback
        self._tasks.add(task)
        self.import_button.setEnabled(False)
        # 2026-10-12：本次修改原因：查询导入与回传共用任务锁，处理期间不允许启动第二个 ERP 导入窗口。
        self.erp_import_button.setEnabled(False)
        # 2026-10-11：本次修改原因：后台任务运行时禁用回传按钮，避免重复发起同一批商品。
        self.erp_button.setEnabled(False)
        self.erp_current_button.setEnabled(False)
        # 2026-10-11：本次修改原因：后台任务运行期间禁止换账号或重新绑定，避免查询和发送账号不一致。
        self.erp_bind_button.setEnabled(False)
        # 2026-10-11：本次修改原因：防止同一未知记录被同时核对。
        self.erp_reconcile_button.setEnabled(False)
        self.miaoshou_settings.set_busy(True)
        self.erp_mode.setEnabled(False)
        self.statusBar().showMessage("正在处理，请稍候…")

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
        self.statusBar().showMessage("处理失败，详细原因已写入日志", 6000)
        QMessageBox.warning(self, "处理失败", message)

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
            text += "\n\n缺失字段和解析原因可在商品库 / 采集记录中查看。"
            QMessageBox.information(self, "导入结果", text)
            self.statusBar().showMessage("文件导入结束", 6000)

        self.run_task(lambda: self.service.import_files(paths), done)

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
                f"• {issue}" for issue in product.review_issues()) for product in invalid)
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
            self.statusBar().showMessage("所选商品已审核，可以导出", 6000)

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
        return dialog.exec() == QMessageBox.StandardButton.Yes

    def _transfer_products(self, product_ids: list[str]) -> None:
        if not product_ids or self._tasks:
            return
        mode = self.settings.erp_transfer_mode
        if self.erp_service.unavailable_reason:
            # 未接通时记录检查结果，不向用户展示“正在发送”的假状态。
            notice = self.erp_service.unavailable_reason + "\n\n本次不会向妙手发送，只记录未发送原因，商品保持“未传”。"
            if not self._confirm_transfer("回传尚未接通", notice + "\n\n是否继续记录？", "继续记录"):
                return
        elif not self._confirm_transfer(
                # "确认传回妙手 ERP",
                # f"将按“{MODE_LABELS[mode]}”处理 {len(product_ids)} 个商品。\n"
                # "结果未知时请先到妙手核对。是否继续？",
                # 2026-10-11：本次修改原因：实际发送前清楚说明目标为公共采集箱和操作方式。
                "确认回传公共采集箱",
                f"将按“{MODE_LABELS[mode]}”向妙手公共采集箱写入 {len(product_ids)} 个商品。\n"
                "更新只合并本机修改过的字段。结果未知时请先到妙手核对。是否继续？",
                "继续回传"):
            return

        def done(results: list[dict]) -> None:
            counts = {state: sum(row.get("state") == state for row in results)
                      for state in ("succeeded", "blocked", "failed", "unknown")}
            message = (f"成功 {counts['succeeded']} 个 · 未发送 {counts['blocked']} 个 · "
                       f"失败 {counts['failed']} 个 · 结果未知 {counts['unknown']} 个")
            failures = [row for row in results if row.get("state") != "succeeded"]
            if failures:
                message += "\n\n" + "\n\n".join(row["message"] for row in failures[:3])
                message += "\n\n完整原因见“回传记录”。"
            QMessageBox.information(self, "回传处理结果", message)

        self.run_task(lambda: self.erp_service.transfer(product_ids, mode), done)

    # 2026-10-11：本次修改原因：查看原始发送快照之外的任务摘要，说明失败原因和对应商品版本。
    def show_erp_records(self) -> None:
        records = self.repository.erp_transfers()
        titles = {product.id: product.title or product.main_code for product in self._products}
        lines = []
        for record in records:
            lines.append(
                f"{readable_time(record['created_at'])}  {titles.get(record['product_id'], record['product_id'])}\n"
                f"方式：{MODE_LABELS.get(record['mode'], record['mode'])}  ·  v{record['revision']}  ·  "
                f"{STATE_LABELS.get(record['state'], record['state'])}\n"
                f"记录：{record['id']}\n妙手目标：{record['target_id'] or '尚无'}\n{record['message']}"
                # 2026-10-11：本次修改原因：显示真实接口响应以便核对错误码，服务层已剥离凭证和签名。
                + "\n回执：" + json.dumps(json.loads(record["receipt"]), ensure_ascii=False, indent=2)
            )
        self.text_dialog("妙手回传记录", "\n\n".join(lines) or "暂无回传记录。")

    def export_selected(self) -> None:
        if not self.checked_ids:
            return
        chosen = [product for product in self._products if product.id in self.checked_ids]
        if any(not product.approved or product.issues() for product in chosen):
            QMessageBox.warning(self, "尚不能导出", "所选商品中包含未审核或未完善项。请先完成审核。")
            return
        name = f"BeadDiff_妙手导入_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        destination, _ = QFileDialog.getSaveFileName(self, "导出妙手商品表格", name, "Excel 工作簿 (*.xlsx)")
        if not destination:
            return
        path = Path(destination).with_suffix(".xlsx")
        # 2026-10-10：本次修改原因：补齐后缀后再次核对实际文件，避免覆盖另一个未确认的路径。
        if path != Path(destination) and path.exists():
            if QMessageBox.question(self, "确认覆盖", f"实际导出文件已存在：\n{path}\n是否覆盖？",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        product_ids = list(self.checked_ids)

        def done(result) -> None:
            product_count, sku_count = result
            QMessageBox.information(self, "导出完成", f"已导出 {product_count} 个商品 / {sku_count} 个 SKU。\n{path}\n\n"
                                    "请先在妙手验证 .xlsx 格式与字段映射；本软件未自动上传或发布。")
            self.statusBar().showMessage("导出完成，已记录商品版本", 6000)

        self.run_task(lambda: export_products(self.repository, product_ids, path), done)

    def selected_capture(self) -> dict | None:
        row = self.capture_table.currentRow()
        item = self.capture_table.item(row, 0) if row >= 0 else None
        if not item:
            QMessageBox.information(self, "选择记录", "请先选择一条采集记录。")
            return None
        return self.repository.capture(item.data(Qt.ItemDataRole.UserRole))

    def show_raw(self) -> None:
        record = self.selected_capture()
        if not record:
            return
        try:
            text = Path(record["raw_path"]).read_text(encoding="utf-8")
            truncated = len(text) > 300_000
            self.text_dialog("原始采集材料", text[:300_000] + ("\n\n【显示已截断，完整文件保存在下方路径】" if truncated else ""), record["raw_path"])
        except OSError as error:
            QMessageBox.warning(self, "读取失败", str(error))

    def reparse_selected(self) -> None:
        record = self.selected_capture()
        if record:
            # self.run_task(lambda: self.service.reparse(record["id"]),
            #               lambda result: QMessageBox.information(self, "解析结果", f"结果：{result['state']}\n已有商品编辑会保留。"))
            # 2026-10-11：本次修改原因：将补齐数量或失败原因直接反馈给用户。
            self.run_task(lambda: self.service.reparse(record["id"]),
                          lambda result: QMessageBox.information(
                              self, "解析结果", f"结果：{result['state']}\n\n{result.get('message', '')}"))

    def open_export(self, directory: bool = False) -> None:
        row = self.export_table.currentRow()
        item = self.export_table.item(row, 0) if row >= 0 else None
        if item:
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            target = path.parent if directory else path
            if target.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
            else:
                QMessageBox.warning(self, "文件不存在", "导出文件可能已被移动或删除。记录保留了原保存位置。")
        else:
            QMessageBox.information(self, "选择记录", "请先选择一条导出记录。")

    def update_connection(self) -> None:
        running = self.receiver.server is not None and not self.receiver.error
        self.receiver_badge.setText("● 本机接收运行中" if running else "● 本机接收未启动")
        self.receiver_badge.setToolTip(self.receiver.error or self.settings.endpoint)
        # self.connection_state.setText(f"运行中 · 127.0.0.1:{self.receiver.settings.port} · 插件尚需配置转发" if running else
        #                               "启动失败：" + (self.receiver.error or "尚未启动") + "。仍可使用文件导入。")
        # 2026-10-11：本次修改原因：仅展示本机实际状态，不推断浏览器是否已加载或配置插件。
        self.connection_state.setText(f"运行中 · 127.0.0.1:{self.receiver.settings.port} · 请在扩展选项中测试连接" if running else
                                      "启动失败：" + (self.receiver.error or "尚未启动") + "。仍可使用文件导入。")

    def copy_text(self, value: str) -> None:
        QApplication.clipboard().setText(value)
        self.statusBar().showMessage("已复制到剪贴板", 4000)

    def save_port(self) -> None:
        try:
            # saved = Settings(self.settings.data_dir, self.settings.token, self.port.value())
            # 2026-10-11：本次修改原因：保存端口时保留 ERP 回传方式；仅下一次启动应用新端口。
            saved = Settings(self.settings.data_dir, self.settings.token, self.port.value(), self.settings.erp_transfer_mode)
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
            saved = Settings(self.settings.data_dir, self.settings.token, int(content.get("port", self.settings.port)), mode)
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
        account = self.miaoshou_config.config.account_id
        return product.erp_status if account and product.erp_account_id == account else "未传"

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
    def reconcile_erp_current(self) -> None:
        if self._tasks or not self.current_product:
            return
        record = next((row for row in self.repository.erp_transfers(self.current_product.id) if row["state"] == "unknown"), None)
        if not record:
            QMessageBox.information(self, "无需核对", "当前商品没有结果未知的回传记录。")
            return
        snapshot = json.loads(record["snapshot"])
        target, ok = QInputDialog.getText(self, "只读核对未知回传",
            "请先在妙手公共采集箱核对标题、来源和发送时间。\n填写确认属于这次回传的妙手商品 ID；程序只读取详情，字段一致才确认成功。",
            text=snapshot.get("erp_original_id", "") if record["mode"] == "update" else "")
        if ok and target.strip():
            self.run_task(lambda: self.erp_service.reconcile(record["id"], target.strip()),
                          lambda message: QMessageBox.information(self, "核对结果", message))

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
        #     QMessageBox.information(self, "任务正在进行", "请等待当前导入或导出完成后再关闭，避免材料保存不完整。")
        # 2026-10-11：本次修改原因：AI 任务进行中保护候选和素材留档。
        if self._tasks or self.ai_hub.busy:
            QMessageBox.information(self, "任务正在进行", "请等待当前导入、导出或 AI 任务完成后再关闭。")
            event.ignore()
            return
        super().closeEvent(event)
