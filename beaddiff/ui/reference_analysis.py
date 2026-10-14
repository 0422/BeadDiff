# 2026-10-13：本次修改原因：提供独立爆款分析与本机 Prompt 库，提前准备参考方案供商品 AI 加工选择。
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QProgressBar, QTabWidget, QVBoxLayout, QWidget,
)

from ..ai.contracts import AIRequest
from ..ai.references import VISUAL_GUIDE
from ..ai.workflow import safe_error
from .ai_workbench import compact_combo, scroll_content
from .layout_support import PersistentSplitter
from .media_list import MediaList
# from .model_settings import ModelSettingsDialog
# 2026-10-14：本次修改原因：业务页面不再打开模型设置弹窗。
# 模型配置统一从设置页进入。
# 2026-10-14：本次修改原因：爆款分析 Prompt 长文按内容增高，超过上限后在控件内滚动。
from .widgets import AutoHeightTextEdit, button, card, label


class ReferenceAnalysisPage(QWidget):
    def __init__(self, service, hub, store, parent=None):
        super().__init__(parent)
        self.service, self.hub, self.store = service, hub, store
        self.busy = False
        self.identifier = ""
        self.baseline = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.splitter = PersistentSplitter(Qt.Orientation.Horizontal, "ui/references/library_editor_v1", [300, 800], self)
        library, left = card()
        library.setMinimumWidth(240)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索方案名称 / Prompt")
        self.search.textChanged.connect(self.filter_rows)
        left.addWidget(self.search)
        self.records = QListWidget()
        self.records.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.records.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.records.currentItemChanged.connect(self.select_record)
        left.addWidget(self.records, 1)
        actions = QHBoxLayout()
        self.new_button = button("新增方案", self.new_record, primary=True)
        self.delete_button = button("删除方案", self.delete_record)
        actions.addWidget(self.new_button)
        actions.addWidget(self.delete_button)
        left.addLayout(actions)
        self.empty = label("尚无方案。可分析参考素材，也可直接填写 Prompt 保存。", "hint", True)
        left.addWidget(self.empty)
        self.splitter.addWidget(library)
        editor, right = card()
        editor.setMinimumWidth(460)
        self.name = QLineEdit()
        self.name.setPlaceholderText("方案名称，例如：家居收纳 · 柔光简约")
        right.addWidget(self.name)
        self.tabs = QTabWidget()
        inputs = QWidget()
        contents = QVBoxLayout(inputs)
        contents.setContentsMargins(12, 12, 12, 12)
        contents.setSpacing(12)
        contents.addWidget(label("参考标题、卖点与分析要求", "panelTitle"))
        # self.material = QPlainTextEdit()
        # 2026-10-14：本次修改原因：参考素材说明较长时随内容增高，过长后在控件内滚动。
        self.material = AutoHeightTextEdit(maximum_lines=8)
        self.material.setPlaceholderText("粘贴参考标题、简述、详情，或填写想提炼的风格。商品链接只作为备注，当前不会自动抓取链接内容。")
        self.material.setMinimumHeight(150)
        contents.addWidget(self.material)
        contents.addWidget(label("参考商品图片", "panelTitle"))
        self.images = MediaList([], {}, service.assets)
        contents.addWidget(self.images)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        # self.models = compact_combo()
        # form.addRow("分析模型", self.models)
        # 2026-10-14：本次修改原因：分析页显示设置中的当前文本模型，不提供重复的模型选择器。
        self.models = label("", "hint", True)
        form.addRow("当前分析模型", self.models)
        contents.addLayout(form)
        model_row = QHBoxLayout()
        # model_row.addWidget(button("模型配置", self.configure_models))
        # 2026-10-14：本次修改原因：移除重复弹窗入口。
