# 2026-10-10：本次修改原因：提供电商商品分区编辑、规格定价和人工审核，所有修改保存为新版本。
from __future__ import annotations

from dataclasses import asdict
# 2026-10-15：本次修改原因：商品编辑页可查看冻结配方的完整资料，不从现有原料反推历史设计。
import json

# from PySide6.QtCore import Qt
# 2026-10-11：本次修改原因：延迟更新缩略图并支持打开已采集的视频链接。
# from PySide6.QtCore import Qt, QTimer, QUrl
# 2026-10-13：本次修改原因：商品编辑改为页面，通过信号返回列表，不运行模态事件循环。
from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QEvent
 # from PySide6.QtGui import QDesktopServices
# 2026-10-13：本次修改原因：Ctrl+S 复用保存修改，编辑器布局使用独立显示偏好。
from PySide6.QtGui import QDesktopServices, QShortcut, QKeySequence
from PySide6.QtCore import QSettings
from .layout_support import PersistentSplitter, Panel, save_splitters
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget, QAbstractItemView,
    # 2026-10-12：本次修改原因：滚动表单由内部最小尺寸约束撑开，避免表格与后续控件重叠。
    QLayout,
)
# 2026-10-13：本次修改原因：页面顶部使用矢量返回图标，保持高 DPI 和主题切换清晰。
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QToolButton
from .widgets import icon
from .theme import theme_tokens

# from ..models import Product, SKU, positive_decimal
# 2026-10-10：本次修改原因：预览前限制图片链接协议为 HTTP/HTTPS。
from ..models import Product, SKU, positive_decimal, valid_url
from ..storage import Repository
# from .widgets import ImagePreview, button, label
# 2026-10-11：本次修改原因：编辑页增加图片分组缩略图与来源 SKU 信息展示。
# from .widgets import ImageGallery, ImagePreview, button, label
# 2026-10-13：本次修改原因：属性与图片栏目改为完整分区卡片，表格不再嵌在错位的标签列中。
from .widgets import ImageGallery, ImagePreview, button, label, card
# 2026-10-11：本次修改原因：按妙手八个栏目组织编辑器，图文详情和图片排序使用独立控件。
from ..content import attribute_description, detail_html, sku_image_groups, with_detail_images
from .media_list import MediaList
# from .table_support import configure_table
from .table_support import configure_table, fit_table_rows
from .rich_description import RichDescription

# 2026-10-11：本次修改原因：字段就地 AI 入口复用公共服务，生成结果先应用到表单，再由原保存流程版本化。
from html import escape
import re
from ..ai.service import AIService
from ..assets import valid_media_url
from .ai_runner import TaskHub
from .ai_workspace import AIWorkspace
 # 2026-10-13：本次修改原因：统一模式页和原子应用草稿，复用已保存爆款方案。
# from PySide6.QtWidgets import QStackedWidget, QTabBar
# 2026-10-13：本次修改原因：商品身份文本可缩短显示，确保返回和模式切换始终可见。
from PySide6.QtWidgets import QStackedWidget, QTabBar, QSizePolicy
from ..ai.references import ReferenceStore
from ..ai.workflow import apply_changes
from .ai_workbench import AIWorkbench
# 2026-10-12：本次修改原因：字段 AI 缺少有效配置时可就地打开共用模型设置。
# from .model_settings import ModelSettingsDialog
# 2026-10-14：本次修改原因：业务页面不再打开模型设置弹窗。
# 模型配置统一从设置页进入。
# 2026-10-12：本次修改原因：共用字段限制和表单差异保护，标题/AI 文案修改不连带改写原始详情及 SKU 元数据。
# from ..miaoshou_mapping import draft_limit_issues, preserve_unedited_form
# 2026-10-12：本次修改原因：主图实时数量和审核反馈使用相同上限，格式校验统一交给保存/审核服务。
from ..miaoshou_mapping import MAX_MAIN_IMAGES, MAX_SPEC_IMAGES, preserve_unedited_form


def text_editor(text: str = "", placeholder: str = "", height: int = 100) -> QPlainTextEdit:
    editor = QPlainTextEdit(text)
    editor.setPlaceholderText(placeholder)
    editor.setMinimumHeight(height)
    return editor


