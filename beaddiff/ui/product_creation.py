# 2026-10-11：本次修改原因：白底图路线先建真实商品草稿，用户补充实物事实，随后复用采集商品编辑和 AI 模块。
from pathlib import Path
# 2026-10-11：本次修改原因：数据库写入失败在建档窗口提供可读提示。
import sqlite3

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QListWidget,
    QMessageBox, QVBoxLayout,
)

from ..assets import AssetStore
from ..models import Product, SKU
from ..storage import Repository
from .widgets import button, label


# class ProductCreation(QDialog):
#     def __init__(self, repository: Repository, assets: AssetStore, parent=None):
#         super().__init__(parent)
#         self.repository, self.assets = repository, assets
#         self.created_product: Product | None = None
#         self.paths: list[Path] = []
#         self.setWindowTitle("上传白底图 · 新建商品")
#         self.resize(720, 740)
#         layout = QVBoxLayout(self)
#         layout.addWidget(label("上传白底图创建商品", "sectionTitle"))
#         layout.addWidget(label("先上传本店实物图片并补充已确认的信息。标题和描述可以稍后通过 AI 生成。", "hint", True))
#         upload = QHBoxLayout()
#         upload.addWidget(button("选择白底图 / 实物图", self.select_files, primary=True))
#         upload.addWidget(button("移除选中", self.remove_selected))
#         upload.addStretch()
#         layout.addLayout(upload)
#         self.files = QListWidget()
#         self.files.setMaximumHeight(155)
#         layout.addWidget(self.files)
#         form = QFormLayout()
#         self.fields = {}
#         for key, caption in (("title", "产品标题（可稍后生成）"), ("category", "产品类目"),
#                              ("material", "实际材质"), ("color", "实际颜色"), ("length", "实际尺寸 / 长度"),
#                              ("quantity", "实际数量"), ("package", "实际包装")):
#             editor = QLineEdit()
#             editor.setPlaceholderText("不清楚可留空，后续按实物补充")
#             self.fields[key] = editor
#             form.addRow(caption, editor)
#         self.currency = QComboBox()
#         self.currency.addItems(["", "USD", "CNY", "EUR", "GBP", "JPY"])
#         form.addRow("售价币种（可稍后填）", self.currency)
#         layout.addLayout(form)
#         layout.addWidget(label("默认创建一个待完善 SKU。售价、库存、规格及包装信息可在编辑页补充，不影响先生成商品内容。", "hint", True))
#         layout.addStretch()
#         footer = QHBoxLayout()
#         footer.addStretch()
#         footer.addWidget(button("取消", self.reject))
#         footer.addWidget(button("创建并编辑", self.create, primary=True))
#         layout.addLayout(footer)

#     def select_files(self):
#         paths, _ = QFileDialog.getOpenFileNames(self, "选择白底图 / 实物图", "", "图片 (*.png *.jpg *.jpeg *.webp *.gif)")
#         self.paths = list(dict.fromkeys(self.paths + [Path(value) for value in paths]))
#         self.files.clear()
#         self.files.addItems([str(path) for path in self.paths])

#     def remove_selected(self):
#         row = self.files.currentRow()
#         if row >= 0:
#             self.paths.pop(row)
#             self.files.takeItem(row)

#     def create(self):
#         if not self.paths:
#             QMessageBox.information(self, "请选择图片", "上传至少一张当前商品的实物图。")
#             return
#         try:
#             images = [self.assets.import_file(path) for path in self.paths]
#             attributes = {caption: self.fields[key].text().strip() for key, caption in
#                 (("material", "材质"), ("color", "颜色"), ("length", "尺寸 / 长度"),
#                  ("quantity", "数量"), ("package", "包装")) if self.fields[key].text().strip()}
#             product = Product(source="upload", title=self.fields["title"].text().strip(),
#                 category=self.fields["category"].text().strip(), attributes=attributes,
#                 currency=self.currency.currentText(), images=[image.uri for image in images],
#                 image_sizes={image.uri: f"{image.width} × {image.height}" for image in images},
#                 skus=[SKU(image=images[0].uri)], warnings=["自拍商品：请按实物完善规格、售价和包装信息。"])
#             self.created_product = self.repository.create_product(product)
#             self.accept()
#         # except (ValueError, OSError) as error:
#         # 2026-10-11：本次修改原因：建档失败不关闭窗口，保留用户填写内容。
#         except (ValueError, OSError, sqlite3.Error) as error:
#             QMessageBox.warning(self, "未能创建商品", str(error))
# 2026-10-14：本次修改原因：原白底图单草稿实现注释保留，采用完整 Listing 创建流程。
# 2026-10-14：本次修改原因：上传白底图展示类目和建档预设；创建后自动整套生成，也保留只建草稿入口。
from dataclasses import replace
from PySide6.QtWidgets import QScrollArea, QWidget
from ..listing import ListingDefaults, ListingDefaultsStore, uploaded_product
from ..ai.product_plan import active_model
from .widgets import AutoHeightTextEdit