# 模型配置只在设置页保留。
        model_row.addStretch()
        self.analyze_button = button("分析并提炼 Prompt", self.analyze, primary=True)
        # model_row.addWidget(self.analyze_button)
        # 2026-10-13：本次修改原因：参考素材较长时仍可直接分析，将主操作移到固定页脚。
        # 分析操作固定在页面底部，与保存方案保持可见。
        contents.addLayout(model_row)
        # contents.addWidget(label("使用内置电商视觉分析指引，提炼光感、排布、文案结构和图片次序；当前未接入 ec-visual-skill 原文。", "hint", True))
        # 2026-10-13：本次修改原因：页面说明关注操作用途，第三方接入边界在交付说明中记录。
        contents.addWidget(label("提炼光感、排布、文案结构和图片次序。分析后可编辑参考 Prompt，保存供商品加工复用。", "hint", True))
        contents.addStretch()
        self.tabs.addTab(scroll_content(inputs), "参考素材")
        output = QWidget()
        output_layout = QVBoxLayout(output)
        output_layout.setContentsMargins(12, 12, 12, 12)
        # self.prompt = QPlainTextEdit()
        # 2026-10-14：本次修改原因：分析结果和手动 Prompt 长文保持可见且不挤出底部操作。
        self.prompt = AutoHeightTextEdit(maximum_lines=12)
        self.prompt.setPlaceholderText("分析结果显示在这里，可手动编辑，也可直接粘贴现成 Prompt。保存后可在商品加工 → AI 处理 → Prompt 方案中选择。")
        output_layout.addWidget(self.prompt, 1)
        self.tabs.addTab(output, "参考 Prompt")
        right.addWidget(self.tabs, 1)
        self.status = label("", "hint", True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.hide()
        right.addWidget(self.progress)
        # save_row = QHBoxLayout()
        # save_row.addStretch()
        # 2026-10-13：本次修改原因：分析和保存均固定显示，避免滚动查找主操作。
        save_row = QHBoxLayout()
        save_row.addWidget(self.analyze_button)
        save_row.addStretch()
        self.save_button = button("保存方案", self.save, primary=True)
        save_row.addWidget(self.save_button)
        right.addLayout(save_row)
        self.splitter.addWidget(editor)
        root.addWidget(self.splitter)
        self.shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.shortcut.activated.connect(self.save)
        self.refresh()
        self.baseline = self.snapshot()

    def record(self):
        return {"id": self.identifier, "name": self.name.text().strip(), "material": self.material.toPlainText(),
                "images": self.images.toPlainText().splitlines(), "prompt": self.prompt.toPlainText()}

    def snapshot(self):
        return json.dumps(self.record(), ensure_ascii=False, sort_keys=True)

    def can_leave(self):
        if self.busy:
            self.status.setText("分析正在进行，请等待完成后切换页面。")
            return False
        if self.baseline and self.snapshot() != self.baseline:
            answer = QMessageBox.question(self, "尚未保存的爆款方案", "保存此方案后再离开？",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Save:
                return self.save()
            self.load(next((row for row in getattr(self, "rows", []) if row["id"] == self.identifier), {}))
        return True

    def refresh(self):
        try:
            self.rows = self.store.list()
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return
        self.records.blockSignals(True)
        self.records.clear()
        for row in self.rows:
            item = QListWidgetItem(row["name"])
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            item.setToolTip(row.get("updated_at", "") + "\n" + row["prompt"][:250])
            self.records.addItem(item)
            if row["id"] == self.identifier:
                self.records.setCurrentItem(item)
        self.records.blockSignals(False)
        self.empty.setVisible(not self.rows)
        self.delete_button.setEnabled(bool(self.identifier) and not self.busy)
        self.filter_rows()
        # old = self.models.currentData() or self.service.config.active.get("text")
        # self.models.clear()
        # for profile in self.service.config.profiles:
        #     if profile.category == "text" and not profile.problems():
        #         self.models.addItem(profile.caption, profile.id)
        # self.models.setCurrentIndex(self.models.findData(old))
        # 2026-10-14：本次修改原因：只读显示当前模型；缺配置时给出设置位置。
        from ..ai.product_plan import active_model
        try:
            self.models.setText(active_model(self.service, "text").caption)
        except ValueError:
            self.models.setText("尚未配置，请到设置 → AI 模型选择当前文本模型。")

    def filter_rows(self):
        query = self.search.text().strip().casefold()
        lookup = {row["id"]: row for row in getattr(self, "rows", [])}
        for index in range(self.records.count()):
            item = self.records.item(index)
            row = lookup.get(item.data(Qt.ItemDataRole.UserRole), {})
            item.setHidden(query not in (row.get("name", "") + " " + row.get("prompt", "")).casefold())

    def select_record(self, current, previous):
        if not current:
            return
        identifier = current.data(Qt.ItemDataRole.UserRole)
        if identifier == self.identifier:
            return
        if not self.can_leave():
            self.records.blockSignals(True)
            for index in range(self.records.count()):
                if self.records.item(index).data(Qt.ItemDataRole.UserRole) == self.identifier:
                    self.records.setCurrentRow(index)
                    break
            else:
                self.records.setCurrentRow(-1)
            self.records.blockSignals(False)
            return
        self.load(next(row for row in self.rows if row["id"] == identifier))

    def load(self, row):
        self.identifier = row.get("id", "")
        self.name.setText(row.get("name", ""))
        self.material.setPlainText(row.get("material", ""))
        self.images.set_urls(row.get("images", []))
        self.prompt.setPlainText(row.get("prompt", ""))
        self.baseline = self.snapshot()
        self.delete_button.setEnabled(bool(self.identifier))
        self.status.setText("")
        # self.tabs.setCurrentIndex(1 if self.identifier else 0)
        # 2026-10-13：本次修改原因：保存后切换方案同步左侧高亮，避免列表选中项与右侧内容不一致。
        self.tabs.setCurrentIndex(1 if self.identifier else 0)
        self.records.blockSignals(True)
        self.records.setCurrentRow(next((index for index in range(self.records.count())
            if self.records.item(index).data(Qt.ItemDataRole.UserRole) == self.identifier), -1))
        self.records.blockSignals(False)

    def new_record(self):
        if self.can_leave():
            self.load({})
            self.records.blockSignals(True)
            self.records.setCurrentRow(-1)
            self.records.blockSignals(False)
            self.name.setFocus()

    def save(self):
        if self.busy:
            return False
        try:
            row = self.store.save(self.record())
        except (ValueError, OSError) as error:
            self.status.setText("未保存：" + str(error))
            return False
        self.identifier = row["id"]
        self.baseline = self.snapshot()
        self.refresh()
        self.status.setText("已保存，可在商品加工 → AI 处理 → Prompt 方案中选择。")
        return True

    def delete_record(self):
        if self.busy or not self.identifier:
            return
        if QMessageBox.warning(self, "删除爆款方案", "删除此方案？已应用到商品的内容和历史生成记录不受影响。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete(self.identifier)
        except (ValueError, OSError) as error:
            self.status.setText("删除失败：" + str(error))
            return
        self.load({})
        self.refresh()
        self.status.setText("方案已删除。共享素材文件保留。")

    # def configure_models(self):
    #     ModelSettingsDialog(self.service.config, self.service.assets, self.hub, self).exec()
    #     self.refresh()
    # 2026-10-14：本次修改原因：业务页不再编辑模型配置。
    # 模型设置弹窗入口已移到设置页。

    def set_busy(self, busy):
        self.busy = busy
        for control in (self.records, self.new_button, self.delete_button, self.tabs, self.name, self.save_button):
            control.setEnabled(not busy)
        self.delete_button.setEnabled(not busy and bool(self.identifier))
        self.progress.setVisible(busy)
        self.analyze_button.setText("正在分析…" if busy else "分析并提炼 Prompt")

    def analyze(self):
        if self.busy:
            return
        images = self.images.toPlainText().splitlines()
        if not images and not self.material.toPlainText().strip():
            self.status.setText("请提供参考图片或参考文案。")
            return
        try:
            # identifier = self.models.currentData()
            # if not identifier:
            #     raise ValueError("请先选择文本模型，或在模型配置中新增。")
            # profile = self.service.config.get(identifier, "text")
            # if images and not profile.supports_vision:
            #     raise ValueError("参考图片分析需要启用图片理解的文本模型。")
            # 2026-10-14：本次修改原因：分析提交时读取当前文本配置，并验证图片理解能力。
            from ..ai.product_plan import active_model
            profile = active_model(self.service, "text", bool(images))
            identifier = profile.id
            self.models.setText(profile.caption)
        except ValueError as error:
            self.status.setText(str(error))
            return
        if self.prompt.toPlainText().strip() and QMessageBox.question(self, "重新分析", "新分析结果会替换当前 Prompt，继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        request = AIRequest("reference_analysis", {"id": "reference-" + (self.identifier or "draft")},
            model_id=identifier, instruction=VISUAL_GUIDE, language="中文",
            reference_text=self.material.toPlainText(), reference_images=images)
        self.set_busy(True)
        self.status.setText("正在分析参考素材…")
        self.hub.submit(lambda report: self.service.generate(request, report), self.finished, self.failed, self.status.setText)

    def finished(self, result):
        self.set_busy(False)
        # self.prompt.setPlainText(result.candidates[0] if result.candidates else "")
        # 2026-10-13：本次修改原因：空分析响应保留已有方案文字。
        if not result.candidates or not result.candidates[0].strip():
            self.status.setText("未返回有效分析结果，原 Prompt 已保留。")
            return
        self.prompt.setPlainText(result.candidates[0])
        self.tabs.setCurrentIndex(1)
        self.status.setText("分析完成。可编辑 Prompt，确认后保存方案。")

    def failed(self, message):
        self.set_busy(False)
        self.status.setText("分析失败：" + safe_error(self.service, message) + "。原 Prompt 已保留。")


class PackageTrackingPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        frame, layout = card()
        layout.addStretch()
        title = label("包裹追踪 · 待接入", "sectionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        message = label("已预留页面，尚未接入物流查询服务。", "muted", True)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        layout.addStretch()
        root.addWidget(frame)
