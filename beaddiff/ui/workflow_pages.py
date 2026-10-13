# 2026-10-12：本次修改原因：为接口/插件采集、ERP 回传和操作帮助提供独立页面及明确的下一步入口。
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
# from PySide6.QtGui import QColor
# 2026-10-13：本次修改原因：Delete 只在记录表获得焦点时调用现有移除按钮，输入框不受影响。
from PySide6.QtGui import QColor, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QHeaderView, QHBoxLayout,
    QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea, QTableWidget,
    # QTableWidgetItem, QVBoxLayout, QWidget,
    # 2026-10-13：本次修改原因：采集与回传用一级日志标签切换，原记录控件直接嵌入。
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..erp import MODE_LABELS, STATE_LABELS
from ..workflow import TARGET_LABEL, receipt_data, record_guidance
from .widgets import button, card, label
# 2026-10-12：本次修改原因：记录表统一多行行高和完整内容查看，避免标题或数字被裁切。
from .table_support import configure_table
# 2026-10-13：本次修改原因：记录与原始/回执详情可拖拽，保持全部查询、清理和核对入口。
from .layout_support import PersistentSplitter, Panel
from .theme import status_colors


def time_text(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%m-%d %H:%M")
    except ValueError:
        return value


def record_table(headers: list[str]) -> QTableWidget:
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(54)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    configure_table(widget, editable=False, multiline=True)
    return widget


def fill_records(widget: QTableWidget, rows: list[dict], values) -> None:
    selected = widget.item(widget.currentRow(), 0)
    previous = selected.data(Qt.ItemDataRole.UserRole)["id"] if selected else ""
    widget.blockSignals(True)
    widget.setRowCount(len(rows))
    selected_row = 0
    for index, record in enumerate(rows):
        for column, value in enumerate(values(record)):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            item.setData(Qt.ItemDataRole.UserRole, record)
            if record["state"] in {"failed", "unknown", "解析失败", "待补充"}:
                # item.setForeground(QColor("#b56936"))
                # 2026-10-13：本次修改原因：失败/未知行用高对比提示色，状态含义不变。
                bg, fg = status_colors("结果未知" if record["state"] == "unknown" else "失败")
                item.setBackground(QColor(bg))
                item.setForeground(QColor(fg))
            widget.setItem(index, column, item)
        if record["id"] == previous:
            selected_row = index
    widget.blockSignals(False)
    if rows:
        widget.selectRow(selected_row)


class AcquisitionRecordsPage(QWidget):
    # def __init__(self, owner):
    # 2026-10-13：本次修改原因：作为日志子页时省去重复标题，保留来源切换、说明和所有操作。
    def __init__(self, owner, *, embedded=False):
        super().__init__(owner)
        self.owner = owner
        self.route = owner.settings.capture_route
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # layout.addWidget(label("采集记录", "pageTitle"))
        if not embedded:
            layout.addWidget(label("采集记录", "pageTitle"))
        # layout.addWidget(label("查看每次获取结果，从记录进入商品加工；切换标签可查看另一条路线的历史。", "muted", True))
        # 2026-10-13：本次修改原因：日志分类已由标签说明，删除常驻流程文字，工具与数据分块呈现。
        layout.setSpacing(12)
        tabs = QHBoxLayout()
        self.routes = QButtonGroup(self)
        for index, text in enumerate(("妙手接口", "插件同步")):
            item = button(text)
            item.setObjectName("filterTab")
            item.setCheckable(True)
            item.setChecked((index == 0) == (self.route == "miaoshou"))
            self.routes.addButton(item, index)
            tabs.addWidget(item)
        self.routes.idClicked.connect(self.change_route)
        tabs.addStretch()
        tabs.addWidget(button("采集路线设置", lambda: owner.open_settings(0)))
        # layout.addLayout(tabs)
        frame, contents = card()
        contents.setContentsMargins(12, 10, 12, 10)
        # actions = QHBoxLayout()
        self.summary = label("", "hint", True)
        # actions.addWidget(self.summary, 1)
        self.sync = button("同步妙手采集箱", owner.import_miaoshou, primary=True)
        self.files = button("导入采集文件", owner.import_files)
        # actions.addWidget(self.sync)
        # actions.addWidget(self.files)
        # contents.addLayout(actions)
        # 2026-10-13：本次修改原因：来源切换、配置和获取入口共用一行，数量移到列表标题旁。
        tabs.addWidget(self.sync)
        tabs.addWidget(self.files)
        contents.addLayout(tabs)
        layout.addWidget(frame)
        list_body = QWidget()
        list_contents = QVBoxLayout(list_body)
        list_contents.setContentsMargins(0, 0, 0, 0)
        list_contents.setSpacing(10)
        self.table = record_table(["获取时间", "商品 / ID", "结果", "说明"])
        self.table.setProperty("embeddedTable", True)
        list_contents.addWidget(self.table, 1)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self.open_product())
        # contents.addWidget(self.table, 1)
        # 2026-10-13：本次修改原因：保留查看原始数据按钮，原弹窗内容改在下方详情区展示。
        self.detail_splitter = PersistentSplitter(Qt.Orientation.Vertical, "ui/captures/records_detail_splitter_v1", [540, 210], self)
        # self.detail_splitter.addWidget(Panel("采集条目", self.table, collapsible=False))
        # 2026-10-13：本次修改原因：列表和操作共用一层边界，外层不再套卡片。
        list_panel = Panel("采集条目", list_body, collapsible=False)
        list_panel.heading_layout.insertWidget(1, self.summary)
        self.detail_splitter.setHandleWidth(12)
        self.detail_splitter.addWidget(list_panel)
        self.raw_view = QPlainTextEdit()
        self.raw_view.setReadOnly(True)
        self.raw_view.setProperty("embeddedViewer", True)
        self.raw_view.setPlaceholderText("选中条目，点击“查看原始数据”在这里查看；双击条目进入加工。")
        self.raw_panel = Panel("原始数据", self.raw_view)
        self.detail_splitter.addWidget(self.raw_panel)
        # contents.addWidget(self.detail_splitter, 1)
        layout.addWidget(self.detail_splitter, 1)
        self.empty = label("", "empty", True)
        # contents.addWidget(self.empty)
        list_contents.addWidget(self.empty)
        self.hint = label("", "hint", True)
        # contents.addWidget(self.hint)
        # 2026-10-13：本次修改原因：条目说明已在表格中完整展示，不再在表格下重复；原刷新对象保留。
        self.hint.setParent(self)
        self.hint.hide()
        controls = QHBoxLayout()
        self.raw = button("查看原始数据", self.show_raw)
        self.reparse = button("重新解析", self.parse_again)
        self.edit = button("进入商品加工", self.open_product, primary=True)
        controls.addWidget(self.raw)
        controls.addWidget(self.reparse)
        # 2026-10-12：本次修改原因：两类采集记录可移除、清空当前路线并恢复，商品和原始材料保留。
        self.remove_record = button("移除所选", lambda: self.cleanup(False))
        self.clear_records = button("清空当前路线", lambda: self.cleanup(True))
        # self.restore_records = button("恢复记录", lambda: owner.restore_local_list(self.cleanup_kind()))
        # 2026-10-13：本次修改原因：记录恢复改为打开对应类型回收站，支持逐条恢复和清空。
        self.restore_records = button("回收站", lambda: owner.open_recycle_bin(self.cleanup_kind()))
        self.cleanup_buttons = (self.remove_record, self.clear_records, self.restore_records)
        for item in self.cleanup_buttons:
            controls.addWidget(item)
        controls.addStretch()
        controls.addWidget(self.edit)
        # contents.addLayout(controls)
        # layout.addWidget(frame, 1)
        list_contents.addLayout(controls)

        self.delete_shortcut = QShortcut(QKeySequence("Delete"), self.table)
        self.delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.delete_shortcut.activated.connect(self.remove_record.click)

    def change_route(self, index: int) -> None:
        self.route = "miaoshou" if index == 0 else "plugin"
        self.refresh()

    def selected(self) -> dict | None:
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def refresh(self) -> None:
        owner = self.owner
        if self.route == "miaoshou":
            rows = owner.repository.miaoshou_import_records()
            # known = {row["product_id"] for row in rows if row.get("product_id")}
            # 2026-10-12：本次修改原因：清理后的旧记录不会因回退快照而重新出现。
            known = {row["product_id"] for row in owner.repository.miaoshou_import_records(include_hidden=True) if row.get("product_id")}
            # hidden = owner.repository.hidden_local_ids("imports")
            # 2026-10-13：本次修改原因：永久删除的旧版导入入口不再作为快照回退项重新显示。
            hidden = owner.repository.hidden_local_ids("imports") | owner.repository.hidden_local_ids("purged-import")
            # 2026-10-12：本次修改原因：旧版接口导入没有任务记录，仍可查看保留的导入快照。
            rows += [{"id": "legacy:" + product.id, "product_id": product.id,
                      "created_at": product.erp_imported_at or product.created_at,
                      "target_id": product.erp_original_id, "title": product.title,
                      "state": "imported", "message": "旧版导入，展示首次详情快照。",
                      "detail": json.dumps(product.erp_remote_snapshot, ensure_ascii=False)}
                     for product in owner._products if product.erp_imported and product.id not in known
                     and "legacy:" + product.id not in hidden]
            rows.sort(key=lambda row: row["created_at"], reverse=True)
            # states = {"imported": "已导入", "existing": "本机已有", "failed": "同步失败"}
            # 2026-10-13：本次修改原因：同步结果属于历史；说明另附实时去向，不把旧回收站说明当成当前状态。
            states = {"imported": "已导入", "existing": "同步时已有", "failed": "同步失败"}
            indexes = {account: owner.repository.miaoshou_import_index(account)
                       for account in {row.get("account_id", "") for row in rows} if account}
            active_ids = {product.id for product in owner._products}
            archived_ids = owner.repository.hidden_local_ids("products")
            for row in rows:
                current = indexes.get(row.get("account_id", ""), {}).get(str(row["target_id"]))
                product_id = current["product_id"] if current else row.get("product_id", "")
                if (current and current["archived"]) or product_id in archived_ids:
                    now = "当前：本机商品在回收站，可恢复后继续加工。"
                elif current or product_id in active_ids:
                    now = "当前：本机商品在商品加工列表，可继续加工。"
                elif row["state"] in {"imported", "existing"}:
                    now = "当前：本机已无此商品，可重新同步。"
                else:
                    now = ""
                row["display_message"] = "同步当时：" + row.get("message", "") + ("\n" + now if now else "")
            fill_records(self.table, rows, lambda row: [time_text(row["created_at"]),
                f"{row['title'] or '未获取标题'}\n妙手 ID {row['target_id']}",
                # states[row["state"]], row["message"]])
                states[row["state"]], row["display_message"]])
            # self.summary.setText(f"共 {len(rows)} 条同步记录；重复导入保留本机修改。")
            # 2026-10-13：本次修改原因：列表标题仅显示数量，重复导入解释归入帮助与条目说明。
            self.summary.setText(f"共 {len(rows)} 条")
            self.empty.setText("尚无接口同步记录。点击“同步妙手采集箱”，查询、勾选并导入商品。")
        else:
            rows = owner.repository.captures()
            fill_records(self.table, rows, lambda row: [time_text(row["received_at"]),
                f"{row['source'].upper()} / {row['site'] or '—'}\n{row['source_id']}",
                row["state"], row["message"]])
            # self.summary.setText(f"共 {len(rows)} 条插件 / 文件记录；原始材料和解析结果保存在本机。")
            self.summary.setText(f"共 {len(rows)} 条")
            self.empty.setText("尚无插件材料。先在设置启用备用插件路线，或导入已有 JSON / HAR 文件。")
        self.empty.setVisible(not rows)
        self.sync.setVisible(self.route == "miaoshou")
        self.files.setVisible(self.route == "plugin")
        self.sync.setEnabled(not owner._tasks)
        self.files.setEnabled(not owner._tasks)
        self.reparse.setVisible(self.route == "plugin")
        self.selection_changed()
        self.set_cleanup_busy(bool(owner._tasks))

    # 2026-10-12：本次修改原因：清理范围按当前采集路线确定，接口/插件历史互不影响。
    def cleanup_kind(self) -> str:
        return "imports" if self.route == "miaoshou" else "captures"

    def cleanup(self, all_visible: bool) -> None:
        rows = [self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(self.table.rowCount())] if all_visible else [self.selected()]
        self.owner.clean_local_list(self.cleanup_kind(), [row["id"] for row in rows if row])

    def set_cleanup_busy(self, busy: bool) -> None:
        for item in self.cleanup_buttons:
            item.setEnabled(not busy)

    def selection_changed(self) -> None:
        record = self.selected()
        # 2026-10-13：本次修改原因：选择变化清空旧快照，避免误把上一商品材料当作当前商品。
        self.raw_view.clear()
        self.raw.setEnabled(bool(record))
        self.edit.setEnabled(bool(record and record.get("product_id")))
        self.reparse.setEnabled(bool(record) and not self.owner._tasks)
        # self.hint.setText(record.get("message", "") if record else "选中记录后可查看原始数据或进入商品加工。")
        # 2026-10-13：本次修改原因：底部提示与说明列使用相同的历史/当前信息，避免残留旧回收站提示。
        self.hint.setText(record.get("display_message", record.get("message", "")) if record else
                          "选中记录后可查看原始数据或进入商品加工。")

    def open_product(self) -> None:
        record = self.selected()
        if record and record.get("product_id"):
            self.owner.focus_product(record["product_id"], edit=True)

    def show_raw(self) -> None:
        record = self.selected()
        if not record:
            return
        try:
            text = record.get("detail", "{}") if self.route == "miaoshou" else Path(record["raw_path"]).read_text(encoding="utf-8")
            if self.route == "miaoshou":
                # text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                # 2026-10-12：本次修改原因：跳过重复导入不再请求详情，其原始数据入口显示首次导入快照并明确标记。
                data = json.loads(text)
                if not data and record.get("product_id"):
                    product = self.owner.repository.product(record["product_id"])
                    data = {"说明": "本次重复同步未请求远端详情；以下为首次导入快照。",
                            "editCommonCollectBoxDetail": product.erp_remote_snapshot if product else {}}
                text = json.dumps(data, ensure_ascii=False, indent=2)
            # self.owner.text_dialog("接口详情快照" if self.route == "miaoshou" else "插件原始材料",
                # text[:300000] + ("\n【预览已截断】" if len(text) > 300000 else ""), record.get("raw_path", ""))
            # 2026-10-13：本次修改原因：原始数据按钮仍读取同一材料，只改为分栏内查看。
            self.raw_view.setPlainText(text[:300000] + ("\n【预览已截断】" if len(text) > 300000 else "")
                + ("\n\n原始文件：" + record.get("raw_path", "") if record.get("raw_path") else ""))
            # self.raw_view.show()
            # self.raw_panel.collapse.setText("收起")
            # 2026-10-13：本次修改原因：查看原始材料时同时恢复分区高度，避免内容展开后仍被压在标题栏下面。
            self.raw_panel.set_expanded(True)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法读取原始数据", str(error))

    def parse_again(self) -> None:
        record = self.selected()
        if record and self.route == "plugin" and not self.owner._tasks:
            # 2026-10-12：本次修改原因：重新解析失败反馈说明正在进行的具体操作。
            self.owner.run_task(lambda: self.owner.service.reparse(record["id"]),
                lambda result: QMessageBox.information(self, "重新解析结果",
                    f"{result['state']}\n{result.get('message', '')}\n已保存的人工修改继续保留。"),
                "重新解析采集材料")


