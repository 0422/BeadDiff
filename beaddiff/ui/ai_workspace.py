# 2026-10-11：本次修改原因：字段按钮与白底图商品共用生成面板，区分主体/风格素材，支持候选编辑、套图排序和单张重做。
from __future__ import annotations

from dataclasses import asdict
import json

# from PySide6.QtCore import Qt
# 2026-10-13：本次修改原因：独立的关闭信号避开原AI任务finished回调名称，内嵌候选生命周期不改任务逻辑。
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from ..ai.contracts import AIRequest, AIResult
from ..ai.service import AIService, facts
from ..content import detail_html, description_images
from .ai_runner import TaskHub
# 2026-10-13：本次修改原因：AI 输入/候选区域复用可记忆分栏，生成请求和应用规则保持原样。
from .layout_support import PersistentSplitter, Panel, save_splitters
from .media_list import MediaList
from .model_settings import ModelSettingsDialog
from .widgets import ImagePreview, button, label


TITLES = {"title": "AI 产品标题", "simple_description": "AI 简易描述", "description_html": "AI 图文详情",
          "image": "AI 商品改图", "image_set": "AI 商品套图"}


class AIWorkspace(QDialog):
    closed = Signal(int)
    def __init__(self, service: AIService, hub: TaskHub, product: dict, operation: str, network,
                 subject: str = "", parent=None):
        super().__init__(parent)
        self.service, self.hub, self.product, self.operation = service, hub, product, operation
        self.is_image = operation in {"image", "image_set"}
        self.busy = False
        self.result: AIResult | None = None
        self.applied_text = ""
        self.applied_assets: list[str] = []
        self.apply_mode = "replace"
        self.replacement_row: int | None = None
        self.history_rows = []
        self.setWindowTitle(TITLES[operation])
        self.resize(1280, 850)
        self.setMinimumSize(1100, 700)
        root = QVBoxLayout(self)
        heading = QHBoxLayout()
        heading.addWidget(label(TITLES[operation], "sectionTitle"))
        heading.addStretch()
        self.settings_button = button("模型设置", self.configure_models)
        heading.addWidget(self.settings_button)
        root.addLayout(heading)
        # splitter = QSplitter()
        # 2026-10-13：本次修改原因：内嵌到编辑器右侧时上下排列，避免窄侧栏塞入两列图片工具。
        splitter = PersistentSplitter(Qt.Orientation.Vertical, "ui/ai_workspace/input_output_splitter_v1", [420, 380], self)
        inputs = QWidget()
        left = QVBoxLayout(inputs)
        form = QFormLayout()
        self.models = QComboBox()
        form.addRow("本次模型", self.models)
        self.language = QComboBox()
        self.language.setEditable(True)
        self.language.addItems(["English", "中文", "Deutsch", "Français", "日本語", "Español"])
        form.addRow("目标语言", self.language)
        self.count = QSpinBox()
        self.count.setRange(1, 4)
        self.count.setValue(1 if self.is_image or operation == "description_html" else 3)
        if operation != "image_set":
            form.addRow("候选数量", self.count)
        self.size = QComboBox()
        self.size.setEditable(True)
        self.size.addItems(["1024x1024", "1536x1024", "1024x1536", "2048x2048", "3840x2160"])
        if self.is_image:
            form.addRow("期望图片尺寸", self.size)
        left.addLayout(form)
        self.instruction = QPlainTextEdit()
        self.instruction.setPlaceholderText("例如：保留商品主体，参考爆款图的柔和光影和场景；突出已确认的商品卖点。")
        self.instruction.setMinimumHeight(95)
        left.addWidget(label("处理要求 / Prompt", "hint"))
        left.addWidget(self.instruction)
        left.addWidget(label("爆款参考文案 / 提炼后的风格", "hint"))
        self.reference_text = QPlainTextEdit()
        self.reference_text.setPlaceholderText("粘贴参考标题、描述，或已提炼的风格 Prompt")
        self.reference_text.setMinimumHeight(85)
        left.addWidget(self.reference_text)
        images = list(dict.fromkeys(product.get("images", []) + product.get("detail_images", [])
            + [sku.get("image", "") for sku in product.get("skus", []) if sku.get("image")]
            + description_images(product.get("description_html", ""))))
        add_row = QHBoxLayout()
        self.product_images = QComboBox()
        self.product_images.addItem("从当前商品选择图片…", "")
        for index, address in enumerate(images):
            self.product_images.addItem(f"商品图片 {index + 1} · {address[-50:]}", address)
        add_row.addWidget(self.product_images, 1)
        add_row.addWidget(button("加入主体", self.add_subject))
        left.addLayout(add_row)
        initial = subject or (images[0] if images else "")
        # self.subjects = MediaList([initial] if initial and self.is_image else [], product.get("image_sizes", {}), service.assets)
        # 2026-10-11：本次修改原因：白底图看图写文案也能使用主体图，纯文本任务可关闭图片理解。
        self.subjects = MediaList([initial] if initial else [], product.get("image_sizes", {}), service.assets)
        self.use_subject = QCheckBox("结合商品主体图写文案（需文本模型支持图片理解）")
        self.use_subject.setChecked(product.get("source") == "upload")
        self.use_subject.setVisible(not self.is_image)
        left.addWidget(self.use_subject)
        left.addWidget(label("商品主体图 · 多张可用于提供不同实物角度", "hint"))
        left.addWidget(self.subjects)
        self.references = MediaList([], {}, service.assets)
        left.addWidget(label("爆款风格参考图 · 与商品主体分开", "hint"))
        left.addWidget(self.references)
        self.analyze_button = button("分析参考 / 提炼 Prompt", self.analyze)
        left.addWidget(self.analyze_button)
        if operation == "image_set":
            left.addWidget(label("套图用途与排布 · 每行一张，行顺序即图片顺序", "hint"))
        self.slots = QPlainTextEdit("主图：完整展示商品主体，干净背景\n场景图：展示使用场景，主体清晰\n细节图：突出实际可见的材质与结构\n卖点图：仅表现已确认的卖点，预留文案区")
        self.slots.setMinimumHeight(110)
        self.slots.setVisible(operation == "image_set")
        left.addWidget(self.slots)
        self.keep_images = QCheckBox("生成详情时保留当前详情图片")
        self.keep_images.setChecked(True)
        self.keep_images.setVisible(operation == "description_html")
        left.addWidget(self.keep_images)
        summary = QPlainTextEdit(json.dumps(facts(product), ensure_ascii=False, indent=2))
        summary.setReadOnly(True)
        summary.setMaximumHeight(120)
        left.addWidget(label("本次商品事实 · 如需修正，请返回商品编辑", "hint"))
        left.addWidget(summary)
        left.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inputs)
        # 2026-10-11：本次修改原因：提交时冻结输入，重做期间保护候选次序。
        self.inputs = inputs
        # splitter.addWidget(scroll)
        scroll.setMinimumSize(0, 0)
        # splitter.addWidget(Panel("生成要求与参考素材", scroll))
        # 2026-10-13：本次修改原因：用户主动进入 AI 后展开操作表单，辅助区默认收起不隐藏正在使用的主界面。
        splitter.addWidget(Panel("生成要求与参考素材", scroll, default_collapsed=False))
        outputs = QWidget()
        right = QVBoxLayout(outputs)
        history_row = QHBoxLayout()
        self.history = QComboBox()
        self.history.addItem("选择历史候选…", "")
        history_row.addWidget(self.history, 1)
        history_row.addWidget(button("载入", self.load_history))
        right.addLayout(history_row)
        self.candidates = QListWidget()
        self.candidates.setMinimumHeight(170)
        self.candidates.currentRowChanged.connect(self.select_candidate)
        right.addWidget(self.candidates, 1)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("生成后在这里预览和编辑候选，再应用到当前字段。")
        self.text.setMinimumHeight(200)
        self.text.textChanged.connect(self.edit_candidate)
        right.addWidget(self.text, 1)
        self.preview = ImagePreview(network, 260)
        self.preview.setVisible(False)
        right.addWidget(self.preview)
        ordering = QHBoxLayout()
        self.up = button("上移", lambda: self.move_candidate(-1))
        self.down = button("下移", lambda: self.move_candidate(1))
        self.redo = button("重做选中图", self.regenerate)
        for control in (self.up, self.down, self.redo):
            control.setVisible(self.is_image)
            ordering.addWidget(control)
        ordering.addStretch()
        right.addLayout(ordering)
        self.application = QComboBox()
        self.application.addItem("替换当前图片", "replace")
        self.application.addItem("追加到图片组", "append")
        if operation == "image_set":
            self.application.addItem("替换整套图片（应用勾选项）", "replace_set")
            self.application.setCurrentIndex(1)
        self.application.setVisible(self.is_image)
        right.addWidget(self.application)
        right.addWidget(label("图片可勾选、排序后应用；尺寸以实际生成结果为准。套图每张独立请求，部分失败会保留成功项。", "hint", True))
        # splitter.addWidget(outputs)
        # splitter.setSizes([600, 580])
        # 2026-10-13：本次修改原因：候选区内部滚动，高 DPI/小窗口下不裁掉应用和排序控件。
        output_scroll = QScrollArea()
        output_scroll.setWidgetResizable(True)
        output_scroll.setWidget(outputs)
        output_scroll.setMinimumSize(0, 0)
        # splitter.addWidget(Panel("候选预览与历史", output_scroll))
        splitter.addWidget(Panel("候选预览与历史", output_scroll, default_collapsed=False))
        root.addWidget(splitter, 1)
        self.status = label("生成候选将留档；应用只更新编辑表单，保存商品后才形成新版本。", "hint", True)
        root.addWidget(self.status)
        footer = QHBoxLayout()
        self.generate_button = button("生成候选", self.generate, primary=True)
        footer.addWidget(self.generate_button)
        footer.addStretch()
        footer.addWidget(button("关闭", self.reject))
        self.apply_button = button("应用到当前字段", self.apply, primary=True)
        self.apply_button.setEnabled(False)
        footer.addWidget(self.apply_button)
        root.addLayout(footer)
        self.reload_models()
        self.reload_history()

    def reload_models(self):
        kind = "image" if self.is_image else "text"
        old = self.models.currentData()
        self.models.clear()
        for profile in self.service.config.profiles:
            if profile.category == kind and not profile.problems():
                suffix = " · 当前" if profile.id == self.service.config.active[kind] else ""
                self.models.addItem(profile.caption + suffix, profile.id)
        selected = old or self.service.config.active[kind]
        index = self.models.findData(selected)
        # 没有当前项时不静默选择别的配置，用户可明确在本次模型中临时选择。
        self.models.setCurrentIndex(index)

    def configure_models(self):
        ModelSettingsDialog(self.service.config, self.service.assets, self.hub, self).exec()
        self.reload_models()

    def add_subject(self):
        address = self.product_images.currentData()
        if address:
            self.subjects.set_urls(self.subjects.toPlainText().splitlines() + [address])

    def request(self, operation: str | None = None) -> AIRequest:
        operation = operation or self.operation
        model_id = str(self.models.currentData() or "")
        # if operation == "reference_analysis":
        # 2026-10-11：本次修改原因：文本页参考分析遵循本次文本模型，图片页使用当前文本模型分析。
        if operation == "reference_analysis" and self.is_image:
            model_id = self.service.config.active["text"]
        if not model_id:
            raise ValueError("请在设置中选择当前模型，或在本次模型列表中明确选择配置。")
        return AIRequest(operation, dict(self.product), model_id, self.instruction.toPlainText().strip(),
            self.language.currentText().strip(), self.reference_text.toPlainText().strip(),
            # self.subjects.toPlainText().splitlines(), self.references.toPlainText().splitlines(),
            # 2026-10-11：本次修改原因：只在勾选看图写文案时发送文本任务的商品图片。
            self.subjects.toPlainText().splitlines() if self.is_image or self.use_subject.isChecked() else [],
            self.references.toPlainText().splitlines(),
            self.size.currentText().strip(), self.count.value(),
            [line.strip() for line in self.slots.toPlainText().splitlines() if line.strip()])

    def generate(self):
        self.replacement_row = None
        try:
            self.start(self.request())
        except ValueError as error:
            QMessageBox.warning(self, "请完善生成要求", str(error))

    def analyze(self):
        self.replacement_row = None
        try:
            request = self.request("reference_analysis")
            request.count = 1
            if not request.reference_text and not request.reference_images:
                raise ValueError("请先添加爆款参考文案或图片。")
            self.start(request)
        except ValueError as error:
            QMessageBox.warning(self, "参考分析", str(error))

    def start(self, request: AIRequest):
        if self.busy:
            return
        self.service.config.get(request.model_id)
        self.busy = True
        self.last_request = request
        self.controls_busy(True)
        self.status.setText("任务已提交，正在处理…")
        self.hub.submit(lambda progress: self.service.generate(request, progress), self.finished, self.failed,
                        self.status.setText)

    def controls_busy(self, busy: bool):
        # 2026-10-11：本次修改原因：生成使用提交时快照，避免重做期间候选行发生变化。
        self.inputs.setEnabled(not busy)
        self.candidates.setEnabled(not busy)
        self.text.setEnabled(not busy)
        for control in (self.generate_button, self.analyze_button, self.settings_button, self.redo,
                        self.models, self.history, self.application, self.up, self.down):
            control.setEnabled(not busy)
        self.apply_button.setEnabled(not busy and self.result is not None)

    def finished(self, result: AIResult):
        self.busy = False
        if self.replacement_row is not None and self.result and result.assets:
            old_job = self.result.job_id
            items = [self.candidates.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.candidates.count())]
            # items[self.replacement_row] = (asdict(result.assets[0]), result.purposes[0])
            # 2026-10-11：本次修改原因：单张重做保留该图用途，记录组合候选来源和生成模型。
            items[self.replacement_row] = (asdict(result.assets[0]), items[self.replacement_row][1])
            result.operation = self.operation
            from ..assets import ImageAsset
            result.assets = [ImageAsset(**value[0]) for value in items]
            result.purposes = [value[1] for value in items]
            # self.service.jobs.save({"id": result.job_id, "state": "completed", "operation": self.operation,
            #     "product_id": self.product.get("id", ""), "parent_job_id": old_job,
            #     "request": asdict(self.last_request), "result": asdict(result)})
            profile = self.service.config.get(self.last_request.model_id)
            self.service.jobs.save({"id": result.job_id, "state": "partial" if result.errors else "completed",
                "operation": self.operation, "product_id": self.product.get("id", ""), "parent_job_id": old_job,
                "model": profile.public_dict(), "request": asdict(self.last_request), "result": asdict(result)})
        self.result = result
        self.render_result()
        self.controls_busy(False)
        self.reload_history()
        self.status.setText("生成完成。" + ("\n" + "\n".join(result.errors) if result.errors else "请预览候选后应用。"))

    def failed(self, message: str):
        self.busy = False
        self.controls_busy(False)
        self.status.setText(message)
        QMessageBox.warning(self, "AI 任务未完成", message)

    def render_result(self):
        self.candidates.blockSignals(True)
        self.candidates.clear()
        if self.result:
            if self.result.assets:
                for index, (asset, purpose) in enumerate(zip(self.result.assets, self.result.purposes)):
                    item = QListWidgetItem(f"{index + 1}. {purpose}\n{asset.width} × {asset.height}")
                    item.setData(Qt.ItemDataRole.UserRole, (asdict(asset), purpose))
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked)
                    self.candidates.addItem(item)
            else:
                for index, text in enumerate(self.result.candidates):
                    item = QListWidgetItem(f"候选 {index + 1} · {text[:75]}")
                    item.setData(Qt.ItemDataRole.UserRole, text)
                    self.candidates.addItem(item)
        self.candidates.blockSignals(False)
        self.candidates.setCurrentRow(0)
        self.select_candidate(0)

    def select_candidate(self, row):
        item = self.candidates.item(row)
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        is_image = isinstance(value, tuple) or isinstance(value, list)
        self.preview.setVisible(is_image)
        self.text.setVisible(not is_image)
        self.text.blockSignals(True)
        self.text.setPlainText(value if isinstance(value, str) else "")
        self.text.blockSignals(False)
        if is_image:
            self.preview.set_url(value[0]["uri"])
        self.apply_button.setText("采用为风格要求" if self.result and self.result.operation == "reference_analysis" else "应用到当前字段")

    def edit_candidate(self):
        item = self.candidates.currentItem()
        if item and isinstance(item.data(Qt.ItemDataRole.UserRole), str):
            item.setData(Qt.ItemDataRole.UserRole, self.text.toPlainText())

    def move_candidate(self, step):
        row = self.candidates.currentRow()
        target = row + step
        if 0 <= row and 0 <= target < self.candidates.count():
            item = self.candidates.takeItem(row)
            self.candidates.insertItem(target, item)
            self.candidates.setCurrentRow(target)

    def regenerate(self):
        row = self.candidates.currentRow()
        item = self.candidates.item(row)
        if not item or not self.result or not self.result.assets:
            return
        try:
            request = self.request("image")
            purpose = item.data(Qt.ItemDataRole.UserRole)[1]
            request.instruction += "\n本张用途与排布：" + purpose
            request.count = 1
            self.replacement_row = row
            self.start(request)
        except ValueError as error:
            QMessageBox.warning(self, "重新生成", str(error))

    def apply(self):
        if self.busy or not self.result:
            return
        if self.result.operation == "reference_analysis":
            self.reference_text.setPlainText(self.text.toPlainText())
            self.status.setText("已采用提炼后的风格，可编辑后继续生成。")
            self.apply_button.setEnabled(False)
            return
        if self.result.assets:
            self.applied_assets = [self.candidates.item(i).data(Qt.ItemDataRole.UserRole)[0]["uri"]
                for i in range(self.candidates.count()) if self.candidates.item(i).checkState() == Qt.CheckState.Checked]
            if not self.applied_assets:
                QMessageBox.information(self, "请选择候选", "请至少勾选一张图片。")
                return
            self.apply_mode = self.application.currentData()
        else:
            self.applied_text = self.text.toPlainText().strip()
            if not self.applied_text:
                QMessageBox.information(self, "候选为空", "请选择或填写需要应用的内容。")
                return
            if self.operation == "description_html" and self.keep_images.isChecked():
                images = description_images(self.product.get("description_html", "")) or self.product.get("detail_images", [])
                self.applied_text += "\n" + detail_html("", images)
        self.accept()

    def reload_history(self):
        self.history_rows = self.service.jobs.list(self.product.get("id", ""), self.operation)
        self.history.clear()
        self.history.addItem("选择历史候选…", "")
        for job in self.history_rows:
            self.history.addItem(job.get("updated_at", "") + " · " + job.get("state", ""), job["id"])

    def load_history(self):
        if self.busy:
            return
        job = next((value for value in self.history_rows if value["id"] == self.history.currentData()), None)
        if job:
            try:
                self.result = self.service.restore(job)
                self.render_result()
                self.controls_busy(False)
                self.status.setText("已载入历史候选，应用前请核对当前商品。")
            except (TypeError, KeyError) as error:
                QMessageBox.warning(self, "历史候选不可读取", str(error))

    def done(self, result):
        if self.busy:
            QMessageBox.information(self, "AI 任务正在进行", "请等待任务完成；生成结果会自动留档。")
            return
        # 2026-10-13：本次修改原因：关闭候选时记住布局，不影响任务留档和 accept/reject 结果。
        save_splitters(self)
        super().done(result)
        self.closed.emit(int(result))
