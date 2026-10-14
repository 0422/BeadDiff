# 2026-10-13：本次修改原因：将分散的文案、单图、SKU 图和套图入口汇总为全页工作区，支持复用已保存爆款 Prompt。
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar,
    QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

from ..ai.contracts import AIRequest
from ..ai.references import ReferenceStore, VISUAL_GUIDE
from ..ai.workflow import TEXT_TASKS, run_workflow, safe_error, sku_locator
from ..content import description_images
from ..miaoshou_mapping import MAX_MAIN_IMAGES
from .layout_support import Panel, PersistentSplitter
from .media_list import MediaList
# from .model_settings import ModelSettingsDialog
# 2026-10-14：本次修改原因：业务页面不再打开模型设置弹窗。
# 模型配置统一从设置页进入。
from .widgets import ImagePreview, button, card, label


def scroll_content(widget):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(widget)
    return scroll


def compact_combo():
    control = QComboBox()
    control.setMinimumWidth(0)
    control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return control


# class AIWorkbench(QWidget):
#     applyRequested = Signal(object)
#     busyChanged = Signal(bool)
#
#     def __init__(self, service, hub, store: ReferenceStore, network, parent=None):
#         super().__init__(parent)
#         self.service, self.hub, self.store, self.network = service, hub, store, network
#         self.busy = False
#         self.pending = False
#         self.product = {}
#         self.entries = []
#         self.text_choices = {}
#         self._rendering = False
#         self._active_text = None
#         self._loaded_reference = ""
#         self._input_revision = 0
#         # self._generated_revision = 0
#         # 2026-10-13：本次修改原因：独立保护未生成的 Prompt，重试时保留候选选择。
#         self._generated_revision = 0
#         self.input_dirty = False
#         self._resume_view = {}
#         root = QVBoxLayout(self)
#         root.setContentsMargins(0, 0, 0, 0)
#         root.setSpacing(10)
#         self.splitter = PersistentSplitter(Qt.Orientation.Horizontal, "ui/ai_workbench/input_result_v1", [460, 620], self)
#         self.inputs = QTabWidget()
#         self.inputs.setMinimumWidth(360)
#         self._build_inputs()
#         self.outputs = QTabWidget()
#         self.outputs.setMinimumWidth(380)
#         self._build_outputs()
#         self.splitter.addWidget(self.inputs)
#         self.splitter.addWidget(self.outputs)
#         root.addWidget(self.splitter, 1)
#         self.status = label("选择处理任务，生成后核对并应用。", "hint", True)
#         self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
#         root.addWidget(self.status)
#         self.progress = QProgressBar()
#         self.progress.setFixedHeight(8)
#         self.progress.setTextVisible(False)
#         self.progress.hide()
#         root.addWidget(self.progress)
#         actions = QHBoxLayout()
#         self.generate_button = button("生成所选内容", self.generate, primary=True)
#         self.retry_button = button("重试失败项", self.retry_failed)
#         self.retry_button.hide()
#         actions.addWidget(self.generate_button)
#         actions.addWidget(self.retry_button)
#         actions.addStretch()
#         self.apply_button = button("应用所选结果", self.apply, primary=True)
#         self.apply_button.setEnabled(False)
#         actions.addWidget(self.apply_button)
#         root.addLayout(actions)
#         for control in self.inputs.findChildren(QPlainTextEdit):
#             control.textChanged.connect(self.inputs_changed)
#         for control in self.inputs.findChildren(QComboBox):
#             control.currentIndexChanged.connect(self.inputs_changed)
#             if control.isEditable():
#                 control.editTextChanged.connect(self.inputs_changed)
#         for control in self.inputs.findChildren(QCheckBox):
#             control.toggled.connect(self.inputs_changed)
#         self.subjects.textChanged.connect(self.inputs_changed)
#         self.references.textChanged.connect(self.inputs_changed)
#         # self.reload_models()
#         #
#         # _build_inputs
#         # 2026-10-13：本次修改原因：初始化模型不触发未保存提示。
#         self._rendering = True
#         self.reload_models()
#         self._rendering = False
#
#     def _build_inputs(self):
#         materials = QWidget()
#         layout = QVBoxLayout(materials)
#         layout.setContentsMargins(16, 16, 16, 16)
#         layout.setSpacing(12)
#         layout.addWidget(label("处理内容", "panelTitle"))
#         choices = QGridLayout()
#         self.tasks = {}
#         for index, (operation, caption) in enumerate([*TEXT_TASKS.items(), ("images", "商品图片")]):
#             control = QCheckBox(caption)
#             control.setChecked(operation == "title")
#             self.tasks[operation] = control
#             choices.addWidget(control, index // 2, index % 2)
#         layout.addLayout(choices)
#         self.image_options = QWidget()
#         form = QFormLayout(self.image_options)
#         form.setContentsMargins(0, 0, 0, 0)
#         form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
#         self.target = compact_combo()
#         self.anchor = compact_combo()
#         self.image_kind = compact_combo()
#         self.image_kind.addItem("单图修改 / 生成候选", "single")
#         self.image_kind.addItem("按用途生成套图", "suite")
#         self.apply_mode = compact_combo()
#         self.apply_mode.addItem("替换选中的图片", "replace")
#         self.apply_mode.addItem("追加到图片组", "append")
#         self.apply_mode.addItem("替换整个图片组", "replace_set")
#         form.addRow("应用位置", self.target)
#         form.addRow("目标图片", self.anchor)
#         form.addRow("生成方式", self.image_kind)
#         form.addRow("应用方式", self.apply_mode)
#         self.limit_hint = label("", "hint", True)
#         form.addRow(self.limit_hint)
#         layout.addWidget(self.image_options)
#         # self.tasks["images"].toggled.connect(self.image_options.setVisible)
#         # 2026-10-13：本次修改原因：图片任务勾选变化同步套图用途区。
#         self.tasks["images"].toggled.connect(self.image_options.setVisible)
#         self.tasks["images"].toggled.connect(self.update_slots)
#         self.image_options.hide()
#         self.target.currentIndexChanged.connect(self.target_changed)
#         self.anchor.currentIndexChanged.connect(self.anchor_changed)
#         self.image_kind.currentIndexChanged.connect(self.update_slots)
#         self.apply_mode.currentIndexChanged.connect(self.update_limit)
#         layout.addWidget(label("商品主体图", "panelTitle"))
#         source_row = QHBoxLayout()
#         self.product_images = compact_combo()
#         source_row.addWidget(self.product_images, 1)
#         source_row.addWidget(button("加入主体", self.add_subject))
#         layout.addLayout(source_row)
#         # self.subjects = MediaList([], {}, self.service.assets)
#         # 2026-10-13：本次修改原因：左侧窄栏的主体图操作使用两列布局。
#         self.subjects = MediaList([], {}, self.service.assets, action_columns=2)
#         layout.addWidget(self.subjects)
#         self.use_subject = QCheckBox("结合主体图写文案（文本模型需支持看图）")
#         layout.addWidget(self.use_subject)
#         self.keep_images = QCheckBox("生成详情时保留当前详情图片")
#         self.keep_images.setChecked(True)
#         layout.addWidget(self.keep_images)
#         self.slot_box = QWidget()
#         slots_layout = QVBoxLayout(self.slot_box)
#         slots_layout.setContentsMargins(0, 0, 0, 0)
#         slots_layout.addWidget(label("套图用途与顺序 · 每行一张，最多 12 张", "hint", True))
#         self.slots = QPlainTextEdit("主图：完整展示商品，干净背景\n场景图：表现真实使用场景\n细节图：展示可见材质与结构\n卖点图：呈现已确认卖点，预留文案区")
#         self.slots.setMinimumHeight(140)
#         slots_layout.addWidget(self.slots)
#         layout.addWidget(self.slot_box)
#         self.slot_box.hide()
#         self.slots.textChanged.connect(self.update_limit)
#         advanced = QWidget()
#         advanced_form = QFormLayout(advanced)
#         advanced_form.setContentsMargins(0, 0, 0, 0)
#         advanced_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
#         advanced_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
#         self.text_model, self.image_model = compact_combo(), compact_combo()
#         self.language, self.size, self.count = compact_combo(), compact_combo(), compact_combo()
#         self.language.setEditable(True)
#         self.language.addItems(["English", "中文", "Deutsch", "Français", "日本語", "Español"])
#         self.size.setEditable(True)
#         self.size.addItems(["1024x1024", "1536x1024", "1024x1536", "2048x2048"])
#         for number in range(1, 5):
#             self.count.addItem(str(number), number)
#         for caption, control in [("文本模型", self.text_model), ("生图模型", self.image_model),
#                                  ("目标语言", self.language), ("图片尺寸", self.size), ("每项候选数", self.count)]:
#             advanced_form.addRow(caption, control)
#         advanced_form.addRow(button("模型配置", self.configure_models))
#         self.count.currentIndexChanged.connect(self.update_limit)
#         layout.addWidget(Panel("模型与参数", advanced))
#         video = button("AI 视频 · 暂未开放")
#         video.setEnabled(False)
#         layout.addWidget(video)
#         layout.addStretch()
#         self.inputs.addTab(scroll_content(materials), "素材与任务")
#         prompt = QWidget()
#         prompt_layout = QVBoxLayout(prompt)
#         prompt_layout.setContentsMargins(16, 16, 16, 16)
#         prompt_layout.setSpacing(12)
#         prompt_layout.addWidget(label("已保存的爆款方案", "panelTitle"))
#         # self.saved_reference = compact_combo()
#         # 2026-10-13：本次修改原因：说明已分析方案的复用入口。
#         prompt_layout.addWidget(label("先在左侧“爆款分析”保存方案，即可直接复用，无需再次分析。", "hint", True))
#         self.saved_reference = compact_combo()
#         self.saved_reference.currentIndexChanged.connect(self.select_reference)
#         # prompt_layout.addWidget(self.saved_reference)
#         # 2026-10-13：本次修改原因：方案列表可刷新，保留正在编辑的 Prompt。
#         reference_row = QHBoxLayout()
#         reference_row.addWidget(self.saved_reference, 1)
#         reference_row.addWidget(button("刷新方案", self.reload_references))
#         prompt_layout.addLayout(reference_row)
#         self.reference_prompt = QPlainTextEdit()
#         self.reference_prompt.setPlaceholderText("选择爆款分析中保存的方案，或粘贴参考标题、描述、视觉风格 Prompt。选择方案仅复制文字，不自动发送方案中的图片。")
#         self.reference_prompt.setMinimumHeight(160)
#         prompt_layout.addWidget(self.reference_prompt, 1)
#         prompt_layout.addWidget(label("本次调整要求 / Prompt", "panelTitle"))
#         self.instruction = QPlainTextEdit()
#         self.instruction.setPlaceholderText("直接填写也可以：保留商品主体与真实规格，调整光影、排布；描述用简洁的英文卖点……")
#         self.instruction.setMinimumHeight(140)
#         prompt_layout.addWidget(self.instruction, 1)
#         inline = QWidget()
#         inline_layout = QVBoxLayout(inline)
#         inline_layout.setContentsMargins(0, 0, 0, 0)
#         # self.references = MediaList([], {}, self.service.assets)
#         # 2026-10-13：本次修改原因：折叠参考图区域使用两列工具，避免高 DPI 下按钮溢出。
#         self.references = MediaList([], {}, self.service.assets, action_columns=2)
#         inline_layout.addWidget(self.references)
#         self.analyze_button = button("分析参考并提炼 Prompt", self.analyze)
#         inline_layout.addWidget(self.analyze_button)
#         inline_layout.addWidget(label("使用内置视觉分析指引；有参考图时需文本模型支持图片理解。", "hint", True))
#         prompt_layout.addWidget(Panel("临时参考图（可选）", inline))
#         self.inputs.addTab(scroll_content(prompt), "Prompt 方案")
#
#     def _build_outputs(self):
#         text_page = QWidget()
#         layout = QVBoxLayout(text_page)
#         layout.setContentsMargins(16, 16, 16, 16)
#         layout.setSpacing(10)
#         self.text_kind = compact_combo()
#         for operation, caption in TEXT_TASKS.items():
#             self.text_kind.addItem(caption, operation)
#         self.text_kind.currentIndexChanged.connect(self.show_text)
#         layout.addWidget(self.text_kind)
#         self.text_candidate = compact_combo()
#         self.text_candidate.currentIndexChanged.connect(self.select_text_candidate)
#         layout.addWidget(self.text_candidate)
#         self.text_apply = QCheckBox("应用当前字段的此候选")
#         self.text_apply.toggled.connect(self.toggle_text_apply)
#         layout.addWidget(self.text_apply)
#         self.before_text = QPlainTextEdit()
#         self.before_text.setReadOnly(True)
#         self.before_text.setMaximumHeight(120)
#         layout.addWidget(Panel("原内容", self.before_text))
#         self.text_result = QPlainTextEdit()
#         self.text_result.setPlaceholderText("生成后显示候选，可手动调整。详细描述使用 HTML。")
#         self.text_result.textChanged.connect(self.edit_text)
#         layout.addWidget(self.text_result, 1)
#         self.text_length = label("", "hint")
#         layout.addWidget(self.text_length)
#         self.outputs.addTab(text_page, "文案候选")
#         image_page = QWidget()
#         image_layout = QVBoxLayout(image_page)
#         image_layout.setContentsMargins(16, 16, 16, 16)
#         self.image_candidates = QListWidget()
#         self.image_candidates.setMinimumHeight(100)
#         self.image_candidates.setMaximumHeight(180)
#         self.image_candidates.setTextElideMode(Qt.TextElideMode.ElideRight)
#         self.image_candidates.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
#         self.image_candidates.currentRowChanged.connect(self.show_image)
#         self.image_candidates.itemChanged.connect(self.update_limit)
#         image_layout.addWidget(self.image_candidates)
#         order = QHBoxLayout()
#         self.image_buttons = [button("上移", lambda: self.move_image(-1)), button("下移", lambda: self.move_image(1)),
#                               button("重做选中图", self.redo_image)]
#         for control in self.image_buttons:
#             order.addWidget(control)
#         order.addStretch()
#         image_layout.addLayout(order)
#         previews = QHBoxLayout()
#         self.before_image = ImagePreview(self.network, 220)
#         self.after_image = ImagePreview(self.network, 220)
#         for caption, preview in [("原图", self.before_image), ("生成图", self.after_image)]:
#             column = QVBoxLayout()
#             column.addWidget(label(caption, "hint"))
#             preview.setMinimumWidth(0)
#             column.addWidget(preview)
#             previews.addLayout(column, 1)
#         image_layout.addLayout(previews)
#         self.image_info = label("勾选、排序后应用；单个 SKU 只能选择一张。", "hint", True)
#         image_layout.addWidget(self.image_info)
#         image_layout.addStretch()
#         self.outputs.addTab(scroll_content(image_page), "图片候选")
#         history_page = QWidget()
#         history_layout = QVBoxLayout(history_page)
#         history_layout.setContentsMargins(16, 16, 16, 16)
#         self.history = QListWidget()
#         self.history.setTextElideMode(Qt.TextElideMode.ElideRight)
#         history_layout.addWidget(self.history, 1)
#         history_layout.addWidget(button("载入所选历史", self.load_history))
#         history_layout.addWidget(label("历史保留生成时的目标。目标字段已改变时不会直接覆盖，需重新生成。", "hint", True))
#         self.outputs.addTab(history_page, "历史")
#
#     # def set_product(self, product):
#     #     if self.busy:
#     #         return
#     #     first = not self.product
#     #     old_product = self.product
#     #     self.product = deepcopy(product)
#     #     if old_product != self.product and self.entries:
#     #         self.status.setText("商品草稿已更新；已有候选保持原样，应用时会核对目标是否改变。")
#     #     previous = self.target.currentData()
#     #     self.target.blockSignals(True)
#     #     self.target.clear()
#     #     self.target.addItem("产品图片 / 主图", {"field": "images"})
#     #     self.target.addItem("详情图片 / 正文图片", {"field": "detail_images"})
#     #     for sku in product.get("skus", []):
#     #         caption = " · ".join(filter(None, [sku.get("spec1"), sku.get("spec2"), sku.get("platform_sku")])) or "未命名 SKU"
#     #         self.target.addItem("SKU · " + caption, {"field": "sku", "locator": sku_locator(sku)})
#     #     index = next((i for i in range(self.target.count()) if self.target.itemData(i) == previous), 0)
#     #     self.target.setCurrentIndex(index)
#     #     self.target.blockSignals(False)
#     #     self.target_changed()
#     #     images = list(dict.fromkeys(product.get("images", []) + product.get("detail_images", [])
#     #         + description_images(product.get("description_html", ""))
#     #         + [row["image"] for row in product.get("skus", []) if row.get("image")]))
#     #     self.product_images.clear()
#     #     self.product_images.addItem("选择当前商品图片…", "")
#     #     for index, address in enumerate(images):
#     #         self.product_images.addItem(f"图片 {index + 1} · {address[-45:]}", address)
#     #     if first:
#     #         self.subjects.set_urls(images[:1])
#     #         self.use_subject.setChecked(product.get("source") == "upload")
#     #     self.reload_references()
#     #     self.reload_models()
#     #     self.reload_history()
#     # 2026-10-13：本次修改原因：模式切换保留输入，局部重试保留候选状态，部分应用后继续保护剩余结果。
#     def set_product(self, product):
#         if self.busy:
#             return
#         first = not self.product
#         old_product = self.product
#         self.product = deepcopy(product)
#         if old_product != self.product and self.entries:
#             self.status.setText("商品草稿已更新；已有候选保持原样，应用时会核对目标是否改变。")
#         rendering = self._rendering
#         self._rendering = True
#         try:
#             previous = self.target.currentData()
#             self.target.blockSignals(True)
#             self.target.clear()
#             self.target.addItem("产品图片 / 主图", {"field": "images"})
#             self.target.addItem("详情图片 / 正文图片", {"field": "detail_images"})
#             for sku in product.get("skus", []):
#                 caption = " · ".join(filter(None, [sku.get("spec1"), sku.get("spec2"), sku.get("platform_sku")])) or "未命名 SKU"
#                 self.target.addItem("SKU · " + caption, {"field": "sku", "locator": sku_locator(sku)})
#             index = next((i for i in range(self.target.count()) if self.target.itemData(i) == previous), 0)
#             self.target.setCurrentIndex(index)
#             self.target.blockSignals(False)
#             self.target_changed()
#             images = list(dict.fromkeys(product.get("images", []) + product.get("detail_images", [])
#                 + description_images(product.get("description_html", ""))
#                 + [row["image"] for row in product.get("skus", []) if row.get("image")]))
#             previous_image = self.product_images.currentData()
#             self.product_images.clear()
#             self.product_images.addItem("选择当前商品图片…", "")
#             for index, address in enumerate(images):
#                 self.product_images.addItem(f"图片 {index + 1} · {address[-45:]}", address)
#             self.product_images.setCurrentIndex(max(0, self.product_images.findData(previous_image)))
#             if first:
#                 self.subjects.set_urls(images[:1])
#                 self.use_subject.setChecked(product.get("source") == "upload")
#             self.reload_references()
#             self.reload_models()
#             self.reload_history()
#         finally:
#             self._rendering = rendering
#
#     def target_changed(self):
#         target = self.target.currentData() or {"field": "images"}
#         field = target["field"]
#         if field == "sku":
#             rows = [row for row in self.product.get("skus", []) if sku_locator(row) == target["locator"]]
#             addresses = [rows[0].get("image", "")] if len(rows) == 1 else []
#         else:
#             addresses = list(self.product.get(field, []))
#             if field == "detail_images":
#                 addresses = list(dict.fromkeys(addresses + description_images(self.product.get("description_html", ""))))
#         old = self.anchor.currentData()
#         self.anchor.blockSignals(True)
#         self.anchor.clear()
#         for index, address in enumerate(filter(None, addresses)):
#             self.anchor.addItem(f"第 {index + 1} 张 · {address[-40:]}", address)
#         self.anchor.setCurrentIndex(max(0, self.anchor.findData(old)))
#         self.anchor.blockSignals(False)
#         self.image_kind.setEnabled(field != "sku")
#         self.apply_mode.setEnabled(field != "sku")
#         if field == "sku":
#             self.image_kind.setCurrentIndex(0)
#             self.apply_mode.setCurrentIndex(0)
#         elif not addresses:
#             self.apply_mode.setCurrentIndex(1)
#         self.anchor_changed()
#         self.update_slots()
#
#     # def anchor_changed(self):
#     #     address = self.anchor.currentData()
#     #     if address:
#     #         # 新目标先使用对应主体，避免上一 SKU 的颜色进入下一 SKU 改图。
#     #         self.subjects.set_urls([address])
#     #     self.update_limit()
#     # 2026-10-13：本次修改原因：模式切换保留输入，局部重试保留候选状态，部分应用后继续保护剩余结果。
#     def anchor_changed(self):
#         if not self._rendering:
#             address = self.anchor.currentData()
#             self.subjects.set_urls([address] if address else [])
#         self.update_limit()
#
#     def update_slots(self):
#         # self.slot_box.setVisible(self.image_kind.currentData() == "suite" and self.tasks["images"].isChecked())
#         # 2026-10-13：本次修改原因：初始化及目标联动时保护尚未创建的控件。
#         if not hasattr(self, "slot_box"):
#             return
#         self.slot_box.setVisible(self.image_kind.currentData() == "suite" and self.tasks["images"].isChecked())
#         self.update_limit()
#
#     def add_subject(self):
#         address = self.product_images.currentData()
#         if address:
#             self.subjects.set_urls(self.subjects.toPlainText().splitlines() + [address])
#             self.inputs_changed()
#
#     def update_limit(self, *_):
#         if not hasattr(self, "limit_hint") or not hasattr(self, "count"):
#             return
#         field = (self.target.currentData() or {}).get("field")
#         count = len([line for line in self.slots.toPlainText().splitlines() if line.strip()]) if self.image_kind.currentData() == "suite" else (self.count.currentData() or 1)
#         if field == "images":
#             old = len(self.product.get("images", []))
#             mode = self.apply_mode.currentData()
#             total = count if mode == "replace_set" else old + count - (1 if mode == "replace" and old else 0)
#             self.limit_hint.setText(f"当前 {old}/{MAX_MAIN_IMAGES} 张 · 全选生成图后预计 {total}/{MAX_MAIN_IMAGES} 张" + (" · 超限时请减少选择" if total > MAX_MAIN_IMAGES else ""))
#         elif field == "sku":
#             self.limit_hint.setText("生成后仅选择一张图片应用到此 SKU。")
#         else:
#             self.limit_hint.setText("应用详情图时同步正文中的对应图片；保存沿用现有回传校验。")
#
#     def reload_models(self):
#         for category, combo in [("text", self.text_model), ("image", self.image_model)]:
#             old = combo.currentData() or self.service.config.active.get(category)
#             combo.clear()
#             for profile in self.service.config.profiles:
#                 if profile.category == category and not profile.problems():
#                     combo.addItem(profile.caption, profile.id)
#             combo.setCurrentIndex(combo.findData(old))
#
#     def configure_models(self):
#         ModelSettingsDialog(self.service.config, self.service.assets, self.hub, self).exec()
#         self.reload_models()
#
#     def reload_references(self):
#         try:
#             rows = self.store.list()
#         except (ValueError, OSError) as error:
#             self.status.setText(str(error))
#             return
#         previous = self.saved_reference.currentData()
#         self.saved_reference.blockSignals(True)
#         self.saved_reference.clear()
#         # self.saved_reference.addItem("不使用已保存方案 / 手动输入", "")
#         # 2026-10-13：本次修改原因：切回手动模式时明确已有文字继续参与生成，避免误以为已清空。
#         self.saved_reference.addItem("手动输入 / 编辑当前 Prompt", "")
#         self.reference_rows = {row["id"]: row for row in rows}
#         for row in rows:
#             self.saved_reference.addItem(row["name"], row["id"])
#         self.saved_reference.setCurrentIndex(max(0, self.saved_reference.findData(previous)))
#         self.saved_reference.blockSignals(False)
#
#     def select_reference(self):
#         identifier = self.saved_reference.currentData() or ""
#         row = getattr(self, "reference_rows", {}).get(identifier)
#         if not row:
#             # 选择“不使用”不暗中清空已经手工编辑的文字。
#             self._loaded_reference = identifier
#             return
#         if self.reference_prompt.toPlainText().strip() and QMessageBox.question(
#             self, "替换参考 Prompt", "用此方案替换当前参考 Prompt？本次调整要求保留。",
#             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
#             QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
#             self.saved_reference.blockSignals(True)
#             self.saved_reference.setCurrentIndex(max(0, self.saved_reference.findData(self._loaded_reference)))
#             self.saved_reference.blockSignals(False)
#             return
#         self._loaded_reference = identifier
#         self.reference_prompt.setPlainText(row["prompt"])
#
#     def inputs_changed(self, *_):
#         if self._rendering:
#             return
#         # self._input_revision += 1
#         # 2026-10-13：本次修改原因：仅编辑 Prompt 或素材也会触发退出保护。
#         self._input_revision += 1
#         self.input_dirty = True
#         if self.entries:
#             self.status.setText("输入或 Prompt 已调整；已有候选不会自动改变。点击生成可重新处理。")
#
#     def model_id(self, image=False, images=False):
#         combo = self.image_model if image else self.text_model
#         identifier = combo.currentData()
#         if not identifier:
#             raise ValueError("请展开“模型与参数”，选择" + ("生图" if image else "文本") + "模型，或打开模型配置。")
#         profile = self.service.config.get(identifier, "image" if image else "text")
#         if images and not image and not profile.supports_vision:
#             raise ValueError("当前文本模型未启用图片理解，请换用支持看图的配置，或取消图片输入。")
#         return identifier
#
#     def request(self, operation, product=None):
#         image = operation == "image"
#         subjects = self.subjects.toPlainText().splitlines() if image or self.use_subject.isChecked() else []
#         references = self.references.toPlainText().splitlines()
#         return AIRequest(operation, deepcopy(product or self.product),
#             model_id=self.model_id(image, bool(subjects or references)),
#             instruction=self.instruction.toPlainText().strip(), language=self.language.currentText().strip(),
#             reference_text=self.reference_prompt.toPlainText().strip(), subject_images=subjects,
#             reference_images=references, size=self.size.currentText().strip(), count=self.count.currentData() or 1)
#
#     def build_tasks(self):
#         tasks = []
#         for operation, caption in TEXT_TASKS.items():
#             if self.tasks[operation].isChecked():
#                 # target = {"field": operation, "before": self.product.get(operation, ""), "keep_images": self.keep_images.isChecked()}
#                 # 2026-10-13：本次修改原因：文案候选关联生成时的商品。
#                 target = {"field": operation, "before": self.product.get(operation, ""), "keep_images": self.keep_images.isChecked(),
#                           "product_id": self.product.get("id", "")}
#                 tasks.append({"id": uuid4().hex, "caption": caption, "request": asdict(self.request(operation)), "target": target})
#         if self.tasks["images"].isChecked():
#             target = deepcopy(self.target.currentData())
#             target["mode"] = self.apply_mode.currentData()
#             # target["anchor"] = self.anchor.currentData() or ""
#             # 2026-10-13：本次修改原因：图片候选保存商品与完整正文快照。
#             target["anchor"] = self.anchor.currentData() or ""
#             target["product_id"] = self.product.get("id", "")
#             if target["field"] == "detail_images":
#                 target["html_before"] = self.product.get("description_html", "")
#             product = deepcopy(self.product)
#             if target["field"] == "sku":
#                 from ..ai.workflow import resolve_sku
#                 _, sku = resolve_sku(product, target["locator"])
#                 target["before"] = deepcopy(sku)
#                 product["skus"] = [sku]
#             else:
#                 target["before"] = list(product.get(target["field"], []))
#                 if target["mode"] == "replace" and target["anchor"] not in target["before"]:
#                     # 正文独有图片也可改图，实际补丁先检查正文快照。
#                     if target["field"] != "detail_images" or target["anchor"] not in description_images(product.get("description_html", "")):
#                         raise ValueError("请先选择要替换的图片，或改为追加图片。")
#                     target["html_only"] = True
#                     target["html_before"] = product.get("description_html", "")
#             request = self.request("image", product)
#             if not request.subject_images:
#                 raise ValueError("请加入商品主体图，再生成图片。")
#             if self.image_kind.currentData() == "suite":
#                 purposes = [line.strip() for line in self.slots.toPlainText().splitlines() if line.strip()]
#                 if not 1 <= len(purposes) <= 12:
#                     raise ValueError("套图用途需填写 1～12 行，每行生成一张。")
#             else:
#                 purposes = ["单图候选 " + str(index + 1) for index in range(request.count)]
#             for purpose in purposes:
#                 item = deepcopy(request)
#                 item.count = 1
#                 item.instruction += "\n本张用途与排布：" + purpose
#                 tasks.append({"id": uuid4().hex, "caption": purpose, "request": asdict(item), "target": deepcopy(target)})
#         if not tasks:
#             raise ValueError("请至少选择一项处理内容。")
#         return tasks
#
#     def generate(self):
#         if self.busy:
#             return
#         try:
#             tasks = self.build_tasks()
#         except ValueError as error:
#             self.status.setText(str(error))
#             return
#         if self.pending and QMessageBox.question(self, "重新生成候选", "已有未应用的候选。重新生成将显示新结果，原始生成结果仍可从历史查看。",
#             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
#             QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
#             return
#         self.start(tasks, [])
#
#     # def start(self, tasks, previous):
#     #     self.set_busy(True)
#     # 2026-10-13：本次修改原因：后台任务使用提交时快照，并保存重试前的勾选、顺序及文案选择。
#     def start(self, tasks, previous):
#         self._resume_view = self.capture_view() if previous else {}
#         tasks, previous, product_id = deepcopy(tasks), deepcopy(previous), self.product.get("id", "")
#         self.set_busy(True)
#         self._generated_revision = self._input_revision
#         self.progress.setRange(0, len(tasks))
#         self.progress.setValue(0)
#         self.status.setText("正在准备所选任务…")
#         # self.hub.submit(lambda report: run_workflow(self.service, deepcopy(tasks), self.product.get("id", ""), report, deepcopy(previous)),
#         # 2026-10-13：本次修改原因：后台线程只访问已冻结的请求数据。
#         self.hub.submit(lambda report: run_workflow(self.service, tasks, product_id, report, previous),
#                         self.finished, self.failed, self.report)
#
#     def report(self, message):
#         try:
#             value = json.loads(message)
#             self.progress.setRange(0, value["total"])
#             self.progress.setValue(value["completed"])
#             self.status.setText(value["message"])
#         except (ValueError, KeyError, TypeError):
#             self.status.setText(message)
#
#     def finished(self, job):
#         self.entries = job["result"]["entries"]
#         # self.text_choices = {}
#         # self.pending = any(entry.get("result") for entry in self.entries)
#         # 2026-10-13：本次修改原因：重试保留未重做字段的候选选择，已留档 Prompt 不重复报未保存。
#         self.text_choices = deepcopy(self._resume_view.get("text", {}))
#         self.pending = any(entry.get("result") and not entry.get("applied") for entry in self.entries)
#         self.input_dirty = False
#         self.set_busy(False)
#         # self.render_results()
#         # errors =
#         # 2026-10-13：本次修改原因：重新渲染恢复候选状态而不重置全部选择。
#         self.render_results(self._resume_view)
#         errors = [entry["caption"] + "：" + entry["error"] for entry in self.entries if entry.get("error")]
#         good = sum(bool(entry.get("result")) for entry in self.entries)
#         # self.status.setText(f"已取得 {good} 项候选；应用只修改草稿，保存后生效。" + ("\n" + "\n".join(errors) if errors else ""))
#         # 2026-10-13：本次修改原因：批量错误不撑高整页，保留完整错误提示。
#         summary = f"已取得 {good} 项候选；应用后请核对并保存。"
#         if errors:
#             summary += f" 有 {len(errors)} 项失败：{errors[0][:180]}（完整错误见悬停提示）"
#         self.status.setText(summary)
#         self.status.setToolTip("\n".join(errors))
#         self.reload_history()
#
#     def failed(self, message):
#         self.set_busy(False)
#         self.status.setText("任务未完成：" + safe_error(self.service, message) + "。已留档的结果可在历史中查看。")
#         self.reload_history()
#
#     def set_busy(self, busy):
#         self.busy = busy
#         self.inputs.setEnabled(not busy)
#         self.outputs.setEnabled(not busy)
#         self.generate_button.setEnabled(not busy)
#         self.generate_button.setText("正在生成…" if busy else "生成所选内容")
#         self.retry_button.setEnabled(not busy)
#         # self.apply_button.setEnabled(not busy and any(row.get("result") for row in self.entries))
#         # 2026-10-13：本次修改原因：应用过的目标不会被分析完成回调重新启用。
#         self.apply_button.setEnabled(not busy and any(row.get("result") and not row.get("applied") for row in self.entries))
#         self.progress.setVisible(busy)
#         self.busyChanged.emit(busy)
#
#     def analyze(self):
#         if self.busy:
#             return
#         references = self.references.toPlainText().splitlines()
#         if not references and not self.reference_prompt.toPlainText().strip():
#             self.status.setText("请提供临时参考图片或参考文案，也可以直接选择已保存的爆款方案。")
#             return
#         try:
#             request = AIRequest("reference_analysis", {}, model_id=self.model_id(images=bool(references)),
#                 instruction=VISUAL_GUIDE + "\n" + self.instruction.toPlainText(), language="中文",
#                 reference_text=self.reference_prompt.toPlainText(), reference_images=references)
#         except ValueError as error:
#             self.status.setText(str(error))
#             return
#         self.set_busy(True)
#         self.progress.setRange(0, 0)
#         self.hub.submit(lambda report: self.service.generate(request, report), self.analysis_done, self.failed, self.status.setText)
#
#     def analysis_done(self, result):
#         self.set_busy(False)
#         # self.reference_prompt.setPlainText(result.candidates[0] if result.candidates else "")
#         # 2026-10-13：本次修改原因：空分析响应不清空用户已编辑的 Prompt。
#         if not result.candidates or not result.candidates[0].strip():
#             self.status.setText("未返回有效分析结果，原 Prompt 已保留。")
#             return
#         self.reference_prompt.setPlainText(result.candidates[0])
#         self.status.setText("已提炼参考 Prompt，可直接编辑；需长期复用时在“爆款分析”保存方案。")
#
#     # def render_results(self):
#     #     self._rendering = True
#     #     self.image_candidates.clear()
#     #     for entry in self.entries:
#     #         result = entry.get("result") or {}
#     #         if result.get("candidates"):
#     #             self.text_choices.setdefault(entry["target"]["field"], {"index": 0, "apply": True})
#     #         for index, asset in enumerate(result.get("assets", [])):
#     #             item = QListWidgetItem(entry["caption"])
#     #             item.setData(Qt.ItemDataRole.UserRole, (entry["id"], index))
#     #             item.setToolTip(f"{entry['caption']} · {asset['width']} × {asset['height']}")
#     #             item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
#     #             item.setCheckState(Qt.CheckState.Checked)
#     #             self.image_candidates.addItem(item)
#     #     self._rendering = False
#     #     self.show_text()
#     #     self.image_candidates.setCurrentRow(0)
#     #     self.retry_button.setVisible(any(row.get("error") for row in self.entries))
#     #     self.apply_button.setEnabled(not self.busy and any(row.get("result") for row in self.entries))
#     #     first_text = next((row["target"]["field"] for row in self.entries if (row.get("result") or {}).get("candidates")), None)
#     #     if first_text:
#     #         self.text_kind.setCurrentIndex(self.text_kind.findData(first_text))
#     #         self.outputs.setCurrentIndex(0)
#     #     elif self.image_candidates.count():
#     #         self.outputs.setCurrentIndex(1)
#     # 2026-10-13：本次修改原因：模式切换保留输入，局部重试保留候选状态，部分应用后继续保护剩余结果。
#     def capture_view(self):
#         items = [self.image_candidates.item(row) for row in range(self.image_candidates.count())]
#         return {"order": [tuple(item.data(Qt.ItemDataRole.UserRole)) for item in items],
#                 "checks": {tuple(item.data(Qt.ItemDataRole.UserRole)): item.checkState() for item in items},
#                 "text": deepcopy(self.text_choices), "kind": self.text_kind.currentData(),
#                 "tab": self.outputs.currentIndex()}
#
#     def render_results(self, view=None):
#         view = view or {}
#         self._rendering = True
#         self.image_candidates.clear()
#         candidates = []
#         for entry in self.entries:
#             result = entry.get("result") or {}
#             if result.get("candidates") and not entry.get("applied"):
#                 self.text_choices.setdefault(entry["target"]["field"], {"index": 0, "apply": True})
#             for index, asset in enumerate(result.get("assets", [])):
#                 key = (entry["id"], index)
#                 item = QListWidgetItem(entry["caption"] + (" · 已应用" if entry.get("applied") else ""))
#                 item.setData(Qt.ItemDataRole.UserRole, key)
#                 item.setToolTip(f'{entry["caption"]} · {asset["width"]} × {asset["height"]}')
#                 item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
#                 item.setCheckState(view.get("checks", {}).get(key, Qt.CheckState.Checked))
#                 if entry.get("applied"):
#                     item.setCheckState(Qt.CheckState.Unchecked)
#                     item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
#                 candidates.append((key, item))
#         order = {key: index for index, key in enumerate(view.get("order", []))}
#         for key, item in sorted(candidates, key=lambda pair: order.get(pair[0], len(order))):
#             self.image_candidates.addItem(item)
#         self._rendering = False
#         self.show_text()
#         self.image_candidates.setCurrentRow(0 if self.image_candidates.count() else -1)
#         self.show_image()
#         self.retry_button.setVisible(any(row.get("error") and not row.get("applied") for row in self.entries))
#         self.apply_button.setEnabled(not self.busy and any(row.get("result") and not row.get("applied") for row in self.entries))
#         first_text = next((row["target"]["field"] for row in self.entries
#                            if not row.get("applied") and (row.get("result") or {}).get("candidates")), None)
#         if view:
#             self.text_kind.setCurrentIndex(max(0, self.text_kind.findData(view.get("kind"))))
#             self.outputs.setCurrentIndex(view.get("tab", 0))
#         elif first_text:
#             self.text_kind.setCurrentIndex(self.text_kind.findData(first_text))
#             self.outputs.setCurrentIndex(0)
#         elif self.image_candidates.count():
#             self.outputs.setCurrentIndex(1)
#
#     def text_entry(self):
#         field = self.text_kind.currentData()
#         # return next((row for row in self.entries if row["target"]["field"] == field and (row.get("result") or {}).get("candidates")), None)
#         # 2026-10-13：本次修改原因：已应用文案不再次覆盖草稿。
#         return next((row for row in self.entries if not row.get("applied") and row["target"]["field"] == field and (row.get("result") or {}).get("candidates")), None)
#
#     def show_text(self, *_):
#         if not hasattr(self, "text_candidate"):
#             return
#         self._rendering = True
#         entry = self.text_entry()
#         self.text_candidate.clear()
#         if entry:
#             for index in range(len(entry["result"]["candidates"])):
#                 self.text_candidate.addItem(f"候选 {index + 1}", index)
#             choice = self.text_choices.setdefault(entry["target"]["field"], {"index": 0, "apply": True})
#             # self.text_candidate.setCurrentIndex(choice["index"])
#             # 2026-10-13：本次修改原因：重试候选数量减少时维持有效选择。
#             choice["index"] = min(choice["index"], len(entry["result"]["candidates"]) - 1)
#             self.text_candidate.setCurrentIndex(choice["index"])
#             self.text_apply.setChecked(choice["apply"])
#             self.before_text.setPlainText(str(entry["target"]["before"]))
#         else:
#             self.text_apply.setChecked(False)
#             self.before_text.clear()
#         self.text_result.setEnabled(bool(entry))
#         self.text_apply.setEnabled(bool(entry))
#         self._rendering = False
#         self.select_text_candidate()
#
#     def select_text_candidate(self, *_):
#         if self._rendering:
#             return
#         entry = self.text_entry()
#         index = self.text_candidate.currentIndex()
#         self._rendering = True
#         self._active_text = (entry["id"], index) if entry and index >= 0 else None
#         self.text_result.setPlainText(entry["result"]["candidates"][index] if self._active_text else "")
#         if entry and index >= 0:
#             self.text_choices[entry["target"]["field"]]["index"] = index
#         self._rendering = False
#         self.text_length.setText(f"{len(self.text_result.toPlainText())} 字符")
#
#     def toggle_text_apply(self, checked):
#         if not self._rendering and self.text_entry():
#             self.text_choices[self.text_kind.currentData()]["apply"] = checked
#
#     def edit_text(self):
#         if self._rendering or not self._active_text:
#             return
#         identifier, index = self._active_text
#         entry = next(row for row in self.entries if row["id"] == identifier)
#         entry["result"]["candidates"][index] = self.text_result.toPlainText()
#         self.pending = True
#         self.text_length.setText(f"{len(self.text_result.toPlainText())} 字符")
#
#     def image_entry(self, item):
#         if not item:
#             return None, None
#         identifier, index = item.data(Qt.ItemDataRole.UserRole)
#         entry = next((row for row in self.entries if row["id"] == identifier), None)
#         return entry, index
#
#     def show_image(self, *_):
#         entry, index = self.image_entry(self.image_candidates.currentItem())
#         self.before_image.set_url(entry["target"].get("anchor", "") if entry else "")
#         self.after_image.set_url(entry["result"]["assets"][index]["uri"] if entry else "")
#         if entry:
#             target = entry["target"]
#             caption = {"images": "产品图片", "detail_images": "详情图片", "sku": "SKU 图片"}.get(target["field"], "图片")
#             self.image_info.setText(caption + " · " + {"replace": "替换所选图片", "append": "追加", "replace_set": "替换整组"}.get(target["mode"], "") + " · " + entry["caption"])
#
#     def move_image(self, step):
#         row = self.image_candidates.currentRow()
#         if 0 <= row + step < self.image_candidates.count():
#             item = self.image_candidates.takeItem(row)
#             self.image_candidates.insertItem(row + step, item)
#             self.image_candidates.setCurrentRow(row + step)
#
#     def retry_failed(self):
#         # tasks = [deepcopy(row) for row in self.entries if row.get("error")]
#         # 2026-10-13：本次修改原因：已应用结果不再参与失败重试。
#         tasks = [deepcopy(row) for row in self.entries if row.get("error") and not row.get("applied")]
#         # if tasks and not self.busy:
#         #     self.start(tasks, self.entries)
#         # 2026-10-13：本次修改原因：失败重试沿用失败的请求；单图重做才使用新 Prompt。
#         if tasks and not self.busy:
#             for task in tasks:
#                 task["request"] = deepcopy(task.get("retry_request", task["request"]))
#             self.start(tasks, self.entries)
#
#     def redo_image(self):
#         entry, _ = self.image_entry(self.image_candidates.currentItem())
#         # if entry and not self.busy:
#         #     task = deepcopy(entry)
#         # 2026-10-13：本次修改原因：已应用目标需重新取草稿快照，避免重做结果无法安全定位。
#         if entry and not self.busy:
#             if entry.get("applied"):
#                 self.status.setText("此目标已应用。请按当前草稿重新生成，再继续调整。")
#                 return
#             task = deepcopy(entry)
#             # 重做使用最新手动 Prompt，目标与主体仍固定为该候选，避免跳到其他 SKU。
#             task["request"]["instruction"] = self.instruction.toPlainText().strip() + "\n本张用途与排布：" + entry["caption"]
#             task["request"]["reference_text"] = self.reference_prompt.toPlainText().strip()
#             self.start([task], self.entries)
#
#     def apply(self):
#         if self.busy:
#             return
#         changes = []
#         for entry in self.entries:
#             field = entry["target"]["field"]
#             choice = self.text_choices.get(field)
#             # if field in TEXT_TASKS and choice and choice["apply"] and entry.get("result"):
#             # 2026-10-13：本次修改原因：应用时跳过已处理的文案目标。
#             if field in TEXT_TASKS and choice and choice["apply"] and entry.get("result") and not entry.get("applied"):
#                 changes.append({"target": entry["target"], "value": entry["result"]["candidates"][choice["index"]]})
#         groups = {}
#         for row in range(self.image_candidates.count()):
#             item = self.image_candidates.item(row)
#             if item.checkState() != Qt.CheckState.Checked:
#                 continue
#             entry, index = self.image_entry(item)
#             key = json.dumps(entry["target"], ensure_ascii=False, sort_keys=True)
#             group = groups.setdefault(key, {"target": entry["target"], "value": [], "assets": []})
#             asset = entry["result"]["assets"][index]
#             group["value"].append(asset["uri"])
#             group["assets"].append(asset)
#         changes.extend(groups.values())
#         if not changes:
#             self.status.setText("请勾选至少一个文案字段或图片候选。")
#             return
#         if any(change["target"].get("mode") == "replace_set" for change in changes):
#             if QMessageBox.question(self, "替换整组图片", "将用勾选的生成图替换目标图片组。保存前仍可放弃此次商品修改。",
#                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
#                 QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
#                 return
#         self.applyRequested.emit(deepcopy(changes))
#
#     # def applied(self):
#     #     self.pending = False
#     #     self.apply_button.setEnabled(False)
#     #     self.status.setText("已应用到商品草稿，请在手动修改页核对并保存。")
#     # 2026-10-13：本次修改原因：模式切换保留输入，局部重试保留候选状态，部分应用后继续保护剩余结果。
#     def applied(self, changes):
#         view = self.capture_view()
#         targets = [change["target"] for change in changes]
#         for entry in self.entries:
#             if entry["target"] in targets:
#                 entry["applied"] = True
#         self.pending = any(row.get("result") and not row.get("applied") for row in self.entries)
#         self.render_results(view)
#         self.status.setText("所选结果已应用到商品草稿，请在手动修改页核对并保存。" +
#                             (" 其他未选结果仍保留，可继续选择应用。" if self.pending else ""))
#
#     def reload_history(self):
#         self.history.clear()
#         self.history_rows = self.service.jobs.list(self.product.get("id", ""), "product_workflow")
#         for job in self.history_rows:
#             count = len(job.get("result", {}).get("entries", []))
#             item = QListWidgetItem(f"{job.get('updated_at', '')} · {count} 项 · {job.get('state', '')}")
#             item.setData(Qt.ItemDataRole.UserRole, job["id"])
#             self.history.addItem(item)
#
#     def load_history(self):
#         item = self.history.currentItem()
#         if not item or self.busy:
#             return
#         if self.pending and QMessageBox.question(self, "载入历史", "替换当前候选视图？尚未应用的手动候选编辑会丢弃。",
#             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
#             QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
#             return
#         job = next(row for row in self.history_rows if row["id"] == item.data(Qt.ItemDataRole.UserRole))
#         self.entries = deepcopy(job["result"]["entries"])
#         # self.text_choices = {}
#         # self.pending = True
#         # self.render_results()
#         # 2026-10-13：本次修改原因：历史恢复保留已应用标记。
#         self.text_choices = {}
#         self.pending = any(row.get("result") and not row.get("applied") for row in self.entries)
#         self.render_results()
#         self.status.setText("历史候选已载入；应用前会核对原目标字段与图片组。")
# 2026-10-14：本次修改原因：旧两栏工作区完整注释保留，对外接口切换为整商品分阶段加工。
from .product_ai_workbench import ProductAIWorkbench as AIWorkbench
