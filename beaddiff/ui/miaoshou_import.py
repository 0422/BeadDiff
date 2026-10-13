# 2026-10-12：本次修改原因：为电商操作提供查询、详情核对及勾选批量导入入口，读取 ERP 数据后复用现有编辑器和 AI。
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox,
    QPlainTextEdit, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
    # 2026-10-12：本次修改原因：同步提供导入状态筛选、分页大小、实际进度和内嵌结果卡片。
    QComboBox, QProgressBar, QPushButton,
)

from ..miaoshou import MiaoshouAdapter, detail_id
from ..miaoshou_import import MiaoshouImportService
from ..storage import Repository
from .widgets import button, label, card
from .table_support import configure_table
# 2026-10-13：本次修改原因：同步列表与完整详情使用记忆分栏，查询、并发数和去重逻辑保持原样。
from .layout_support import PersistentSplitter, Panel, save_splitters


class MiaoshouImportDialog(QDialog):
    def __init__(self, repository: Repository, adapter: MiaoshouAdapter, runner, parent=None):
        super().__init__(parent)
        self.client = adapter.client()
        self.service = MiaoshouImportService(repository, adapter)
        self.runner = runner
        self.last_product_id = ""
        # 2026-10-12：本次修改原因：查询结果与本机身份索引分离，切换筛选无需重复联网。
        self.repository = repository
        self.rows, self.import_index = [], {}
        # self.setWindowTitle("从妙手公共采集箱导入")
        # 2026-10-12：本次修改原因：同步入口明确查询、选择、导入三个步骤。
        self.setWindowTitle("同步妙手公共采集箱")
        self.resize(1020, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        # layout.addWidget(label("导入妙手采集箱商品", "pageTitle"))
        layout.addWidget(label("查询 → 勾选 → 导入本机", "pageTitle"))
        # layout.addWidget(label("查询并勾选商品，读取详情后导入本机编辑。重复导入保留本机修改；更新原商品请在设置 → 妙手回传选择“更新”。", "hint", True))
        # 2026-10-12：本次修改原因：同步结果进入采集记录，后续统一加工与接口回传。
        layout.addWidget(label("查询并勾选商品后导入本机。重复导入保留加工内容；每条结果写入采集记录。回传方式在设置 → 妙手 ERP 中选择。", "hint", True))
        search = QHBoxLayout()
        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText("货源商品 ID 关键词；留空查询全部公共采集箱商品")
        self.page = QSpinBox()
        self.page.setRange(1, 100000)
        self.page.setPrefix("第 ")
        self.page.setSuffix(" 页")
        search.addWidget(self.keyword, 1)
        search.addWidget(self.page)
        self.page_size = QComboBox()
        for size in (100, 200, 500):
            self.page_size.addItem(f"每页 {size} 条", size)
        search.addWidget(self.page_size)
        search.addWidget(button("查询采集箱", self.search, primary=True))
        layout.addLayout(search)
        # self.table = QTableWidget(0, 5)
        # self.table.setHorizontalHeaderLabels(["选择", "妙手商品 ID", "产品标题", "平台 / 站点 / 货源 ID", "货源链接"])
        # 2026-10-12：本次修改原因：按账号及商品 ID 标记已导入，并显示首次导入/最近同步时间。
        filters = QHBoxLayout()
        self.import_filter = QComboBox()
        for title, value in (("全部商品", "all"), ("仅未导入", "new"), ("仅已导入", "existing")):
            self.import_filter.addItem(title, value)
        self.import_filter.currentIndexChanged.connect(self.render_rows)
        filters.addWidget(self.import_filter)
        # 2026-10-12：本次修改原因：大批量默认有限并发，受账号限流影响时可直接切换串行。
        filters.addWidget(label("详情并发", "hint"))
        self.workers = QComboBox()
        for count in (3, 2, 1):
            self.workers.addItem(f"{count} 个请求", count)
        filters.addWidget(self.workers)
        filters.addWidget(label("账号 + 妙手 ID 去重；重复同步保留本机加工内容。", "hint"), 1)
        filters.addWidget(button("上一页", lambda: self.change_page(-1)))
        filters.addWidget(button("下一页", lambda: self.change_page(1)))
        layout.addLayout(filters)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["选择", "妙手商品 ID", "产品标题", "本机状态", "首次导入 / 最近同步", "平台 / 货源 ID", "货源链接"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 48)
        self.table.verticalHeader().hide()
        configure_table(self.table, editable=False, multiline=True)
        # 2026-10-12：本次修改原因：数字 ID 和时间列保证基本可读，标题与链接占剩余空间。
        for column, width in ((1, 155), (3, 112), (4, 158), (5, 135)):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self.select_row)
        self.table.itemDoubleClicked.connect(lambda _item: self.inspect())
        # layout.addWidget(self.table, 1)
        self.detail_splitter = PersistentSplitter(Qt.Orientation.Vertical, "ui/miaoshou_import/list_detail_splitter_v1", [480, 180], self)
        self.detail_splitter.addWidget(Panel("采集箱查询结果", self.table, collapsible=False))
        direct = QHBoxLayout()
        self.target = QLineEdit()
        self.target.setPlaceholderText("可直接填写公共采集箱商品 ID（不是 Temu 等平台的商品 ID）")
        direct.addWidget(self.target, 1)
        direct.addWidget(button("查看详情", self.inspect))
        direct.addWidget(button("导入此商品", self.import_current))
        layout.addLayout(direct)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        # self.details.setMaximumHeight(210)
        self.details.setMinimumHeight(100)
        self.details.setPlaceholderText("选中商品后查看完整 API 详情；导入将保存全部字段。")
        # layout.addWidget(self.details)
        # self.detail_splitter.addWidget(Panel("商品接口详情", self.details))
        # 2026-10-13：本次修改原因：商品接口详情默认收起，主动查看及同步失败时再展开，原接口查询不变。
        self.details_panel = Panel("商品接口详情", self.details)
        self.detail_splitter.addWidget(self.details_panel)
        layout.addWidget(self.detail_splitter, 1)
        # 2026-10-12：本次修改原因：结果在原窗口以卡片展示，错误明细可滚动，不再弹出冗长的普通消息框。
        self.result_card, result_layout = card()
        result_row = QHBoxLayout()
        self.result_labels = {}
        for state, caption in (("imported", "新导入"), ("existing", "已导入跳过"), ("failed", "失败")):
            value = label(f"{caption}  0", "sectionTitle")
            self.result_labels[state] = (value, caption)
            result_row.addWidget(value, 1)
        result_layout.addLayout(result_row)
        self.result_card.hide()
        layout.addWidget(self.result_card)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(16)
        self.progress.hide()
        layout.addWidget(self.progress)
        # self.status = label("尚未查询。导入只读取妙手数据，回传需在商品库另行操作。", "hint", True)
        self.status = label("尚未查询。先查询采集箱，勾选后导入；随后进入商品加工。", "hint", True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        # actions.addWidget(button("勾选本页", lambda: self.check_page(True)))
        # 2026-10-12：本次修改原因：批量勾选默认只包含未导入商品，减少无效同步。
        actions.addWidget(button("勾选未导入", lambda: self.check_page(True)))
        actions.addWidget(button("取消勾选", lambda: self.check_page(False)))
        actions.addWidget(button("查看同步记录", self.view_records))
        actions.addStretch()
        # actions.addWidget(button("返回商品库", self.reject))
        # 2026-10-12：本次修改原因：导入完成提供进入加工入口，并定位最后导入商品。
        actions.addWidget(button("返回", self.reject))
        self.enter_button = button("进入商品加工", self.enter_processing)
        self.enter_button.setEnabled(False)
        actions.addWidget(self.enter_button)
        actions.addWidget(button("导入勾选商品", self.import_selected, primary=True))
        layout.addLayout(actions)

    # 2026-10-12：本次修改原因：导入成功后用户选择进入加工，查询失败仍可停留重试。
    # 2026-10-13：本次修改原因：窗口关闭时只保存显示比例，处理中的关闭保护仍由原 reject 决定。
    def done(self, result):
        if self._is_busy():
            return
        save_splitters(self)
        super().done(result)

    def enter_processing(self) -> None:
        if self.last_product_id and not self._is_busy():
            self.accept()

    def _is_busy(self) -> bool:
        return bool(getattr(self.parent(), "_tasks", set()))

    def reject(self) -> None:
        if not self._is_busy():
            super().reject()

    def check_page(self, checked: bool) -> None:
        if not self._is_busy():
            for row in range(self.table.rowCount()):
                # self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                # 2026-10-12：本次修改原因：按稳定身份跳过已导入项，不依赖商品更新时间猜测。
                target = self.table.item(row, 1).text()
                self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked and target not in self.import_index else Qt.CheckState.Unchecked)

    def select_row(self) -> None:
        item = self.table.item(self.table.currentRow(), 1)
        if item:
            self.target.setText(item.text())
            self.details.clear()

    # def search(self) -> None:
    #     if self._is_busy():
    #         return
    #     keyword, page = self.keyword.text().strip(), self.page.value()
    #     # 2026-10-12：本次修改原因：查询期间明确实际操作，失败时主窗口会更新该状态。
    #     self.status.setText("正在查询公共采集箱…")
    #
    #     def done(result: dict) -> None:
    #         rows = result["detailList"]
    #         self.table.setRowCount(0)
    #         for value in rows:
    #             if not isinstance(value, dict):
    #                 continue
    #             row = self.table.rowCount()
    #             self.table.insertRow(row)
    #             check = QTableWidgetItem()
    #             check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
    #             check.setCheckState(Qt.CheckState.Unchecked)
    #             self.table.setItem(row, 0, check)
    #             sources = [item for item in (value.get("sourceList") or []) if isinstance(item, dict)]
    #             values = [str(value.get("commonCollectBoxDetailId", "")), str(value.get("title") or ""),
    #                       "\n".join(f"{item.get('source', '')} / {item.get('sourceSite', '')} / {item.get('sourceItemId', '')}" for item in sources),
    #                       "\n".join(str(item.get("sourceItemUrl") or "") for item in sources)]
    #             for column, text in enumerate(values, 1):
    #                 item = QTableWidgetItem(text)
    #                 item.setToolTip(text)
    #                 self.table.setItem(row, column, item)
    #         self.status.setText(f"第 {page} 页 · 本页 {self.table.rowCount()} 条 · 总计 {result.get('total', '未知')} 条；每页 100 条。勾选后导入。")
    #     self.runner(lambda: self.client.list_products(keyword, page, 100), done)

    # 2026-10-12：本次修改原因：一次查询列表与本机身份，筛选及翻页不再逐条联网判断。
    def search(self) -> None:
        if self._is_busy():
            return
        keyword, page, size = self.keyword.text().strip(), self.page.value(), self.page_size.currentData()
        self.status.setText("正在查询公共采集箱…")
        self.result_card.hide()
        def done(result: dict) -> None:
            self.rows, self.import_index = result["page"]["detailList"], result["known"]
            self.render_rows()
            self.status.setText(f"第 {page} 页 · 本页 {len(self.rows)} 条 · 总计 {result['page'].get('total', '未知')} 条；勾选后导入。")
        self.runner(lambda: {"page": self.client.list_products(keyword, page, size),
            "known": self.repository.miaoshou_import_index(self.client.config.account_id)}, done, "查询妙手采集箱")

    # 2026-10-12：本次修改原因：同时显示是否导入及首次导入/最近同步时间，时间不用于替代身份去重。
    def render_rows(self, *_args) -> None:
        mode = self.import_filter.currentData()
        self.table.setRowCount(0)
        for value in self.rows:
            if not isinstance(value, dict):
                continue
            target = str(value.get("commonCollectBoxDetailId", ""))
            known = self.import_index.get(target)
            if (mode == "new" and known) or (mode == "existing" and not known):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check)
            sources = [item for item in (value.get("sourceList") or []) if isinstance(item, dict)]
            status = ("已导入 · 回收站" if known["archived"] else "已导入") if known else "未导入"
            times = "\n".join(known[key][:19].replace("T", " ") for key in ("imported_at", "last_sync_at")) if known else "—"
            values = [target, str(value.get("title") or ""), status, times,
                "\n".join(f"{item.get('source', '')} / {item.get('sourceItemId', '')}" for item in sources),
                "\n".join(str(item.get("sourceItemUrl") or "") for item in sources)]
            for column, text in enumerate(values, 1):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, column, item)

    # 2026-10-12：本次修改原因：保持关键字及每页条数翻页，查询期间禁止更改参数。
    def change_page(self, step: int) -> None:
        if not self._is_busy():
            self.page.setValue(max(1, self.page.value() + step))
            self.search()

    # 2026-10-12：本次修改原因：任务锁覆盖同步窗口，终态停止进度动画并恢复按钮。
    def set_busy(self, busy: bool) -> None:
        for item in self.findChildren(QPushButton):
            item.setEnabled(not busy)
        # 2026-10-12：本次修改原因：同步期间固定并发设置，不允许当前批次中途变更。
        for item in (self.keyword, self.page, self.page_size, self.import_filter, self.workers, self.table, self.target):
            item.setEnabled(not busy)
        self.enter_button.setEnabled(not busy and bool(self.last_product_id))
        self.progress.setRange(0, 0 if busy else 1)
        if not busy:
            self.progress.setValue(1)
        self.progress.show()

    # 2026-10-12：本次修改原因：窗口内同步展示真实完成数量，与底部进度保持一致。
    def show_progress(self, value: dict) -> None:
        self.progress.setRange(0, max(1, value["total"]))
        self.progress.setValue(value["completed"])
        self.status.setText(f"同步 {value['completed']}/{value['total']} · 导入 {value['imported']} · 跳过 {value['existing']} · 失败 {value['failed']}")

    # 2026-10-12：本次修改原因：同步完成后可直接进入持久记录查看逐条原因。
    def view_records(self) -> None:
        if not self._is_busy():
            # self.parent().navigate(1)
            # self.parent().capture_records_page.change_route(0)
            # 2026-10-13：本次修改原因：查询窗口的同步记录入口定位日志记录 → 采集日志 → 妙手接口。
            self.parent().show_capture_records(route_index=0)
            self.reject()

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
            self.details_panel.set_expanded(True)
            self.status.setText("详情已读取。导入时会再次读取最新数据，商品价格按接口人民币单位保存。")
        # self.runner(lambda: self.client.detail(target), done)
        # 2026-10-12：本次修改原因：详情查询使用独立任务名称，结束后明确退出查询状态。
        self.runner(lambda: self.client.detail(target), done, "查看妙手商品详情")

    def import_current(self) -> None:
        self._import([self.target.text().strip()])

    def import_selected(self) -> None:
        targets = [self.table.item(row, 1).text() for row in range(self.table.rowCount())
                   if self.table.item(row, 0).checkState() == Qt.CheckState.Checked]
        self._import(targets)

    # def _import(self, targets: list[str]) -> None:
    #     if self._is_busy():
    #         return
    #     try:
    #         if not targets:
    #             raise ValueError("请先勾选要导入的商品。")
    #         targets = [str(detail_id(value)) for value in targets]
    #     except ValueError as error:
    #         QMessageBox.warning(self, "请选择商品", str(error))
    #         return
    #
    #     def done(result: dict) -> None:
    #         rows = result["results"]
    #         counts = {state: sum(row["state"] == state for row in rows) for state in ("imported", "existing", "failed")}
    #         accepted = [row for row in rows if row.get("product_id")]
    #         if accepted:
    #             self.last_product_id = accepted[-1]["product_id"]
    #         message = f"新增导入 {counts['imported']} 个 · 本机已有 {counts['existing']} 个 · 失败 {counts['failed']} 个。"
    #         # message += "\n已有商品保留本机内容。返回商品库可编辑、使用 AI、保存审核后回传。"
    #         # 2026-10-12：本次修改原因：说明同步留档及下一步，并提供可点击入口。
    #         self.enter_button.setEnabled(bool(self.last_product_id))
    #         # message += "\n结果已记录。点击“进入商品加工”编辑或使用 AI，保存审核后回传。"
    #         # 2026-10-12：本次修改原因：留档失败时不误报全部记录已保存。
    #         message += ("\n部分同步记录未保存，请查看下方原因。" if any(row.get("record_error") for row in rows)
    #                     else "\n同步结果已记录。")
    #         if self.last_product_id:
    #             message += "点击“进入商品加工”编辑或使用 AI，保存审核后回传。"
    #         errors = [f"妙手 ID {row['target_id']}：{row['message']}" for row in rows if row["state"] == "failed"]
    #         # if errors:
    #             # message += "\n\n" + "\n".join(errors[:8])
    #         # 2026-10-12：本次修改原因：本机留档失败也反馈，不能误报全部结果已保存。
    #         errors += [row["record_error"] for row in rows if row.get("record_error")]
    #         if errors:
    #             message += "\n\n" + "\n".join(errors[:8])
    #         self.status.setText(message)
    #         QMessageBox.information(self, "采集箱导入结果", message)
    #     # 2026-10-12：本次修改原因：实际读取期间显示商品数，不残留上一次成功状态。
    #     self.status.setText(f"正在读取 {len(set(targets))} 个商品详情并导入本机…")
    #     self.runner(lambda: self.service.import_products(self.client, targets), done)

    # 2026-10-12：本次修改原因：同步报告真实进度，结果用内嵌卡片及可滚动明细展示，去掉冗长弹窗。
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
        self.result_card.hide()
        self.details.clear()
        def done(result: dict) -> None:
            rows = result["results"]
            counts = {state: sum(row["state"] == state for row in rows) for state in self.result_labels}
            accepted = [row for row in rows if row.get("product_id")]
            if accepted:
                self.last_product_id = accepted[-1]["product_id"]
            for state, (widget, caption) in self.result_labels.items():
                widget.setText(f"{caption}  {counts[state]}")
            self.result_card.show()
            self.enter_button.setEnabled(bool(self.last_product_id))
            errors = [f"妙手 ID {row['target_id']}：{row['message']}" for row in rows if row["state"] == "failed"]
            errors += [row["record_error"] for row in rows if row.get("record_error")]
            self.details.setPlainText("\n".join(errors) if errors else "同步完成。已有商品保留本机修改；进入商品加工继续编辑、AI 加工和审核。")
            # 2026-10-13：本次修改原因：失败明细展开供用户处理，成功时保持辅助区原来的收起状态。
            if errors:
                self.details_panel.set_expanded(True)
            self.status.setText("同步完成，部分失败可重新勾选后重试；完整结果见采集记录。" if errors else "同步完成，可进入商品加工。")
            self.import_index = self.repository.miaoshou_import_index(self.client.config.account_id)
            self.render_rows()
        self.status.setText(f"准备同步 {len(set(targets))} 个商品，已导入项将直接跳过…")
        # self.runner(lambda report: self.service.import_products(self.client, targets, progress=report),
        # 2026-10-12：本次修改原因：启动时冻结用户选择的读取并发数，保持后台任务不读取 UI 控件。
        workers = self.workers.currentData()
        self.runner(lambda report: self.service.import_products(self.client, targets, progress=report, workers=workers),
                    done, "同步妙手采集箱", with_progress=True)
