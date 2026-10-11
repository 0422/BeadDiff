# 2026-10-11：本次修改原因：通过列表/详情查询及人工确认绑定原商品，禁止把平台商品 ID 当作 ERP 商品 ID。
from __future__ import annotations

# from PySide6.QtCore import Qt
# 2026-10-11：本次修改原因：对话框不需要 Qt 常量，保留旧导入为注释。
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox, QPlainTextEdit, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout

from ..miaoshou import MiaoshouAdapter, detail_id
from ..miaoshou_mapping import match_sku_links
from ..models import Product
from ..storage import Repository
from .widgets import button, label


class MiaoshouBindingDialog(QDialog):
    def __init__(self, repository: Repository, product: Product, adapter: MiaoshouAdapter, runner, parent=None):
        super().__init__(parent)
        self.repository, self.product, self.adapter, self.runner = repository, product, adapter, runner
        self.client = adapter.client()
        self.origin = repository.erp_origin_product(product.id) or product
        self.verified = None
        self.links = {}
        self.setWindowTitle("关联妙手公共采集箱原商品")
        self.resize(940, 720)
        layout = QVBoxLayout(self)
        layout.addWidget(label("确认要更新哪一条妙手商品", "sectionTitle"))
        layout.addWidget(label(f"本机商品：{product.title}\n来源：{product.source} / {product.site} / {product.source_id}\n{product.source_url}", "hint", True))
        layout.addWidget(label("列表查询是关键词检索，结果可能包括相似 ID。请核对标题、来源链接和站点；点击详情查看后才能关联。关联只保存在本机。", "hint", True))
        search = QHBoxLayout()
        self.keyword = QLineEdit(product.source_id)
        self.keyword.setPlaceholderText("来源平台商品 ID 关键词")
        self.page = QSpinBox()
        self.page.setRange(1, 100000)
        self.page.setPrefix("第 ")
        self.page.setSuffix(" 页")
        self.search_button = button("查询采集箱", self.search)
        search.addWidget(self.keyword, 1)
        search.addWidget(self.page)
        search.addWidget(self.search_button)
        layout.addLayout(search)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["妙手商品 ID", "标题", "货源 ID / 平台 / 站点", "货源链接"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.itemSelectionChanged.connect(self.select_row)
        self.table.itemDoubleClicked.connect(lambda _item: self.inspect())
        layout.addWidget(self.table, 1)
        direct = QHBoxLayout()
        self.target = QLineEdit(product.erp_original_id)
        self.target.setPlaceholderText("也可直接填写已知的公共采集箱商品 ID")
        self.target.textChanged.connect(self.invalidate)
        self.inspect_button = button("读取并核对详情", self.inspect)
        direct.addWidget(self.target, 1)
        direct.addWidget(self.inspect_button)
        layout.addLayout(direct)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(190)
        layout.addWidget(self.details)
        self.status = label("尚未查询；如采集任务刚完成，可稍后查询。", "hint", True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("关闭", self.reject))
        self.bind_button = button("确认关联此商品", self.bind, primary=True)
        self.bind_button.setEnabled(False)
        actions.addWidget(self.bind_button)
        layout.addLayout(actions)

    def _is_busy(self) -> bool:
        return bool(getattr(self.parent(), "_tasks", set()))

    def reject(self) -> None:
        if not self._is_busy():
            super().reject()

    def invalidate(self, *_args) -> None:
        self.verified = None
        self.links = {}
        self.bind_button.setEnabled(False)
        self.details.clear()

    def select_row(self) -> None:
        item = self.table.item(self.table.currentRow(), 0)
        if item:
            self.target.setText(item.text())

    def search(self) -> None:
        if self._is_busy():
            return
        keyword, page = self.keyword.text().strip(), self.page.value()
        self.invalidate()

        def done(result: dict) -> None:
            rows = result["detailList"]
            self.table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                sources = row.get("sourceList") or []
                values = [str(row.get("commonCollectBoxDetailId", "")), str(row.get("title", "")),
                          "\n".join(f"{source.get('sourceItemId', '')} / {source.get('source', '')} / {source.get('sourceSite', '')}" for source in sources),
                          "\n".join(str(source.get("sourceItemUrl", "")) for source in sources)]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    self.table.setItem(index, column, item)
            self.status.setText(f"本页 {len(rows)} 条，检索总计 {result.get('total', '未知')} 条；每页 100 条。请人工核对来源并读取详情。")
        self.runner(lambda: self.client.list_products(keyword, page, 100), done)

    def inspect(self) -> None:
        if self._is_busy():
            return
        try:
            target = detail_id(self.target.text())
        except ValueError as error:
            QMessageBox.warning(self, "商品 ID 无效", str(error))
            return
        self.invalidate()

        def done(result: dict) -> None:
            remote = result["editCommonCollectBoxDetail"]
            # 2026-10-11：本次修改原因：查询期间输入框变更 ID 后，不能用旧查询结果启用新目标的关联按钮。
            if str(target) != self.target.text().strip():
                self.status.setText("商品 ID 在查询期间已改变，请重新读取当前目标详情。")
                return
            self.verified = result
            self.links = match_sku_links(self.product, self.origin, remote)
            sources = remote.get("sourceList") or []
            lines = [f"妙手 ID：{target}", f"标题：{remote.get('title', '')}", f"主编号：{remote.get('itemNum', '')}",
                     f"远端 SKU：{len(remote.get('skuMap') or {})}；本机可靠匹配：{len(self.links)}/{len(self.product.skus)}"]
            lines.extend(f"货源：{row.get('sourceItemId', '')} / {row.get('source', '')} / {row.get('sourceSite', '')}\n{row.get('sourceItemUrl', '')}" for row in sources)
            self.details.setPlainText("\n".join(lines))
            self.status.setText("请核对上方商品。未匹配的 SKU 可关联商品，但不能回传该 SKU 的修改。")
            self.bind_button.setEnabled(True)
        self.runner(lambda: self.client.detail(target), done)

    def bind(self) -> None:
        if self._is_busy() or not self.verified:
            return
        # if self.adapter.store.get().account_id != self.client.config.account_id:
        #     QMessageBox.warning(self, "账号已改变", "请关闭此窗口，以当前账号重新查询和关联。")
        #     return
        try:
            # 2026-10-11：本次修改原因：关联时配置加载失败也应展示原因，不让异常逃出 UI 槽。
            if self.adapter.store.get().account_id != self.client.config.account_id:
                raise ValueError("账号已改变，请关闭此窗口，以当前账号重新查询和关联。")
            target = str(detail_id(self.verified["editCommonCollectBoxDetail"]["commonCollectBoxDetailId"]))
            self.repository.bind_erp_original(self.product.id, target, self.client.config.account_id,
                                              self.links, self.product.revision)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "关联失败", str(error))
            return
        self.accept()
