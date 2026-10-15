# 2026-10-15：本次修改原因：ERP 汇总承接原完整商品列表，采集箱加工提供同步及编辑入口，避免维护两套回传表格。
from __future__ import annotations

from PySide6.QtWidgets import QComboBox,QHBoxLayout,QVBoxLayout,QWidget

from .widgets import button,label


class ErpReturnPage(QWidget):
    def __init__(self,owner):
        super().__init__(owner)
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        # 2026-10-15：本次修改原因：复用原有委托、筛选、审核、账号回执和批量回传的完整实现。
        layout.addWidget(owner._products_page())


class CaptureProcessingPage(QWidget):
    def __init__(self,owner):
        super().__init__(owner); self.owner = owner
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(12)
        # title = QHBoxLayout(); title.addWidget(label("采集箱加工","pageTitle")); title.addStretch()
        # 2026-10-15：本次修改原因：侧栏已显示模块名称，页面直接从采集操作开始，去掉重复页标题。
        title = QHBoxLayout(); title.addStretch()
        self.sync_button = button("同步妙手采集箱",owner.import_miaoshou,primary=True); title.addWidget(self.sync_button)
        self.import_button = button("导入插件采集文件",owner.import_files); title.addWidget(self.import_button)
        root.addLayout(title)
        root.addWidget(label("同步采集箱商品后，选择商品进入原有手动 / AI 编辑流程。商品列表、审核与回传统一在“回传 ERP”管理。","hint",True))
        chooser = QHBoxLayout(); self.products = QComboBox(); self.products.setMinimumWidth(0); chooser.addWidget(self.products,1)
        # 2026-10-15：本次修改原因：长商品标题不撑宽整个页面，完整资料在下方展示。
        self.products.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.products.setMinimumContentsLength(20)
        # self.edit_button = button("进入商品加工",self.edit_current,primary=True); chooser.addWidget(self.edit_button); chooser.addWidget(button("刷新",self.refresh)); root.addLayout(chooser)
        # 2026-10-15：本次修改原因：拆分模块后，采集箱入口明确编辑当前所选商品。
        self.edit_button = button("编辑所选商品",self.edit_current,primary=True); chooser.addWidget(self.edit_button); chooser.addWidget(button("刷新",self.refresh)); root.addLayout(chooser)
        self.details = label("暂无采集商品，请先同步采集箱。","muted",True); root.addWidget(self.details)
        self.products.currentIndexChanged.connect(self.show_details)
        root.addWidget(button("查看统一商品列表",lambda:owner.navigate(owner.PAGE_ERP_RETURN)))
        root.addStretch()

    def refresh(self):
        previous = self.products.currentData(); self.products.blockSignals(True); self.products.clear()
        for product in self.owner.repository.products():
            if product.acquisition_route in {"miaoshou","plugin"}:
                self.products.addItem(f"{product.main_code or product.source_id} · {product.title or '待完善标题'} · {product.status}",product.id)
        self.products.setCurrentIndex(max(0,self.products.findData(previous))); self.products.blockSignals(False)
        plugin = self.owner.settings.capture_route == "plugin"
        self.sync_button.setVisible(not plugin); self.import_button.setVisible(plugin)
        self.edit_button.setEnabled(self.products.count() > 0); self.show_details()

    def show_details(self,*_args):
        product = self.owner.repository.product(self.products.currentData()) if self.products.currentData() else None
        self.products.setToolTip(self.products.currentText())
        self.details.setText(f"{product.title}\n{product.acquisition_label} · 主图 {len(product.images)} 张 · SKU {len(product.skus)} 个\n"+"；".join(product.review_issues()) if product else "暂无采集商品，请先同步采集箱。")

    def select_product(self,product_id):
        index = self.products.findData(product_id)
        if index >= 0: self.products.setCurrentIndex(index)

    def edit_current(self):
        product_id = self.products.currentData()
        if product_id: self.owner.focus_product(product_id,edit=True)