class ERPRecordsPage(QWidget):
    # def __init__(self, owner):
    # 2026-10-13：本次修改原因：回传作为日志子页时复用原左右布局，省去重复大标题。
    def __init__(self, owner, *, embedded=False):
        super().__init__(owner)
        self.owner = owner
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # layout.addWidget(label("回传记录", "pageTitle"))
        if not embedded:
            layout.addWidget(label("回传记录", "pageTitle"))
        # layout.addWidget(label("成功表示写入公共采集箱；结果未知需先核对，发布仍在妙手完成。", "muted", True))
        # 2026-10-13：本次修改原因：结果含义在回执建议和帮助中说明，页面只保留筛选、列表及操作。
        layout.setSpacing(12)
        frame, contents = card()
        contents.setContentsMargins(12, 10, 12, 10)
        actions = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索商品、主编号或妙手目标 ID")
        self.search.textChanged.connect(self.refresh)
        actions.addWidget(self.search, 1)
        self.state = QComboBox()
        self.state.addItem("全部结果", "")
        for key, value in STATE_LABELS.items():
            self.state.addItem(value, key)
        self.state.currentIndexChanged.connect(self.refresh)
        actions.addWidget(self.state)
        actions.addWidget(button("刷新", owner.refresh))
        contents.addLayout(actions)
        layout.addWidget(frame)
        self.summary = label("", "hint")
        # contents.addWidget(self.summary)
        # 2026-10-13：本次修改原因：条目数量随列表标题呈现，不额外占用一行。
        list_body = QWidget()
        list_contents = QVBoxLayout(list_body)
        list_contents.setContentsMargins(0, 0, 0, 0)
        list_contents.setSpacing(10)
        self.table = record_table(["发送时间", "商品 / 版本", "方式", "位置 / 账号", "结果", "妙手 ID"])
        self.table.setProperty("embeddedTable", True)
        list_contents.addWidget(self.table, 1)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self.open_product())
        # contents.addWidget(self.table, 1)
        # 2026-10-13：本次修改原因：回传记录与回执分栏，按钮和未知结果保护保留。
        # self.detail_splitter = PersistentSplitter(Qt.Orientation.Vertical, "ui/transfers/records_detail_splitter_v1", [520, 240], self)
        # 2026-10-13：本次修改原因：回传条目与回执左右对照，新布局键避免还原旧版的垂直方向。
        self.detail_splitter = PersistentSplitter(Qt.Orientation.Horizontal, "ui/transfers/records_receipt_splitter_v2", [660, 440], self)
        self.table.setMinimumWidth(350)
        # 2026-10-13：本次修改原因：窄列表保留可读的商品列宽，辅助列仍可横向滚动和拖动宽度。
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((110, 230, 130, 145, 90, 110)):
            self.table.setColumnWidth(column, width)
        # self.detail_splitter.addWidget(Panel("回传条目", self.table, collapsible=False))
        # 2026-10-13：本次修改原因：回传条目和操作共用一个圆角区，与右侧回执通过留白区分。
        list_panel = Panel("回传条目", list_body, collapsible=False)
        list_panel.heading_layout.insertWidget(1, self.summary)
        self.detail_splitter.setHandleWidth(12)
        self.detail_splitter.addWidget(list_panel)
        self.empty = label("暂无回传记录。请在商品加工保存审核后点击“传回 ERP”。", "empty", True)
        # contents.addWidget(self.empty)
        list_contents.addWidget(self.empty)
        self.guidance = label("", "hint", True)
        # contents.addWidget(self.guidance)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setProperty("embeddedViewer", True)
        # self.details.setMaximumHeight(230)
        # 2026-10-13：本次修改原因：详情高度改由分隔条分配，取消固定 230 像素上限。
        self.details.setMinimumHeight(100)
        self.details.setPlaceholderText("选中记录查看原因、图片进度和接口回执。")
        # contents.addWidget(self.details)
        # self.detail_splitter.addWidget(Panel("接口回执与处理建议", self.details))
        # 2026-10-13：本次修改原因：处理建议跟随右侧回执，默认收起；手动选中条目时展开查看。
        receipt_area = QWidget()
        receipt_layout = QVBoxLayout(receipt_area)
        receipt_layout.setContentsMargins(0, 0, 0, 0)
        receipt_layout.addWidget(self.guidance)
        receipt_layout.addWidget(self.details, 1)
        self.receipt_panel = Panel("接口回执与处理建议", receipt_area)
        self.detail_splitter.addWidget(self.receipt_panel)
        self.table.clicked.connect(lambda _index: self.receipt_panel.set_expanded(True))
        # contents.addWidget(self.detail_splitter, 1)
        layout.addWidget(self.detail_splitter, 1)
        controls = QHBoxLayout()
        self.edit = button("进入商品加工", self.open_product)
        self.reconcile = button("只读核对未知结果", self.check_unknown, primary=True)
        controls.addWidget(self.edit)
        # 2026-10-12：本次修改原因：回传历史支持当前筛选范围清理，未知/发送中证据保留，支持恢复。
        self.remove_record = button("移除所选", lambda: self.cleanup(False))
        self.clear_records = button("清空当前结果", lambda: self.cleanup(True))
        # self.restore_records = button("恢复记录", lambda: owner.restore_local_list("transfers"))
        # 2026-10-13：本次修改原因：回传记录也提供可浏览回收站，选择恢复或永久删除已完成记录。
        self.restore_records = button("回收站", lambda: owner.open_recycle_bin("transfers"))
        self.cleanup_buttons = (self.remove_record, self.clear_records, self.restore_records)
        for item in self.cleanup_buttons:
            controls.addWidget(item)
        controls.addStretch()
        controls.addWidget(self.reconcile)
        # contents.addLayout(controls)
        # layout.addWidget(frame, 1)
        list_contents.addLayout(controls)
        # 2026-10-13：本次修改原因：快捷键只调用已有移除入口，保护条件仍由原方法决定。
        self.delete_shortcut = QShortcut(QKeySequence("Delete"), self.table)
        self.delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.delete_shortcut.activated.connect(self.remove_record.click)


    def selected(self) -> dict | None:
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def refresh(self, *_args) -> None:
        query = self.search.text().strip().casefold()
        products = {product.id: product for product in self.owner._products}
        # 2026-10-13：本次修改原因：批量判定回收站商品仍可恢复，避免为每条历史逐次查询数据库。
        existing_ids = set(products) | self.owner.repository.hidden_local_ids("products")
        rows = []
        # 2026-10-12：本次修改原因：清理只影响历史展示，商品状态仍依据全部回执判断。
        hidden = self.owner.repository.hidden_local_ids("transfers")
        for record in self.owner._erp_records:
            if record["id"] in hidden:
                continue
            product = products.get(record["product_id"])
            # title = product.title or product.main_code if product else record["product_id"]
            # 2026-10-13：本次修改原因：商品移入回收站或永久删除后，独立回传记录仍使用发送快照显示和搜索标题。
            try:
                snapshot = json.loads(record.get("snapshot", "{}"))
                if not isinstance(snapshot, dict):
                    snapshot = {}
            except (TypeError, ValueError):
                snapshot = {}
            code = product.main_code if product else snapshot.get("main_code", "")
            title = (product.title or code) if product else (snapshot.get("title") or code or record["product_id"])
            if self.state.currentData() and record["state"] != self.state.currentData():
                continue
            # if query and query not in (title + " " + (product.main_code if product else "") + " " + record["target_id"]).casefold():
            if query and query not in (title + " " + code + " " + record["target_id"]).casefold():
                continue
            # rows.append({**record, "display_title": title})
            rows.append({**record, "display_title": title, "product_exists": record["product_id"] in existing_ids})
        fill_records(self.table, rows, lambda row: [time_text(row["created_at"]),
            f"{row['display_title']}\nv{row['revision']}", MODE_LABELS[row["mode"]],
            TARGET_LABEL + "\n账号 " + (receipt_data(row).get("account_id", "")[:8] or "未记录"),
            STATE_LABELS[row["state"]], row["target_id"] or "尚无"])
        # self.summary.setText(f"当前 {len(rows)} 条 / 共 {len(self.owner._erp_records)} 条回传记录")
        # 2026-10-12：本次修改原因：清理后的总数不包含隐藏条目，另行说明可恢复数量。
        visible_total = sum(record["id"] not in hidden for record in self.owner._erp_records)
        # self.summary.setText(f"当前 {len(rows)} 条 / 共 {visible_total} 条回传记录" + (f" · 已移除 {len(hidden)} 条，可恢复" if hidden else ""))
        # 2026-10-13：本次修改原因：列表标题旁只保留紧凑数量，已移除说明放入悬停提示，避免挤压左右分区。
        self.summary.setText(f"当前 {len(rows)} 条 / 共 {visible_total} 条")
        self.summary.setToolTip(f"已移除 {len(hidden)} 条，可从回收站恢复。" if hidden else "当前筛选结果 / 本机回传记录总量")
        self.empty.setVisible(not rows)
        self.selection_changed()
        self.set_cleanup_busy(bool(self.owner._tasks))

    # 2026-10-12：本次修改原因：清空仅针对当前筛选显示的记录，未核对结果由存储层再次保护。
    def cleanup(self, all_visible: bool) -> None:
        rows = [self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(self.table.rowCount())] if all_visible else [self.selected()]
        self.owner.clean_local_list("transfers", [row["id"] for row in rows if row])

    def set_cleanup_busy(self, busy: bool) -> None:
        for item in self.cleanup_buttons:
            item.setEnabled(not busy)
        record = self.selected()
        self.remove_record.setEnabled(not busy and bool(record) and record["state"] not in {"sending", "unknown"})

    def selection_changed(self) -> None:
        record = self.selected()
        # self.edit.setEnabled(bool(record and record.get("product_id")))
        # 2026-10-13：本次修改原因：保留回执不意味着本机商品仍存在，删除后禁用进入商品加工。
        self.edit.setEnabled(bool(record and record.get("product_exists")))
        # 2026-10-12：本次修改原因：选择未知/发送中记录时即禁用移除，避免误删核对入口。
        self.remove_record.setEnabled(bool(record) and record["state"] not in {"sending", "unknown"} and not self.owner._tasks)
        self.reconcile.setEnabled(bool(record and record["state"] == "unknown") and not self.owner._tasks)
        # self.guidance.setText(record_guidance(record) if record else "")
        guidance = record_guidance(record) if record else ""
        if record and not record.get("product_exists"):
            guidance += " 本机商品已永久删除，发送快照和接口回执仍可查看。"
        self.guidance.setText(guidance)
        self.details.setPlainText((f"记录：{record['id']}\n{record['message']}\n\n回执：\n"
            + json.dumps(receipt_data(record), ensure_ascii=False, indent=2)) if record else "")
        # 2026-10-13：本次修改原因：键盘切换记录与鼠标选中一致；后台刷新不强制展开辅助区。
        if record and self.table.hasFocus():
            self.receipt_panel.set_expanded(True)

    def open_product(self) -> None:
        record = self.selected()
        # if record:
        # 2026-10-13：本次修改原因：双击历史记录也遵守商品存在性检查。
        if record and record.get("product_exists"):
            self.owner.focus_product(record["product_id"], edit=True)

    def check_unknown(self) -> None:
        record = self.selected()
        if record and not self.owner._tasks:
            self.owner.reconcile_erp_record(record)