# class ProductEditor(QDialog):
# 2026-10-13：本次修改原因：编辑内容直接加入主窗口页面栈，保存和取消仍使用原校验与结果代码。
class ProductEditor(QWidget):
    closed = Signal(int)
    accepted = Signal()
    rejected = Signal()
    # def __init__(self, repository: Repository, product: Product, network: QNetworkAccessManager, parent=None):
    # 2026-10-11：本次修改原因：两条来源共用模型服务与后台任务，兼容现有编辑器构造方式。
    # def __init__(self, repository: Repository, product: Product, network: QNetworkAccessManager, parent=None,
    #              ai_service: AIService | None = None, ai_hub: TaskHub | None = None):
    # 2026-10-13：本次修改原因：新增共享方案库参数，现有调用参数兼容。
    def __init__(self, repository: Repository, product: Product, network: QNetworkAccessManager, parent=None,
                 ai_service: AIService | None = None, ai_hub: TaskHub | None = None, reference_store=None):
        super().__init__(parent)
        self.repository, self.product, self.dirty = repository, product, False
        # 2026-10-11：本次修改原因：SKU 预览复用主窗口的异步图片连接。
        self.network = network
        self.ai_service = ai_service
        self.ai_hub = ai_hub or TaskHub(self)
        # 2026-10-13：本次修改原因：统一 AI 工作区延迟创建，不把 Prompt 编辑误标成商品已修改。
        self.reference_store = reference_store or (ReferenceStore(ai_service.config.path.parent) if ai_service else None)
        self.ai_workbench = None
        self.setWindowTitle(f"编辑商品 · {product.main_code}")
        # self.resize(1120, 790)
        # self.setMinimumSize(940, 650)
        # 2026-10-13：本次修改原因：编辑页跟随主内容区大小，不再要求独立窗口尺寸。
        self.setObjectName("productEditorPage")
        self._finished = False
        root = QVBoxLayout(self)
        # root.setContentsMargins(26, 22, 26, 20)
        # root.setSpacing(16)
        # root.addWidget(label("商品编辑", "pageTitle"))
        # root.addWidget(label(f"{product.source.upper()} · {product.source_id} · {product.site or '站点未提供'}    /    当前版本 v{product.revision}", "muted"))
        # 2026-10-13：本次修改原因：返回入口与商品身份同一行展示，主表单保留更多可用高度。
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        heading = QHBoxLayout()
        self.back_button = QToolButton()
        self.back_button.setObjectName("editorBack")
        self.back_button.setIcon(icon("back", theme_tokens()["text"]))
        self.back_button.setIconSize(QSize(20, 20))
        self.back_button.setFixedSize(36, 36)
        self.back_button.setToolTip("返回商品列表")
        self.back_button.setAccessibleName("返回商品列表")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.reject)
        heading.addWidget(self.back_button)
        heading.addWidget(label("商品编辑", "sectionTitle"))
        identity = label(f"{product.main_code} · {product.source.upper()} · {product.site or '站点未提供'} · v{product.revision}", "muted")
        # identity.setToolTip(f"货源 ID：{product.source_id}")
        # 2026-10-13：本次修改原因：长商品编号不撑宽页面，完整信息可通过悬停查看。
        identity.setToolTip(identity.text() + f"\n货源 ID：{product.source_id}")
        identity.setMinimumWidth(0)
        identity.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.addWidget(identity, 1)
        # 2026-10-13：本次修改原因：单一模式切换代替每个字段的 AI 按钮，返回列表入口保持原位。
        self.mode_tabs = QTabBar()
        self.mode_tabs.setObjectName("editorModeTabs")
        self.mode_tabs.addTab("手动修改")
        self.mode_tabs.addTab("AI 处理")
        self.mode_tabs.setExpanding(False)
        # self.mode_tabs.setDrawBase(False)
        # self.mode_tabs.currentChanged.connect(self.switch_mode)
        # 2026-10-13：本次修改原因：模式切换只有两项，保持完整文字并撤下滚动箭头，防止样式生效后 AI 入口被挤住。
        self.mode_tabs.setDrawBase(False)
        self.mode_tabs.setUsesScrollButtons(False)
        self.mode_tabs.setElideMode(Qt.TextElideMode.ElideNone)
        # self.mode_tabs.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        # self.mode_tabs.currentChanged.connect(self.switch_mode)
        # 2026-10-13：本次修改原因：按已生效样式预留两个标签及边距，消除 Qt 标签尺寸取整造成的边缘裁切。
        self.mode_tabs.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.mode_tabs.ensurePolished()
        self.mode_tabs.setMinimumWidth(self.mode_tabs.sizeHint().width() + 8)
        self.mode_tabs.currentChanged.connect(self.switch_mode)
        heading.addWidget(self.mode_tabs)
        root.addLayout(heading)
        # 2026-10-12：本次修改原因：显示 API 来源及人民币单位，帮助用户区分旧插件自解析商品。
        if product.erp_imported:
            root.addWidget(label(f"妙手 API 导入 · 原商品 ID {product.erp_original_id} · 金额单位 CNY · 未编辑的远端字段完整保留", "hint", True))
        self.tabs = QTabWidget()
        # root.addWidget(self.tabs, 1)
        # 2026-10-13：本次修改原因：字段与图片/AI候选分栏，不恢复商品列表速览，不改变保存和应用边界。
        # self.editor_splitter = PersistentSplitter(Qt.Orientation.Horizontal, "ui/editor/form_preview_splitter_v1", [780, 340], self)
        # self.tabs.setMinimumWidth(560)
        # 2026-10-13：本次修改原因：取消常驻图片预览区，平时表单全宽，点击 AI 后才显示右侧工作区。
        # self.editor_splitter = PersistentSplitter(Qt.Orientation.Horizontal, "ui/editor/form_ai_splitter_v2", [620, 480], self)
        # self.tabs.setMinimumWidth(420)
        # self.editor_splitter.addWidget(self.tabs)
        # self.preview_area = QWidget()
        # self.preview_layout = QVBoxLayout(self.preview_area)
        # self.preview_layout.setContentsMargins(0, 0, 0, 0)
        # self.edit_preview = ImagePreview(network, 220)
        # self.preview_layout.addWidget(self.edit_preview)
        # self.preview_layout.addWidget(label("预览当前主图；字段旁的 AI 按钮在此展开候选。应用后仍需保存。", "hint", True))
        # self.preview_layout.addStretch()
        # self.preview_panel = Panel("图片预览 / AI 候选", self.preview_area)
        # self.editor_splitter.addWidget(self.preview_panel)
        # 2026-10-13：本次修改原因：AI 容器无预览占位、无额外折叠标题，关闭 AI 后完全让出宽度。
        # self.ai_area = QWidget()
        # self.ai_area.setMinimumWidth(440)
        # self.ai_layout = QVBoxLayout(self.ai_area)
        # self.ai_layout.setContentsMargins(0, 0, 0, 0)
        # self.editor_splitter.addWidget(self.ai_area)
        # self.ai_area.hide()
        # root.addWidget(self.editor_splitter, 1)
        # 2026-10-13：本次修改原因：手动表单/AI 使用全宽页面，高 DPI 下不再压缩为狭窄抽屉。
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self.tabs)
        root.addWidget(self.mode_stack, 1)
        self.ai_workspace = None
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
        # 2026-10-15：本次修改原因：成链商品更换图片或规格后提供配方核对入口，审核前明确重新确认。
        self.design_review = None
        if product.source_route == "bead_chain":
            design_row = QHBoxLayout()
            design_row.addWidget(button("查看锁定配方", self.show_design_recipe))
            self.design_review = QCheckBox("已对照锁定配方核对当前图片、SKU 与文案")
            self.design_review.setChecked(bool(product.bom_snapshot.get("images_confirmed")))
            self.design_review.setToolTip("修改图片、规格或文案后会取消确认；售价和库存单独修改时保留确认。配方改款请回到散珠成链复制设计。")
            design_row.addWidget(self.design_review, 1)
            root.addLayout(design_row)
        # 2026-10-12：本次修改原因：加工阶段提前说明本机图片上传边界及 AI 应用后仍需保存。
        self.edit_feedback = label("AI 结果应用后需保存商品；本机白底图及生成图回传前需转换为公网链接。", "hint", True)
        # 2026-10-14：本次修改原因：本机素材状态单独显示，不被未保存或 AI 应用成功提示覆盖。
        self.local_media_hint = label("", "warning", True)
        self.local_media_hint.hide()
        # self.local_media_hint.setToolTip("先将本机图片或附件托管为公网链接，再在商品对应栏目替换链接、保存审核。软件尚未自动托管。")
        # 2026-10-14：本次修改原因：图片已在同步 ERP 前由图床流程自动托管，附件类素材仍需单独检查公网要求。
        self.local_media_hint.setToolTip("采用的本机图片会在同步 ERP 前自动托管并替换为新公网链接；视频、认证附件和说明书仍需按对应字段补充可访问链接。设置 → 图床可检测与重试。")
        root.addWidget(self.local_media_hint)
        root.addWidget(self.edit_feedback)
        # footer = QHBoxLayout()
        # 2026-10-13：本次修改原因：AI 模式仅展示生成/应用操作，商品保存留在手动核对页面。
        self.manual_footer = QWidget()
        footer = QHBoxLayout(self.manual_footer)
        footer.setContentsMargins(0, 0, 0, 0)
        # footer.addWidget(button("检查完整性", self.check))
        # 2026-10-13：本次修改原因：右侧候选展开期间锁住检查和保存，保持原模态窗口的操作范围。
        self.check_button = button("检查完整性", self.check)
        footer.addWidget(self.check_button)
        footer.addStretch()
        footer.addWidget(button("取消", self.reject))
        # footer.addWidget(button("保存修改", lambda: self.save_product(False)))
        # footer.addWidget(button("保存并审核", lambda: self.save_product(True), primary=True))
        # 2026-10-13：本次修改原因：AI 候选打开时维持原弹窗锁定语义，避免生成中提交表单。
        self.save_button = button("保存修改", lambda: self.save_product(False))
        self.approve_save_button = button("保存并审核", lambda: self.save_product(True), primary=True)
        footer.addWidget(self.save_button)
        footer.addWidget(self.approve_save_button)
        # root.addLayout(footer)
        root.addWidget(self.manual_footer)
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
        # 2026-10-15：本次修改原因：人工勾选确认独立于内容变动，保存时交由存储层核验来源快照。
        if self.design_review is not None:
            self.design_review.toggled.connect(self.mark_dirty)
        self.tabs.currentChanged.connect(lambda _index: self.refresh_sku_images())
        # 2026-10-13：本次修改原因：预览不触发字段修改；标签页与快捷键仅复用现有编辑入口。
        # 2026-10-13：本次修改原因：预览复用现有异步图片接口，不生成或存储新商品字段。
        # self.edit_preview.set_url(product.images[0] if product.images else "")
        # self.images.textChanged.connect(self.update_edit_preview)
        self.save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.save_shortcut.activated.connect(self.save_button.click)
        self.editor_preferences = QSettings("BeadDiff", "BeadDiff")
        tab = self.editor_preferences.value("ui/editor/current_tab", 0)
        if isinstance(tab, int) and 0 <= tab < self.tabs.count():
            self.tabs.setCurrentIndex(tab)
        self.dirty = False
        # 2026-10-11：本次修改原因：记录表单初始显示内容，避免描述回退和 SKU 币种规范化把直接保存误判为人工修改。
        try:
            # self.initial_form_content = self.collect().business_content()
            # 2026-10-12：本次修改原因：保留首屏规范化表单快照，后续只应用用户实际改变的单字段。
            self.initial_form_product = self.collect()
            self.initial_form_content = self.initial_form_product.business_content()
            # 2026-10-15：本次修改原因：记录表单规范化后的核对内容，未编辑字段不误取消原有人工确认。
            self._last_design_review_content = self.initial_form_product.design_review_content()
        except ValueError:
            self.initial_form_content = None

        # 2026-10-14：本次修改原因：打开已有本机图的商品时立即显示回传条件，且不标记商品已修改。
        self.refresh_local_media_hint()

    # 2026-10-13：本次修改原因：主图地址变化仅刷新异步预览，不参与审核或保存判断。
    # def update_edit_preview(self):
    #     urls = self.images.toPlainText().splitlines()
    #     self.edit_preview.set_url(urls[0] if urls else "")

    # 2026-10-13：本次修改原因：返回图标随应用主题更新；其他字段和编辑行为不变。
    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange) and hasattr(self, "back_button"):
            self.back_button.setIcon(icon("back", theme_tokens()["text"]))

    # 2026-10-14：本次修改原因：只读取图片和附件控件，其他字段尚未填完时也能正确提示本机素材。
    def refresh_local_media_hint(self):
        from ..content import description_images
        addresses = self.images.toPlainText().splitlines() + self.detail_images.toPlainText().splitlines()
        addresses += description_images(self.rich_description.html())
        addresses += [self.sku_table.item(row, 8).text() for row in range(self.sku_table.rowCount())
                      if self.sku_table.item(row, 8)]
        addresses += [self.fields[name].text() for name in (
            "video", "certificate", "size_chart", "body_size_chart", "instruction_manual") if name in self.fields]
        count = len({address.strip() for address in addresses if address.strip().startswith("file:")})
        # self.local_media_hint.setText(f"当前商品含 {count} 项本机素材：可预览和保存；回传前须托管并替换为 HTTP/HTTPS 链接，自动托管尚未接入。" if count else "")
        # 2026-10-14：本次修改原因：提示与当前图片自动上传、附件单独校验的链路保持一致。
        self.local_media_hint.setText(
            f"当前商品含 {count} 项本机素材：保存并审核后，同步 ERP 时会自动托管采用的图片并替换为新 HTTP/HTTPS 链接；视频、认证附件和说明书请在对应栏目补充公网链接。" if count else "")
        self.local_media_hint.setVisible(bool(count))

    def mark_dirty(self, *_args) -> None:
        self.dirty = True
        # 2026-10-15：本次修改原因：手动编辑和 AI 应用均不能沿用与旧图片、旧规格对应的确认状态。
        if getattr(self, "design_review", None) is not None and hasattr(self, "_last_design_review_content"):
            try:
                current = self.collect().design_review_content()
            except (ValueError, AttributeError):
                current = None
            if current != self._last_design_review_content:
                self._last_design_review_content = current
                self.design_review.setChecked(False)
        # 2026-10-12：本次修改原因：手动和 AI 操作均明确显示未保存状态。
        if hasattr(self, "edit_feedback"):
            # self.edit_feedback.setText("有未保存修改。保存修改形成新版本；保存并审核后才可检查回传条件。")
            # 2026-10-14：本次修改原因：修改或应用图片后实时保留本机素材回传提示，不被成功提示覆盖。
            self.edit_feedback.setText("有未保存修改。保存修改形成新版本；保存并审核后才可检查回传条件。")
        if hasattr(self, "local_media_hint"):
            self.refresh_local_media_hint()

    # 2026-10-14：本次修改原因：主编号缺失时给出来源与补填方式，仅由用户点击填入且不覆盖已有编号。
    def refresh_main_code_help(self, *_args):
        empty = not self.fields["main_code"].text().strip()
        source_id = self.product.source_id.strip()
        imported_empty = self.product.erp_imported and not self.product.main_code
        explanation = "妙手导入时未提供产品主编号。" if imported_empty else "当前产品主编号为空。"
        self.main_code_help.setText(explanation + "新增商品前需补全；来源商品 ID 与妙手商品 ID 是不同字段。")
        self.main_code_help.setVisible(empty)
        self.fill_main_code_button.setVisible(empty and bool(source_id))
        self.fill_main_code_button.setEnabled(bool(source_id) and len(source_id) <= 255)
        self.fill_main_code_button.setToolTip(f"将来源商品 ID「{source_id}」填入主编号，仅修改当前草稿，保存后生效。")

    def fill_main_code_from_source(self):
        field = self.fields["main_code"]
        source_id = self.product.source_id.strip()
        if field.text().strip() or not source_id or len(source_id) > 255:
            return
        field.setText(source_id)
        field.setFocus()

    def _tab_form(self, title: str) -> QFormLayout:
        contents = QWidget()
        # 2026-10-13：本次修改原因：明确表单内容白底，滚动区域不再露出 Qt 默认灰色底板。
        contents.setObjectName("editorForm")
        form = QFormLayout(contents)
        form.setContentsMargins(24, 24, 24, 24)
        form.setSpacing(16)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        # 2026-10-12：本次修改原因：内部控件高度不足时滚动，不压缩表格和图片工具栏相互覆盖。
        form.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(contents)
        self.tabs.addTab(scroll, title)
        return form

    # 2026-10-13：本次修改原因：复杂表格/图片整块独占栏目宽度，顶部对齐且由外层统一滚动。
    def _section_page(self, title: str) -> QVBoxLayout:
        contents = QWidget()
        contents.setObjectName("editorForm")
        layout = QVBoxLayout(contents)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(contents)
        self.tabs.addTab(scroll, title)
        return layout

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
        # 2026-10-12：本次修改原因：编辑时就显示公共采集箱文本上限，AI 输出保存前使用同样校验。
        form.addRow("", label("公共采集箱：标题最多 255 字符，简述最多 65536 字符，详细描述 HTML 最多 100000 字符。", "hint", True))
        # form.addRow("产品主编号 *", self._field("main_code", "同一商品的 SKU 共用一个产品主编号"))
        # 2026-10-14：本次修改原因：主编号为空时解释原始数据并提供主动补填入口，不在导入或 AI 应用中自动改编号。
        code_row = QWidget()
        code_layout = QHBoxLayout(code_row)
        code_layout.setContentsMargins(0, 0, 0, 0)
        code_layout.addWidget(self._field("main_code", "同一商品的 SKU 共用一个产品主编号"), 1)
        self.fill_main_code_button = button("使用来源商品 ID 填入", self.fill_main_code_from_source)
        code_layout.addWidget(self.fill_main_code_button)
        form.addRow("产品主编号 *", code_row)
        self.main_code_help = label("", "warning", True)
        form.addRow("", self.main_code_help)
        self.fields["main_code"].textChanged.connect(self.refresh_main_code_help)
        self.refresh_main_code_help()
        simple = self.product.simple_description
        if not simple and "simple_description" not in self.product.manual_fields:
            simple = attribute_description(self.product.attributes)
        self.simple_description = text_editor(simple, "产品简述；可从产品属性生成", 140)
        # form.addRow("简易描述", self.simple_description)
        # 2026-10-11：本次修改原因：简易描述使用同一文本模型入口。
        self.ai_field(form, "简易描述", self.simple_description, "simple_description")
        form.addRow("", button("从产品属性更新简易描述", self.describe_attributes))
        # 2026-10-11：本次修改原因：说明简易描述与 22 列模板的映射边界，避免编辑后误以为会单列导出。
        # 2026-10-12：本次修改原因：撤下表格路线，说明简述和详情的独立加工及回传。
        form.addRow("", label("简易描述与图文详情分别保存并回传，可独立手动或 AI 修改。", "hint", True))
        html = self.product.description_html
        if not html and "description_html" not in self.product.manual_fields:
            legacy_text = self.product.description if "description" in self.product.manual_fields else ""
            html = detail_html(legacy_text, self.product.detail_images)
        self.rich_description = RichDescription(self.network, html)
        # form.addRow("详细描述", self.rich_description)
        # 2026-10-11：本次修改原因：详情支持 AI 文案与其中单张图片处理。
        self.ai_field(form, "详细描述", self.rich_description, "description_html")
        # self.rich_description.aiRequested.connect(lambda address: self.open_ai("image", "html", address))
        # 2026-10-13：本次修改原因：详情正文图片在统一 AI 页选择，手动表单取消分散的 AI 入口。
        form.addRow("", button("用详情图更新图文描述", self.describe_images))

    # 2026-10-11：本次修改原因：产品属性按妙手的名称/值两列编辑，而非仅展示一段文字。
    # def _attribute_tab(self) -> None:
    #     form = self._tab_form("产品属性")
    #     form.addRow("类目路径", self._field("category", "来源类目；发布时仍需匹配目标渠道类目"))
    #     self.attribute_table = QTableWidget(0, 2)
    #     self.attribute_table.setHorizontalHeaderLabels(["属性名称", "属性值"])
    #     self.attribute_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    #     self.attribute_table.setAlternatingRowColors(True)
    #     self.attribute_table.verticalHeader().setDefaultSectionSize(44)
    #     self.attribute_table.setMinimumHeight(380)
    #     # 2026-10-12：本次修改原因：属性值及行号统一字体安全高度，单元格输入框不继承大表单内边距。
    #     configure_table(self.attribute_table)
    #     form.addRow(self.attribute_table)
    #     for name, value in self.product.attributes.items():
    #         self.add_attribute(name, value)
    #     self.attribute_count = label(f"产品属性（{self.attribute_table.rowCount()} 项）")
    #     # form.addRow(self.attribute_count, self.attribute_table)
    #     # 2026-10-12：本次修改原因：属性表独占整行，属性数放在工具栏以免窄屏标签挤压表格。
    #     actions = QHBoxLayout()
    #     actions.addWidget(self.attribute_count)
    #     actions.addWidget(button("新增属性", lambda: self.add_attribute()))
    #     actions.addWidget(button("移除选中", self.remove_attributes))
    #     actions.addStretch()
    #     form.addRow("", actions)
    #     form.addRow("", label("材料、颜色、长度和包装请按实物核对；串珠 BOM 约束仍需后续实现。", "hint", True))

    # 2026-10-13：本次修改原因：属性区以标题、完整表格和工具栏分层，短表按行数收起空白；不再固定 380px 高度。
    def _attribute_tab(self) -> None:
        layout = self._section_page("产品属性")
        frame, contents = card()
        category = QHBoxLayout()
        category.addWidget(label("类目路径", "hint"))
        category.addWidget(self._field("category", "来源类目；发布时仍需匹配目标渠道类目"), 1)
        contents.addLayout(category)
        heading = QHBoxLayout()
        heading.addWidget(label("产品属性", "sectionTitle"), 1)
        self.attribute_count = label("0 项", "muted")
        heading.addWidget(self.attribute_count)
        heading.addWidget(button("新增属性", lambda: self.add_attribute()))
        heading.addWidget(button("移除所选", self.remove_attributes))
        contents.addLayout(heading)
        self.attribute_table = QTableWidget(0, 2)
        self.attribute_table.setHorizontalHeaderLabels(["属性名称", "属性值"])
        self.attribute_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        configure_table(self.attribute_table)
        fit_table_rows(self.attribute_table, maximum_rows=10)
        contents.addWidget(self.attribute_table)
        for name, value in self.product.attributes.items():
            self.add_attribute(name, value)
        contents.addWidget(label("双击编辑；长内容可右键完整编辑。材料、颜色、长度和包装请按实物核对，串珠 BOM 约束仍需后续实现。", "hint", True))
        layout.addWidget(frame)

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
            # if not name or not value:
            # 2026-10-12：本次修改原因：ERP 原有空属性可随无关字段编辑保留，不强迫补写远端未要求的数据。
            original_value = self.product.erp_imported and name in self.product.attributes and self.product.attributes[name] == value
            if not name or not value and not original_value:
                raise ValueError(f"属性第 {row + 1} 行需要同时填写名称和值。")
            # if name in result or any(character in name + value for character in "；\n\r"):
            # 2026-10-12：本次修改原因：API 原属性的分号/换行保持原值，手动新输入仍按原编辑规则校验。
            if name in result or not original_value and any(character in name + value for character in "；\n\r"):
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
    # def _miaoshou_images_tab(self) -> None:
    #     form = self._tab_form("产品图片")
    #     # self.images = MediaList(self.product.images, self.product.image_sizes)
    #     # 2026-10-11：本次修改原因：商品图片支持本地上传和单图 AI，套图仍保持可排序图片组。
    #     assets = self.ai_service.assets if self.ai_service else None
    #     # self.images = MediaList(self.product.images, self.product.image_sizes, assets, enable_ai=True)
    #     # 2026-10-12：本次修改原因：原有超限列表打开即显示 16 / 15，手动粘贴、上传和 AI 套图后实时更新。
    #     self.images = MediaList(self.product.images, self.product.image_sizes, assets, enable_ai=True, maximum=MAX_MAIN_IMAGES)
    #     self.images.aiRequested.connect(lambda address: self.open_ai("image", "images", address))
    #     self.product_gallery = ImageGallery(self.network)
    #     self.product_gallery.enable_ai = True
    #     self.product_gallery.aiRequested.connect(lambda address: self.open_ai("image", "images", address))
    #     # 2026-10-11：本次修改原因：预览返回实际图片尺寸，补齐源材料未提供的尺寸显示。
    #     self.product_gallery.sizeLoaded.connect(self.images.update_size)
    #     form.addRow("产品图片 *", self.images)
    #     form.addRow("", button("AI 生成套图", lambda: self.open_ai("image_set", "images")))
    #     # form.addRow("", label("第一张为主图，可上移/下移调整顺序；像素尺寸仅显示采集材料的明确值。", "hint", True))
    #     # 2026-10-12：本次修改原因：明确整个产品图片列表最多 15 张，不只第一张主图受限，不自动删图。
    #     form.addRow("", label(f"产品图片最多 {MAX_MAIN_IMAGES} 张，第一张为主图，可上移/下移排序；超限须先移除或调整图片用途才能保存。", "hint", True))
    #     form.addRow("", self.product_gallery)
    #     self.sku_group_dimension = QComboBox()
    #     self.sku_group_dimension.addItems([self.fields["spec1_name"].text(), self.fields["spec2_name"].text()])
    #     color_index = next((index for index, name in enumerate(
    #         [self.product.spec1_name, self.product.spec2_name]) if "颜色" in name or "color" in name.lower()), 0)
    #     self.sku_group_dimension.setCurrentIndex(color_index)
    #     self.sku_group = QComboBox()
    #     group_actions = QHBoxLayout()
    #     group_actions.addWidget(label("分组维度"))
    #     group_actions.addWidget(self.sku_group_dimension)
    #     group_actions.addWidget(self.sku_group, 1)
    #     form.addRow("SKU 图片", group_actions)
    #     self.sku_group_count = label("", "muted", True)
    #     form.addRow("", self.sku_group_count)
    #     self.sku_group_gallery = ImageGallery(self.network)
    #     form.addRow("", self.sku_group_gallery)
    #     self.sku_group_table = QTableWidget(0, 2)
    #     self.sku_group_table.setHorizontalHeaderLabels(["对应 SKU 规格", "SKU 图片链接"])
    #     self.sku_group_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    #     self.sku_group_table.setMinimumHeight(155)
    #     # 2026-10-12：本次修改原因：分组图片表原先使用 Qt 默认行高，导致图片链接和行号被全局 padding 裁切。
    #     configure_table(self.sku_group_table)
    #     self.sku_group_table.itemChanged.connect(self.group_image_changed)
    #     form.addRow("", self.sku_group_table)
    #     self.sku_group_dimension.currentIndexChanged.connect(lambda _index: self.refresh_sku_images())
    #     self.sku_group.currentIndexChanged.connect(lambda _index: self.render_sku_group())
    #     # self.detail_images = MediaList(self.product.detail_images, self.product.image_sizes)
    #     # 2026-10-11：本次修改原因：详情图同样可上传和 AI 修改，并同步已有正文中的对应图。
    #     self.detail_images = MediaList(self.product.detail_images, self.product.image_sizes, assets, enable_ai=True)
    #     self.detail_images.aiRequested.connect(lambda address: self.open_ai("image", "detail_images", address))
    #     self.detail_gallery = ImageGallery(self.network)
    #     self.detail_gallery.enable_ai = True
    #     self.detail_gallery.aiRequested.connect(lambda address: self.open_ai("image", "detail_images", address))
    #     self.detail_gallery.sizeLoaded.connect(self.detail_images.update_size)
    #     form.addRow("详情图片", self.detail_images)
    #     form.addRow("", self.detail_gallery)
    #     form.addRow("产品尺码表", self._field("size_chart", "产品尺码表图片链接"))
    #     form.addRow("身体尺码表", self._field("body_size_chart", "身体尺寸对照图片链接"))
    #     form.addRow("", label("SKU 图片与销售属性表双向同步；编辑详情图列表后，可在基本信息中更新图文描述。", "hint", True))
    #     self.gallery_timer = QTimer(self)
    #     self.gallery_timer.setSingleShot(True)
    #     self.gallery_timer.setInterval(500)
    #     self.gallery_timer.timeout.connect(self.refresh_galleries)
    #     self.images.textChanged.connect(lambda: self.gallery_timer.start())
    #     self.detail_images.textChanged.connect(lambda: self.gallery_timer.start())
    #     self.refresh_galleries()
    #     self.refresh_sku_images()
    #
    # # 2026-10-11：本次修改原因：从正在编辑的 SKU 行计算选项和分组，保存前即能核对。

    # 2026-10-13：本次修改原因：主图、SKU 图片、详情图、尺码表分别以完整卡片排列，统一左边界及底部背景。
    def _miaoshou_images_tab(self) -> None:
        layout = self._section_page("产品图片")
        assets = self.ai_service.assets if self.ai_service else None
        frame, contents = card()
        heading = QHBoxLayout()
        heading.addWidget(label("产品主图", "sectionTitle"), 1)
        # heading.addWidget(button("AI 生成套图", lambda: self.open_ai("image_set", "images")))
        # 2026-10-13：本次修改原因：生成套图移入统一 AI 模式。
        contents.addLayout(heading)
        contents.addWidget(label(f"最多 {MAX_MAIN_IMAGES} 张，第一张为主图。选中后上移 / 下移；超限请调整后再保存。", "hint", True))
        # self.images = MediaList(self.product.images, self.product.image_sizes, assets, enable_ai=True, maximum=MAX_MAIN_IMAGES)
        # self.images.aiRequested.connect(lambda address: self.open_ai("image", "images", address))
        # 2026-10-13：本次修改原因：保留手动图片管理和数量限制，改图入口统一。
        self.images = MediaList(self.product.images, self.product.image_sizes, assets, maximum=MAX_MAIN_IMAGES)
        contents.addWidget(self.images)
        self.product_gallery = ImageGallery(self.network)
        # self.product_gallery.enable_ai = True
        # self.product_gallery.aiRequested.connect(lambda address: self.open_ai("image", "images", address))
        self.product_gallery.sizeLoaded.connect(self.images.update_size)
        contents.addWidget(self.product_gallery)
        layout.addWidget(frame)

        frame, contents = card()
        contents.addWidget(label("SKU 规格图片", "sectionTitle"))
        self.sku_group_dimension = QComboBox()
        self.sku_group_dimension.addItems([self.fields["spec1_name"].text(), self.fields["spec2_name"].text()])
        color_index = next((index for index, name in enumerate(
            [self.product.spec1_name, self.product.spec2_name]) if "颜色" in name or "color" in name.lower()), 0)
        self.sku_group_dimension.setCurrentIndex(color_index)
        self.sku_group = QComboBox()
        group_actions = QHBoxLayout()
        group_actions.addWidget(label("分组维度", "hint"))
        group_actions.addWidget(self.sku_group_dimension)
        group_actions.addWidget(self.sku_group, 1)
        contents.addLayout(group_actions)
        self.sku_group_count = label("", "muted", True)
        contents.addWidget(self.sku_group_count)
        self.sku_group_table = QTableWidget(0, 2)
        self.sku_group_table.setHorizontalHeaderLabels(["对应 SKU 规格", "图片链接"])
        self.sku_group_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.sku_group_table.setColumnWidth(0, 200)
        self.sku_group_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        configure_table(self.sku_group_table)
        fit_table_rows(self.sku_group_table, maximum_rows=6)
        self.sku_group_table.itemChanged.connect(self.group_image_changed)
        contents.addWidget(self.sku_group_table)
        self.sku_group_gallery = ImageGallery(self.network)
        contents.addWidget(self.sku_group_gallery)
        self.sku_group_dimension.currentIndexChanged.connect(lambda _index: self.refresh_sku_images())
        self.sku_group.currentIndexChanged.connect(lambda _index: self.render_sku_group())
        layout.addWidget(frame)

        frame, contents = card()
        contents.addWidget(label("详情图片", "sectionTitle"))
        contents.addWidget(label("详情图列表与正文分别保存；在基本信息点击“用详情图更新图文描述”同步到正文。", "hint", True))
        # self.detail_images = MediaList(self.product.detail_images, self.product.image_sizes, assets, enable_ai=True)
        # self.detail_images.aiRequested.connect(lambda address: self.open_ai("image", "detail_images", address))
        # 2026-10-13：本次修改原因：详情图片保留手动列表，AI 统一选择目标。
        self.detail_images = MediaList(self.product.detail_images, self.product.image_sizes, assets)
        contents.addWidget(self.detail_images)
        self.detail_gallery = ImageGallery(self.network)
        # self.detail_gallery.enable_ai = True
        # self.detail_gallery.aiRequested.connect(lambda address: self.open_ai("image", "detail_images", address))
        self.detail_gallery.sizeLoaded.connect(self.detail_images.update_size)
        contents.addWidget(self.detail_gallery)
        layout.addWidget(frame)

        frame, contents = card()
        contents.addWidget(label("尺码表", "sectionTitle"))
        sizes = QFormLayout()
        sizes.addRow("产品尺码表", self._field("size_chart", "产品尺码表图片链接"))
        sizes.addRow("身体尺码表", self._field("body_size_chart", "身体尺寸对照图片链接"))
        sizes.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        contents.addLayout(sizes)
        layout.addWidget(frame)
        self.gallery_timer = QTimer(self)
        self.gallery_timer.setSingleShot(True)
        self.gallery_timer.setInterval(500)
        self.gallery_timer.timeout.connect(self.refresh_galleries)
        self.images.textChanged.connect(lambda: self.gallery_timer.start())
        self.detail_images.textChanged.connect(lambda: self.gallery_timer.start())
        self.refresh_galleries()
        self.refresh_sku_images()
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
        # self.sku_group_count.setText(f"共 {len(self.sku_groups)} 组 · 当前组 {len(urls)} 张独立图片")
        # 2026-10-12：本次修改原因：规格1共享图片组也显示上限；按第二规格预览时不错误套用规格1上限。
        capped = self.sku_group_dimension.currentIndex() == 0
        count_text = f"共 {len(self.sku_groups)} 组 · 当前组 {len(urls)} 张独立图片"
        if capped:
            count_text += f" / 最多 {MAX_SPEC_IMAGES} 张"
            if len(urls) > MAX_SPEC_IMAGES:
                count_text += f" · 超出 {len(urls) - MAX_SPEC_IMAGES} 张，保存前请调整"
        self.sku_group_count.setText(count_text)
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
        # 2026-10-12：本次修改原因：附件说明改为 ERP 接口及公网素材要求。
        form.addRow("", label("未提供的附件留空；回传附件需使用可访问的网络链接。身体尺码表尚未适配回传。", "hint", True))

    def _logistics_tab(self) -> None:
        form = self._tab_form("物流信息")
        form.addRow("包裹重量 KG", self._field("package_weight", "填写实测重量，例如 0.35"))
        form.addRow("包裹尺寸 CM", self._field("package_dimensions", "长*宽*高，例如 30*20*3"))
        # 2026-10-12：本次修改原因：物流按商品及 SKU 分别核实，使用接口回传。
        form.addRow("", label("商品与 SKU 包装重量、尺寸分别核实填写，回传前统一检查数值和单位。", "hint", True))

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
        # form.addRow("", label("单规格新增必须有货源价。优先使用这里的金额，否则读取已确认币种的采集货源价；销售金额不会代填货源价。", "hint", True))
        # 2026-10-12：本次修改原因：多 SKU 新增也必须有独立商品价，API 导入则已读取妙手的货源价。
        form.addRow("", label("新增商品必须有独立货源价，单规格可读取币种明确的采集货源价。SKU 销售金额不会代填；API 导入的货源价为人民币。", "hint", True))
        # 2026-10-12：本次修改原因：货源备注已使用接口回传，不再引用模板列。
        form.addRow("", label("货源链接与备注可随商品回传；新增商品必须填写独立货源价，SKU 售价不能代填。", "hint", True))

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
        # 2026-10-12：本次修改原因：售价币种与人民币回传换算说明一致。
        self.currency.setToolTip("选择实际报价币种，回传时使用设置中已确认的人民币汇率")
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
        # 2026-10-13：本次修改原因：销售属性页使用统一白底，表格完整边框与栏目背景保持一致。
        page.setObjectName("editorForm")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        # 2026-10-13：本次修改原因：销售属性和其他分区一样顶部排列，不让剩余高度拉伸表格卡片形成底部空矩形。
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
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
        # 2026-10-12：本次修改原因：销售属性行、行号和双击输入框使用同一套安全几何。
        configure_table(self.sku_table)
        # self.sku_table.setMinimumHeight(210)
        # 2026-10-13：本次修改原因：少量 SKU 按完整行数展示，避免表底部行号灰条和多余空白。
        fit_table_rows(self.sku_table, maximum_rows=8)
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
        # layout.addWidget(self.sku_table, 1)
        # 2026-10-13：本次修改原因：销售属性表独立包在完整卡片内，缩放时表底边框保持对齐。
        frame, table_layout = card()
        table_layout.setContentsMargins(12, 12, 12, 12)
        table_layout.addWidget(self.sku_table)
        layout.addWidget(frame)
        self.sku_preview = ImagePreview(self.network, 110)
        self.sku_preview.setFixedWidth(165)
        preview_row = QHBoxLayout()
        preview_row.addWidget(self.sku_preview)
        self.sku_source_summary = label("选择 SKU 查看规格图片和来源库存信息。", "hint", True)
        preview_row.addWidget(self.sku_source_summary, 1)
        # 2026-10-11：本次修改原因：SKU 改图显式绑定所选规格，避免改动其他颜色的图片。
        # preview_row.addWidget(button("AI 改当前 SKU 图", self.open_sku_ai))
        # 2026-10-13：本次修改原因：SKU 改图在统一 AI 模式按规格选择，原 SKU 表保留。
        layout.addLayout(preview_row)
        self.sku_table.itemSelectionChanged.connect(self.preview_sku)
        self.sku_table.itemChanged.connect(self.sku_item_changed)
        self.confirm_mapping = QCheckBox("已人工核对：将超过两个维度的来源规格明确合并到上面两列；原始材料仍保留")
        self.confirm_mapping.setVisible(any(len(sku.specs) > 2 for sku in self.product.skus))
        # 2026-10-12：本次修改原因：ERP 三维规格不允许在两列编辑器中合并，避免误以为可重构远端 SKU。
        if self.product.erp_imported:
            self.confirm_mapping.setVisible(False)
            if any(len(sku.specs) > 2 for sku in self.product.skus):
                layout.addWidget(label("妙手第三规格完整保留；本页只展示前两列，三维 SKU 的修改请在妙手完成。", "hint", True))
        layout.addWidget(self.confirm_mapping)
        layout.addWidget(label("尺寸建议按“长*宽*高”填写，单位 CM。横向滚动可编辑规格图片链接。", "hint"))
        # self.tabs.addTab(page, f"规格与定价（{len(self.product.skus)}）")
        # self.sku_tab_index = self.tabs.addTab(page, f"规格与定价（{len(self.product.skus)}）")
        # 2026-10-11：本次修改原因：销售属性栏目与妙手命名一致。
        # self.sku_tab_index = self.tabs.addTab(page, f"销售属性（{len(self.product.skus)}）")
        # 2026-10-12：本次修改原因：销售属性整页可滚动，小窗口不压缩表格、提示和 SKU 预览产生重叠。
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.sku_tab_index = self.tabs.addTab(scroll, f"销售属性（{len(self.product.skus)}）")
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
            # 2026-10-13：本次修改原因：数字右对齐、币种居中、文本左对齐，提升规格表横向比较可读性。
            if col in {3, 4, 5, 6, 11, 12}:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            elif col in {10, 13}:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
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
        # return product
        # 2026-10-12：本次修改原因：保存任一字段时，未编辑的富文本、空值和规格元数据保持打开编辑器前的原值。
        if hasattr(self, "initial_form_product"):
            product = preserve_unedited_form(self.product, self.initial_form_product, product)
        # 2026-10-15：本次修改原因：完整性检查展示当前人工核对状态，最终保存仍通过专用参数确认。
        if self.design_review is not None:
            product.bom_snapshot["images_confirmed"] = self.design_review.isChecked()
        return product

    # 2026-10-15：本次修改原因：在商品加工阶段查看完整锁定排列、BOM 和当时原料资料，避免编辑时失去来源依据。
    def show_design_recipe(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("锁定配方与原料快照")
        dialog.resize(880, 660)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(f"来源设计：{self.product.source_ref_id} · 配方版本：{self.product.design_version_id}", "hint", True))
        snapshot = self.product.bom_snapshot
        materials = snapshot.get("materials", {})
        candidate = snapshot.get("candidate", {})
        lines = ["方案：" + candidate.get("name", "未命名"), "", "串珠排列（从线头开始）："]
        for index, row in enumerate(candidate.get("sequence", []), 1):
            item = materials.get(row["material_id"], {})
            lines.append(f"{index}. {item.get('code', row['material_id'])} · {item.get('name', '')} × {row['quantity']}")
        lines.extend(["", "配件用量："])
        for row in candidate.get("components", []):
            item = materials.get(row["material_id"], {})
            lines.append(f"{item.get('code', row['material_id'])} · {item.get('name', '')} × {row['quantity']}")
        lines.extend(["", "完整锁定资料：", json.dumps(snapshot, ensure_ascii=False, indent=2)])
        viewer = QPlainTextEdit("\n".join(lines))
        viewer.setReadOnly(True)
        layout.addWidget(viewer, 1)
        layout.addWidget(button("关闭", dialog.accept))
        dialog.exec()

    def check(self) -> None:
        try:
            # issues = self.collect().issues()
            # 2026-10-12：本次修改原因：完整性检查同时显示妙手字数与图片数量限制，修改与 AI 共用结果。
            product = self.collect()
            # issues = product.issues() + draft_limit_issues(product)
            # 2026-10-12：本次修改原因：API 编辑完整性反馈与保存审核共用增量规则，保留未编辑的远端物流默认值。
            # issues = product.review_issues() + draft_limit_issues(product)
            # 2026-10-12：本次修改原因：完整性检查直接复用统一审核问题清单，避免格式限制重复提示。
            # issues = product.review_issues()
            # 2026-10-12：本次修改原因：手动或 AI 尚未保存的 HTML 以当前表单为准进行限制校验。
            issues = product.review_issues(self.product)
            if issues:
                # QMessageBox.warning(self, "商品尚需完善", "\n".join(f"• {issue}" for issue in issues[:30]))
                # 2026-10-14：本次修改原因：检查弹窗提供补全位置。
                QMessageBox.warning(self, "商品尚需完善", "\n".join(explain_issue(issue) for issue in issues[:30]))
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
        # heading.addWidget(button("AI 生成", lambda: self.open_ai(operation)))
        # 2026-10-13：本次修改原因：字段只保留手动编辑，统一模式选择需要生成的内容。
        layout.addLayout(heading)
        layout.addWidget(editor)
        form.addRow("", container)

    # 2026-10-13：本次修改原因：旧字段抽屉实现注释留档，由统一 AI 页面承担相同能力。
    # def open_sku_ai(self):
    #     row = self.sku_table.currentRow()
    #     item = self.sku_table.item(row, 8) if row >= 0 else None
    #     if not item:
    #         QMessageBox.information(self, "请选择 SKU", "请先选择需要处理图片的 SKU。")
    #         return
    #     self.open_ai("image", "sku", item.text().strip(), row)
    #
    # def open_ai(self, operation: str, target: str = "images", address: str = "", sku_row: int = -1):
    #     # 2026-10-13：本次修改原因：页面内只容纳一个目标字段的 AI 工作区，避免叠加候选覆盖目标。
    #     if self.ai_workspace is not None:
    #         return
    #     if not self.ai_service:
    #         QMessageBox.information(self, "AI 配置", "请从商品工作台打开编辑器，并在设置 → AI 模型中完成配置。")
    #         return
    #     # 2026-10-12：本次修改原因：缺少有效类别配置时先引导配置，避免进入 AI 面板后无模型可选。
    #     category = "image" if operation in {"image", "image_set"} else "text"
    #     if not any(profile.category == category and not profile.problems() for profile in self.ai_service.config.profiles):
    #         QMessageBox.information(self, "请先配置 AI 模型", "接下来打开模型设置，请新增对应类别的配置并设为当前。")
    #         ModelSettingsDialog(self.ai_service.config, self.ai_service.assets, self.ai_hub, self).exec()
    #         if not any(profile.category == category and not profile.problems() for profile in self.ai_service.config.profiles):
    #             return
    #     try:
    #         snapshot = self.collect().to_dict()
    #     except ValueError as error:
    #         QMessageBox.warning(self, "请检查商品事实", str(error))
    #         return
    #     # 2026-10-11：本次修改原因：SKU 改图只提供当前规格事实，避免其他颜色和尺寸混入。
    #     if target == "sku" and 0 <= sku_row < len(snapshot.get("skus", [])):
    #         snapshot["skus"] = [snapshot["skus"][sku_row]]
    #     workspace = AIWorkspace(self.ai_service, self.ai_hub, snapshot, operation, self.network, address, self)
    #     # 2026-10-11：本次修改原因：SKU 字段只能替换单图，候选默认只生成一张。
    #     if target == "sku":
    #         workspace.count.setValue(1)
    #         workspace.application.setVisible(False)
    #     # if workspace.exec() != QDialog.DialogCode.Accepted:
    #     #     return
    #     # 2026-10-13：本次修改原因：复用原 AI 工作区为右侧内嵌候选；冻结目标和表单，finished 后仍执行原应用代码。
    #     self.ai_workspace = workspace
    #     workspace.setWindowFlags(Qt.WindowType.Widget)
    #     workspace.setMinimumSize(0, 0)
    #     # self.edit_preview.hide()
    #     # for index in range(1, self.preview_layout.count()):
    #     #     item = self.preview_layout.itemAt(index)
    #     #     if item.widget():
    #     #         item.widget().hide()
    #     # self.preview_layout.insertWidget(0, workspace, 1)
    #     # 2026-10-13：本次修改原因：AI 独立工作区按需加入右栏，常规编辑不创建图片预览。
    #     self.ai_layout.addWidget(workspace)
    #     # self.preview_area.show()
    #     # self.preview_panel.collapse.setText("收起")
    #     # 2026-10-13：本次修改原因：AI 入口展开默认收起的辅助分区，退出时恢复原来的收起状态和宽度。
    #     self.ai_normal_sizes = self.editor_splitter.sizes()
    #     # self.ai_preview_was_expanded = not self.preview_area.isHidden()
    #     self.editor_splitter.save_layout()
    #     self.editor_splitter.transient = True
    #     # self.preview_panel.set_expanded(True, persist=False)
    #     self.ai_area.show()
    #     # 2026-10-13：本次修改原因：区域放大按钮已撤下，AI 展开不再操作该按钮。
    #     # self.preview_panel.maximize.setEnabled(False)
    #     self.tabs.setEnabled(False)
    #     self.check_button.setEnabled(False)
    #     self.save_button.setEnabled(False)
    #     self.approve_save_button.setEnabled(False)
    #     # 2026-10-13：本次修改原因：AI展开比例是临时呈现，关闭后恢复原表单/预览比例。
    #     # self.ai_normal_sizes = self.editor_splitter.sizes()
    #     # self.editor_splitter.save_layout()
    #     # self.editor_splitter.transient = True
    #     # self.editor_splitter.setSizes([600, 660])
    #     # 2026-10-13：本次修改原因：给 AI 表单保证可读宽度，不再沿用弹窗中的固定总宽度。
    #     self.editor_splitter.setSizes([max(420, self.width() - 500), 480])
    #     workspace.closed.connect(lambda result: self.finish_ai_workspace(workspace, result, operation, target, address, sku_row))
    #     workspace.show()
    #     workspace.instruction.setFocus()
    #
    # def finish_ai_workspace(self, workspace, result, operation, target, address, sku_row):
    #     # self.preview_layout.removeWidget(workspace)
    #     self.ai_layout.removeWidget(workspace)
    #     self.ai_workspace = None
    #     self.editor_splitter.transient = False
    #     # 2026-10-13：本次修改原因：恢复进入 AI 前的辅助区可见状态，不因临时 AI 布局改变默认收起偏好。
    #     # self.preview_panel.set_expanded(self.ai_preview_was_expanded, persist=False)
    #     # 2026-10-13：本次修改原因：AI 退出后右侧工作区完全隐藏，不恢复已撤下的预览区域。
    #     self.ai_area.hide()
    #     self.editor_splitter.setSizes(self.ai_normal_sizes)
    #     self.tabs.setEnabled(True)
    #     self.check_button.setEnabled(True)
    #     self.save_button.setEnabled(True)
    #     self.approve_save_button.setEnabled(True)
    #     # self.preview_panel.maximize.setEnabled(True)
    #     # self.edit_preview.show()
    #     # for index in range(self.preview_layout.count()):
    #     #     item = self.preview_layout.itemAt(index)
    #     #     if item.widget():
    #     #         item.widget().show()
    #     workspace.deleteLater()
    #     if result != QDialog.DialogCode.Accepted:
    #         return
    #     if operation == "title":
    #         self.fields["title"].setText(workspace.applied_text)
    #     elif operation == "simple_description":
    #         self.simple_description.setPlainText(workspace.applied_text)
    #     elif operation == "description_html":
    #         self.rich_description.set_html(workspace.applied_text)
    #     elif workspace.applied_assets:
    #         values = workspace.applied_assets
    #         if target == "sku":
    #             if len(values) != 1:
    #                 QMessageBox.information(self, "SKU 图片", "一个 SKU 图片字段只能应用一张图，请从历史候选中勾选一张后应用。")
    #                 return
    #             self.sku_table.item(sku_row, 8).setText(values[0])
    #         elif target == "html":
    #             # self.replace_description_image(address, values)
    #             # 2026-10-11：本次修改原因：详情正文按用户的替换/追加选择处理，同步对应详情图列表。
    #             if workspace.apply_mode == "append":
    #                 self.rich_description.set_html(self.rich_description.html() + detail_html("", values))
    #                 self.detail_images.set_urls(self.detail_images.toPlainText().splitlines() + values)
    #             else:
    #                 self.replace_description_image(address, values)
    #                 old = self.detail_images.toPlainText().splitlines()
    #                 if address in old:
    #                     index = old.index(address)
    #                     self.detail_images.set_urls(old[:index] + values + old[index + 1:])
    #             self.detail_images.textChanged.emit()
    #         else:
    #             media = self.detail_images if target == "detail_images" else self.images
    #             old = media.toPlainText().splitlines()
    #             if workspace.apply_mode == "replace_set":
    #                 updated = values
    #             elif workspace.apply_mode == "replace" and address in old:
    #                 index = old.index(address)
    #                 updated = old[:index] + values + old[index + 1:]
    #             else:
    #                 updated = old + values
    #             media.set_urls(updated)
    #             media.textChanged.emit()
    #             if target == "detail_images" and workspace.apply_mode == "replace":
    #                 self.replace_description_image(address, values)
    #             if workspace.result:
    #                 for asset in workspace.result.assets:
    #                     media.update_size(asset.uri, asset.width, asset.height)
    #     self.mark_dirty()
    #     # 2026-10-12：本次修改原因：应用候选只改变表单，明确提示保存和审核下一步。
    #     self.edit_feedback.setText("AI 结果已应用到当前字段，尚未保存。请核对后保存修改或保存并审核。")

    # 2026-10-13：本次修改原因：模式切换读取当前未保存草稿，候选保留在同一工作区实例。
    # 2026-10-14：本次修改原因：白底图建档后启动整套 Listing，复用现有候选审核、原子应用与保存。
    def start_white_listing(self, defaults):
        from ..ai.product_plan import white_listing_draft
        self.mode_tabs.setCurrentIndex(1)
        if self.ai_workbench is None:
            return
        workbench = self.ai_workbench
        try:
            draft = white_listing_draft(self.collect().to_dict(), defaults)
            workbench.processing.save(draft)
        except (ValueError, OSError) as error:
            workbench.message(str(error))
            return
        workbench.draft = draft
        workbench._rendering = True
        workbench.instruction.setPlainText(draft['options']['instruction'])
        workbench._rendering = False
        workbench.render()
        workbench.generate()

    def switch_mode(self, index):
        if self.ai_workbench and self.ai_workbench.busy:
            self.mode_tabs.blockSignals(True)
            self.mode_tabs.setCurrentIndex(1)
            self.mode_tabs.blockSignals(False)
            return
        if index == 1:
            try:
                if not self.ai_service:
                    raise ValueError("请先在设置中配置 AI 模型。")
                snapshot = self.collect().to_dict()
                # if self.ai_workbench is None:
                #     self.ai_workbench = AIWorkbench
                # 2026-10-13：本次修改原因：首次进入 AI 时承接手动页选中的图片，之后保留工作区状态。
                first = self.ai_workbench is None
                if first:
                    self.ai_workbench = AIWorkbench(self.ai_service, self.ai_hub, self.reference_store, self.network, self)
                    self.ai_workbench.applyRequested.connect(self.apply_ai_changes)
                    self.ai_workbench.busyChanged.connect(self.ai_busy_changed)
                    self.mode_stack.addWidget(self.ai_workbench)
                # self.ai_workbench.set_product(snapshot)
                # 2026-10-13：本次修改原因：从当前 SKU 或图片列表进入时直接定位处理目标。
                self.ai_workbench.set_product(snapshot)
                if first:
                    self.seed_ai_selection(snapshot)
            except ValueError as error:
                self.edit_feedback.setText(str(error))
                self.mode_tabs.blockSignals(True)
                self.mode_tabs.setCurrentIndex(0)
                self.mode_tabs.blockSignals(False)
                return
        self.mode_stack.setCurrentIndex(index)
        self.manual_footer.setVisible(index == 0)
        self.edit_feedback.setVisible(index == 0)

    # 2026-10-13：本次修改原因：后台任务期间冻结切换与提交，避免请求仍使用旧商品快照。
    # def ai_busy_changed(self, busy):
    # 2026-10-13：本次修改原因：仅首次进入时承接选中的图片与 SKU，不增加分散的 AI 入口。
    # def seed_ai_selection(self, snapshot):
    #     workbench = self.ai_workbench
    #     target, address = None, ""
    #     if self.tabs.currentIndex() == 2:
    #         row = self.sku_table.currentRow()
    #         if 0 <= row < len(snapshot.get("skus", [])):
    #             from ..ai.workflow import sku_locator
    #             sku = snapshot["skus"][row]
    #             target, address = {"field": "sku", "locator": sku_locator(sku)}, sku.get("image", "")
    #     elif self.tabs.currentIndex() == 3:
    #         for field, media in (("detail_images", self.detail_images), ("images", self.images)):
    #             if media.table.selectionModel().selectedRows():
    #                 item = media.table.item(media.table.currentRow(), 0)
    #                 if item and item.text().strip():
    #                     target, address = {"field": field}, item.text().strip()
    #                     break
    #     if target is None:
    #         return
    #     workbench._rendering = True
    #     try:
    #         index = next((i for i in range(workbench.target.count()) if workbench.target.itemData(i) == target), -1)
    #         if index < 0:
    #             return
    #         workbench.target.setCurrentIndex(index)
    #         workbench.anchor.setCurrentIndex(workbench.anchor.findData(address))
    #         workbench.subjects.set_urls([address] if address else [])
    #         for field, control in workbench.tasks.items():
    #             control.setChecked(field == "images")
    #     finally:
    #         workbench._rendering = False
    # 2026-10-14：本次修改原因：进入 AI 时定位分组，避免选中单张图后把处理范围误限为一张。
    def seed_ai_selection(self, snapshot):
        # 选择仅决定初始图片分组，整商品素材始终完整保留。
        field, address, locator = "images", "", None
        if self.tabs.currentIndex() == 2:
            field = "sku"
            row = self.sku_table.currentRow()
            if 0 <= row < len(snapshot.get("skus", [])):
                from ..ai.workflow import sku_locator
                sku = snapshot["skus"][row]
                address, locator = sku.get("image", ""), sku_locator(sku)
        elif self.tabs.currentIndex() == 3:
            for group, media in (("detail_images", self.detail_images), ("images", self.images)):
                if media.table.selectionModel().selectedRows():
                    field = group
                    item = media.table.item(media.table.currentRow(), 0)
                    address = item.text().strip() if item else ""
                    break
        self.ai_workbench.focus_target(field, address, locator)

    # 2026-10-13：本次修改原因：后台任务期间禁止切换与提交，保护生成快照。
    def ai_busy_changed(self, busy):
        self.mode_tabs.setEnabled(not busy)
        self.back_button.setEnabled(not busy)
        self.check_button.setEnabled(not busy)
        self.save_button.setEnabled(not busy)
        self.approve_save_button.setEnabled(not busy)

    # 2026-10-13：本次修改原因：先构建并校验完整补丁，再一次性应用选中字段；不修改审核或 ERP 状态。
    def apply_ai_changes(self, changes):
        if not self.ai_workbench or self.ai_workbench.busy:
            return
        try:
            before = self.collect().to_dict()
            updated = apply_changes(before, changes)
        except (ValueError, TypeError, KeyError) as error:
            self.ai_workbench.status.setText("未应用：" + str(error))
            return
        if before.get("title") != updated.get("title"):
            self.fields["title"].setText(updated["title"])
        if before.get("simple_description") != updated.get("simple_description"):
            self.simple_description.setPlainText(updated["simple_description"])
        if before.get("description_html") != updated.get("description_html"):
            self.rich_description.set_html(updated["description_html"])
        for field, media in (("images", self.images), ("detail_images", self.detail_images)):
            if before.get(field) != updated.get(field):
                media.set_urls(updated[field])
                media.textChanged.emit()
            # for address, dimensions in updated.get("image_sizes", {}).items():
            #     if isinstance(dimensions, (list, tuple)) and len(dimensions) == 2:
            #         media.update_size(address, dimensions[0], dimensions[1])
            # 2026-10-13：本次修改原因：尺寸显示从已选素材同步，商品缓存仍使用既有字符串格式。
            for change in changes:
                for asset in change.get("assets", []):
                    media.update_size(asset["uri"], asset["width"], asset["height"])
        for index, sku in enumerate(updated.get("skus", [])):
            if sku.get("image") != before["skus"][index].get("image"):
                item = self.sku_table.item(index, 8)
                if item:
                    item.setText(sku["image"])
        self.refresh_sku_images()
        self.mark_dirty()
        # self.ai_workbench.applied()
        # 2026-10-13：本次修改原因：仅标记实际应用的目标，未选择结果继续保留。
        # self.ai_workbench.applied(changes)
        # 2026-10-14：本次修改原因：记录应用后的商品快照，并与加工草稿分别保存。
        self.ai_workbench.applied(changes, updated)
        self.mode_tabs.setCurrentIndex(0)
        targets = {change["target"]["field"] for change in changes}
        self.tabs.setCurrentIndex(0 if targets & {"title", "simple_description", "description_html"} else
                                  (2 if "sku" in targets else 3))
        self.edit_feedback.setText("AI 结果已应用，尚未保存。请核对后保存修改或保存并审核。")

    # 2026-10-13：本次修改原因：保存不会隐式应用候选；未应用内容仍需用户明确取舍。
    # def confirm_pending_ai(self):
    #     # if self.ai_workbench and self.ai_workbench.pending:
    #     # 2026-10-13：本次修改原因：保存退出前也保护只输入但未生成的 Prompt。
    #     if self.ai_workbench and (self.ai_workbench.pending or self.ai_workbench.input_dirty):
    #         return QMessageBox.question(self, "存在未应用的 AI 候选",
    #             "继续将只保存当前商品表单，未应用候选及 Prompt 的手动编辑不会保存；原始生成结果仍可从历史查看。",
    #             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
    #             QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes
    #     return True
    # 2026-10-14：本次修改原因：退出前可独立保存加工方案和候选编辑，未应用结果不会隐式写入商品。
    def confirm_pending_ai(self):
        return not self.ai_workbench or self.ai_workbench.confirm_leave()

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
        # 2026-10-13：本次修改原因：内嵌页面保留 AI 候选锁，不能绕过禁用按钮直接提交。
        # if self.ai_workspace is not None or self._finished:
        # 2026-10-13：本次修改原因：持久 AI 页存在不再阻止保存；任务进行中和 AI 模式仍不可直接提交。
        if self._finished or self.mode_stack.currentIndex() != 0 or (self.ai_workbench and self.ai_workbench.busy):
            return
        if not self.confirm_pending_ai():
            return
        try:
            # self.repository.save_product(self.collect(), approve=approve)
            # 2026-10-11：本次修改原因：没有实际表单内容改动时保留原商品内容，只存预览像素缓存和审核操作。
            product = self.collect()
            if product.business_content() == self.initial_form_content:
                sizes = product.image_sizes
                product = Product.from_dict(self.product.to_dict())
                product.image_sizes = sizes
            # self.repository.save_product(product, approve=approve)
            # 2026-10-15：本次修改原因：普通商品保持原保存方式，成链商品明确提交本次配方及图片核对结果。
            self.repository.save_product(product, approve=approve,
                                         confirm_design_images=self.design_review.isChecked() if self.design_review is not None else None)
        except Exception as error:
            # QMessageBox.warning(self, "未能保存", str(error))
            # 2026-10-14：本次修改原因：保存失败提供具体栏目和字段。
            QMessageBox.warning(self, "未能保存", explain_errors(str(error)))
            return
        self.dirty = False
        self.accept()

    # 2026-10-13：本次修改原因：保存显示布局；AI 抽屉沿用原等待任务完成保护，取消先关闭候选。
    def done(self, result):
        # if self.ai_workspace is not None:
        #     self.edit_feedback.setText("请先在右侧关闭或应用 AI 候选，再保存或退出编辑。")
        # 2026-10-13：本次修改原因：统一页面仅在任务进行中阻止离开，不再依赖旧抽屉是否存在。
        if self.ai_workbench and self.ai_workbench.busy:
            self.edit_feedback.setText("AI 任务正在进行，请等待完成。")
            return
        save_splitters(self)
        self.editor_preferences.setValue("ui/editor/current_tab", self.tabs.currentIndex())
        # super().done(result)
        # 2026-10-13：本次修改原因：页面用关闭信号交回主窗口，保留 Accepted/Rejected 和原保存结果语义。
        if self._finished:
            return False
        self._finished = True
        if result == QDialog.DialogCode.Accepted:
            self.accepted.emit()
        else:
            self.rejected.emit()
        self.closed.emit(int(result))
        return True

    # 2026-10-13：本次修改原因：兼容原保存入口的 accept 调用，实际返回主窗口的商品列表。
    def accept(self):
        return self.done(QDialog.DialogCode.Accepted)

    # def reject(self) -> bool:
    #     # if self.ai_workspace is not None:
    #         # self.ai_workspace.reject()
    #         # return
    #         # 2026-10-13：本次修改原因：生成中不离开编辑页；空闲候选在确认放弃后随页面关闭。
    #     #     if self.ai_workspace.busy:
    #     #         self.ai_workspace.reject()
    #     #         return False
    #     # if self.dirty and QMessageBox.question(self, "未保存的修改", "关闭后将丢弃本次未保存的修改。是否关闭？",
    #     # 2026-10-13：本次修改原因：统一草稿、未应用候选和任务生命周期，返回列表保持原有保护。
    #     if self.ai_workbench and self.ai_workbench.busy:
    #         self.ai_workbench.status.setText("AI 任务正在进行，请等待完成后离开。")
    #         return False
    #     # pending = bool(self.ai_workbench and self.ai_workbench.pending)
    #     # 2026-10-13：本次修改原因：返回列表时包含 AI 输入草稿，避免用户文字静默丢失。
    #     pending = bool(self.ai_workbench and (self.ai_workbench.pending or self.ai_workbench.input_dirty))
    #     if (self.dirty or pending) and QMessageBox.question(self, "未保存的修改", "关闭将丢弃未保存的商品修改、Prompt 和候选手动编辑。原始生成结果保留在历史中。是否关闭？",
    #                                           QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
    #                                           QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Discard:
    #         return False
    #     # super().reject()
    #     # if self.ai_workspace is not None:
    #     #     self.ai_workspace.reject()
    #     return self.done(QDialog.DialogCode.Rejected)
    # 2026-10-14：本次修改原因：返回列表分开保护加工草稿和商品编辑，保存加工草稿不代表保存商品。
    def reject(self) -> bool:
        if self.ai_workbench and not self.ai_workbench.confirm_leave():
            return False
        if self.dirty and QMessageBox.question(self, "未保存的商品修改",
                "关闭将放弃尚未保存的商品修改。已保存的加工草稿仍可下次继续，是否关闭？",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Discard:
            return False
        return self.done(QDialog.DialogCode.Rejected)

    # 2026-10-13：本次修改原因：外部关闭编辑控件与返回按钮遵守相同的未保存和 AI 任务保护。
    def closeEvent(self, event):
        if self._finished or self.reject():
            event.accept()
        else:
            event.ignore()

# 2026-10-14：本次修改原因：校验反馈共用可定位的字段补充说明。
from ..validation_guidance import explain_errors, explain_issue
