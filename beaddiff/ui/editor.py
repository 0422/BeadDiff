# 2026-10-10：本次修改原因：提供电商商品分区编辑、规格定价和人工审核，所有修改保存为新版本。
from __future__ import annotations

from dataclasses import asdict

# from PySide6.QtCore import Qt
# 2026-10-11：本次修改原因：延迟更新缩略图并支持打开已采集的视频链接。
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget, QAbstractItemView,
)

# from ..models import Product, SKU, positive_decimal
# 2026-10-10：本次修改原因：预览前限制图片链接协议为 HTTP/HTTPS。
from ..models import Product, SKU, positive_decimal, valid_url
from ..storage import Repository
# from .widgets import ImagePreview, button, label
# 2026-10-11：本次修改原因：编辑页增加图片分组缩略图与来源 SKU 信息展示。
from .widgets import ImageGallery, ImagePreview, button, label
# 2026-10-11：本次修改原因：按妙手八个栏目组织编辑器，图文详情和图片排序使用独立控件。
from ..content import attribute_description, detail_html, sku_image_groups, with_detail_images
from .media_list import MediaList
from .rich_description import RichDescription

# 2026-10-11：本次修改原因：字段就地 AI 入口复用公共服务，生成结果先应用到表单，再由原保存流程版本化。
from html import escape
import re
from ..ai.service import AIService
from ..assets import valid_media_url
from .ai_runner import TaskHub
from .ai_workspace import AIWorkspace


def text_editor(text: str = "", placeholder: str = "", height: int = 100) -> QPlainTextEdit:
    editor = QPlainTextEdit(text)
    editor.setPlaceholderText(placeholder)
    editor.setMinimumHeight(height)
    return editor