class ProductCreation(QDialog):
    def __init__(self, repository, assets, parent=None, *, defaults_store=None, ai_service=None):
        super().__init__(parent)
        self.repository, self.assets, self.ai_service = repository, assets, ai_service
        self.defaults_store = defaults_store or ListingDefaultsStore(assets.root.parent)
        self.created_product, self.generate_listing = None, False
        self.paths = []
        try:
            self.defaults = self.defaults_store.get()
            self.config_error = ''
        except (ValueError, OSError) as error:
            self.defaults, self.config_error = ListingDefaults(), str(error)
        self.setWindowTitle('上传白底图 · 生成完整 Listing')
        self.resize(760, 720)
        root = QVBoxLayout(self)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(label('上传白底图创建商品', 'sectionTitle'))
        layout.addWidget(label('确认类目和实物事实后，自动生成文案、主图、详情图及 SKU 图。完成后选择满意版本并应用；不满意可修改 Prompt 重做。', 'hint', True))
        upload = QHBoxLayout()
        upload.addWidget(button('选择白底图 / 实物图', self.select_files, primary=True))
        upload.addWidget(button('移除选中', self.remove_selected))
        upload.addStretch()
        layout.addLayout(upload)
        self.files = QListWidget()
        self.files.setMaximumHeight(140)
        layout.addWidget(self.files)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.fields = {}
        for key, caption in (('title', '标题（留空自动生成）'), ('category', '产品类目'), ('material', '实际材质'),
                             ('color', '实际颜色'), ('length', '实际尺寸 / 长度'), ('quantity', '实际数量'), ('package', '实际包装')):
            control = QLineEdit(self.defaults.category if key == 'category' else '')
            control.setPlaceholderText('仅填写已确认事实；类目必填，其余可留空')
            self.fields[key] = control
            form.addRow(caption, control)
        self.currency = QComboBox()
        self.currency.setEditable(True)
        self.currency.addItems(['CNY', 'USD', 'EUR', 'GBP', 'JPY'])
        self.currency.setCurrentText(self.defaults.currency)
        form.addRow('建档币种', self.currency)
        self.prompt = AutoHeightTextEdit(self.defaults.instruction)
        form.addRow('本次整套生成要求', self.prompt)
        layout.addLayout(form)
        values = self.defaults
        layout.addWidget(label(f'建档预设：SKU 售价 {values.price}，独立货源价 {values.supply_price}，库存 {values.stock}，'
            f'重量 {values.weight} KG，包装 {values.dimensions} CM，规格1“{values.spec1}”。主编号与 SKU 编号自动生成。'
            '这些是可修改预设；请在销售属性、物流信息和货源链接中核对实际值。', 'warning', True))
        layout.addWidget(label('预设来自设置 → 白底图 Listing；当前文本、图片模型来自设置 → AI 模型。'
            '白底图首次回传选择设置 → 妙手 ERP → 新增；本机采用图在同步时自动上传设置中的图床。', 'hint', True))
        if self.config_error:
            layout.addWidget(label(self.config_error, 'warning', True))
        layout.addStretch()
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setWidget(body)
        root.addWidget(scroller, 1)
        footer = QHBoxLayout()
        footer.addWidget(button('取消', self.reject))
        footer.addStretch()
        footer.addWidget(button('仅创建草稿', lambda _=False: self.create(generate=False)))
        footer.addWidget(button('创建并生成完整 Listing', lambda _=False: self.create(generate=True), primary=True))
        root.addLayout(footer)

    def select_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择白底图 / 实物图', '', '图片 (*.png *.jpg *.jpeg *.webp *.gif)')
        self.paths = list(dict.fromkeys(self.paths + [Path(value) for value in paths]))
        self.files.clear()
        self.files.addItems([str(path) for path in self.paths])

    def remove_selected(self):
        row = self.files.currentRow()
        if row >= 0:
            self.paths.pop(row)
            self.files.takeItem(row)

    def create(self, *, generate=True):
        try:
            if self.config_error:
                raise ValueError(self.config_error)
            if not self.paths:
                raise ValueError('上传白底图窗口 → 选择白底图 / 实物图：至少添加一张当前商品实物图。')
            if len(self.paths) > 15:
                raise ValueError('上传白底图窗口 → 图片列表：主图素材最多 15 张，请先移除多余图片。')
            defaults = replace(self.defaults, category=self.fields['category'].text().strip(),
                currency=self.currency.currentText().strip().upper(), instruction=self.prompt.toPlainText().strip())
            errors = defaults.problems(require_category=True)
            if errors:
                raise ValueError('\n'.join(errors))
            if generate:
                if self.ai_service is None:
                    raise ValueError('设置 → AI 模型：保存文本与图片模型，并分别点击“设为当前”；文本模型须开启图片理解。')
                active_model(self.ai_service, 'text', True)
                # active_model(self.ai_service, 'image')
                # 2026-10-14：本次修改原因：整套生图必需实物参考图，上传前检查图片模型对应能力。
                active_model(self.ai_service, 'image', True)
            # images = [self.assets.import_file(path) for path in self.paths]
            # 2026-10-14：本次修改原因：上传入口统一转换 Path，兼容文件选择结果和恢复的字符串路径。
            images = [self.assets.import_file(Path(path)) for path in self.paths]
            product = uploaded_product(images, {key: control.text() for key, control in self.fields.items()}, defaults)
            self.created_product = self.repository.create_product(product)
            self.defaults, self.generate_listing = defaults, generate
            self.accept()
        except (ValueError, OSError, sqlite3.Error) as error:
            # QMessageBox.warning(self, '未能创建商品', str(error))
            # 2026-10-14：本次修改原因：建档前检查失败提供设置与字段的具体处理位置。
            from ..validation_guidance import explain_errors
            QMessageBox.warning(self, '未能创建商品', explain_errors(str(error)))
