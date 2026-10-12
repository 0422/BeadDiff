# 2026-10-12：本次修改原因：为电商操作提供查询、详情核对及勾选批量导入入口，读取 ERP 数据后复用现有编辑器和 AI。
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox,
    QPlainTextEdit, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..miaoshou import MiaoshouAdapter, detail_id
from ..miaoshou_import import MiaoshouImportService
from ..storage import Repository
from .widgets import button, label


class MiaoshouImportDialog(QDialog):
    def __init__(self, repository: Repository, adapter: MiaoshouAdapter, runner, parent=None):
        super().__init__(parent)
        self.client = adapter.client()
        self.service = MiaoshouImportService(repository, adapter)
        self.runner = runner
        self.last_product_id = ""
        self.setWindowTitle("从妙手公共采集箱导入")
        self.resize(1020, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.addWidget(label("导入妙手采集箱商品", "pageTitle"))
        layout.addWidget(label("查询并勾选商品，读取详情后导入本机编辑。重复导入保留本机修改；更新原商品请在设置 → 妙手回传选择“更新”。", "hint", True))
        search = QHBoxLayout()
        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText("货源商品 ID 关键词；留空查询全部公共采集箱商品")
        self.page = QSpinBox()
        self.page.setRange(1, 100000)
        self.page.setPrefix("第 ")
        self.page.setSuffix(" 页")
        search.addWidget(self.keyword, 1)
        search.addWidget(self.page)
        search.addWidget(button("查询采集箱", self.search, primary=True))
        layout.addLayout(search)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["选择", "妙手商品 ID", "产品标题", "平台 / 站点 / 货源 ID", "货源链接"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 48)
        self.table.verticalHeader().hide()
        self.table.itemSelectionChanged.connect(self.select_row)
        self.table.itemDoubleClicked.connect(lambda _item: self.inspect())
        layout.addWidget(self.table, 1)
        direct = QHBoxLayout()
        self.target = QLineEdit()
        self.target.setPlaceholderText("可直接填写公共采集箱商品 ID（不是 Temu 等平台的商品 ID）")
        direct.addWidget(self.target, 1)
        direct.addWidget(button("查看详情", self.inspect))
        direct.addWidget(button("导入此商品", self.import_current))
        layout.addLayout(direct)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(210)
        self.details.setPlaceholderText("选中商品后查看完整 API 详情；导入将保存全部字段。")
        layout.addWidget(self.details)
        self.status = label("尚未查询。导入只读取妙手数据，回传需在商品库另行操作。", "hint", True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addWidget(button("勾选本页", lambda: self.check_page(True)))
        actions.addWidget(button("取消勾选", lambda: self.check_page(False)))
        actions.addStretch()
        actions.addWidget(button("返回商品库", self.reject))
        actions.addWidget(button("导入勾选商品", self.import_selected, primary=True))
        layout.addLayout(actions)

    def _is_busy(self) -> bool:
        return bool(getattr(self.parent(), "_tasks", set()))

    def reject(self) -> None:
        if not self._is_busy():
            super().reject()

    def check_page(self, checked: bool) -> None:
        if not self._is_busy():
            for row in range(self.table.rowCount()):
                self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def select_row(self) -> None:
        item = self.table.item(self.table.currentRow(), 1)
        if item:
            self.target.setText(item.text())
            self.details.clear()

    def search(self) -> None:
        if self._is_busy():
            return
        keyword, page = self.keyword.text().strip(), self.page.value()

        def done(result: dict) -> None:
            rows = result["detailList"]
            self.table.setRowCount(0)
            for value in rows:
                if not isinstance(value, dict):
                    continue
                row = self.table.rowCount()
                self.table.insertRow(row)
                check = QTableWidgetItem()
                check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                check.setCheckState(Qt.CheckState.Unchecked)
                self.table.setItem(row, 0, check)
                sources = [item for item in (value.get("sourceList") or []) if isinstance(item, dict)]
                values = [str(value.get("commonCollectBoxDetailId", "")), str(value.get("title") or ""),
                          "\n".join(f"{item.get('source', '')} / {item.get('sourceSite', '')} / {item.get('sourceItemId', '')}" for item in sources),
                          "\n".join(str(item.get("sourceItemUrl") or "") for item in sources)]
                for column, text in enumerate(values, 1):
                    item = QTableWidgetItem(text)
                    item.setToolTip(text)
                    self.table.setItem(row, column, item)
            self.status.setText(f"第 {page} 页 · 本页 {self.table.rowCount()} 条 · 总计 {result.get('total', '未知')} 条；每页 100 条。勾选后导入。")
        self.runner(lambda: self.client.list_products(keyword, page, 100), done)

    def inspect(self) -> None:
        if self._is_busy():
            return
        try:
            target = detail_id(self.target.text())
        except ValueError as error:
            QMessageBox.warning(self, "请选择商品", str(error))
            return

        def done(result: dict) -> None:
            if str(target) != self.target.text().strip():
                return
            self.details.setPlainText(json.dumps(self.client._safe(result), ensure_ascii=False, indent=2))
            self.status.setText("详情已读取。导入时会再次读取最新数据，商品价格按接口人民币单位保存。")
        self.runner(lambda: self.client.detail(target), done)

    def import_current(self) -> None:
        self._import([self.target.text().strip()])

    def import_selected(self) -> None:
        targets = [self.table.item(row, 1).text() for row in range(self.table.rowCount())
                   if self.table.item(row, 0).checkState() == Qt.CheckState.Checked]
        self._import(targets)

    def _import(self, targets: list[str]) -> None:
        if self._is_busy():
            return
        try:
            if not targets:
                raise ValueError("请先勾选要导入的商品。")
            targets = [str(detail_id(value)) for value in targets]
        except ValueError as error:
            QMessageBox.warning(self, "请选择商品", str(error))
            return

        def done(result: dict) -> None:
            rows = result["results"]
            counts = {state: sum(row["state"] == state for row in rows) for state in ("imported", "existing", "failed")}
            accepted = [row for row in rows if row.get("product_id")]
            if accepted:
                self.last_product_id = accepted[-1]["product_id"]
            message = f"新增导入 {counts['imported']} 个 · 本机已有 {counts['existing']} 个 · 失败 {counts['failed']} 个。"
            message += "\n已有商品保留本机内容。返回商品库可编辑、使用 AI、保存审核后回传。"
            errors = [f"妙手 ID {row['target_id']}：{row['message']}" for row in rows if row["state"] == "failed"]
            if errors:
                message += "\n\n" + "\n".join(errors[:8])
            self.status.setText(message)
            QMessageBox.information(self, "采集箱导入结果", message)
        self.runner(lambda: self.service.import_products(self.client, targets), done)
