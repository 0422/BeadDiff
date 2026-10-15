# 2026-10-15：本次修改原因：原料逐字段维护事实来源与图片观察，沿用现有表格、主题和自适应输入控件。
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3

# from PySide6.QtCore import Qt
# 2026-10-15：本次修改原因：原料图片改用缩略图选择，按固定缩略图尺寸读取，避免显示存储文件名。
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager
# from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
#                                QInputDialog, QLineEdit, QListWidget, QMessageBox, QScrollArea, QSpinBox,
#                                QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
# 2026-10-15：本次修改原因：编号、类型及采购资料改为顶部横向排布，撤下纵向表单布局依赖。
# from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout,
#                                QInputDialog, QLineEdit, QListWidget, QMessageBox, QScrollArea, QSpinBox,
#                                QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
# 2026-10-15：本次修改原因：库存改用可留空的数字输入框，撤下库存勾选框与固定零值数字控件依赖。
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QInputDialog, QLineEdit, QListWidget, QMessageBox, QScrollArea,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
# 2026-10-15：本次修改原因：单价限制非负小数、库存限制非负整数，统一小数点格式并支持空值。
from PySide6.QtCore import QLocale
from PySide6.QtGui import QDoubleValidator, QIntValidator
# 2026-10-15：本次修改原因：新增原料合并为类型菜单，原料列表用独立圆角外框承载。
from PySide6.QtWidgets import QFrame, QMenu
# 2026-10-15：本次修改原因：多张原料图通过窄栏缩略图切换，单张图隐藏选择栏以扩大预览。
from PySide6.QtWidgets import QListView, QListWidgetItem
# 2026-10-15：本次修改原因：空图片区使用可点击上传框，有图时将添加和移除操作叠放在预览右上角。
from PySide6.QtWidgets import QGridLayout, QStackedWidget
# 2026-10-15：本次修改原因：资料表与成本等资料水平排列，可拖动分配两侧宽度。
from PySide6.QtWidgets import QSizePolicy, QSplitter

from ..ai.contracts import AIRequest
# 2026-10-15：本次修改原因：缩略图仅从受管理的本机素材读取，沿用现有图片路径解析。
from ..assets import local_asset_path
from ..beads import MATERIAL_CATEGORY_LABELS, MaterialItem, VISIBLE_FACT_FIELDS
from ..bead_workflow import parse_object
# from .table_support import configure_table
# 2026-10-15：本次修改原因：原料资料改为表格内多行编辑，继续复用统一单元格委托的主题和几何设置。
# from .table_support import CellEditorDelegate, configure_table
# 2026-10-15：本次修改原因：资料表新增改用边缘悬停入口，保持原有直接多行编辑。
from .table_support import CellEditorDelegate, TableEdgeActions, configure_table
from .widgets import AutoHeightTextEdit, ImagePreview, button, label

SOURCE_LABELS = {"user": "用户提供", "vision": "图片观察", "supplier": "供应商资料", "human": "人工核实", "unknown": "待补充"}
STATUS_LABELS = {"confirmed": "已确认", "observed": "仅观察", "pending": "待确认", "conflict": "有冲突"}
FACT_FIELDS = {"material": "材质", "color": "颜色", "shape": "形状", "size": "尺寸说明", "diameter_mm": "直径 mm",
               "hole_mm": "孔径 mm", "axial_mm": "沿线占长 mm", "texture": "表面质感", "transparency": "透明度",
               "unit": "计量单位", "usage": "搭配用途", "care": "注意事项", "meaning": "文化寓意（非功效）"}
VISIBLE_FIELDS = VISIBLE_FACT_FIELDS


def scroll_form(body):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidget(body)
    return area


# 2026-10-15：本次修改原因：来源与状态使用紧凑下拉框，关闭时忽略滚轮，避免滚动表格误改资料。
class FactChoiceComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("materialFactChoice", True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()

    # 2026-10-15：本次修改原因：展开列表独立计算完整选项及内边距宽度，修复“供应商资料”在紧凑列中被省略。
    def showPopup(self):
        self.ensurePolished()
        view = self.view()
        view.ensurePolished()
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        metrics = view.fontMetrics()
        text_width = max((metrics.horizontalAdvance(self.itemText(index))
                          for index in range(self.count())), default=0)
        content_width = max(text_width + 24, view.sizeHintForColumn(self.modelColumn()))
        margins = view.contentsMargins()
        popup_width = max(self.width(), content_width + margins.left() + margins.right()
                          + 2 * view.frameWidth() + 12)
        view.setMinimumWidth(popup_width)
        popup = view.window()
        popup_margins = popup.contentsMargins()
        popup.setMinimumWidth(popup_width + popup_margins.left() + popup_margins.right())
        super().showPopup()


# 2026-10-15：本次修改原因：直接双击资料值即可多行输入，输入内容变长时增加当前行高度，保留完整内容右键编辑。
class FactValueDelegate(CellEditorDelegate):
    def __init__(self, table):
        super().__init__(table)
        self.table = table

    def createEditor(self, parent, option, index):
        editor = AutoHeightTextEdit(parent=parent, minimum_lines=2, maximum_lines=10)
        editor.setProperty("cellEditor", True)
        # 2026-10-15：本次修改原因：多行单元格保留 Enter 换行，用 Tab 离开并提交编辑。
        editor.setTabChangesFocus(True)

        def fit_row():
            if index.isValid():
                self.table.setRowHeight(index.row(), max(self.table.verticalHeader().minimumSectionSize(), editor.height() + 2))

        editor.height_timer.timeout.connect(fit_row)
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(str(index.data(Qt.ItemDataRole.EditRole) or ""))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText(), Qt.ItemDataRole.EditRole)


