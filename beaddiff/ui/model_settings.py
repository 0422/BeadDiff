# 2026-10-11：本次修改原因：设置页按文本/图片分类展示本地配置，支持新增、编辑、删除、切换与手工文件重载。
from __future__ import annotations

from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLineEdit, QMessageBox, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..ai.client import CompatibleClient
from ..ai.config import ModelConfigStore, ModelProfile
from ..assets import AssetStore
from .ai_runner import TaskHub
# 2026-10-13：本次修改原因：模型表沿用统一行高、完整内容查看和主题样式。
from .table_support import configure_table
from .widgets import button, label


class ModelEditDialog(QDialog):
    def __init__(self, profile: ModelProfile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("编辑模型配置" if profile.url or profile.modelname else "新增模型配置")
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(label("文本模型" if profile.category == "text" else "图片模型", "sectionTitle"))
        form = QFormLayout()
        self.fields = {}
        for key, caption in (("name", "配置名称"), ("provider", "厂商 *"), ("url", "URL *"),
                             ("key", "API Key *"), ("modelname", "模型名称 *")):
            editor = QLineEdit(getattr(profile, key))
            editor.setPlaceholderText({"name": "可选，用于区分日常文案、场景图等配置",
                "provider": "厂商或中转服务名称", "url": "https://服务地址 或 https://服务地址/v1",
                "modelname": "填写服务实际支持的模型名称", "key": "填写 API Key"}[key])
            self.fields[key] = editor
            if key == "key":
                row = QHBoxLayout()
                editor.setEchoMode(QLineEdit.EchoMode.Password)
                row.addWidget(editor)
                show = QCheckBox("显示")
                # show.toggled.connect(lambda checked: editor.setEchoMode(
                #     QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
                # show.toggled.disconnect()
                # 2026-10-11：本次修改原因：捕获密钥编辑器，避免循环结束后指向模型名称输入框。
                show.toggled.connect(lambda checked, target=editor: target.setEchoMode(
                    QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
                row.addWidget(show)
                form.addRow(caption, row)
            else:
                form.addRow(caption, editor)
        layout.addLayout(form)
        advanced = QGroupBox("高级调用选项")
        options = QFormLayout(advanced)
        self.vision = QCheckBox("此模型支持图片理解（爆款图片分析／看图写文案）")
        self.vision.setChecked(profile.supports_vision)
        self.vision.setVisible(profile.category == "text")
        options.addRow(self.vision)
        self.mode = QComboBox()
        for caption, value in (("自动：单图编辑，多图聊天生图", "auto"),
                               ("图片接口：generations / edits", "images"), ("聊天生图：chat/completions", "chat")):
            self.mode.addItem(caption, value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(profile.image_mode)))
        if profile.category == "image":
            options.addRow("图片接口模式", self.mode)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 1800)
        self.timeout.setSuffix(" 秒")
        self.timeout.setValue(profile.timeout)
        options.addRow("请求超时", self.timeout)
        layout.addWidget(advanced)
        layout.addWidget(label("四项基本信息用于兼容协议服务。可保存未填完整的草稿；设为当前前需要补齐。", "hint", True))
        layout.addStretch()
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("取消", self.reject))
        actions.addWidget(button("保存配置", self.accept, primary=True))
        layout.addLayout(actions)

    def value(self) -> ModelProfile:
        return ModelProfile(id=self.profile.id, category=self.profile.category,
            **{key: editor.text().strip() for key, editor in self.fields.items()},
            image_mode=str(self.mode.currentData()), supports_vision=self.vision.isChecked(), timeout=self.timeout.value())


