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


class ProductCreation(QDialog):
    def __init__(self, repository: Repository, assets: AssetStore, parent=None):
        super().__init__(parent)
        self.repository, self.assets = repository, assets
        self.created_product: Product | None = None
        self.paths: list[Path] = []
        self.setWindowTitle("上传白底图 · 新建商品")
        self.resize(720, 740)
        layout = QVBoxLayout(self)
        layout.addWidget(label("上传白底图创建商品", "sectionTitle"))
        layout.addWidget(label("先上传本店实物图片并补充已确认的信息。标题和描述可以稍后通过 AI 生成。", "hint", True))
        upload = QHBoxLayout()
        upload.addWidget(button("选择白底图 / 实物图", self.select_files, primary=True))
        upload.addWidget(button("移除选中", self.remove_selected))
        upload.addStretch()
        layout.addLayout(upload)
        self.files = QListWidget()
        self.files.setMaximumHeight(155)
        layout.addWidget(self.files)
        form = QFormLayout()
        self.fields = {}
        for key, caption in (("title", "产品标题（可稍后生成）"), ("category", "产品类目"),
                             ("material", "实际材质"), ("color", "实际颜色"), ("length", "实际尺寸 / 长度"),
                             ("quantity", "实际数量"), ("package", "实际包装")):
            editor = QLineEdit()
            editor.setPlaceholderText("不清楚可留空，后续按实物补充")
            self.fields[key] = editor
            form.addRow(caption, editor)
        self.currency = QComboBox()
        self.currency.addItems(["", "USD", "CNY", "EUR", "GBP", "JPY"])
        form.addRow("售价币种（可稍后填）", self.currency)
        layout.addLayout(form)
        layout.addWidget(label("默认创建一个待完善 SKU。售价、库存、规格及包装信息可在编辑页补充，不影响先生成商品内容。", "hint", True))
        layout.addStretch()
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(button("取消", self.reject))
        footer.addWidget(button("创建并编辑", self.create, primary=True))
        layout.addLayout(footer)

    def select_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择白底图 / 实物图", "", "图片 (*.png *.jpg *.jpeg *.webp *.gif)")
        self.paths = list(dict.fromkeys(self.paths + [Path(value) for value in paths]))
        self.files.clear()
        self.files.addItems([str(path) for path in self.paths])

    def remove_selected(self):
        row = self.files.currentRow()
        if row >= 0:
            self.paths.pop(row)
            self.files.takeItem(row)

    def create(self):
        if not self.paths:
            QMessageBox.information(self, "请选择图片", "上传至少一张当前商品的实物图。")
            return
        try:
            images = [self.assets.import_file(path) for path in self.paths]
            attributes = {caption: self.fields[key].text().strip() for key, caption in
                (("material", "材质"), ("color", "颜色"), ("length", "尺寸 / 长度"),
                 ("quantity", "数量"), ("package", "包装")) if self.fields[key].text().strip()}
            product = Product(source="upload", title=self.fields["title"].text().strip(),
                category=self.fields["category"].text().strip(), attributes=attributes,
                currency=self.currency.currentText(), images=[image.uri for image in images],
                image_sizes={image.uri: f"{image.width} × {image.height}" for image in images},
                skus=[SKU(image=images[0].uri)], warnings=["自拍商品：请按实物完善规格、售价和包装信息。"])
            self.created_product = self.repository.create_product(product)
            self.accept()
        # except (ValueError, OSError) as error:
        # 2026-10-11：本次修改原因：建档失败不关闭窗口，保留用户填写内容。
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "未能创建商品", str(error))