class MaterialDialog(QDialog):
    # def __init__(self, store, assets, item=None, parent=None, ai_service=None, ai_hub=None, library_category="beads"):
    # 2026-10-15：本次修改原因：从新增原料菜单选择的类型直接带入弹窗，编辑已有原料仍使用原记录类型。
    def __init__(self, store, assets, item=None, parent=None, ai_service=None, ai_hub=None, library_category="beads", material_category="bead"):
        super().__init__(parent)
        self.store, self.assets, self.ai_service, self.ai_hub = store, assets, ai_service, ai_hub
        # self.item = deepcopy(item) if item else MaterialItem(library_category=library_category)
        # 2026-10-15：本次修改原因：新建时采用菜单指定的原料类型，减少打开弹窗后的重复选择。
        self.item = deepcopy(item) if item else MaterialItem(library_category=library_category, category=material_category)
        self.busy = False
        self.setWindowTitle("编辑原料" if item else "新增原料")
        # self.resize(960, 780)
        # 2026-10-15：本次修改原因：为左右资料区提供默认空间，并按当前屏幕可用尺寸收敛窗口。
        available = self.screen().availableGeometry()
        self.resize(min(1240, available.width() - 48), min(920, available.height() - 48))
        root = QVBoxLayout(self)
        # 2026-10-15：本次修改原因：撤下重复标题与顶部说明，将空间让给原料输入和图片、资料表。
        # root.addWidget(label("原料资料", "sectionTitle"))
        # root.addWidget(label("图片仅用于观察外观。天然石种类、贵金属成分、准确尺寸和孔径需要资料或实测确认。", "hint", True))
        body = QWidget(); self.form_body = body; layout = QVBoxLayout(body)
        # form = QFormLayout(); form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        # 2026-10-15：本次修改原因：顶部第一行并排放置编号与类型，三行表单共用外层滚动区域。
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        form = QHBoxLayout()
        form.setSpacing(12)
        self.code = QLineEdit(self.item.code)
        # 2026-10-15：本次修改原因：新增原料无需手工起号，留空由保存事务自动分配全库唯一编号。
        # self.code.setPlaceholderText("保存时自动分配，如 M000001；也可自定义" if not item else "已有原料编号不能为空")
        # self.code.setToolTip("新原料留空即可自动编号，各类目共用唯一编号；已有原料保留原编号。")
        # 2026-10-15：本次修改原因：在编号占位提示中说明自定义编号需要全库唯一，悬停补充实际格式规则与示例。
        self.code.setPlaceholderText("留空自动编号；自定义需全库唯一，如 B001" if not item else "已有原料编号不能为空")
        self.code.setToolTip(
            "新原料留空自动编号，如 M000001；已有原料编号不能为空。\n"
            "自定义编号不限前缀和位数，如 B001、GL-8MM-01；前后空格会自动去除。\n"
            "编号需全库唯一，不可与其他类目或已归档原料的编号重复。"
        )
        # self.name = AutoHeightTextEdit(self.item.name, minimum_lines=1, maximum_lines=3)
        self.kind = QComboBox()
        for key, title in MATERIAL_CATEGORY_LABELS.items(): self.kind.addItem(title, key)
        self.kind.setCurrentIndex(max(0, self.kind.findData(self.item.category)))
        # form.addRow("原料编号（唯一）", self.code); form.addRow("名称", self.name); form.addRow("原料类型", self.kind)
        # 2026-10-15：本次修改原因：明确新增时编号可留空，已有记录仍要求唯一编号。
        # form.addRow("原料编号（唯一）" if item else "原料编号（留空自动）", self.code); form.addRow("名称", self.name); form.addRow("原料类型", self.kind)
        # 2026-10-15：本次修改原因：编号输入框已有自动编号提示，简化标签并撤下名称输入，使用编号和类型识别原料。
        # form.addRow("原料编号", self.code); form.addRow("原料类型", self.kind)
        # 2026-10-15：本次修改原因：原料编号、类型水平排列，自动编号说明继续放在输入框提示中。
        form.addWidget(label("原料编号"))
        form.addWidget(self.code, 3)
        form.addWidget(label("原料类型"))
        form.addWidget(self.kind, 1)
        layout.addLayout(form)
        # 2026-10-15：本次修改原因：原右侧采购表单移到顶部第二行，长文本继续使用自动增高输入框。
        # economics = QGridLayout()
        # economics.setHorizontalSpacing(12)
        # economics.setVerticalSpacing(6)
        # 2026-10-15：本次修改原因：采购资料拆为两行，第一行将单件价格、币种和库存标签与输入框水平排布。
        economics = QHBoxLayout()
        economics.setSpacing(12)
        self.cost = QLineEdit(self.item.unit_cost)
        self.cost.setPlaceholderText("可选；按计量单位填写，留空表示未知")
        self.cost.setToolTip(self.cost.placeholderText())
        # self.currency = QLineEdit(self.item.currency or "CNY")
        # 2026-10-15：本次修改原因：单价采用数值校验且保留原始小数文本，币种改用现有编辑器风格的下拉框。
        numeric_locale = QLocale.c()
        numeric_locale.setNumberOptions(QLocale.NumberOption.RejectGroupSeparator)
        cost_validator = QDoubleValidator(self.cost)
        cost_validator.setBottom(0.0)
        cost_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        cost_validator.setLocale(numeric_locale)
        self.cost.setValidator(cost_validator)
        self.currency = QComboBox()
        self.currency.setEditable(True)
        self.currency.addItems(["CNY", "USD", "EUR", "GBP", "JPY", "CAD", "AUD"])
        self.currency.setCurrentText(self.item.currency or "CNY")
        self.currency.setAccessibleName("单件价格币种")
        self.currency.setToolTip("选择原料采购单价币种；其他币种可输入三位代码，例如 HKD。")
        self.cost.setMinimumWidth(100)
        # self.currency.setMinimumWidth(70)
        # for control in (self.cost, self.currency):
        #     control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        # self.track = QCheckBox("记录")
        # self.track.setToolTip("记录库存数量；关闭时库存显示为未知，开启时零表示确实没有库存。")
        # self.track.setAccessibleName("记录库存数量")
        # self.track.setChecked(self.item.track_inventory)
        # self.quantity = QSpinBox()
        # self.quantity.setRange(0, 10_000_000)
        # self.quantity.setValue(self.item.quantity)
        # 2026-10-15：本次修改原因：币种紧邻单价并预留箭头宽度；库存留空表示未记录，零值仍可明确填写。
        self.cost.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.currency.setMinimumWidth(100)
        self.currency.setMaximumWidth(150)
        self.quantity = QLineEdit(str(self.item.quantity) if self.item.track_inventory else "")
        quantity_validator = QIntValidator(0, 10_000_000, self.quantity)
        quantity_validator.setLocale(numeric_locale)
        self.quantity.setValidator(quantity_validator)
        self.quantity.setPlaceholderText("留空表示未记录库存")
        self.quantity.setToolTip("可填 0～10000000 的整数；留空表示库存未知，填 0 表示确实没有库存。")
        self.quantity.setMinimumWidth(112)
        self.quantity.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        # self.quantity.setEnabled(self.track.isChecked())
        # self.track.toggled.connect(self.quantity.setEnabled)
        # stock = QWidget()
        # stock_layout = QHBoxLayout(stock)
        # stock_layout.setContentsMargins(0, 0, 0, 0)
        # stock_layout.setSpacing(8)
        # stock_layout.addWidget(self.track)
        # stock_layout.addWidget(self.quantity, 1)
        self.supplier = AutoHeightTextEdit(self.item.supplier, minimum_lines=1, maximum_lines=3)
        self.supplier_url = AutoHeightTextEdit(self.item.supplier_url, minimum_lines=1, maximum_lines=3)
        self.supplier.setMinimumWidth(140)
        self.supplier_url.setMinimumWidth(180)
        # for col, (title, control, stretch) in enumerate((("单位成本", self.cost, 2),
        #                                                ("成本币种", self.currency, 1),
        #                                                ("库存总量", stock, 3),
        #                                                ("供应商", self.supplier, 3),
        #                                                ("采购链接", self.supplier_url, 5))):
        #     economics.addWidget(label(title), 0, col)
        #     economics.addWidget(control, 1, col, Qt.AlignmentFlag.AlignTop)
        #     economics.setColumnStretch(col, stretch)
        # 2026-10-15：本次修改原因：第一行显示单价、币种和库存，供应商及采购链接另占下一行以增加输入宽度。
        economics.addWidget(label("单件价格"))
        economics.addWidget(self.cost, 2)
        economics.addWidget(self.currency)
        economics.addWidget(label("库存总量"))
        economics.addWidget(self.quantity, 2)
        layout.addLayout(economics)
        purchasing = QHBoxLayout()
        purchasing.setSpacing(12)
        purchasing.addWidget(label("供应商"))
        purchasing.addWidget(self.supplier, 2)
        purchasing.addWidget(label("采购链接"))
        purchasing.addWidget(self.supplier_url, 3)
        layout.addLayout(purchasing)
        # 2026-10-15：本次修改原因：内部备注独占顶部第三行，初始两行并随长内容增高，给下方图片与表格留出高度。
        self.notes = AutoHeightTextEdit(self.item.notes, minimum_lines=2, maximum_lines=10)
        # notes_row = QHBoxLayout()
        # notes_row.setSpacing(12)
        # notes_row.addWidget(label("内部备注"))
        # notes_row.addWidget(self.notes, 1)
        # layout.addLayout(notes_row)
        # 2026-10-15：本次修改原因：内部备注改为输入框内的占位提示，撤下框外标签，原有内容与自动增高继续保留。
        self.notes.setPlaceholderText("内部备注")
        self.notes.setAccessibleName("内部备注")
        layout.addWidget(self.notes)
        # 2026-10-15：本次修改原因：下方改为左图片区、右资料表，分别使用圆角外框并允许拖动调宽。
        self.details_splitter = QSplitter(Qt.Orientation.Horizontal)
        # 2026-10-15：本次修改原因：为当前图片与资料分隔条限定透明拖拽样式，撤下悬停和按下时的深绿色长条。
        self.details_splitter.setObjectName("materialDetailsSplitter")
        self.details_splitter.setChildrenCollapsible(False)
        self.details_splitter.setHandleWidth(10)
        layout.addWidget(self.details_splitter, 1)
        photo_panel = QFrame()
        photo_panel.setObjectName("materialImageFrame")
        photo_panel.setMinimumWidth(340)
        photo_layout = QVBoxLayout(photo_panel)
        photo_layout.setContentsMargins(12, 12, 12, 12)
        photo_layout.setSpacing(10)
        # photos = QHBoxLayout()
        # self.photos = QListWidget(); self.photos.setMaximumHeight(135)
        # self.preview = ImagePreview(QNetworkAccessManager(self), 135)
        # photos.addWidget(self.photos, 1); photos.addWidget(self.preview, 1); layout.addLayout(photos)
        # self.photos.currentRowChanged.connect(lambda row: self.preview.set_url(self.item.images[row] if 0 <= row < len(self.item.images) else ""))
        # 2026-10-15：本次修改原因：将撤下名称输入释放的高度用于大图，文件名列表改为窄栏缩略图，单张图使用整行预览。
        self.photos = QListWidget()
        self.photos.setViewMode(QListView.ViewMode.IconMode)
        # self.photos.setFlow(QListView.Flow.TopToBottom)
        # 2026-10-15：本次修改原因：缩略图改为大图下方的单行横向图片带，配合左右按钮切换并保留手动横向滚动。
        self.photos.setObjectName("materialPhotoThumbnails")
        self.photos.setAccessibleName("原料图片缩略图，选择图片以预览")
        self.photos.setToolTip("可添加正面、背面、侧面及细节图；点击缩略图或左右按钮切换预览。")
        self.photos.setFlow(QListView.Flow.LeftToRight)
        self.photos.setWrapping(False)
        self.photos.setMovement(QListView.Movement.Static)
        # self.photos.setIconSize(QSize(64, 64))
        # 2026-10-15：本次修改原因：缩略图调整为 48px，降低图片带高度并为上方大图释放空间。
        self.photos.setIconSize(QSize(48, 48))
        # self.photos.setGridSize(QSize(88, 98))
        # 2026-10-15：本次修改原因：底部缩略图采用统一紧凑网格，图片区变宽时展示更多图片。
        # self.photos.setGridSize(QSize(88, 96))
        # 2026-10-15：本次修改原因：撤下单张序号后压缩缩略图网格，保留选中边框与图片之间的留白。
        self.photos.setGridSize(QSize(68, 64))
        self.photos.setResizeMode(QListView.ResizeMode.Adjust)
        self.photos.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.photos.setFrameShape(QFrame.Shape.NoFrame)
        # self.photos.setFixedSize(110, 220)
        # 2026-10-15：本次修改原因：缩略图栏随左侧图片区增高，保持窄栏选图与单图隐藏行为。
        # self.photos.setFixedWidth(110)
        # self.photos.setMinimumHeight(280)
        # self.photos.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        # self.photos.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 2026-10-15：本次修改原因：底部图片带固定紧凑高度，宽度随分区伸缩，溢出时沿用统一横向滚动条。
        # self.photos.setFixedHeight(112)
        # 2026-10-15：本次修改原因：图片带从 112px 降到 80px，并为溢出图片的横向滚动条预留高度。
        self.photos.setFixedHeight(80)
        self.photos.setMinimumWidth(0)
        self.photos.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.photos.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.photos.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.photos.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview = ImagePreview(QNetworkAccessManager(self), 220)
        # 2026-10-15：本次修改原因：仅解除当前弹窗预览的固定高度，图片随分区伸展且不以位图尺寸撑大窗口。
        self.preview.setMinimumHeight(280)
        self.preview.setMaximumHeight(16_777_215)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        # photos.addWidget(self.photos); photos.addWidget(self.preview, 1); layout.addLayout(photos)
        # 2026-10-15：本次修改原因：点击整块虚线上传区即可选图，居中加号与说明共用按钮的鼠标、键盘和无障碍入口。
        self.upload_button = button("", self.add_images)
        self.upload_button.setObjectName("materialUpload")
        self.upload_button.setAutoDefault(False)
        self.upload_button.setAccessibleName("添加白底图")
        self.upload_button.setToolTip("点击添加白底图，可一次选择多张")
        upload_layout = QVBoxLayout(self.upload_button)
        upload_layout.setContentsMargins(20, 20, 20, 20)
        upload_layout.setSpacing(6)
        upload_layout.addStretch()
        for text, name in (("＋", "materialUploadPlus"), ("点击添加白底图", "materialUploadCaption")):
            caption = label(text, name)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            upload_layout.addWidget(caption)
        upload_layout.addStretch()
        # 2026-10-15：本次修改原因：有图时在预览角落提供小型添加和移除图标，节省下方按钮占用并保留多图管理。
        self.image_preview_page = QWidget()
        preview_layout = QGridLayout(self.image_preview_page)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        preview_layout.addWidget(self.preview, 0, 0)
        image_tools = QWidget()
        tools_layout = QHBoxLayout(image_tools)
        tools_layout.setContentsMargins(10, 10, 10, 10)
        tools_layout.setSpacing(6)
        self.add_image_button = button("＋", self.add_images)
        self.remove_image_button = button("×", self.remove_image)
        for control, title in ((self.add_image_button, "继续添加白底图"), (self.remove_image_button, "移除当前图片")):
            control.setObjectName("materialImageAction")
            control.setFixedSize(32, 32)
            control.setAutoDefault(False)
            control.setToolTip(title)
            control.setAccessibleName(title)
            tools_layout.addWidget(control)
        self.remove_image_button.setProperty("removeImage", True)
        preview_layout.addWidget(image_tools, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        image_tools.raise_()
        self.image_stack = QStackedWidget()
        # self.image_stack.setFixedHeight(220)
        # 2026-10-15：本次修改原因：上传区和有图预览共用图片区剩余高度，保持较大的可见面积。
        self.image_stack.setMinimumHeight(280)
        self.image_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_stack.addWidget(self.upload_button)
        self.image_stack.addWidget(self.image_preview_page)
        # photos.addWidget(self.photos); photos.addWidget(self.image_stack, 1); layout.addLayout(photos)
        # 2026-10-15：本次修改原因：图片与缩略图放入左侧独立分区，预留底部 AI 操作行。
        # photos.addWidget(self.photos)
        # photos.addWidget(self.image_stack, 1)
        # photo_layout.addLayout(photos, 1)
        # 2026-10-15：本次修改原因：预览使用上部完整宽度，底部追加缩略图轮播与张数，AI 操作仍位于其下方。
        photo_layout.addWidget(self.image_stack, 1)
        self.photo_carousel = QWidget()
        carousel_layout = QVBoxLayout(self.photo_carousel)
        carousel_layout.setContentsMargins(0, 0, 0, 0)
        carousel_layout.setSpacing(2)
        thumbnails = QHBoxLayout()
        thumbnails.setSpacing(6)
        self.previous_photo_button = button("‹", lambda: self._step_image(-1))
        self.next_photo_button = button("›", lambda: self._step_image(1))
        for control, title in ((self.previous_photo_button, "上一张原料图"),
                               (self.next_photo_button, "下一张原料图")):
            control.setObjectName("materialPhotoNav")
            control.setFixedSize(28, 32)
            control.setAutoDefault(False)
            control.setToolTip(title)
            control.setAccessibleName(title)
        thumbnails.addWidget(self.previous_photo_button)
        thumbnails.addWidget(self.photos, 1)
        thumbnails.addWidget(self.next_photo_button)
        carousel_layout.addLayout(thumbnails)
        self.photo_position = label("第 0 / 0 张", "hint")
        self.photo_position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        carousel_layout.addWidget(self.photo_position)
        photo_layout.addWidget(self.photo_carousel)
        self.details_splitter.addWidget(photo_panel)
        self.photos.currentRowChanged.connect(self._select_image)
        # 2026-10-15：本次修改原因：下半部左右拆分，左侧表格使用剩余高度，右侧长表单独立滚动。
        # self.details_splitter = QSplitter(Qt.Orientation.Horizontal)
        # self.details_splitter.setChildrenCollapsible(False)
        # self.details_splitter.setHandleWidth(10)
        # facts_panel = QWidget()
        # 2026-10-15：本次修改原因：资料表放在右侧独立圆角框内，与左侧图片区清楚区分。
        facts_panel = QFrame()
        facts_panel.setObjectName("materialFactsFrame")
        facts_layout = QVBoxLayout(facts_panel)
        # facts_layout.setContentsMargins(0, 0, 0, 0)
        # 2026-10-15：本次修改原因：表格与边缘新增入口留出内边距，避免遮挡独立分区的圆角边框。
        facts_layout.setContentsMargins(12, 12, 12, 12)
        facts_panel.setMinimumWidth(420)
        # layout.addWidget(self.details_splitter, 1)
        # image_buttons = QHBoxLayout(); image_buttons.addWidget(button("添加白底图", self.add_images)); image_buttons.addWidget(button("移除选中图", self.remove_image))
        # 2026-10-15：本次修改原因：图片添加和移除移至图片区，下方仅保留 AI 观察及资料操作。
        image_buttons = QHBoxLayout()
        # self.observe_button = button("AI 观察外观", self.observe, symbol="analysis"); image_buttons.addWidget(self.observe_button); image_buttons.addStretch(); layout.addLayout(image_buttons)
        # 2026-10-15：本次修改原因：资料操作移至表格上方同一行右侧，采用观察时无需滚动到底部。
        # self.observe_button = button("AI 观察外观", self.observe, symbol="analysis"); image_buttons.addWidget(self.observe_button); image_buttons.addStretch()
        # 2026-10-15：本次修改原因：两个 AI 操作集中到图片区右下角，左侧伸缩空白使按钮整体居右。
        image_buttons.addStretch()
        self.observe_button = button("AI 观察外观", self.observe, symbol="analysis")
        image_buttons.addWidget(self.observe_button)
        # image_buttons.addWidget(button("新增自定义字段", self.add_fact))
        # 2026-10-15：本次修改原因：撤下常驻新增按钮，尾行与尾列边缘分别提供新增字段和属性入口。
        adopt_button = button("采用选中外观观察", self.adopt_observation)
        adopt_button.setToolTip("将选中字段的外观观察写入资料值，来源记为图片观察，状态记为已确认。")
        # image_buttons.addWidget(adopt_button); layout.addLayout(image_buttons)
        # layout.addWidget(label("双击资料值直接编辑；Enter 换行，Tab 完成编辑。长内容也可右键编辑完整内容。", "hint", True))
        # 2026-10-15：本次修改原因：资料操作和说明放入左侧表格区，右侧表单可与表格同时查看。
        # image_buttons.addWidget(adopt_button); facts_layout.addLayout(image_buttons)
        # 2026-10-15：本次修改原因：采用观察与 AI 观察并排放在图片区底部，资料表继续保留直接编辑提示。
        image_buttons.addWidget(adopt_button)
        photo_layout.addLayout(image_buttons)
        facts_layout.addWidget(label("双击资料值编辑；Enter 换行，Tab 完成。表格末行／末列边缘悬停新增，双击自定义列表头可改名。", "hint", True))
        self.facts = QTableWidget(0, 5)
        self.facts.setHorizontalHeaderLabels(["字段", "资料值（可编辑）", "来源", "状态", "图片观察 / 冲突提示"])
        # configure_table(self.facts, editable=True, multiline=True)
        # 2026-10-15：本次修改原因：字段值在自适应高度的完整编辑框中输入，避免单行表格编辑器遮挡长资料。
        # configure_table(self.facts, editable=False, multiline=True)
        # 2026-10-15：本次修改原因：修正可编辑表头与只读行为不一致，资料值改用表格内自适应多行编辑。
        configure_table(self.facts, editable=True, multiline=True)
        # 2026-10-15：本次修改原因：资料表已有独立圆角外框，使用现有嵌入表格样式减少重复描边。
        self.facts.setProperty("embeddedTable", True)
        self.facts.setItemDelegateForColumn(1, FactValueDelegate(self.facts))
        self.facts.setWordWrap(True)
        self.facts.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.facts.itemChanged.connect(self._fit_fact_row)
        # self.facts.horizontalHeader().sectionResized.connect(lambda *_args: self._fit_fact_rows())
        # 2026-10-15：本次修改原因：来源与状态按最长选项限制最小列宽，拖窄时避免文字被裁切，其他列继续自适应行高。
        self.facts.horizontalHeader().sectionResized.connect(self._resize_fact_column)
        # for col, width in enumerate((120, 220, 130, 130, 290)): self.facts.setColumnWidth(col, width)
        # self.facts.setMinimumHeight(390)
        # layout.addWidget(self.facts)
        # 2026-10-15：本次修改原因：压缩固定资料列的初始宽度，补充属性列恢复后也能直接多行编辑。
        # for col, width in enumerate((106, 180, 124, 106, 210)):
        # 2026-10-15：本次修改原因：紧凑选择列按实际字体和最长文字计算初始宽度，不再预留过宽的箭头空白。
        self.facts.ensurePolished()
        choice_widths = (self._fact_choice_minimum_width(2), self._fact_choice_minimum_width(3))
        for col, width in enumerate((106, 180, *choice_widths, 210)):
            self.facts.setColumnWidth(col, width)
        self.facts.setMinimumHeight(280)
        for title in self.item.fact_attributes:
            self._attribute_column(title)
        self.facts.horizontalHeader().sectionDoubleClicked.connect(self.rename_attribute)
        self.fact_edges = TableEdgeActions(self.facts, self.add_fact, self.add_attribute)
        facts_layout.addWidget(self.fact_edges, 1)
        self.details_splitter.addWidget(facts_panel)
        # self.fact_title = label("选中字段后编辑完整资料", "muted")
        # self.fact_value = AutoHeightTextEdit("", minimum_lines=2, maximum_lines=8)
        # self.fact_value.setPlaceholderText("选中上方字段后，在这里填写完整资料；来源和确认状态在表格内选择。")
        # self.fact_value.setEnabled(False)
        # layout.addWidget(self.fact_title); layout.addWidget(self.fact_value)
        # self.facts.currentCellChanged.connect(self._select_fact)
        # self.fact_value.textChanged.connect(self._edit_fact)
        # facts_buttons = QHBoxLayout(); facts_buttons.addWidget(button("新增自定义字段", self.add_fact)); facts_buttons.addWidget(button("采用选中外观观察", self.adopt_observation)); facts_buttons.addStretch(); layout.addLayout(facts_buttons)
        # self.observation_notes = label(self.item.observation_notes, "hint", True); layout.addWidget(self.observation_notes)
        # 2026-10-15：本次修改原因：观察提示留在左侧资料表旁，空内容时收起以节省行高。
        self.observation_notes = label(self.item.observation_notes, "hint", True)
        self.observation_notes.setVisible(bool(self.item.observation_notes))
        # facts_layout.addWidget(self.observation_notes)
        # 2026-10-15：本次修改原因：资料表底部右侧增加全部确认按钮，与观察提示同排，便于一键确认所有字段。
        facts_footer = QHBoxLayout()
        facts_footer.addWidget(self.observation_notes, 1)
        facts_footer.addStretch()
        self.confirm_all_button = button("全部确认", self.confirm_all_facts)
        self.confirm_all_button.setAutoDefault(False)
        self.confirm_all_button.setToolTip("将所有行（含自定义字段）的状态设为已确认，点击保存原料后保存。")
        facts_footer.addWidget(self.confirm_all_button, 0, Qt.AlignmentFlag.AlignBottom)
        facts_layout.addLayout(facts_footer)
        # 2026-10-15：本次修改原因：右侧经济资料表单迁至顶部第二、三行，旧布局仅注释保留。
        # economics_panel = QWidget()
        # economics_panel.setMinimumWidth(0)
        # economics_layout = QVBoxLayout(economics_panel)
        # economics_layout.setContentsMargins(8, 0, 4, 0)
        # economics = QFormLayout(); economics.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        # 2026-10-15：本次修改原因：窄侧栏将标签置于输入框上方，避免压缩长文本、下拉框及数字输入区。
        # economics.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        # self.cost = QLineEdit(self.item.unit_cost); self.cost.setPlaceholderText("可选；按计量单位填写，留空表示未知")
        # self.currency = QLineEdit(self.item.currency or "CNY")
        # self.track = QCheckBox("记录库存数量"); self.track.setChecked(self.item.track_inventory)
        # self.quantity = QSpinBox(); self.quantity.setRange(0, 10_000_000); self.quantity.setValue(self.item.quantity)
        # self.quantity.setEnabled(self.track.isChecked()); self.track.toggled.connect(self.quantity.setEnabled)
        # self.supplier = AutoHeightTextEdit(self.item.supplier, minimum_lines=1, maximum_lines=3)
        # self.supplier_url = AutoHeightTextEdit(self.item.supplier_url, minimum_lines=1, maximum_lines=3)
        # self.notes = AutoHeightTextEdit(self.item.notes, minimum_lines=3, maximum_lines=10)
        # for title, control in (("单位成本",self.cost),("成本币种",self.currency),("库存管理",self.track),("库存总量",self.quantity),("供应商",self.supplier),("采购链接",self.supplier_url),("内部备注",self.notes)): economics.addRow(title,control)
        # layout.addLayout(economics); root.addWidget(scroll_form(body), 1)
        # 2026-10-15：本次修改原因：右侧长表单独立滚动，外层保留小屏滚动，表格随窗口高度伸展。
        # economics_layout.addLayout(economics)
        # economics_layout.addStretch()
        # economics_scroll = scroll_form(economics_panel)
        # economics_scroll.setMinimumWidth(250)
        # economics_scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        # self.details_splitter.addWidget(economics_scroll)
        # self.details_splitter.setStretchFactor(0, 3)
        # self.details_splitter.setStretchFactor(1, 1)
        # self.details_splitter.setSizes([850, 300])
        # 2026-10-15：本次修改原因：默认给右侧资料表更多宽度，左侧预览可随用户拖动分隔条扩大。
        self.details_splitter.setStretchFactor(0, 1)
        self.details_splitter.setStretchFactor(1, 2)
        self.details_splitter.setSizes([380, 800])
        root.addWidget(scroll_form(body), 1)
        self.status = label("", "hint", True); root.addWidget(self.status)
        footer = QHBoxLayout(); footer.addStretch(); footer.addWidget(button("取消",self.reject)); self.save_button = button("保存原料",self.save,primary=True); footer.addWidget(self.save_button); root.addLayout(footer)
        self._populate_facts(); self._show_images()
        self.facts.setCurrentCell(0,1)

    # 2026-10-15：本次修改原因：长字段沿用现有多行输入控件，切换字段时不丢失已输入内容。
    # def _select_fact(self, row, *_args):
    #     valid = 0 <= row < self.facts.rowCount() and self.facts.item(row,1) is not None
    #     self.fact_value.blockSignals(True)
    #     self.fact_value.setPlainText(self.facts.item(row,1).text() if valid else "")
    #     self.fact_value.blockSignals(False); self.fact_value.setEnabled(valid)
    #     self.fact_title.setText("完整编辑："+self.facts.item(row,0).text() if valid else "选中字段后编辑完整资料")

    # def _edit_fact(self):
    #     row = self.facts.currentRow()
    #     if row >= 0 and self.facts.item(row,1): self.facts.item(row,1).setText(self.fact_value.toPlainText())

    # 2026-10-15：本次修改原因：长资料在表格内换行并随内容调整高度，超长文本通过编辑器滚动或右键完整查看。
    def _fit_fact_row(self, item):
        row = item.row()
        # 2026-10-15：本次修改原因：新增属性列表头也会变更资料项，仅对有效资料行计算高度。
        if row < 0:
            return
        self.facts.resizeRowToContents(row)
        maximum = max(self.facts.verticalHeader().minimumSectionSize(), self.facts.fontMetrics().lineSpacing() * 10 + 32)
        self.facts.setRowHeight(row, min(maximum, self.facts.rowHeight(row)))

    def _fit_fact_rows(self):
        for row in range(self.facts.rowCount()):
            item = self.facts.item(row, 1)
            if item is not None:
                self._fit_fact_row(item)

    # 2026-10-15：本次修改原因：选择列仅保留最长选项、左侧留白和单份箭头空间，五字来源也能完整展示。
    def _fact_choice_minimum_width(self, column):
        values = SOURCE_LABELS if column == 2 else STATUS_LABELS
        metrics = self.facts.fontMetrics()
        return max(metrics.horizontalAdvance(text) for text in values.values()) + 34

    # 2026-10-15：本次修改原因：仅防止来源和状态列缩到文字所需宽度以下，表格变窄时通过横向滚动查看。
    def _resize_fact_column(self, column, _old_width, width):
        if column in (2, 3):
            minimum = self._fact_choice_minimum_width(column)
            if width < minimum:
                self.facts.setColumnWidth(column, minimum)
                return
        self._fit_fact_rows()

    def _invalidate_observation(self):
        self.item.observations = {}; self.item.observation_notes = "原料图片已变更，请重新观察。"
        self.observation_notes.setText(self.item.observation_notes)
        # 2026-10-15：本次修改原因：图片区变更后立即显示重新观察提示，空提示不占表格高度。
        self.observation_notes.setVisible(bool(self.item.observation_notes))
        for row in range(self.facts.rowCount()):
            self.facts.item(row,4).setText("")
            if self.facts.cellWidget(row,2).currentData() == "vision":
                state = self.facts.cellWidget(row,3); state.setCurrentIndex(state.findData("pending"))

    def _populate_facts(self):
        fields = dict(FACT_FIELDS)
        # fields.update({key: key for key in self.item.facts if key not in fields})
        # 2026-10-15：本次修改原因：只填补充属性或暂未填值的自定义字段，重开时也保留对应行。
        for mapping in (self.item.facts, self.item.fact_sources, self.item.fact_statuses,
                        *self.item.fact_attributes.values()):
            fields.update({key: key for key in mapping if key not in fields})
        self.facts.setRowCount(0)
        for key, title in fields.items():
            value = self.item.facts.get(key, self.item.material_type if key == "material" else "")
            self._fact_row(key, title, value, self.item.fact_sources.get(key,"user"), self.item.fact_statuses.get(key,"pending"))

    def _fact_row(self,key,title,value="",source="user",state="pending"):
        row = self.facts.rowCount(); self.facts.insertRow(row)
        name = QTableWidgetItem(title); name.setData(Qt.ItemDataRole.UserRole,key); name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.facts.setItem(row,0,name); self.facts.setItem(row,1,QTableWidgetItem(value))
        for col, values, current in ((2,SOURCE_LABELS,source),(3,STATUS_LABELS,state)):
            # combo = QComboBox()
            # 2026-10-15：本次修改原因：只在资料来源和确认状态两列启用紧凑布局与关闭时的滚轮防误触。
            combo = FactChoiceComboBox(self.facts)
            for code, text in values.items(): combo.addItem(text,code)
            combo.setCurrentIndex(max(0,combo.findData(current))); self.facts.setCellWidget(row,col,combo)
        observation = QTableWidgetItem(self.item.observations.get(key,"")); observation.setFlags(observation.flags() & ~Qt.ItemFlag.ItemIsEditable)
        observation.setToolTip(observation.text()); self.facts.setItem(row,4,observation)
        # 2026-10-15：本次修改原因：已有及新增字段都创建补充属性单元格，支持直接多行输入。
        for col in range(5, self.facts.columnCount()):
            title = self.facts.horizontalHeaderItem(col).text()
            self.facts.setItem(row, col, QTableWidgetItem(self.item.fact_attributes.get(title, {}).get(key, "")))

    # 2026-10-15：本次修改原因：自定义属性作为真正可保存的列，沿用资料值的自适应多行编辑器。
    def _attribute_column(self, title):
        col = self.facts.columnCount()
        self.facts.insertColumn(col)
        header = QTableWidgetItem(title)
        header.setToolTip(title + "\n双击表头修改属性名称")
        self.facts.setHorizontalHeaderItem(col, header)
        self.facts.setColumnWidth(col, 180)
        self.facts.setItemDelegateForColumn(col, FactValueDelegate(self.facts))
        for row in range(self.facts.rowCount()):
            self.facts.setItem(row, col, QTableWidgetItem(""))
        return col

    # 2026-10-15：本次修改原因：右侧边缘新增命名属性列，拒绝空名称和重复名称，新增后直接进入编辑。
    def add_attribute(self):
        title, ok = QInputDialog.getText(self, "新增属性列", "属性名称")
        if not ok:
            return
        title = title.strip()
        if not title:
            QMessageBox.information(self, "需要属性名称", "请输入属性名称。")
            return
        if any(self.facts.horizontalHeaderItem(col).text() == title for col in range(self.facts.columnCount())):
            QMessageBox.information(self, "属性已存在", "已有同名列，请填写其他属性名称。")
            return
        col = self._attribute_column(title)
        row = max(0, self.facts.currentRow())
        self.facts.setCurrentCell(row, col)
        self.facts.scrollToItem(self.facts.item(row, col))
        self.facts.editItem(self.facts.item(row, col))

    # 2026-10-15：本次修改原因：双击补充属性表头即可改名，保存时保留该列现有内容。
    def rename_attribute(self, col):
        if col < 5:
            return
        header = self.facts.horizontalHeaderItem(col)
        title, ok = QInputDialog.getText(self, "修改属性名称", "属性名称", text=header.text())
        if not ok:
            return
        title = title.strip()
        if not title:
            QMessageBox.information(self, "需要属性名称", "请输入属性名称。")
            return
        if any(other != col and self.facts.horizontalHeaderItem(other).text() == title for other in range(self.facts.columnCount())):
            QMessageBox.information(self, "属性已存在", "已有同名列，请填写其他属性名称。")
            return
        header.setText(title)
        header.setToolTip(title + "\n双击表头修改属性名称")

    # def _show_images(self):
    #     self.photos.clear(); self.photos.addItems([f"原料图 {i+1} · {Path(uri).name}" for i,uri in enumerate(self.item.images)])
    #     if self.item.images: self.photos.setCurrentRow(0)
    #     else: self.preview.set_url("")
    # 2026-10-15：本次修改原因：图片只显示缩略图和简短序号，不展示素材文件名；增删后选中相应图片。
    def _show_images(self, current_row=None):
        if current_row is None:
            current_row = self.photos.currentRow()
        self.photos.blockSignals(True)
        self.photos.clear()
        for index, uri in enumerate(self.item.images):
            # photo = QListWidgetItem(f"第 {index + 1} 张")
            # 2026-10-15：本次修改原因：缩略图下方不再显示序号文字，序号仍可通过无障碍读取和悬停提示获取。
            photo = QListWidgetItem()
            photo.setData(Qt.ItemDataRole.AccessibleTextRole, f"第 {index + 1} 张原料图")
            photo.setToolTip(f"第 {index + 1} 张原料图")
            local = local_asset_path(uri)
            if local:
                reader = QImageReader(str(local))
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    reader.setScaledSize(size.scaled(self.photos.iconSize(), Qt.AspectRatioMode.KeepAspectRatio))
                    thumbnail = reader.read()
                    if not thumbnail.isNull():
                        photo.setIcon(QIcon(QPixmap.fromImage(thumbnail)))
            self.photos.addItem(photo)
        # self.photos.setVisible(len(self.item.images) > 1)
        # self.photos.blockSignals(False)
        # if self.item.images:
        #     self.photos.setCurrentRow(max(0, min(current_row, len(self.item.images) - 1)))
        # else:
        #     self._select_image(-1)
        # 2026-10-15：本次修改原因：单张也展示底部缩略图，重建列表后统一同步预览与计数，避免重复加载当前大图。
        selected = max(0, min(current_row, len(self.item.images) - 1)) if self.item.images else -1
        self.photos.setCurrentRow(selected)
        self.photos.blockSignals(False)
        self._select_image(selected)

    # 2026-10-15：本次修改原因：大图跟随缩略图选择，不在预览提示中暴露图片存储文件名。
    def _select_image(self, row):
        valid = 0 <= row < len(self.item.images)
        self.preview.set_url(self.item.images[row] if valid else "")
        self.preview.setToolTip(f"第 {row + 1} 张原料图" if valid else "添加白底图后在此预览")
        # 2026-10-15：本次修改原因：空图和清空最后一张图时恢复虚线上传入口，有图时显示预览及角落操作。
        self.image_stack.setCurrentWidget(self.image_preview_page if valid else self.upload_button)

        # 2026-10-15：本次修改原因：缩略图与大图、当前张数同步，切换后将当前项滚入可见区，清空图片时恢复上传状态。
        count = len(self.item.images)
        self.photo_position.setText(f"第 {row + 1 if valid else 0} / {count} 张")
        self.photo_carousel.setVisible(count > 0)
        self.previous_photo_button.setEnabled(count > 1)
        self.next_photo_button.setEnabled(count > 1)
        self.remove_image_button.setEnabled(valid)
        if valid:
            self.photos.scrollToItem(self.photos.item(row), QListView.ScrollHint.PositionAtCenter)

    # 2026-10-15：本次修改原因：左右按钮循环切换已上传图片，首尾相接；单张或空列表时不触发切换。
    def _step_image(self, step):
        count = len(self.item.images)
        if count > 1:
            self.photos.setCurrentRow((self.photos.currentRow() + step) % count)

    def add_images(self):
        paths,_ = QFileDialog.getOpenFileNames(self,"选择散珠 / 配件白底图","","图片 (*.png *.jpg *.jpeg *.webp)")
        try:
            previous = list(self.item.images)
            for path in paths:
                uri = self.assets.import_file(Path(path)).uri
                if uri not in self.item.images: self.item.images.append(uri)
            if self.item.images != previous: self._invalidate_observation()
            # self._show_images()
            # 2026-10-15：本次修改原因：导入新图后直接预览第一张新图，重复导入或取消时保持原选择。
            self._show_images(len(previous) if self.item.images != previous else None)
        except (ValueError,OSError) as error: QMessageBox.warning(self,"无法导入图片",str(error))

    def remove_image(self):
        row = self.photos.currentRow()
        # if 0 <= row < len(self.item.images): self.item.images.pop(row); self._invalidate_observation(); self._show_images()
        # 2026-10-15：本次修改原因：删除当前图后预览邻近图片，清空最后一张时恢复无图片状态。
        if 0 <= row < len(self.item.images): self.item.images.pop(row); self._invalidate_observation(); self._show_images(row)

    def add_fact(self):
        key,ok = QInputDialog.getText(self,"新增字段","字段名称")
        # if ok and key.strip() and all(self.facts.item(row,0).data(Qt.ItemDataRole.UserRole) != key.strip() for row in range(self.facts.rowCount())): self._fact_row(key.strip(),key.strip())
        # 2026-10-15：本次修改原因：新增自定义资料后立即进入完整编辑框，不需要在长表中查找新字段。
        # if ok and key.strip() and all(self.facts.item(row,0).data(Qt.ItemDataRole.UserRole) != key.strip() for row in range(self.facts.rowCount())):
        # 2026-10-15：本次修改原因：尾行新增时明确提示无效或重复字段，避免点击后没有反馈。
        if not ok:
            return
        key = key.strip()
        if not key:
            QMessageBox.information(self, "需要字段名称", "请输入字段名称。")
            return
        if any(key in (self.facts.item(row, 0).data(Qt.ItemDataRole.UserRole), self.facts.item(row, 0).text())
               for row in range(self.facts.rowCount())):
            QMessageBox.information(self, "字段已存在", "已有同名字段，请编辑已有行或填写其他字段名称。")
            return
        if key:
            self._fact_row(key.strip(),key.strip())
            self.facts.setCurrentCell(self.facts.rowCount()-1,1)
            # self.fact_value.setFocus()
            # 2026-10-15：本次修改原因：自定义字段新增后立即在对应资料单元格输入，省去下方编辑框。
            self.facts.scrollToItem(self.facts.item(self.facts.rowCount()-1,1))
            self.facts.editItem(self.facts.item(self.facts.rowCount()-1,1))

    # 2026-10-15：本次修改原因：一次确认当前原料的全部资料行，包括后续新增的自定义字段，并沿用原料保存流程。
    def confirm_all_facts(self):
        if self.busy:
            return
        self.facts.setFocus(Qt.FocusReason.OtherFocusReason)
        for row in range(self.facts.rowCount()):
            state = self.facts.cellWidget(row, 3)
            state.setCurrentIndex(state.findData("confirmed"))
        self.status.setText(f"已将全部 {self.facts.rowCount()} 行设为已确认，请保存原料。")

    def adopt_observation(self):
        row = self.facts.currentRow()
        if row < 0: return
        key = self.facts.item(row,0).data(Qt.ItemDataRole.UserRole)
        if key not in VISIBLE_FIELDS: QMessageBox.information(self,"请核实资料","此字段需要用户资料或实测确认，不能由照片直接确认。"); return
        value = self.facts.item(row,4).text()
        if value:
            self.facts.item(row,1).setText(value)
            # self._select_fact(row)
            # self.facts.cellWidget(row,2).setCurrentIndex(self.facts.cellWidget(row,2).findData("human"))
            # 2026-10-15：本次修改原因：采用 AI 外观只确认这条观察，事实来源仍应是图片观察而非人工实测。
            self.facts.cellWidget(row,2).setCurrentIndex(self.facts.cellWidget(row,2).findData("vision"))
            self.facts.cellWidget(row,3).setCurrentIndex(self.facts.cellWidget(row,3).findData("confirmed"))
            self.status.setText("已采用选中外观观察，来源为图片观察，状态为已确认。")

    def observe(self):
        if self.busy: return
        if not self.item.images: QMessageBox.information(self,"需要原料图","请先添加原料图片。"); return
        # 2026-10-15：本次修改原因：观察期间冻结输入照片和资料，避免异步结果对应到不同原料图片。
        self.busy = True; self.save_button.setEnabled(False); self.form_body.setEnabled(False)
        request = AIRequest("material_observation",{"attributes":{}},language="中文",subject_images=list(self.item.images),instruction='只观察当前原料的颜色、形状、表面质感、透明度。禁止推断石种、成分、孔径、精确尺寸或功效。输出 JSON {"observations":{"color":"","shape":"","texture":"","transparency":""},"notes":"图片之间不一致或需要用户补充的信息"}。')
        self.ai_hub.submit(lambda progress:self.ai_service.generate(request,progress),self._observed,self._failed,lambda message:self.status.setText(message))

    def _finished(self):
        self.busy = False; self.save_button.setEnabled(True); self.form_body.setEnabled(True)

    def _failed(self,message):
        self._finished(); self.status.setText("观察失败："+message)

    def _observed(self,result):
        self._finished()
        try:
            data = parse_object(result.candidates[0]); observations = data.get("observations",{})
            if not isinstance(observations,dict): raise ValueError("模型未返回有效外观观察")
            self.item.observations.update({key:str(value) for key,value in observations.items() if key in VISIBLE_FIELDS and isinstance(value,str)})
            self.item.observation_notes = str(data.get("notes", "")); self.observation_notes.setText(self.item.observation_notes)
            # 2026-10-15：本次修改原因：观察完成后按实际内容显示提示，避免空标签占据表格高度。
            self.observation_notes.setVisible(bool(self.item.observation_notes))
            for row in range(self.facts.rowCount()):
                key = self.facts.item(row,0).data(Qt.ItemDataRole.UserRole); observed = self.item.observations.get(key,"")
                self.facts.item(row,4).setText(observed); self.facts.item(row,4).setToolTip(observed)
                entered = self.facts.item(row,1).text().strip()
                if observed and entered and observed != entered:
                    combo = self.facts.cellWidget(row,3); combo.setCurrentIndex(combo.findData("conflict"))
            # self.status.setText("图片观察已保留。与已填资料不同的字段已标出冲突，请人工核对；观察不会自动改写资料值。")
            # 2026-10-15：本次修改原因：观察完成后指明采用位置及来源切换规则，避免误以为生成结果已覆盖资料。
            # self.status.setText("图片观察已保留，差异已标为冲突。选中外观字段后，点击表格上方“采用选中外观观察”，来源将切换为图片观察。")
            # 2026-10-15：本次修改原因：采用观察按钮已移至图片区右下角，观察完成提示同步指向实际位置。
            self.status.setText("图片观察已保留，差异已标为冲突。选中外观字段后，点击图片区右下角“采用选中外观观察”，来源将切换为图片观察。")
        except (ValueError,IndexError) as error: self.status.setText("观察结果无法使用："+str(error))

    def save(self):
        if self.busy: return
        # 2026-10-15：本次修改原因：保存前结束当前单元格输入，让最后一个编辑值提交到表格模型。
        self.facts.setFocus(Qt.FocusReason.OtherFocusReason)
        try:
            # item = deepcopy(self.item); item.code = self.code.text().strip(); item.name = self.name.toPlainText().strip(); item.category = self.kind.currentData()
            # 2026-10-15：本次修改原因：原料不再填写名称，保存编号和类型即可，已有名称数据保留以兼容旧记录。
            item = deepcopy(self.item); item.code = self.code.text().strip(); item.category = self.kind.currentData()
            item.facts = {}; item.fact_sources = {}; item.fact_statuses = {}
            # 2026-10-15：本次修改原因：保存所有补充属性列及列顺序，空属性列也保留。
            item.fact_attributes = {self.facts.horizontalHeaderItem(col).text(): {} for col in range(5, self.facts.columnCount())}
            for row in range(self.facts.rowCount()):
                key = self.facts.item(row,0).data(Qt.ItemDataRole.UserRole); value = self.facts.item(row,1).text().strip()
                if value: item.facts[key] = value
                item.fact_sources[key] = self.facts.cellWidget(row,2).currentData(); item.fact_statuses[key] = self.facts.cellWidget(row,3).currentData()
                # 2026-10-15：本次修改原因：按字段编号读取各列值，包含仅填写补充属性的自定义行。
                for col in range(5, self.facts.columnCount()):
                    title = self.facts.horizontalHeaderItem(col).text()
                    attribute = self.facts.item(row, col).text().strip()
                    if attribute:
                        item.fact_attributes[title][key] = attribute
            # item.material_type = item.facts.get("material",""); item.unit_cost = self.cost.text().strip(); item.currency = self.currency.text().strip().upper()
            # item.quantity = self.quantity.value(); item.track_inventory = self.track.isChecked(); item.supplier = self.supplier.toPlainText().strip(); item.supplier_url = self.supplier_url.toPlainText().strip(); item.notes = self.notes.toPlainText()
            # 2026-10-15：本次修改原因：币种从下拉框保存，库存按是否填值区分未知与零；空白时保留既有数量和预留数据。
            item.material_type = item.facts.get("material", "")
            item.unit_cost = self.cost.text().strip()
            item.currency = self.currency.currentText().strip().upper() or "CNY"
            quantity_text = self.quantity.text().strip()
            if quantity_text and not self.quantity.hasAcceptableInput():
                raise ValueError("库存总量请填写 0～10000000 的整数，或留空。")
            item.track_inventory = bool(quantity_text)
            if quantity_text:
                item.quantity = int(quantity_text)
            item.supplier = self.supplier.toPlainText().strip()
            item.supplier_url = self.supplier_url.toPlainText().strip()
            item.notes = self.notes.toPlainText()
            # item.state = "ready" if item.images and item.name else "draft"
            # 2026-10-15：本次修改原因：撤下名称后不再将它作为资料就绪条件，自动编号仍由存储事务分配。
            item.state = "ready" if item.images else "draft"
            self.store.save_material(item,expected_revision=self.item.revision if self.item.id else None); self.accept()
        except (ValueError,OSError,sqlite3.Error) as error: QMessageBox.warning(self,"无法保存原料",str(error))

    def reject(self):
        if self.busy: QMessageBox.information(self,"正在观察图片","请等待任务结束后关闭。"); return
        super().reject()


class BeadDatabasePage(QWidget):
    def __init__(self,store,assets,parent=None,ai_service=None,ai_hub=None):
        super().__init__(parent); self.store,self.assets,self.ai_service,self.ai_hub = store,assets,ai_service,ai_hub; self._rows = []
        # 2026-10-15：本次修改原因：分页位置独立保存，原料类型在点击刷新后才应用，避免待选类型被翻页或自动刷新提前采用。
        self._page = 1
        self._page_count = 0
        self._total = 0
        self._applied_material_category = ""
        self._query_key = None
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(12)
        # toolbar = QHBoxLayout(); toolbar.addWidget(label("散珠数据库","pageTitle"))
        # 2026-10-15：本次修改原因：模块支持多个类目库，统一使用数据库名称。
        # toolbar = QHBoxLayout(); toolbar.addWidget(label("数据库","pageTitle"))
        # 2026-10-15：本次修改原因：侧栏已标识模块名称，首行直接提供当前类目及原料新增操作。
        toolbar = QHBoxLayout(); toolbar.addWidget(label("当前类目"))
        self.library = QComboBox(); self.library.currentIndexChanged.connect(self.refresh); toolbar.addWidget(self.library)
        toolbar.addWidget(button("新增类目",self.add_library)); toolbar.addStretch()
        # self.search = QLineEdit(); self.search.setPlaceholderText("搜索编号、名称、材质"); self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.refresh); toolbar.addWidget(self.search,1)
        # toolbar.addWidget(button("新增原料",self.add_item,primary=True)); root.addLayout(toolbar)
        # tools = QHBoxLayout(); self.category = QComboBox(); self.category.addItem("全部原料类型","")
        # for key,title in MATERIAL_CATEGORY_LABELS.items(): self.category.addItem(title,key)
        # self.category.currentIndexChanged.connect(self.refresh); tools.addWidget(self.category); tools.addStretch(); tools.addWidget(button("编辑选中原料",self.edit_current)); tools.addWidget(button("刷新",self.refresh)); root.addLayout(tools)
        # 2026-10-15：本次修改原因：新增按钮固定显示新增原料，展开选择类型后直接弹出该类型原料编辑窗。
        self.add_button = button("新增原料",primary=True); self.add_button.setMinimumWidth(124)
        self.add_menu = QMenu(self.add_button)
        # 2026-10-15：本次修改原因：菜单打开前按按钮实际宽度设置，确保下拉菜单与新增原料按钮等宽。
        self.add_menu.aboutToShow.connect(lambda: self.add_menu.setFixedWidth(self.add_button.width()))
        for key,title in MATERIAL_CATEGORY_LABELS.items():
            action = self.add_menu.addAction(title)
            action.triggered.connect(lambda _checked=False, kind=key: self.add_item(kind))
        self.add_button.setMenu(self.add_menu); toolbar.addWidget(self.add_button)
        # toolbar.addWidget(button("刷新",self.refresh)); root.addLayout(toolbar)
        # 2026-10-15：本次修改原因：刷新移到搜索框下方，与原料类型筛选及右侧分页操作同行。
        root.addLayout(toolbar)
        # 2026-10-15：本次修改原因：搜索单独一行，不挤占首行类目选择和右侧新增、刷新操作。
        # self.search = QLineEdit(); self.search.setPlaceholderText("搜索编号、名称、材质"); self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.refresh)
        # 2026-10-15：本次修改原因：原料使用编号、类型与资料区分，搜索提示不再要求填写名称。
        self.search = QLineEdit(); self.search.setPlaceholderText("搜索编号、材质等资料"); self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.refresh)
        root.addWidget(self.search)
        # root.addWidget(label("每种原料独立编号；照片观察与已确认资料分别保存。其他类目可先建库，后续接入对应的设计生成模块。","hint",True))
        # 2026-10-15：本次修改原因：撤下列表上方说明，左侧提供原料类型和刷新，右侧提供每页条数、翻页及页码跳转。
        list_tools = QHBoxLayout()
        list_tools.setSpacing(8)
        self.material_filter = QComboBox()
        self.material_filter.addItem("全部原料类型", "")
        for key, title in MATERIAL_CATEGORY_LABELS.items():
            self.material_filter.addItem(title, key)
        self.material_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.material_filter.setAccessibleName("原料类型筛选")
        self.material_filter.setToolTip("选择原料类型后点击刷新，列表和分页将只显示该类型；全部原料类型可取消类型筛选。")
        list_tools.addWidget(self.material_filter)
        self.refresh_button = button("刷新", self._apply_material_filter)
        list_tools.addWidget(self.refresh_button)
        list_tools.addStretch(1)
        self.total_label = label("共 0 条", "hint")
        list_tools.addWidget(self.total_label)
        self.page_size = QComboBox()
        for size in (20, 50, 100, 200):
            self.page_size.addItem(f"每页 {size} 条", size)
        self.page_size.setCurrentIndex(1)
        self.page_size.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.page_size.setAccessibleName("每页原料条数")
        self.page_size.currentIndexChanged.connect(self.refresh)
        list_tools.addWidget(self.page_size)
        self.previous_page_button = button("上一页", lambda: self._change_page(-1))
        list_tools.addWidget(self.previous_page_button)
        self.page_count_label = label("第 0 / 0 页", "hint")
        list_tools.addWidget(self.page_count_label)
        self.next_page_button = button("下一页", lambda: self._change_page(1))
        list_tools.addWidget(self.next_page_button)
        list_tools.addWidget(label("跳至", "hint"))
        self.page_input = QLineEdit()
        self.page_input.setValidator(QIntValidator(1, 1, self.page_input))
        # 2026-10-15：本次修改原因：页码统一使用不含千位分隔符的整数，避免本地化校验通过后无法转换为跳转页码。
        page_locale = QLocale.c()
        page_locale.setNumberOptions(QLocale.NumberOption.RejectGroupSeparator)
        self.page_input.validator().setLocale(page_locale)
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_input.setAccessibleName("跳转页码")
        self.page_input.setToolTip("输入页码后按回车或点击跳转。")
        self.page_input.returnPressed.connect(self._jump_page)
        list_tools.addWidget(self.page_input)
        list_tools.addWidget(label("页", "hint"))
        self.jump_page_button = button("跳转", self._jump_page)
        list_tools.addWidget(self.jump_page_button)
        root.addLayout(list_tools)
        # self.table = QTableWidget(0,8); self.table.setHorizontalHeaderLabels(["编号","名称 / 类型","已填资料","待确认 / 冲突","图片","可用 / 总量","单位成本","版本"])
        # 2026-10-15：本次修改原因：列表只保留编号和原料类型，不再展示已撤下的名称字段。
        self.table = QTableWidget(0,8); self.table.setHorizontalHeaderLabels(["编号","原料类型","已填资料","待确认 / 冲突","图片","可用 / 总量","单位成本","版本"])
        configure_table(self.table,editable=False,multiline=True)
        # 2026-10-15：本次修改原因：圆角边框交给独立外框，表头与滚动条留出内边距，保持四边完整。
        self.table.setProperty("embeddedTable", True)
        self.list_frame = QFrame(); self.list_frame.setObjectName("databaseListFrame")
        list_layout = QVBoxLayout(self.list_frame); list_layout.setContentsMargins(6,6,6,6); list_layout.setSpacing(0)
        list_layout.addWidget(self.table)
        for col,width in enumerate((125,210,300,210,80,120,130,80)): self.table.setColumnWidth(col,width)
        self.table.cellDoubleClicked.connect(lambda row,_col:self.edit_item(self._rows[row].id) if row < len(self._rows) else None)
        # root.addWidget(self.table,1); self.summary = label("","muted"); root.addWidget(self.summary)
        # 2026-10-15：本次修改原因：列表区域使用加粗圆角外框，数量说明仍独立显示在底部。
        root.addWidget(self.list_frame,1); self.summary = label("","muted"); root.addWidget(self.summary)
        # 2026-10-15：本次修改原因：首次加载前同步空列表的禁用状态和页码输入宽度，避免分页按钮短暂可用。
        self._sync_pager()

    def add_library(self):
        title,ok = QInputDialog.getText(self,"新增原料类目","类目名称")
        # if ok and title.strip(): self.store.add_library(title.strip()); self.refresh()
        # 2026-10-15：本次修改原因：重名或写入失败留在当前页面，并在成功后选中新类目。
        if ok and title.strip():
            try:
                key = self.store.add_library(title.strip()); self.refresh()
                self.library.setCurrentIndex(self.library.findData(key))
            except (ValueError,sqlite3.Error) as error: QMessageBox.warning(self,"无法新增类目",str(error))

    # def add_item(self):
    #     if MaterialDialog(self.store,self.assets,parent=self,ai_service=self.ai_service,ai_hub=self.ai_hub,library_category=self.library.currentData() or "beads").exec() == QDialog.DialogCode.Accepted: self.refresh()
    # 2026-10-15：本次修改原因：菜单类型仅决定新原料默认类型，列表始终展示当前类目中的全部原料。
    def add_item(self, material_category="bead"):
        if MaterialDialog(self.store,self.assets,parent=self,ai_service=self.ai_service,ai_hub=self.ai_hub,library_category=self.library.currentData() or "beads",material_category=material_category).exec() == QDialog.DialogCode.Accepted: self.refresh()

    # 2026-10-15：本次修改原因：撤下编辑选中原料按钮，原料通过双击列表进入编辑，旧入口代码注释保留。
    # def edit_current(self):
    #     row = self.table.currentRow()
    #     if 0 <= row < len(self._rows): self.edit_item(self._rows[row].id)

    def edit_item(self,item_id):
        item = self.store.material(item_id)
        if item and MaterialDialog(self.store,self.assets,item,self,ai_service=self.ai_service,ai_hub=self.ai_hub).exec() == QDialog.DialogCode.Accepted: self.refresh()

    # 2026-10-15：本次修改原因：原料类型选择不立即改变列表，只在用户点击刷新后应用；新类型由查询状态检测并回到第一页。
    def _apply_material_filter(self):
        self._applied_material_category = self.material_filter.currentData() or ""
        self.refresh()

    # 2026-10-15：本次修改原因：翻页沿用已应用的类型、搜索条件和每页条数，首页与末页不能越界。
    def _change_page(self, step):
        page = self._page + step
        if 1 <= page <= self._page_count:
            self._page = page
            self.refresh()

    # 2026-10-15：本次修改原因：页码输入使用现有文字输入框样式，支持按钮或回车跳转，并阻止空值及越界页码。
    def _jump_page(self):
        if not self._total or not self.page_input.hasAcceptableInput():
            self.page_input.setFocus()
            self.page_input.selectAll()
            return
        self._page = int(self.page_input.text())
        self.refresh()

    # 2026-10-15：本次修改原因：总数、页数和按钮状态始终对应已应用筛选，空结果禁用翻页和跳转，长页码按文字宽度展示。
    def _sync_pager(self):
        self.total_label.setText(f"共 {self._total} 条")
        self.page_count_label.setText(f"第 {self._page if self._total else 0} / {self._page_count} 页")
        self.previous_page_button.setEnabled(self._total > 0 and self._page > 1)
        self.next_page_button.setEnabled(self._page < self._page_count)
        self.page_input.validator().setTop(max(1, self._page_count))
        self.page_input.setFixedWidth(max(64, self.page_input.fontMetrics().horizontalAdvance(str(max(1, self._page_count))) + 32))
        self.page_input.setText(str(self._page) if self._total else "")
        self.page_input.setEnabled(self._total > 0)
        self.jump_page_button.setEnabled(self._total > 0)

    def refresh(self,*_args):
        selected = self._rows[self.table.currentRow()].id if 0 <= self.table.currentRow() < len(self._rows) else ""
        category = self.library.currentData() or "beads"; self.library.blockSignals(True); self.library.clear()
        for key,title in self.store.libraries(): self.library.addItem(title,key)
        self.library.setCurrentIndex(max(0,self.library.findData(category))); self.library.blockSignals(False)
        # self._rows = self.store.list_materials(self.search.text().strip(),self.category.currentData() or "",self.library.currentData() or "beads")
        # 2026-10-15：本次修改原因：原料类型选择移入新增菜单，不再作为列表筛选状态。
        # self._rows = self.store.list_materials(search=self.search.text().strip(),library_category=self.library.currentData() or "beads")
        # 2026-10-15：本次修改原因：筛选或每页条数变更时回到第一页，普通刷新保留当前页，数据库只读取当前页原料。
        search = self.search.text().strip()
        library = self.library.currentData() or "beads"
        page_size = self.page_size.currentData()
        query_key = (search, self._applied_material_category, library, page_size)
        if query_key != self._query_key:
            self._page = 1
            selected = ""
        self._rows, self._total, self._page = self.store.page_materials(
            search=search, category=self._applied_material_category, library_category=library,
            page=self._page, page_size=page_size,
        )
        self._query_key = query_key
        self._page_count = (self._total + page_size - 1) // page_size
        self.table.clearContents()
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.setRowCount(len(self._rows))
        # 2026-10-15：本次修改原因：分页后的行号按筛选结果连续编号，避免每页重新从 1 开始造成位置误解。
        offset = (self._page - 1) * page_size
        self.table.setVerticalHeaderLabels([str(offset + row + 1) for row in range(len(self._rows))])
        self.table.verticalHeader().setMinimumWidth(max(38, self.table.fontMetrics().horizontalAdvance(str(offset + len(self._rows))) + 16))
        for row,item in enumerate(self._rows):
            pending = [FACT_FIELDS.get(key,key)+"："+STATUS_LABELS.get(state,state) for key,state in item.fact_statuses.items() if state != "confirmed" and (item.facts.get(key) or item.observations.get(key))]
            # values = [item.code, item.name+"\n"+MATERIAL_CATEGORY_LABELS.get(item.category,item.category), "；".join(FACT_FIELDS.get(key,key)+"："+value for key,value in item.facts.items()), "；".join(pending) or "无未决资料",str(len(item.images)),f"{item.available_quantity} / {item.quantity}" if item.track_inventory else "未记录库存",f"{item.unit_cost} {item.currency}" if item.unit_cost else "未知",f"v{item.revision}"]
            # 2026-10-15：本次修改原因：每条原料以唯一编号和类型展示，避免空名称造成多余换行。
            values = [item.code, MATERIAL_CATEGORY_LABELS.get(item.category,item.category), "；".join(FACT_FIELDS.get(key,key)+"："+value for key,value in item.facts.items()), "；".join(pending) or "无未决资料",str(len(item.images)),f"{item.available_quantity} / {item.quantity}" if item.track_inventory else "未记录库存",f"{item.unit_cost} {item.currency}" if item.unit_cost else "未知",f"v{item.revision}"]
            for col,value in enumerate(values):
                cell = QTableWidgetItem(value); cell.setToolTip(value); self.table.setItem(row,col,cell)
            if item.id == selected: self.table.selectRow(row)
        # self.summary.setText(f"当前 {len(self._rows)} 条原料 · 双击编辑资料和查看白底图")
        # 2026-10-15：本次修改原因：底部说明显示当前页覆盖的结果范围，翻页后回到列表顶部并同步分页按钮。
        self.table.scrollToTop()
        self._sync_pager()
        self.summary.setText(
            f"本页显示第 {offset + 1}–{offset + len(self._rows)} 条 · 双击编辑资料和查看白底图"
            if self._rows else "当前筛选下没有原料"
        )