class ModelSettingsPage(QWidget):
    def __init__(self, store: ModelConfigStore, assets: AssetStore, hub: TaskHub, parent=None):
        super().__init__(parent)
        self.store, self.assets, self.hub = store, assets, hub
        self.checking = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)
        # row = QHBoxLayout()
        # row.addWidget(label("AI 模型", "sectionTitle"))
        # 2026-10-13：本次修改原因：设置分组已显示 AI 模型，撤下重复标题与常驻说明。
        # row.addStretch()
        self.reload_button = button("重新加载配置", self.reload)
        # row.addWidget(self.reload_button)
        # layout.addLayout(row)
        # 2026-10-13：本次修改原因：重新加载配置移至页内右下角，顶部直接呈现模型分类。
        # layout.addWidget(label(str(store.path), "muted", True))
        # layout.addWidget(label("文本与图片分别选择当前模型。新增任务使用当前项；模型数据只保存在本机配置文件。", "hint", True))
        # 2026-10-13：本次修改原因：配置路径仍可在重新加载按钮的悬停提示查看，系统设置集中展示存储目录。
        self.reload_button.setToolTip("配置文件：" + str(store.path))
        self.error = label("", "warning", True)
        layout.addWidget(self.error)
        self.tabs = QTabWidget()
        # self.tabs.setToolTip("文本与图片分别选择当前模型，新增任务使用当前配置。")
        # 2026-10-13：本次修改原因：分类标签各有边界，配置区统一圆角框，取消整页悬停提示遮挡操作。
        self.tabs.setObjectName("modelTabs")
        self.tabs.tabBar().setObjectName("modelTypeTabs")
        self.tabs.tabBar().setExpanding(False)
        self.tables: dict[str, QTableWidget] = {}
        self.current_labels = {}
        self.controls = []
        for kind, caption in (("text", "文本模型"), ("image", "图片模型")):
            page = QWidget()
            contents = QVBoxLayout(page)
            self.current_labels[kind] = label("", "hint", True)
            # contents.addWidget(self.current_labels[kind])
            # 2026-10-13：本次修改原因：当前模型已由状态列标识，撤下重复文本，保留原刷新对象。
            self.current_labels[kind].setParent(page)
            self.current_labels[kind].hide()
            contents.setContentsMargins(16, 16, 16, 16)
            contents.setSpacing(12)
            actions = QHBoxLayout()
            for text, callback in (("新增", lambda _checked=False, kind=kind: self.edit(kind)),
                    ("编辑", lambda _checked=False, kind=kind: self.edit(kind, self.selected(kind))),
                    ("删除", lambda _checked=False, kind=kind: self.remove(kind)),
                    ("设为当前", lambda _checked=False, kind=kind: self.activate(kind)),
                    ("检查接口", lambda _checked=False, kind=kind: self.check(kind))):
                control = button(text, callback, primary=text == "新增")
                self.controls.append(control)
                actions.addWidget(control)
            actions.addStretch()
            contents.addLayout(actions)
            table = QTableWidget(0, 5)
            table.setHorizontalHeaderLabels(["状态", "配置名称", "厂商", "URL", "模型名称"])
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.verticalHeader().hide()
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            table.setColumnWidth(0, 85)
            table.setColumnWidth(1, 155)
            table.setColumnWidth(2, 120)
            table.setColumnWidth(4, 180)
            table.cellDoubleClicked.connect(lambda _r, _c, kind=kind: self.activate(kind))
            configure_table(table, editable=False)
            # 2026-10-13：本次修改原因：设置内容区已有圆角边界，模型列表取消叠加的表格外框。
            table.setProperty("embeddedTable", True)
            self.tables[kind] = table
            contents.addWidget(table, 1)
            # contents.addWidget(label("双击配置可切换当前项；API Key 在编辑窗口中查看。接口检查仅访问模型列表，不发起生成。", "hint", True))
            # 2026-10-13：本次修改原因：重复操作说明改为悬停提示，当前模型、检查结果与错误反馈仍直接显示。
            table.setToolTip("双击配置切换当前项；API Key 在编辑窗口查看。接口检查仅访问模型列表，不发起生成。")
            self.tabs.addTab(page, caption)
        video = QWidget()
        video_layout = QVBoxLayout(video)
        video_layout.addWidget(label("AI 视频生成暂未开放，已预留模型提交、进度查询和结果接口。", "empty", True))
        video_layout.addStretch()
        self.tabs.addTab(video, "视频 · 预留")
        layout.addWidget(self.tabs, 1)
        self.status = label("", "hint", True)
        # layout.addWidget(self.status)
        # 2026-10-13：本次修改原因：底部反馈与重新加载按钮共用一行，右下角位置保持稳定。
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.reload_button)
        layout.addLayout(footer)
        self.refresh()

    def refresh(self):
        self.error.setText(self.store.error)
        self.error.setVisible(bool(self.store.error))
        for kind, table in self.tables.items():
            rows = [row for row in self.store.profiles if row.category == kind]
            selected = self.selected(kind)
            table.setRowCount(len(rows))
            for index, profile in enumerate(rows):
                current = self.store.active[kind] == profile.id
                values = ["当前使用" if current else ("草稿" if profile.problems() else "可使用"),
                          profile.caption, profile.provider, profile.url, profile.modelname]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    item.setData(Qt.ItemDataRole.UserRole, profile.id)
                    table.setItem(index, column, item)
                if profile.id == selected:
                    table.selectRow(index)
            if rows and table.currentRow() < 0:
                table.selectRow(0)
            current = next((row for row in rows if row.id == self.store.active[kind]), None)
            self.current_labels[kind].setText("当前使用：" + (current.caption if current else "尚未选择，请选中一项并设为当前"))
        for control in self.controls:
            control.setEnabled(not self.store.error and not self.checking)

    def selected(self, kind: str) -> str:
        table = self.tables[kind]
        row = table.currentRow()
        item = table.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def reload(self):
        self.store.reload()
        self.refresh()
        self.status.setText("已重新加载本地配置。" if not self.store.error else "请修正文件后重新加载。")

    def edit(self, kind: str, profile_id: str = ""):
        profile = next((p for p in self.store.profiles if p.id == profile_id), None)
        if not profile:
            profile = ModelProfile(uuid4().hex, kind)
        dialog = ModelEditDialog(profile, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.store.save(dialog.value())
                self.status.setText("配置已保存；选中配置并设为当前即可使用。")
                self.refresh()
            except (ValueError, OSError) as error:
                QMessageBox.warning(self, "未能保存模型配置", str(error))

    def remove(self, kind: str):
        selected = self.selected(kind)
        if not selected:
            return
        note = "删除当前配置后，此类别会恢复为未选择状态。" if self.store.active[kind] == selected else ""
        # if QMessageBox.question(self, "删除模型配置", "确认删除所选配置？" + note) != QMessageBox.StandardButton.Yes:
        # 2026-10-13：本次修改原因：删除配置的默认焦点为取消，保留原删除行为。
        if QMessageBox.question(self, "删除模型配置", "确认删除所选配置？" + note,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.remove(selected)
            self.refresh()
            self.status.setText("配置已从本地文件移除。")
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "删除失败", str(error))

    def activate(self, kind: str):
        selected = self.selected(kind)
        if not selected:
            return
        try:
            self.store.activate(selected)
            self.refresh()
            self.status.setText("当前模型已切换，新任务立即使用此配置。")
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "无法切换", str(error))

    def check(self, kind: str):
        try:
            profile = self.store.get(self.selected(kind), kind)
        except ValueError as error:
            QMessageBox.warning(self, "模型配置", str(error))
            return
        self.checking = True
        self.refresh()
        self.reload_button.setEnabled(False)
        # 2026-10-13：本次修改原因：连接检查期间原按钮展示 loading 文案，不发起生成请求。
        for control in self.controls:
            if control.text() == "检查接口":
                control.setText("正在检查…")
        self.status.setText("正在检查鉴权与模型列表…")
        self.hub.submit(lambda _progress: CompatibleClient(profile, self.assets).check(), self.check_done, self.check_done)

    def check_done(self, message):
        self.checking = False
        for control in self.controls:
            if control.text() == "正在检查…":
                control.setText("检查接口")
        self.reload_button.setEnabled(True)
        self.refresh()
        self.status.setText(str(message))


class ModelSettingsDialog(QDialog):
    def __init__(self, store: ModelConfigStore, assets: AssetStore, hub: TaskHub, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 模型设置")
        self.resize(1000, 640)
        layout = QVBoxLayout(self)
        self.page = ModelSettingsPage(store, assets, hub, self)
        layout.addWidget(self.page)
        layout.addWidget(button("完成", self.accept, primary=True))

    def done(self, result):
        if self.page.checking:
            QMessageBox.information(self, "正在检查", "请等待接口检查完成后关闭。")
            return
        super().done(result)
