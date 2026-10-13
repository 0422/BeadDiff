# 2026-10-13：本次修改原因：补齐独立回收站，展示已移除内容并支持选择恢复、永久删除及按类型清空。
from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView,
    QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..erp import STATE_LABELS
from .table_support import configure_table
from .widgets import button, card, label
from .workflow_pages import time_text


KINDS = {"products": "商品", "imports": "妙手同步记录", "captures": "插件采集记录", "transfers": "回传记录"}


class RecycleBinPage(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # layout.addWidget(label("回收站", "pageTitle"))
        # layout.addWidget(label("已移除的本机商品和记录在这里管理。勾选后恢复或永久删除；妙手中的商品不受影响。", "hint", True))
        # 2026-10-13：本次修改原因：撤下重复标题与常驻说明，操作区和列表区分别独立成块。
        layout.setSpacing(12)
        frame, contents = card()
        contents.setContentsMargins(16, 12, 16, 12)
        filters = QHBoxLayout()
        self.kind = QComboBox()
        for key, text in KINDS.items():
            self.kind.addItem(text, key)
        self.kind.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.kind)
        self.summary = label("", "muted")
        filters.addWidget(self.summary, 1)
        # filters.addWidget(button("刷新", self.refresh))
        # filters.addWidget(button("返回商品加工", lambda: owner.navigate(0)))
        # 2026-10-13：本次修改原因：撤下与侧栏重复的返回按钮；刷新读取其他实例的本机变化，明确不连接妙手。
        refresh = button("刷新", self.refresh)
        refresh.setToolTip("重新读取本机回收站列表；不请求妙手接口。进入页面、恢复或删除后也会自动刷新。")
        filters.addWidget(refresh)
        contents.addLayout(filters)
        actions = QHBoxLayout()
        self.select_all = QCheckBox("全选当前列表")
        self.select_all.toggled.connect(self.check_all)
        actions.addWidget(self.select_all)
        actions.addStretch()
        self.restore_button = button("恢复所选", lambda: self.apply_action("restore"), primary=True)
        self.delete_button = button("永久删除所选", lambda: self.apply_action("delete"))
        self.clear_button = button("清空此类回收站", lambda: self.apply_action("clear"))
        self.delete_button.setObjectName("danger")
        self.clear_button.setObjectName("danger")
        for item in (self.restore_button, self.delete_button, self.clear_button):
            actions.addWidget(item)
        contents.addLayout(actions)
        # 2026-10-13：本次修改原因：工具块不随窗口纵向拉高，列表使用剩余空间，两块之间留白。
        layout.addWidget(frame)
        list_frame, list_contents = card()
        list_contents.setContentsMargins(12, 12, 12, 12)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["选择", "商品 / 编号", "平台", "移除前状态", "移除时间"])
        configure_table(self.table, editable=False, multiline=True)
        self.table.setProperty("embeddedTable", True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.itemChanged.connect(self.update_actions)
        # contents.addWidget(self.table, 1)
        # self.empty = label("此类回收站为空。", "empty")
        # self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # contents.addWidget(self.empty)
        # 2026-10-13：本次修改原因：删除底部重复空状态文案，数量在操作栏展示；空状态对象保留供刷新调用。
        list_contents.addWidget(self.table, 1)
        self.empty = label("", "empty")
        self.empty.setParent(self)
        self.empty.hide()
        self.scope = label("", "hint", True)
        # contents.addWidget(self.scope)
        # self.feedback = label("选择要恢复或删除的条目。永久删除需要确认且无法撤销。", "hint", True)
        # contents.addWidget(self.feedback)
        # layout.addWidget(frame, 1)
        # 2026-10-13：本次修改原因：删除范围只在危险操作确认时呈现，执行结果由原状态栏反馈。
        self.scope.setParent(self)
        self.scope.hide()
        self.feedback = label("", "hint", True)
        self.feedback.setParent(self)
        self.feedback.hide()
        layout.addWidget(list_frame, 1)

    def open_kind(self, kind: str) -> None:
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        self.refresh()

    def refresh(self, *_args) -> None:
        kind = self.kind.currentData()
        rows = self.owner.repository.recycle_items(kind)
        # 2026-10-13：本次修改原因：切换回收站类型不沿用上一类的勾选状态。
        previous = set(self.selected_ids()) if getattr(self, "_last_kind", kind) == kind else set()
        self._last_kind = kind
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for row, value in enumerate(rows):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            check.setData(Qt.ItemDataRole.UserRole, value["id"])
            check.setCheckState(Qt.CheckState.Checked if value["id"] in previous else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check)
            texts = [value["title"] + "\n" + value["identity"], value["source"].upper(),
                     STATE_LABELS.get(value["state"], value["state"]), time_text(value["hidden_at"])]
            for column, text in enumerate(texts, 1):
                item = QTableWidgetItem(text)
                item.setToolTip(text + ("\n" + value["message"] if value["message"] else ""))
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        self.summary.setText(f"{KINDS[kind]} · {len(rows)} 条")
        # self.empty.setVisible(not rows)
        # 2026-10-13：本次修改原因：空列表沿用操作栏数量，不再额外显示底部文本。
        self.table.setToolTip("此类回收站为空。" if not rows else "勾选要恢复或永久删除的条目。")
        # self.scope.setText(
        #     "永久删除商品会删除本机商品和编辑版本，解除其去重身份；以后同步妙手可重新导入。独立采集记录、原始文件、AI 素材与回传回执保留。"
        #     if kind == "products" else
        #     "永久删除此类记录不会删除关联商品、原始文件或 AI 素材；商品去重身份仍保留。发送中及未知结果不能删除。")
        # 2026-10-13：本次修改原因：按当前类型准确说明永久删除范围，回传记录的接口回执会一并删除。
        scopes = {
            "products": "永久删除商品会删除本机商品和编辑版本，解除去重身份；以后同步妙手可重新导入。保留采集记录、原始文件、AI 素材及独立回传记录。",
            "imports": "永久删除所选妙手同步记录，不删除关联商品、原始文件或 AI 素材，也不解除商品去重身份。旧版首次导入记录仅永久移除展示入口。",
            "captures": "永久删除所选插件采集记录，不删除关联商品、原始文件或 AI 素材，也不解除商品去重身份；正在解析的记录不能删除。",
            "transfers": "永久删除所选回传记录及其发送快照、接口回执，不删除关联商品、原始文件或 AI 素材，也不改变商品已传状态。发送中及未知结果不能删除。",
        }
        self.scope.setText(scopes[kind])
        self.update_actions()

    def selected_ids(self) -> list[str]:
        return [self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(self.table.rowCount())
                if self.table.item(row, 0) and self.table.item(row, 0).checkState() == Qt.CheckState.Checked]

    def check_all(self, checked: bool) -> None:
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.update_actions()

    def update_actions(self, *_args) -> None:
        busy = bool(self.owner._tasks) or self.owner.ai_hub.busy
        selected = len(self.selected_ids())
        self.restore_button.setEnabled(bool(selected) and not busy)
        self.delete_button.setEnabled(bool(selected) and not busy)
        self.clear_button.setEnabled(self.table.rowCount() > 0 and not busy)
        self.select_all.setEnabled(not busy)
        self.select_all.blockSignals(True)
        self.select_all.setChecked(self.table.rowCount() > 0 and selected == self.table.rowCount())
        self.select_all.blockSignals(False)

    def apply_action(self, action: str) -> None:
        if self.owner._tasks or self.owner.ai_hub.busy:
            QMessageBox.information(self, "请等待任务结束", "任务结束后再管理回收站。")
            return
        kind = self.kind.currentData()
        ids = ([self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(self.table.rowCount())]
               if action == "clear" else self.selected_ids())
        if not ids:
            return
        restoring = action == "restore"
        verb = "恢复" if restoring else "永久删除"
        description = ("恢复到原来的本机列表，可继续加工。" if restoring else
                       self.scope.text() + "\n此操作不可撤销；不会删除妙手商品。")
        if not self.owner._confirm_transfer(verb + KINDS[kind], f"{verb} {len(ids)} 条{KINDS[kind]}？\n{description}", "确认" + verb):
            return
        try:
            if restoring:
                count = self.owner.repository.restore_local_items(kind, ids)
                result = f"已恢复 {count} 条。到原列表查看，必要时调整筛选。"
            else:
                outcome = self.owner.repository.purge_local_items(kind, ids)
                result = f"已永久删除 {outcome['deleted']} 条，无法恢复。"
                if outcome["blocked"]:
                    result += f" {outcome['blocked']} 条仍在处理或待核对，已保留。"
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "操作未完成", str(error))
            return
        self.owner.refresh()
        self.feedback.setText(result)
        self.owner.task_progress_text.setText(result)
        self.owner.operation_feedback.setText(result)
        self.owner.statusBar().showMessage(result, 10000)