class ProductEditor(QDialog):
    # def __init__(self, repository: Repository, product: Product, network: QNetworkAccessManager, parent=None):
    # 2026-10-11：本次修改原因：两条来源共用模型服务与后台任务，兼容现有编辑器构造方式。
    def __init__(self, repository: Repository, product: Product, network: QNetworkAccessManager, parent=None,
                 ai_service: AIService | None = None, ai_hub: TaskHub | None = None):
        super().__init__(parent)
        self.repository, self.product, self.dirty = repository, product, False
        # 2026-10-11：本次修改原因：SKU 预览复用主窗口的异步图片连接。
        self.network = network
        self.ai_service = ai_service
        self.ai_hub = ai_hub or TaskHub(self)
        self.setWindowTitle(f"编辑商品 · {product.main_code}")
        self.resize(1120, 790)
        self.setMinimumSize(940, 650)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(16)
        root.addWidget(label("商品编辑", "pageTitle"))
        root.addWidget(label(f"{product.source.upper()} · {product.source_id} · {product.site or '站点未提供'}    /    当前版本 v{product.revision}", "muted"))
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.fields: dict[str, QLineEdit] = {}
        # self._basic_tab()
        # self._images_tab(network)
        # 2026-10-11：本次修改原因：旧三页入口保留，当前入口按妙手八个栏目排列。
        self._miaoshou_basic_tab()
        self._attribute_tab()
        self._sku_tab()
        self._miaoshou_images_tab()
        self._video_tab()
        self._certification_tab()
        self._logistics_tab()
        self._source_tab()
        footer = QHBoxLayout()
        footer.addWidget(button("检查完整性", self.check))
        footer.addStretch()
        footer.addWidget(button("取消", self.reject))
        footer.addWidget(button("保存修改", lambda: self.save_product(False)))
        footer.addWidget(button("保存并审核", lambda: self.save_product(True), primary=True))
        root.addLayout(footer)
        for editor in self.findChildren(QLineEdit):
            if not editor.isReadOnly():
                editor.textChanged.connect(self.mark_dirty)
        for editor in self.findChildren(QPlainTextEdit):
            editor.textChanged.connect(self.mark_dirty)
        self.currency.currentTextChanged.connect(self.mark_dirty)
        self.sku_table.itemChanged.connect(self.mark_dirty)
        self.confirm_mapping.toggled.connect(self.mark_dirty)
        # 2026-10-11：本次修改原因：新增图文、属性表与图片列表修改纳入未保存提示。
        self.rich_description.editor.textChanged.connect(self.mark_dirty)
        self.attribute_table.itemChanged.connect(self.mark_dirty)
        self.images.textChanged.connect(self.mark_dirty)
        self.detail_images.textChanged.connect(self.mark_dirty)
        self.tabs.currentChanged.connect(lambda _index: self.refresh_sku_images())
        self.dirty = False
        # 2026-10-11：本次修改原因：记录表单初始显示内容，避免描述回退和 SKU 币种规范化把直接保存误判为人工修改。
        try:
            self.initial_form_content = self.collect().business_content()
        except ValueError:
            self.initial_form_content = None

    def mark_dirty(self, *_args) -> None:
        self.dirty = True

    def _tab_form(self, title: str) -> QFormLayout:
        contents = QWidget()
        form = QFormLayout(contents)
        form.setContentsMargins(24, 24, 24, 24)
        form.setSpacing(16)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(contents)
        self.tabs.addTab(scroll, title)
        return form

    def _field(self, key: str, placeholder: str = "", readonly: bool = False) -> QLineEdit:
        editor = QLineEdit(str(getattr(self.product, key)))
        editor.setPlaceholderText(placeholder)
        editor.setReadOnly(readonly)
        # 2026-10-11：本次修改原因：长货源和视频链接从开头显示，方便核对域名。
        editor.setCursorPosition(0)
        self.fields[key] = editor
        return editor

    # 2026-10-11：本次修改原因：按妙手基本信息区分简易描述和图片式详细描述。
    def _miaoshou_basic_tab(self) -> None:
        form = self._tab_form("基本信息")
        # form.addRow("产品标题 *", self._field("title", "填写面向销售渠道的产品标题"))
        # 2026-10-11：本次修改原因：标题栏右侧提供妙手式 AI 按钮。
        self.ai_field(form, "产品标题 *", self._field("title", "填写面向销售渠道的产品标题"), "title")
        form.addRow("产品主编号 *", self._field("main_code", "同一商品的 SKU 共用一个产品主编号"))
        simple = self.product.simple_description
        if not simple and "simple_description" not in self.product.manual_fields:
            simple = attribute_description(self.product.attributes)
        self.simple_description = text_editor(simple, "产品简述；可从产品属性生成", 140)
        # form.addRow("简易描述", self.simple_description)
        # 2026-10-11：本次修改原因：简易描述使用同一文本模型入口。
        self.ai_field(form, "简易描述", self.simple_description, "simple_description")
        form.addRow("", button("从产品属性更新简易描述", self.describe_attributes))
        # 2026-10-11：本次修改原因：说明简易描述与 22 列模板的映射边界，避免编辑后误以为会单列导出。
        form.addRow("", label("简易描述单独保存在本地；当前模板没有简易描述列，产品属性导出到“自定义属性”，图文详情导出到“详情描述”。", "hint", True))
        html = self.product.description_html
        if not html and "description_html" not in self.product.manual_fields:
            legacy_text = self.product.description if "description" in self.product.manual_fields else ""
            html = detail_html(legacy_text, self.product.detail_images)
        self.rich_description = RichDescription(self.network, html)
        # form.addRow("详细描述", self.rich_description)
        # 2026-10-11：本次修改原因：详情支持 AI 文案与其中单张图片处理。
        self.ai_field(form, "详细描述", self.rich_description, "description_html")
        self.rich_description.aiRequested.connect(lambda address: self.open_ai("image", "html", address))
        form.addRow("", button("用详情图更新图文描述", self.describe_images))

    # 2026-10-11：本次修改原因：产品属性按妙手的名称/值两列编辑，而非仅展示一段文字。
    def _attribute_tab(self) -> None:
        form = self._tab_form("产品属性")
        form.addRow("类目路径", self._field("category", "来源类目；发布时仍需匹配目标渠道类目"))
        self.attribute_table = QTableWidget(0, 2)
        self.attribute_table.setHorizontalHeaderLabels(["属性名称", "属性值"])
        self.attribute_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.attribute_table.setAlternatingRowColors(True)
        self.attribute_table.verticalHeader().setDefaultSectionSize(44)
        self.attribute_table.setMinimumHeight(380)
        for name, value in self.product.attributes.items():
            self.add_attribute(name, value)
        self.attribute_count = label(f"产品属性（{self.attribute_table.rowCount()} 项）")
        form.addRow(self.attribute_count, self.attribute_table)
        actions = QHBoxLayout()
        actions.addWidget(button("新增属性", lambda: self.add_attribute()))
        actions.addWidget(button("移除选中", self.remove_attributes))
        actions.addStretch()
        form.addRow("", actions)
        form.addRow("", label("材料、颜色、长度和包装请按实物核对；串珠 BOM 约束仍需后续实现。", "hint", True))

    def add_attribute(self, name: str = "", value: str = "") -> None:
        row = self.attribute_table.rowCount()
        self.attribute_table.insertRow(row)
        self.attribute_table.setItem(row, 0, QTableWidgetItem(name))
        self.attribute_table.setItem(row, 1, QTableWidgetItem(value))
        if hasattr(self, "attribute_count"):
            self.attribute_count.setText(f"产品属性（{self.attribute_table.rowCount()} 项）")
            self.mark_dirty()

    def remove_attributes(self) -> None:
        rows = sorted({item.row() for item in self.attribute_table.selectedItems()}, reverse=True)
        for row in rows:
            self.attribute_table.removeRow(row)
        self.attribute_count.setText(f"产品属性（{self.attribute_table.rowCount()} 项）")
        if rows:
            self.mark_dirty()

    def collect_attributes(self) -> dict[str, str]:
        result = {}
        for row in range(self.attribute_table.rowCount()):
            parts = [self.attribute_table.item(row, col).text().strip() if self.attribute_table.item(row, col) else ""
                     for col in range(2)]
            name, value = parts
            if not name and not value:
                continue
            if not name or not value:
                raise ValueError(f"属性第 {row + 1} 行需要同时填写名称和值。")
            if name in result or any(character in name + value for character in "；\n\r"):
                raise ValueError("属性名不能重复，属性中不能含分隔符“；”或换行。")
            result[name] = value
        return result

    def describe_attributes(self) -> None:
        try:
            self.simple_description.setPlainText(attribute_description(self.collect_attributes()))
        except ValueError as error:
            QMessageBox.warning(self, "产品属性", str(error))

    def describe_images(self) -> None:
        self.rich_description.set_html(with_detail_images(self.rich_description.html(), self.detail_images.toPlainText().splitlines()))
        self.mark_dirty()

    # 2026-10-11：本次修改原因：主图支持顺序维护和尺寸核对，SKU 图片按销售属性分组展示。
    def _miaoshou_images_tab(self) -> None:
        form = self._tab_form("产品图片")
        # self.images = MediaList(self.product.images, self.product.image_sizes)
        # 2026-10-11：本次修改原因：商品图片支持本地上传和单图 AI，套图仍保持可排序图片组。
        assets = self.ai_service.assets if self.ai_service else None
        self.images = MediaList(self.product.images, self.product.image_sizes, assets, enable_ai=True)
        self.images.aiRequested.connect(lambda address: self.open_ai("image", "images", address))
        self.product_gallery = ImageGallery(self.network)
        self.product_gallery.enable_ai = True
        self.product_gallery.aiRequested.connect(lambda address: self.open_ai("image", "images", address))
        # 2026-10-11：本次修改原因：预览返回实际图片尺寸，补齐源材料未提供的尺寸显示。
        self.product_gallery.sizeLoaded.connect(self.images.update_size)
        form.addRow("产品图片 *", self.images)
        form.addRow("", button("AI 生成套图", lambda: self.open_ai("image_set", "images")))
        form.addRow("", label("第一张为主图，可上移/下移调整顺序；像素尺寸仅显示采集材料的明确值。", "hint", True))
        form.addRow("", self.product_gallery)
        self.sku_group_dimension = QComboBox()
        self.sku_group_dimension.addItems([self.fields["spec1_name"].text(), self.fields["spec2_name"].text()])
        color_index = next((index for index, name in enumerate(
            [self.product.spec1_name, self.product.spec2_name]) if "颜色" in name or "color" in name.lower()), 0)
        self.sku_group_dimension.setCurrentIndex(color_index)
        self.sku_group = QComboBox()
        group_actions = QHBoxLayout()
        group_actions.addWidget(label("分组维度"))
        group_actions.addWidget(self.sku_group_dimension)
        group_actions.addWidget(self.sku_group, 1)
        form.addRow("SKU 图片", group_actions)
        self.sku_group_count = label("", "muted", True)
        form.addRow("", self.sku_group_count)
        self.sku_group_gallery = ImageGallery(self.network)
        form.addRow("", self.sku_group_gallery)
        self.sku_group_table = QTableWidget(0, 2)
        self.sku_group_table.setHorizontalHeaderLabels(["对应 SKU 规格", "SKU 图片链接"])
        self.sku_group_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sku_group_table.setMinimumHeight(155)
        self.sku_group_table.itemChanged.connect(self.group_image_changed)
        form.addRow("", self.sku_group_table)
        self.sku_group_dimension.currentIndexChanged.connect(lambda _index: self.refresh_sku_images())
        self.sku_group.currentIndexChanged.connect(lambda _index: self.render_sku_group())
        # self.detail_images = MediaList(self.product.detail_images, self.product.image_sizes)
        # 2026-10-11：本次修改原因：详情图同样可上传和 AI 修改，并同步已有正文中的对应图。
        self.detail_images = MediaList(self.product.detail_images, self.product.image_sizes, assets, enable_ai=True)
        self.detail_images.aiRequested.connect(lambda address: self.open_ai("image", "detail_images", address))
        self.detail_gallery = ImageGallery(self.network)
        self.detail_gallery.enable_ai = True
        self.detail_gallery.aiRequested.connect(lambda address: self.open_ai("image", "detail_images", address))
        self.detail_gallery.sizeLoaded.connect(self.detail_images.update_size)
        form.addRow("详情图片", self.detail_images)
        form.addRow("", self.detail_gallery)
        form.addRow("产品尺码表", self._field("size_chart", "产品尺码表图片链接"))
        form.addRow("身体尺码表", self._field("body_size_chart", "身体尺寸对照图片链接"))
        form.addRow("", label("SKU 图片与销售属性表双向同步；编辑详情图列表后，可在基本信息中更新图文描述。", "hint", True))
        self.gallery_timer = QTimer(self)
        self.gallery_timer.setSingleShot(True)
        self.gallery_timer.setInterval(500)
        self.gallery_timer.timeout.connect(self.refresh_galleries)
        self.images.textChanged.connect(lambda: self.gallery_timer.start())
        self.detail_images.textChanged.connect(lambda: self.gallery_timer.start())
        self.refresh_galleries()
        self.refresh_sku_images()

    # 2026-10-11：本次修改原因：从正在编辑的 SKU 行计算选项和分组，保存前即能核对。
    def current_sku_images(self) -> list[SKU]:
        result = []
        for row in range(self.sku_table.rowCount()):
            if any(self.sku_table.item(row, col) is None for col in (1, 2, 8)):
                continue
            result.append(SKU(spec1=self.sku_table.item(row, 1).text().strip(),
                              spec2=self.sku_table.item(row, 2).text().strip(),
                              image=self.sku_table.item(row, 8).text().strip()))
        return result

    def refresh_spec_options(self, *_args) -> None:
        if not hasattr(self, "sku_table") or not hasattr(self, "spec_options"):
            return
        skus = self.current_sku_images()
        names = [self.fields["spec1_name"].text().strip(), self.fields["spec2_name"].text().strip()]
        lines = []
        # 2026-10-11：本次修改原因：更新规格表头不触发单元格编辑回调，避免初始化中重入。
        signals_blocked = self.sku_table.blockSignals(True)
        for index, field in enumerate(("spec1", "spec2")):
            values = list(dict.fromkeys(getattr(sku, field) for sku in skus if getattr(sku, field)))
            lines.append(f"{names[index] or f'规格 {index + 1}'}：{' / '.join(values) or '未填写'}")
            self.sku_table.setHorizontalHeaderItem(index + 1, QTableWidgetItem(names[index] or f"规格 {index + 1}"))
        self.sku_table.blockSignals(signals_blocked)
        self.spec_options.setText("\n".join(lines))
        if hasattr(self, "sku_group_dimension"):
            self.sku_group_dimension.blockSignals(True)
            for index, name in enumerate(names):
                self.sku_group_dimension.setItemText(index, name or f"规格 {index + 1}")
            self.sku_group_dimension.blockSignals(False)
            self.refresh_sku_images()

    def refresh_sku_images(self) -> None:
        if not hasattr(self, "sku_group_table"):
            return
        old = self.sku_group.currentText()
        fallback = "spec1" if self.sku_group_dimension.currentIndex() == 0 else "spec2"
        self.sku_groups = sku_image_groups(self.current_sku_images(), "", fallback)
        self.sku_group.blockSignals(True)
        self.sku_group.clear()
        self.sku_group.addItems(list(self.sku_groups))
        if old in self.sku_groups:
            self.sku_group.setCurrentText(old)
        self.sku_group.blockSignals(False)
        self.render_sku_group()

    def render_sku_group(self) -> None:
        group = self.sku_group.currentText()
        urls = self.sku_groups.get(group, [])
        self.sku_group_gallery.set_urls(urls)
        self.sku_group_count.setText(f"共 {len(self.sku_groups)} 组 · 当前组 {len(urls)} 张独立图片")
        column = 1 if self.sku_group_dimension.currentIndex() == 0 else 2
        self.sku_group_table.blockSignals(True)
        self.sku_group_table.setRowCount(0)
        for row in range(self.sku_table.rowCount()):
            # 2026-10-11：本次修改原因：新增 SKU 的单元格尚未填齐时不进入图片分组。
            if any(self.sku_table.item(row, col) is None for col in (1, 2, 8)):
                continue
            if not self.sku_table.item(row, column) or (self.sku_table.item(row, column).text().strip() or "未填写规格") != group:
                continue
            target = self.sku_group_table.rowCount()
            self.sku_group_table.insertRow(target)
            caption = QTableWidgetItem(" / ".join(self.sku_table.item(row, col).text() for col in (1, 2)))
            caption.setFlags(caption.flags() & ~Qt.ItemFlag.ItemIsEditable)
            caption.setData(Qt.ItemDataRole.UserRole, row)
            self.sku_group_table.setItem(target, 0, caption)
            self.sku_group_table.setItem(target, 1, QTableWidgetItem(self.sku_table.item(row, 8).text()))
        self.sku_group_table.blockSignals(False)

    def group_image_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 1:
            row = self.sku_group_table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
            self.sku_table.item(row, 8).setText(item.text().strip())

    # 2026-10-11：本次修改原因：视频、认证说明、物流及货源分别提供与妙手一致的入口。
    def _video_tab(self) -> None:
        form = self._tab_form("产品视频")
        form.addRow("产品视频", self._field("video", "HTTP/HTTPS 视频链接"))
        form.addRow("", button("打开 / 播放视频", self.open_video))
        # 2026-10-11：本次修改原因：视频保留统一功能位置，当前不发起视频生成请求。
        placeholder = button("AI 生成视频 · 暂未开放")
        placeholder.setEnabled(False)
        form.addRow("", placeholder)
        form.addRow("", label("来源视频单独解析保存；点击后通过浏览器播放。", "hint", True))

    def _certification_tab(self) -> None:
        form = self._tab_form("认证说明")
        form.addRow("产品认证", self._field("certificate", "认证文件链接"))
        form.addRow("", button("打开认证文件", lambda: self.open_attachment("certificate")))
        form.addRow("说明书 PDF", self._field("instruction_manual", "说明书 PDF 链接"))
        form.addRow("", button("打开说明书", lambda: self.open_attachment("instruction_manual")))
        form.addRow("", label("采集材料未提供的附件留空。说明书在本地保存，当前 22 列模板没有对应列。", "hint", True))

    def _logistics_tab(self) -> None:
        form = self._tab_form("物流信息")
        form.addRow("包裹重量 KG", self._field("package_weight", "填写实测重量，例如 0.35"))
        form.addRow("包裹尺寸 CM", self._field("package_dimensions", "长*宽*高，例如 30*20*3"))
        form.addRow("", label("商品级包裹信息保存在本地。现有模板提供的是 SKU 重量/尺寸，请在销售属性逐 SKU 核实填写。", "hint", True))

    def _source_tab(self) -> None:
        form = self._tab_form("货源链接")
        form.addRow("货源链接", self._field("source_url", "HTTP/HTTPS 商品链接"))
        form.addRow("", button("打开货源商品", lambda: self.open_attachment("source_url")))
        form.addRow("货源平台", self._field("source", readonly=True))
        form.addRow("货源 ID", self._field("source_id", readonly=True))
        form.addRow("来源站点", self._field("site", readonly=True))
        form.addRow("货源备注", self._field("source_remark", "采购或货源说明"))
        # 2026-10-11：本次修改原因：公开采集箱单规格新增要求货源价，提供独立输入以免与销售金额混淆。
        form.addRow("回传货源价", self._field("supply_price", "数值金额，币种使用基本信息中的商品币种"))
        form.addRow("", label("单规格新增必须有货源价。优先使用这里的金额，否则读取已确认币种的采集货源价；销售金额不会代填货源价。", "hint", True))
        form.addRow("", label("货源备注在本地保存，现有 22 列模板没有对应列。", "hint", True))

    def open_attachment(self, key: str) -> None:
        url = self.fields[key].text().strip()
        if valid_url(url):
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.information(self, "文件 / 货源链接", "当前没有有效的 HTTP/HTTPS 链接。")

    def _basic_tab(self) -> None:
        form = self._tab_form("基本信息")
        form.addRow("产品名称 *", self._field("title", "填写面向买家的商品名称"))
        form.addRow("产品主编号 *", self._field("main_code", "同一商品的 SKU 通过此编号归组"))
        self.currency = QComboBox()
        self.currency.setEditable(True)
        self.currency.addItems(["", "USD", "CNY", "EUR", "GBP", "JPY", "CAD", "AUD"])
        self.currency.setCurrentText(self.product.currency)
        self.currency.setToolTip("选择实际导出售价使用的币种，不会自动执行汇率换算")
        form.addRow("售价币种 *", self.currency)
        form.addRow("货源链接", self._field("source_url", "https://…"))
        form.addRow("来源商品 ID", self._field("source_id", readonly=True))
        form.addRow("货源类目", self._field("category", "按妙手导入要求填写类目"))
        self.description = text_editor(self.product.description, "纯文本商品描述，突出材质、用途、规格和包装", 140)
        form.addRow("详情描述", self.description)
        self.attributes = text_editor("\n".join(f"{key}:{value}" for key, value in self.product.attributes.items()),
                                      "每行一个属性，例如：\n材质:天然石\n包装:独立袋装", 110)
        # form.addRow("自定义属性", self.attributes)
        # 2026-10-11：本次修改原因：标明商品属性数量，允许补充材质、包装等属性。
        self.attribute_count = label(f"商品属性（{len(self.product.attributes)} 项）")
        form.addRow(self.attribute_count, self.attributes)
        self.attributes.textChanged.connect(lambda: self.attribute_count.setText(
            f"商品属性（{sum(bool(line.strip()) for line in self.attributes.toPlainText().splitlines())} 项）"))
        form.addRow("", label("串珠材质、颜色、长度和包装请按实际商品核对；本版尚未建立 BOM 校验。", "hint", True))

    def _images_tab(self, network: QNetworkAccessManager) -> None:
        form = self._tab_form("图片与附件")
        self.preview = ImagePreview(network, 200)
        form.addRow("主图预览", self.preview)
        self.images = text_editor("\n".join(self.product.images), "每行一个 HTTP/HTTPS 图片链接；第一张作为主图", 100)
        form.addRow("产品主图 *", self.images)
        form.addRow("", button("预览第一张图片", self.preview_first))
        self.detail_images = text_editor("\n".join(self.product.detail_images), "每行一个详情图片链接", 90)
        form.addRow("详情图", self.detail_images)
        # 2026-10-11：本次修改原因：主图与详情图分别显示数量和分页缩略图。
        self.product_gallery = ImageGallery(network)
        self.detail_gallery = ImageGallery(network)
        form.addRow("全部主图", self.product_gallery)
        form.addRow("全部详情图", self.detail_gallery)
        form.addRow("产品视频", self._field("video", "视频链接或妙手支持的值"))
        form.addRow("", button("打开视频", self.open_video))
        form.addRow("产品证书", self._field("certificate", "按渠道要求填写"))
        form.addRow("尺寸图表", self._field("size_chart", "按渠道要求填写"))
        self.preview_first()
        self.gallery_timer = QTimer(self)
        self.gallery_timer.setSingleShot(True)
        self.gallery_timer.setInterval(500)
        self.gallery_timer.timeout.connect(self.refresh_galleries)
        self.images.textChanged.connect(lambda: self.gallery_timer.start())
        self.detail_images.textChanged.connect(lambda: self.gallery_timer.start())
        self.refresh_galleries()

    # 2026-10-11：本次修改原因：图片链接编辑后同步更新数量和缩略图，避免逐次按键发起下载。
    def refresh_galleries(self) -> None:
        self.product_gallery.set_urls([line.strip() for line in self.images.toPlainText().splitlines() if line.strip()])
        self.detail_gallery.set_urls([line.strip() for line in self.detail_images.toPlainText().splitlines() if line.strip()])

    def open_video(self) -> None:
        url = self.fields["video"].text().strip()
        if valid_url(url):
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.information(self, "视频链接", "当前没有有效的视频链接。")

    def preview_first(self) -> None:
        urls = self.images.toPlainText().strip().splitlines()
        # self.preview.set_url(urls[0].strip() if urls else "")
        # 2026-10-10：本次修改原因：无效链接保留在表单里供修正，不交给图片下载器。
        url = urls[0].strip() if urls else ""
        # self.preview.set_url(url if valid_url(url) else "")
        # 2026-10-11：本次修改原因：首图预览也支持受管理的本机素材。
        self.preview.set_url(url if valid_media_url(url) else "")

    def _sku_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        # layout.addWidget(label("采集价仅作参考，不自动转成售价；库存、重量未提供时请留空。", "warning", True))
        # 2026-10-11：本次修改原因：区分来源库存与自有库存，规格尺码与物流包装尺寸。
        # layout.addWidget(label("来源价仅供参考；来源库存、限购不自动转成自有库存。包装重量、尺寸需自行核实。", "warning", True))
        # 2026-10-11：本次修改原因：销售属性按妙手展示规格选项、货源价格、商家售价与库存。
        layout.addWidget(label("货源价格保留原币种；售价与库存请按经营计划填写。规格尺码与包裹尺寸分别维护。", "hint", True))
        self.currency = QComboBox()
        self.currency.setEditable(True)
        self.currency.addItems(["", "USD", "CNY", "EUR", "GBP", "JPY", "CAD", "AUD"])
        self.currency.setCurrentText(self.product.currency)
        currency_row = QHBoxLayout()
        currency_row.addWidget(label("售价币种 *"))
        currency_row.addWidget(self.currency)
        currency_row.addStretch()
        layout.addLayout(currency_row)
        names = QHBoxLayout()
        names.addWidget(label("规格维度"))
        names.addWidget(self._field("spec1_name", "例如：颜色"))
        names.addWidget(self._field("spec2_name", "例如：尺寸"))
        names.addStretch()
        names.addWidget(button("统一填写售价", self.fill_prices))
        names.addWidget(button("添加 SKU", self.add_sku))
        names.addWidget(button("移除选中 SKU", self.remove_sku))
        layout.addLayout(names)
        # 2026-10-11：本次修改原因：像妙手一样显示各规格维度的选项，随 SKU 编辑更新。
        self.spec_options = label("", "muted", True)
        layout.addWidget(self.spec_options)
        # self.sku_table = QTableWidget(0, 10)
        # 2026-10-11：本次修改原因：增加来源币种、来源库存、限购与在售状态的只读列。
        # self.sku_table = QTableWidget(0, 14)
        # 2026-10-11：本次修改原因：来源规格 ID 增加为独立只读列，原列索引保持一致。
        self.sku_table = QTableWidget(0, 15)
        self.sku_table.setHorizontalHeaderLabels([
            # "平台 SKU", "规格 1", "规格 2", "来源价格（原始）", "售价 *", "库存", "重量 KG", "尺寸 CM", "规格图片", "来源规格（只读）",
            "平台 SKU", "规格 1", "规格 2", "来源价格", "售价 *", "自有库存", "包装重量 KG", "包装尺寸 CM", "规格图片", "来源规格（只读）",
            "来源币种", "来源库存", "限购数量", "来源在售",
            "来源规格 ID",
        ])
        self.sku_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sku_table.setAlternatingRowColors(True)
        self.sku_table.verticalHeader().setDefaultSectionSize(48)
        self.sku_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # for col, width in enumerate([155, 100, 100, 130, 95, 85, 95, 110, 190, 180]):
        for col, width in enumerate([160, 150, 160, 110, 95, 95, 115, 140, 190, 180, 90, 90, 90, 90]):
            self.sku_table.setColumnWidth(col, width)
        self.sku_table.horizontalHeader().setStretchLastSection(True)
        self.sku_table.setColumnWidth(14, 170)
        # 2026-10-11：本次修改原因：让来源币种紧邻来源价格，保持原保存字段索引。
        header = self.sku_table.horizontalHeader()
        header.moveSection(header.visualIndex(10), 4)
        for sku in self.product.skus:
            self.add_sku(sku)
        layout.addWidget(self.sku_table, 1)
        self.sku_preview = ImagePreview(self.network, 110)
        self.sku_preview.setFixedWidth(165)
        preview_row = QHBoxLayout()
        preview_row.addWidget(self.sku_preview)
        self.sku_source_summary = label("选择 SKU 查看规格图片和来源库存信息。", "hint", True)
        preview_row.addWidget(self.sku_source_summary, 1)
        # 2026-10-11：本次修改原因：SKU 改图显式绑定所选规格，避免改动其他颜色的图片。
        preview_row.addWidget(button("AI 改当前 SKU 图", self.open_sku_ai))
        layout.addLayout(preview_row)
        self.sku_table.itemSelectionChanged.connect(self.preview_sku)
        self.sku_table.itemChanged.connect(self.sku_item_changed)
        self.confirm_mapping = QCheckBox("已人工核对：将超过两个维度的来源规格明确合并到上面两列；原始材料仍保留")
        self.confirm_mapping.setVisible(any(len(sku.specs) > 2 for sku in self.product.skus))
        layout.addWidget(self.confirm_mapping)
        layout.addWidget(label("尺寸建议按“长*宽*高”填写，单位 CM。横向滚动可编辑规格图片链接。", "hint"))
        # self.tabs.addTab(page, f"规格与定价（{len(self.product.skus)}）")
        # self.sku_tab_index = self.tabs.addTab(page, f"规格与定价（{len(self.product.skus)}）")
        # 2026-10-11：本次修改原因：销售属性栏目与妙手命名一致。
        self.sku_tab_index = self.tabs.addTab(page, f"销售属性（{len(self.product.skus)}）")
        self.fields["spec1_name"].textChanged.connect(self.refresh_spec_options)
        self.fields["spec2_name"].textChanged.connect(self.refresh_spec_options)
        self.refresh_spec_options()
        if self.sku_table.rowCount():
            self.sku_table.selectRow(0)

    # 2026-10-11：本次修改原因：选中 SKU 即展示图片、来源价、来源库存和平台限购。
    def preview_sku(self) -> None:
        row = self.sku_table.currentRow()
        if row < 0 or any(self.sku_table.item(row, col) is None for col in range(14)):
            self.sku_preview.set_url("")
            self.sku_source_summary.setText("选择 SKU 查看规格图片和来源库存信息。")
            return
        values = [self.sku_table.item(row, col).text().strip() for col in range(14)]
        # self.sku_preview.set_url(values[8] if valid_url(values[8]) else "")
        # 2026-10-11：本次修改原因：SKU 预览显示本地生成素材。
        self.sku_preview.set_url(values[8] if valid_media_url(values[8]) else "")
        self.sku_source_summary.setText(
            f"{values[1]}  ·  {values[2]}\n来源价 {values[3] or '未提供'}  {values[10]}\n"
            f"来源库存 {values[11] or '未提供'}  ·  限购 {values[12] or '未提供'}  ·  {values[13]}\n"
            "来源库存与限购属于平台采集时的信息，自有库存需按实际填写。")

    def sku_item_changed(self, item: QTableWidgetItem) -> None:
        if item.row() == self.sku_table.currentRow() and item.column() in {1, 2, 8}:
            self.preview_sku()
        # 2026-10-11：本次修改原因：SKU 编辑后同步规格选项与图片分组。
        if item.column() in {1, 2, 8}:
            self.refresh_spec_options()
            self.refresh_sku_images()

    def add_sku(self, sku: SKU | bool | None = None) -> None:
        if not isinstance(sku, SKU):
            sku = SKU()
        # 2026-10-11：本次修改原因：填齐新 SKU 行后再通知分组控件，避免读取尚未创建的单元格。
        signals_blocked = self.sku_table.blockSignals(True)
        row = self.sku_table.rowCount()
        self.sku_table.insertRow(row)
        values = [sku.platform_sku, sku.spec1, sku.spec2, sku.source_price, sku.price, sku.stock,
                  sku.weight, sku.dimensions, sku.image, " / ".join(f"{key}: {value}" for key, value in sku.specs.items())]
        # 2026-10-11：本次修改原因：来源信息只读展示，保存时保留原始值。
        values.extend([sku.source_currency, sku.source_stock, sku.purchase_limit,
                       {"1": "在售", "0": "非在售"}.get(sku.availability, "未提供")])
        # 2026-10-11：本次修改原因：来源 ID 不作为商家平台 SKU 导出。
        values.append(sku.source_sku_id)
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            # if col in {3, 9}:
            # if col in {3, 9, 10, 11, 12, 13}:
            if col in {3, 9, 10, 11, 12, 13, 14}:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if col == 0:
                item.setData(Qt.ItemDataRole.UserRole, asdict(sku))
            self.sku_table.setItem(row, col, item)
        self.sku_table.blockSignals(signals_blocked)
        if hasattr(self, "sku_tab_index"):
            # self.tabs.setTabText(self.sku_tab_index, f"规格与定价（{self.sku_table.rowCount()}）")
            self.tabs.setTabText(self.sku_tab_index, f"销售属性（{self.sku_table.rowCount()}）")
            self.refresh_spec_options()
            self.refresh_sku_images()
        self.mark_dirty()

    def remove_sku(self) -> None:
        rows = sorted({item.row() for item in self.sku_table.selectedItems()}, reverse=True)
        for row in rows:
            self.sku_table.removeRow(row)
        if rows:
            self.mark_dirty()
            # self.tabs.setTabText(self.sku_tab_index, f"规格与定价（{self.sku_table.rowCount()}）")
            self.tabs.setTabText(self.sku_tab_index, f"销售属性（{self.sku_table.rowCount()}）")
            self.preview_sku()
            self.refresh_spec_options()
            self.refresh_sku_images()

    def fill_prices(self) -> None:
        price, accepted = QInputDialog.getText(self, "统一填写售价", "将应用于当前商品的全部 SKU（不会换算币种）：")
        if accepted:
            if not positive_decimal(price):
                QMessageBox.warning(self, "售价无效", "请输入大于 0 的数值。")
                return
            for row in range(self.sku_table.rowCount()):
                self.sku_table.item(row, 4).setText(price.strip())

    def collect(self) -> Product:
        product = Product.from_dict(self.product.to_dict())
        for key, editor in self.fields.items():
            if not editor.isReadOnly():
                setattr(product, key, editor.text().strip())
        product.currency = self.currency.currentText().strip().upper()
        # product.description = self.description.toPlainText().strip()
        # 2026-10-11：本次修改原因：保存简易描述与图文描述，网页摘要不与编辑字段混用。
        product.simple_description = self.simple_description.toPlainText().strip()
        product.description_html = self.rich_description.html()
        product.images = list(dict.fromkeys(line.strip() for line in self.images.toPlainText().splitlines() if line.strip()))
        product.detail_images = list(dict.fromkeys(line.strip() for line in self.detail_images.toPlainText().splitlines() if line.strip()))
        # 2026-10-11：本次修改原因：保存预览时取得的图片像素元数据。
        product.image_sizes = {**self.images.sizes, **self.detail_images.sizes}
        product.attributes = {}
        # for line in self.attributes.toPlainText().splitlines():
        #     if not line.strip():
        #         continue
        #     parts = line.replace("：", ":", 1).split(":", 1)
        #     if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        #         raise ValueError("自定义属性请使用“属性名:属性值”，每行一项。")
        #     key, value = (part.strip() for part in parts)
        #     if key in product.attributes or any(character in key + value for character in "；\n"):
        #         raise ValueError("属性名不能重复，属性中不能含分隔符“；”。")
        #     product.attributes[key] = value
        # 2026-10-11：本次修改原因：属性按妙手的名称/值两列表格保存并校验。
        product.attributes = self.collect_attributes()
        product.skus = []
        for row in range(self.sku_table.rowCount()):
            # values = [self.sku_table.item(row, col).text().strip() for col in range(10)]
            # 2026-10-11：本次修改原因：保存商品时保留来源币种、库存、限购与在售状态。
            values = [self.sku_table.item(row, col).text().strip() for col in range(14)]
            metadata = self.sku_table.item(row, 0).data(Qt.ItemDataRole.UserRole) or {}
            specs = metadata.get("specs", {})
            if len(specs) <= 2 or self.confirm_mapping.isChecked():
                specs = {name: value for name, value in ((product.spec1_name, values[1]), (product.spec2_name, values[2])) if name and value}
            # product.skus.append(SKU(platform_sku=values[0], spec1=values[1], spec2=values[2],
            #                         source_price=values[3], price=values[4], currency=product.currency,
            #                         stock=values[5], weight=values[6], dimensions=values[7], image=values[8], specs=specs))
            product.skus.append(SKU(platform_sku=values[0], spec1=values[1], spec2=values[2],
                                    # 2026-10-11：本次修改原因：商家 SKU 修改后仍保留稳定来源 ID。
                                    source_sku_id=metadata.get("source_sku_id", ""),
                                    source_price=values[3], price=values[4], currency=product.currency,
                                    source_currency=values[10], stock=values[5], source_stock=values[11],
                                    purchase_limit=values[12], weight=values[6], dimensions=values[7], image=values[8], specs=specs,
                                    availability=metadata.get("availability", "")))
        return product

    def check(self) -> None:
        try:
            issues = self.collect().issues()
            if issues:
                QMessageBox.warning(self, "商品尚需完善", "\n".join(f"• {issue}" for issue in issues[:30]))
            else:
                QMessageBox.information(self, "检查通过", "必填字段和规格已通过检查。请核对商品真实性、售价及渠道要求后审核。")
        except ValueError as error:
            QMessageBox.warning(self, "字段格式", str(error))

    # 2026-10-11：本次修改原因：在字段标题行右侧放置 AI 按钮，避免将模型调用写进控件。
    def ai_field(self, form: QFormLayout, caption: str, editor: QWidget, operation: str):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QHBoxLayout()
        heading.addWidget(label(caption))
        heading.addStretch()
        heading.addWidget(button("AI 生成", lambda: self.open_ai(operation)))
        layout.addLayout(heading)
        layout.addWidget(editor)
        form.addRow("", container)

    def open_sku_ai(self):
        row = self.sku_table.currentRow()
        item = self.sku_table.item(row, 8) if row >= 0 else None
        if not item:
            QMessageBox.information(self, "请选择 SKU", "请先选择需要处理图片的 SKU。")
            return
        self.open_ai("image", "sku", item.text().strip(), row)

    def open_ai(self, operation: str, target: str = "images", address: str = "", sku_row: int = -1):
        if not self.ai_service:
            QMessageBox.information(self, "AI 配置", "请从商品工作台打开编辑器，并在设置 → AI 模型中完成配置。")
            return
        try:
            snapshot = self.collect().to_dict()
        except ValueError as error:
            QMessageBox.warning(self, "请检查商品事实", str(error))
            return
        # 2026-10-11：本次修改原因：SKU 改图只提供当前规格事实，避免其他颜色和尺寸混入。
        if target == "sku" and 0 <= sku_row < len(snapshot.get("skus", [])):
            snapshot["skus"] = [snapshot["skus"][sku_row]]
        workspace = AIWorkspace(self.ai_service, self.ai_hub, snapshot, operation, self.network, address, self)
        # 2026-10-11：本次修改原因：SKU 字段只能替换单图，候选默认只生成一张。
        if target == "sku":
            workspace.count.setValue(1)
            workspace.application.setVisible(False)
        if workspace.exec() != QDialog.DialogCode.Accepted:
            return
        if operation == "title":
            self.fields["title"].setText(workspace.applied_text)
        elif operation == "simple_description":
            self.simple_description.setPlainText(workspace.applied_text)
        elif operation == "description_html":
            self.rich_description.set_html(workspace.applied_text)
        elif workspace.applied_assets:
            values = workspace.applied_assets
            if target == "sku":
                if len(values) != 1:
                    QMessageBox.information(self, "SKU 图片", "一个 SKU 图片字段只能应用一张图，请从历史候选中勾选一张后应用。")
                    return
                self.sku_table.item(sku_row, 8).setText(values[0])
            elif target == "html":
                # self.replace_description_image(address, values)
                # 2026-10-11：本次修改原因：详情正文按用户的替换/追加选择处理，同步对应详情图列表。
                if workspace.apply_mode == "append":
                    self.rich_description.set_html(self.rich_description.html() + detail_html("", values))
                    self.detail_images.set_urls(self.detail_images.toPlainText().splitlines() + values)
                else:
                    self.replace_description_image(address, values)
                    old = self.detail_images.toPlainText().splitlines()
                    if address in old:
                        index = old.index(address)
                        self.detail_images.set_urls(old[:index] + values + old[index + 1:])
                self.detail_images.textChanged.emit()
            else:
                media = self.detail_images if target == "detail_images" else self.images
                old = media.toPlainText().splitlines()
                if workspace.apply_mode == "replace_set":
                    updated = values
                elif workspace.apply_mode == "replace" and address in old:
                    index = old.index(address)
                    updated = old[:index] + values + old[index + 1:]
                else:
                    updated = old + values
                media.set_urls(updated)
                media.textChanged.emit()
                if target == "detail_images" and workspace.apply_mode == "replace":
                    self.replace_description_image(address, values)
                if workspace.result:
                    for asset in workspace.result.assets:
                        media.update_size(asset.uri, asset.width, asset.height)
        self.mark_dirty()

    def replace_description_image(self, address: str, values: list[str]):
        html = self.rich_description.html()
        pattern = r'<img\b[^>]*\bsrc="' + re.escape(escape(address, quote=True)) + r'"[^>]*>'
        # updated = re.sub(pattern, lambda _match: detail_html("", values), html, flags=re.I)
        # 2026-10-11：本次修改原因：替换图片标签时不嵌套段落，保留原图所在的正文结构。
        replacement = "".join(f'<img src="{escape(value, quote=True)}" width="640" />'
                              for value in values if valid_media_url(value))
        updated = re.sub(pattern, lambda _match: replacement, html, flags=re.I)
        if updated != html:
            self.rich_description.set_html(updated)

    def save_product(self, approve: bool) -> None:
        try:
            # self.repository.save_product(self.collect(), approve=approve)
            # 2026-10-11：本次修改原因：没有实际表单内容改动时保留原商品内容，只存预览像素缓存和审核操作。
            product = self.collect()
            if product.business_content() == self.initial_form_content:
                sizes = product.image_sizes
                product = Product.from_dict(self.product.to_dict())
                product.image_sizes = sizes
            self.repository.save_product(product, approve=approve)
        except Exception as error:
            QMessageBox.warning(self, "未能保存", str(error))
            return
        self.dirty = False
        self.accept()

    def reject(self) -> None:
        if self.dirty and QMessageBox.question(self, "未保存的修改", "关闭后将丢弃本次未保存的修改。是否关闭？",
                                              QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                              QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Discard:
            return
        super().reject()