# 2026-10-13：本次修改原因：历史查询合并成日志记录；按采集/回传分标签，各自筛选与操作保留，避免混表误操作。
class LogRecordsPage(QWidget):
    def __init__(self, owner, captures, transfers):
        super().__init__(owner)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        # layout.addWidget(label("日志记录", "pageTitle"))
        # 2026-10-13：本次修改原因：侧栏已标识日志页面，直接展示采集/回传分类，省去重复标题。
        self.tabs = QTabWidget()
        self.tabs.setObjectName("logTabs")
        self.tabs.tabBar().setObjectName("logTypeTabs")
        self.tabs.tabBar().setExpanding(False)
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(captures, "采集日志")
        self.tabs.addTab(transfers, "回传日志")
        self.tabs.setTabToolTip(0, "查看妙手接口及插件获取结果、原始材料和解析说明")
        self.tabs.setTabToolTip(1, "查看 ERP 写回结果、失败建议、接口回执并核对未知结果")
        layout.addWidget(self.tabs, 1)

    def show_capture_tab(self):
        self.tabs.setCurrentIndex(0)

    def show_transfer_tab(self):
        self.tabs.setCurrentIndex(1)

    def is_transfer_tab(self):
        return self.tabs.currentIndex() == 1


class HelpPage(QScrollArea):
    def __init__(self, owner):
        super().__init__(owner)
        self.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        # layout.addWidget(label("操作帮助", "pageTitle"))
        # 2026-10-13：本次修改原因：帮助嵌入设置后使用内容区标题，避免与设置主标题重复抢占空间。
        # layout.addWidget(label("操作帮助", "sectionTitle"))
        # 2026-10-13：本次修改原因：设置左侧分组已显示操作帮助，内容从流程和使用步骤开始。
        layout.addWidget(label("配置 → 获取商品 → 手动 / AI 加工 → 保存校验 → 审核 → ERP 写回 → 查看结果", "muted", True))
        sections = [
            # 2026-10-12：本次修改原因：帮助新增重复同步、进度判读、表格完整编辑及可恢复清理的实际步骤。
            ("1. 配置与获取", "在设置选择采集路线（默认妙手接口），填写妙手 AppKey / AppSecret；文本和图片模型分别填写厂商、URL、API Key、模型名并设为当前。点击“同步妙手采集箱”，查询、勾选并导入。插件路线为备用；白底图可直接创建商品。", "打开设置", lambda: owner.open_settings(0)),
            # ("2. 商品加工与 AI", "按获取方式筛选商品，双击进入编辑页。标题、简易描述、详细描述及图片旁均有 AI 入口。提供主体图、爆款参考或 Prompt，生成后预览、调整，再应用到字段；应用后还需保存商品。视频生成暂未开放。", "进入商品加工", lambda: owner.navigate(0)),
            # ("3. 保存与审核", "保存前检查字数、链接、图片数量和数值。主图最多 15 张，规格一图片每组最多 10 张；超限须调整，输入不会丢失。草稿可缺业务必填项，审核需完善。修改后重新审核当前版本。", "查看采集记录", lambda: owner.navigate(1)),
            # ("4. 写回与发布", "在设置选择新增加工后的商品或更新原商品；当前目标为公共采集箱。新增需独立货源价，更新需可靠的妙手原商品关联。写回前检查账号、方式和问题清单；授权店铺采集箱暂未开放。成功后到妙手认领、编辑并发布。", "配置妙手 ERP", lambda: owner.open_settings(1)),
            # ("5. 图片与失败处理", "本地白底图及 AI 输出需先托管为公网图片链接，当前没有自动素材上传。容量不足需在妙手清理或扩容。失败可查看原因；结果未知不要重复新增，先在妙手找到商品 ID，再只读核对。已传内容再次修改后显示需重传。", "查看回传记录", owner.show_erp_records),
            ("2. 批量同步与重复导入", "查询时可选每页 100/200/500 条，筛选“仅未导入”，点击“勾选未导入”再导入；需要时继续翻页。按账号 + 妙手商品 ID 去重，首次导入和最近同步时间只辅助查找。已有商品直接跳过详情，不覆盖本机加工，也不自动刷新旧商品的远端变化。窗口和底部显示实际完成/导入/跳过/失败数量，结果卡片中查看摘要，采集记录查看逐条原因。读取并发可选 1–3，遇到限流可改为 1 后重试失败商品。", "同步妙手采集箱", owner.import_miaoshou),
            # ("3. 商品加工与 AI", "按获取方式筛选，双击商品编辑。标题、简述、详情和图片旁均有 AI 入口：提供主体图、爆款参考或 Prompt，预览后应用，再保存。单元格双击编辑；长文本/链接可右键“编辑完整内容”或“查看完整内容”。表单可滚动，列宽和行高可拖动。速览主操作固定在底部，来源/关联/核对工具可展开。视频生成暂未开放。", "进入商品加工", lambda: owner.navigate(0)),
            # 2026-10-13：本次修改原因：帮助跟随速览移除后的全宽列表、可选字段列及逐行工具入口。
            # ("3. 商品加工与 AI", "商品列表展示主图、平台/站点、获取方式、SKU/属性、售价币种和处理状态。“显示列”可展开图片/视频、货源 ID、妙手 ID、版本和检查提示。双击商品或点击行内“编辑 / AI”进入分区加工；标题、简述、详情和图片旁有 AI 按钮，预览应用后仍需保存。行内“更多”提供单条回传、货源、原商品关联、完整原始详情、检查提示及未知结果核对；勾选只用于批量操作。编辑表格双击输入，长文本/链接可右键查看完整内容。视频生成暂未开放。", "进入商品加工", lambda: owner.navigate(0)),
            # 2026-10-13：本次修改原因：说明跟随行内操作列撤下后的顶部编辑/更多入口，避免帮助指向已隐藏按钮。
            # ("3. 商品加工与 AI", "商品列表展示主图、平台/站点、获取方式、SKU/属性、售价币种和处理状态。“显示列”可展开图片/视频、货源 ID、妙手 ID、版本和检查提示。双击商品或点击列表上方“编辑 / AI 加工”进入分区加工；标题、简述、详情和图片旁有 AI 按钮，预览应用后仍需保存。“当前商品 · 更多”提供单条回传、货源、原商品关联、完整原始详情、检查提示及未知结果核对；勾选只用于批量操作。编辑表格双击输入，长文本/链接可右键查看完整内容。视频生成暂未开放。", "进入商品加工", lambda: owner.navigate(0)),
            # 2026-10-13：本次修改原因：帮助跟随商品列表左上来源切换区，区分切换展示与实际同步/上传操作。
            ("3. 商品加工与 AI", "商品列表左上切换“采集商品 / 白底图商品”，查看各自的商品；切换只改变展示，不发起请求。采集商品旁“同步妙手采集箱”查询并导入，插件路线显示“导入采集文件”；白底图商品旁“上传白底图”创建商品。双击商品或点击“编辑 / AI 加工”进入编辑，文本和图片旁有 AI 入口，预览应用后仍需保存。“当前商品 · 更多”提供单条回传、货源、原商品关联、原始详情、检查提示及未知结果核对；勾选用于批量操作。“显示列”可展开素材、编号、版本和检查提示。视频生成暂未开放。", "进入商品加工", lambda: owner.navigate(0)),
            # ("4. 保存与审核", "保存前检查字数、链接、图片数量和数值。主图最多 15 张，规格一图片每组最多 10 张；超限须调整，输入不会丢失。草稿可缺业务必填项，审核需完善。修改后重新审核当前版本。", "查看采集记录", lambda: owner.navigate(1)),
            # 2026-10-13：本次修改原因：帮助里的记录入口直接切换到日志中的采集标签，避免停留在上次打开的回传标签。
            ("4. 保存与审核", "保存前检查字数、链接、图片数量和数值。主图最多 15 张，规格一图片每组最多 10 张；超限须调整，输入不会丢失。草稿可缺业务必填项，审核需完善。修改后重新审核当前版本。", "查看采集记录", owner.show_capture_records),
            ("5. 写回与发布", "在设置选择新增副本或更新原商品，当前目标为公共采集箱。新增需独立货源价，更新需可靠的原商品关联；API 导入自动关联。确认账号、方式及问题清单后提交；授权店铺采集箱暂未开放。成功后到妙手认领、编辑并发布。", "配置妙手 ERP", lambda: owner.open_settings(1)),
            ("6. 图片与失败处理", "本地白底图及 AI 输出需先托管为公网图片链接。图片空间不足需在妙手清理或扩容。失败查看原因；结果未知不要重复新增，先在妙手找到商品 ID，再只读核对。已传内容再次修改后显示需重传。", "查看回传记录", owner.show_erp_records),
            # ("7. 清理与恢复", "商品加工勾选后“移除所选”，或“清空当前结果”；采集记录按当前路线清空，回传记录按当前筛选结果清空。操作前显示范围和数量。清理只移除本机列表展示，可通过“恢复回收站/恢复记录”恢复该类全部条目，不删除妙手商品，也不释放本机文件空间。原始材料、版本、去重身份和回传证据保留；回传中、未知结果及仍在解析的条目不能清理。", "进入商品加工", lambda: owner.navigate(0)),
            # 2026-10-13：本次修改原因：帮助明确回收站入口、勾选恢复和永久删除后再次导入的行为。
            # ("7. 回收站与永久删除", "移除后点击侧栏“回收站”或原列表的回收站按钮。选择商品 / 妙手同步记录 / 插件采集记录 / 回传记录，勾选后“恢复所选”或“永久删除所选”；“清空此类回收站”仅清空当前类型。永久删除有范围提示且不能撤销。商品留在回收站时重复同步不会重建，永久删除商品后解除本机去重身份，下次妙手同步可重新导入。仅删除记录不会删除商品或解除商品去重。原始文件、AI 素材和独立回传证据保留；不会删除妙手商品。发送中、未知结果及正在解析条目仍受保护。", "打开回收站", owner.open_recycle_bin),
            # 2026-10-13：本次修改原因：区别删除商品与删除回传记录，明确后者会删除对应接口回执。
            ("7. 回收站与永久删除", "移除后点击侧栏“回收站”或原列表的回收站按钮。选择商品 / 妙手同步记录 / 插件采集记录 / 回传记录，勾选后“恢复所选”或“永久删除所选”；“清空此类回收站”仅清空当前类型。永久删除有范围提示且不能撤销。商品留在回收站时重复同步不会重建，永久删除商品后下次妙手同步可重新导入；独立回传记录保留。仅删除记录不会删除商品或解除商品去重；永久删除回传记录会一并删除其发送快照和接口回执。原始文件、AI 素材保留，不会删除妙手商品。发送中、未知结果及正在解析条目仍受保护。", "打开回收站", owner.open_recycle_bin),
        ]
        for title, text, action, callback in sections:
            frame, contents = card()
            contents.addWidget(label(title, "sectionTitle"))
            contents.addWidget(label(text, "hint", True))
            # contents.addWidget(button(action, callback))
            # 2026-10-13：本次修改原因：帮助按钮以零参数执行原导航回调，避免 clicked 布尔值误作回收站类型或日志来源。
            contents.addWidget(button(action, lambda _checked=False, target=callback: target()))
            layout.addWidget(frame)
        layout.addStretch()
        self.setWidget(body)
