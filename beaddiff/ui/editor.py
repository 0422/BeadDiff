# 2026-10-10：本次修改原因：提供电商商品分区编辑、规格定价和人工审核，所有修改保存为新版本。
from __future__ import annotations

from dataclasses import asdict

from PySide6.QtCore import Qt
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
from .widgets import ImagePreview, button, label


def text_editor(text: str = "", placeholder: str = "", height: int = 100) -> QPlainTextEdit:
    editor = QPlainTextEdit(text)
    editor.setPlaceholderText(placeholder)
    editor.setMinimumHeight(height)
    return editor


class ProductEditor(QDialog):
    def __init__(self, repository: Repository, product: Product, network: QNetworkAccessManager, parent=None):
        super().__init__(parent)
        self.repository, self.product, self.dirty = repository, product, False
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
        self._basic_tab()
        self._images_tab(network)
        self._sku_tab()
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
        self.dirty = False

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
        self.fields[key] = editor
        return editor

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
        form.addRow("自定义属性", self.attributes)
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
        form.addRow("产品视频", self._field("video", "视频链接或妙手支持的值"))
        form.addRow("产品证书", self._field("certificate", "按渠道要求填写"))
        form.addRow("尺寸图表", self._field("size_chart", "按渠道要求填写"))
        self.preview_first()

    def preview_first(self) -> None:
        urls = self.images.toPlainText().strip().splitlines()
        # self.preview.set_url(urls[0].strip() if urls else "")
        # 2026-10-10：本次修改原因：无效链接保留在表单里供修正，不交给图片下载器。
        url = urls[0].strip() if urls else ""
        self.preview.set_url(url if valid_url(url) else "")

    def _sku_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(label("采集价仅作参考，不自动转成售价；库存、重量未提供时请留空。", "warning", True))
        names = QHBoxLayout()
        names.addWidget(label("规格维度"))
        names.addWidget(self._field("spec1_name", "例如：颜色"))
        names.addWidget(self._field("spec2_name", "例如：尺寸"))
        names.addStretch()
        names.addWidget(button("统一填写售价", self.fill_prices))
        names.addWidget(button("添加 SKU", self.add_sku))
        names.addWidget(button("移除选中 SKU", self.remove_sku))
        layout.addLayout(names)
        self.sku_table = QTableWidget(0, 10)
        self.sku_table.setHorizontalHeaderLabels([
            "平台 SKU", "规格 1", "规格 2", "来源价格（原始）", "售价 *", "库存", "重量 KG", "尺寸 CM", "规格图片", "来源规格（只读）",
        ])
        self.sku_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sku_table.setAlternatingRowColors(True)
        self.sku_table.verticalHeader().setDefaultSectionSize(48)
        self.sku_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, width in enumerate([155, 100, 100, 130, 95, 85, 95, 110, 190, 180]):
            self.sku_table.setColumnWidth(col, width)
        self.sku_table.horizontalHeader().setStretchLastSection(True)
        for sku in self.product.skus:
            self.add_sku(sku)
        layout.addWidget(self.sku_table, 1)
        self.confirm_mapping = QCheckBox("已人工核对：将超过两个维度的来源规格明确合并到上面两列；原始材料仍保留")
        self.confirm_mapping.setVisible(any(len(sku.specs) > 2 for sku in self.product.skus))
        layout.addWidget(self.confirm_mapping)
        layout.addWidget(label("尺寸建议按“长*宽*高”填写，单位 CM。横向滚动可编辑规格图片链接。", "hint"))
        self.tabs.addTab(page, f"规格与定价（{len(self.product.skus)}）")

    def add_sku(self, sku: SKU | bool | None = None) -> None:
        if not isinstance(sku, SKU):
            sku = SKU()
        row = self.sku_table.rowCount()
        self.sku_table.insertRow(row)
        values = [sku.platform_sku, sku.spec1, sku.spec2, sku.source_price, sku.price, sku.stock,
                  sku.weight, sku.dimensions, sku.image, " / ".join(f"{key}: {value}" for key, value in sku.specs.items())]
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col in {3, 9}:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if col == 0:
                item.setData(Qt.ItemDataRole.UserRole, asdict(sku))
            self.sku_table.setItem(row, col, item)
        self.mark_dirty()

    def remove_sku(self) -> None:
        rows = sorted({item.row() for item in self.sku_table.selectedItems()}, reverse=True)
        for row in rows:
            self.sku_table.removeRow(row)
        if rows:
            self.mark_dirty()

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
        product.description = self.description.toPlainText().strip()
        product.images = list(dict.fromkeys(line.strip() for line in self.images.toPlainText().splitlines() if line.strip()))
        product.detail_images = list(dict.fromkeys(line.strip() for line in self.detail_images.toPlainText().splitlines() if line.strip()))
        product.attributes = {}
        for line in self.attributes.toPlainText().splitlines():
            if not line.strip():
                continue
            parts = line.replace("：", ":", 1).split(":", 1)
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                raise ValueError("自定义属性请使用“属性名:属性值”，每行一项。")
            key, value = (part.strip() for part in parts)
            if key in product.attributes or any(character in key + value for character in "；\n"):
                raise ValueError("属性名不能重复，属性中不能含分隔符“；”。")
            product.attributes[key] = value
        product.skus = []
        for row in range(self.sku_table.rowCount()):
            values = [self.sku_table.item(row, col).text().strip() for col in range(10)]
            metadata = self.sku_table.item(row, 0).data(Qt.ItemDataRole.UserRole) or {}
            specs = metadata.get("specs", {})
            if len(specs) <= 2 or self.confirm_mapping.isChecked():
                specs = {name: value for name, value in ((product.spec1_name, values[1]), (product.spec2_name, values[2])) if name and value}
            product.skus.append(SKU(platform_sku=values[0], spec1=values[1], spec2=values[2],
                                    source_price=values[3], price=values[4], currency=product.currency,
                                    stock=values[5], weight=values[6], dimensions=values[7], image=values[8], specs=specs))
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

    def save_product(self, approve: bool) -> None:
        try:
            self.repository.save_product(self.collect(), approve=approve)
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
