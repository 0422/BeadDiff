# 2026-10-14：本次修改原因：以整商品素材、加工方案、生成审核三个阶段替换分散任务，支持多目标批量处理和加工草稿恢复。
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import Qt, Signal, QMimeData, QPoint, QTimer
from PySide6.QtGui import QDrag, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QProgressBar, QScrollArea, QSizePolicy, QSpinBox,
    QTabBar, QTextBrowser, QVBoxLayout, QWidget,
)
from ..ai.product_plan import (
    ACTIONS, GENERATE, GROUPS, ProcessingStore, accept_plan, active_model, chosen_version,
    compose_changes, final_value, image_row, model_summary, new_draft, planning_request,
    prepare_tasks, relevant, resume_tasks, run_tasks, summary, validate_draft,
)
from ..ai.workflow import safe_error
# from .widgets import ImagePreview, button, label
# 2026-10-14：本次修改原因：统一 AI 页复用自动增高的 Prompt 控件。
from .widgets import ImagePreview, AutoHeightTextEdit, button, label
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
    # control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    # 2026-10-14：本次修改原因：组合框占用可见宽度且长文本不撑开页面，防止最小宽度被忽略后越界。
    control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    # control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    # control.setMinimumContentsLength(8)
    # 2026-10-14：本次修改原因：避免 Qt 组合框动态尺寸策略在反复样式刷新时触发内部布局重入；明确最小宽度保留操作范围。
    control.setMinimumWidth(120)
    return control

from .layout_support import Panel


class ClickPreview(ImagePreview):
    clicked = Signal()
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ImageCard(QFrame):
    reordered = Signal(str, str)
    def __init__(self, workbench, row, index):
        super().__init__()
        self.workbench, self.row = workbench, row
        self.start = QPoint()
        self.setObjectName("aiImageCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(row["group"] in {"images", "detail_images"})
        self.setMinimumWidth(210)
        self.setMaximumWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        title = label(f"{index + 1:02d}  {row['purpose']}", "panelTitle")
        title.setWordWrap(True)
        title.setFixedHeight(36)
        title.setToolTip(row["purpose"] + ("\n拖动标题调整同组图片顺序" if self.acceptDrops() else ""))
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(title)
        self.preview = ClickPreview(workbench.network, 142)
        self.preview.setMinimumWidth(0)
        self.preview.setCursor(Qt.CursorShape.PointingHandCursor)
        version = chosen_version(row)
        address = version["value"]["uri"] if workbench.stage == 2 and version else row["original"] or next(iter(row["sources"]), "")
        self.preview_address, self.preview_loaded = address, False
        self.preview.clicked.connect(lambda: workbench.edit_image(row["id"]))
        # 2026-10-14：本次修改原因：原图或生成版本来自本机时，就地标明尚未托管，不影响选择和应用。
        if address.startswith("file:"):
            # local_badge = label("本机图片 · 尚未托管", "warning")
            # local_badge.setToolTip("可以预览和保存；回传前需要公网图片链接，当前未自动上传。")
            # 2026-10-14：本次修改原因：候选阶段只提示同步时自动托管，避免用户误以为生成阶段已上传。
            local_badge = label("本机图片 · 同步时自动托管", "warning")
            local_badge.setToolTip("候选图片不会自动上传；采用并保存审核后，同步 ERP 时会自动上传到设置的图床并替换为新的公网链接。")
            layout.addWidget(local_badge)
        layout.addWidget(self.preview)
        if workbench.stage == 2:
            choice = workbench.version_combo(row)
            choice.currentIndexChanged.connect(lambda: workbench.choose(row["id"], choice.currentData()))
            layout.addWidget(choice)
            adopt = QCheckBox("采用此版本")
            adopt.setChecked(bool(row["approved"] and version))
            adopt.setEnabled(bool(version) and row["action"] != "omit")
            adopt.toggled.connect(lambda checked: workbench.approve(row["id"], checked))
            layout.addWidget(adopt)
        else:
            action = workbench.action_combo(row)
            action.currentIndexChanged.connect(lambda: workbench.set_action(row["id"], action.currentData()))
            layout.addWidget(action)
            detail = label(row["instruction"] or ("共用：" + "、".join(item["caption"] for item in row["bindings"])) or "点击图片填写用途与本项要求", "hint", True)
            detail.setFixedHeight(34)
            detail.setToolTip(detail.text())
            layout.addWidget(detail)
        state = label(workbench.row_status(row), "hint", True)
        state.setFixedHeight(34)
        state.setToolTip(state.text())
        layout.addWidget(state)
        layout.addWidget(button("对照 / 调整" if workbench.stage == 2 else "用途 / 素材", lambda: workbench.edit_image(row["id"])))

    def mousePressEvent(self, event):
        self.start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.acceptDrops() and not self.workbench.busy and not self.workbench.draft.get("applied")
                and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self.start).manhattanLength() >= QApplication.startDragDistance()):
            mime = QMimeData()
            mime.setData("application/x-beaddiff-plan-row", self.row["id"].encode("utf-8"))
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction)
        else:
            super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-beaddiff-plan-row"):
            source = bytes(event.mimeData().data("application/x-beaddiff-plan-row")).decode("utf-8")
            row = self.workbench.find_row(source)
            if row and row["group"] == self.row["group"] and source != self.row["id"]:
                event.acceptProposedAction()

    def dropEvent(self, event):
        source = bytes(event.mimeData().data("application/x-beaddiff-plan-row")).decode("utf-8")
        self.workbench.reorder(source, self.row["id"])
        event.acceptProposedAction()


class CardGrid(QWidget):
    def __init__(self):
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.cards, self.columns = [], 0

    def set_cards(self, cards):
        for old in self.cards:
            self.grid.removeWidget(old)
            old.hide()
            old.deleteLater()
        self.cards, self.columns = cards, 0
        self.reflow()

    def reflow(self):
        columns = max(1, (self.width() - 8) // 238)
        if columns == self.columns:
            return
        for card in self.cards:
            self.grid.removeWidget(card)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns)
        self.columns = columns

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()


class ProductAIWorkbench(QWidget):
    applyRequested = Signal(object)
    busyChanged = Signal(bool)

    def __init__(self, service, hub, store, network, parent=None):
        super().__init__(parent)
        self.service, self.hub, self.store, self.network = service, hub, store, network
        self.processing = ProcessingStore(service.config.path.parent)
        self.product, self.draft = {}, None
        self.busy, self.input_dirty, self._rendering = False, False, False
        self._store_error, self._restored = "", False
        # self.pause_flag = Event()
        # root = QVBoxLayout(self)
        # 2026-10-14：本次修改原因：缩略图排队使用页面所属计时器，页面销毁后自动取消回调。
        self.pause_flag = Event()
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.load_visible)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.controls = QWidget()
        body = QVBoxLayout(self.controls)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        self.steps = QTabBar()
        self.steps.setObjectName("processingSteps")
        for caption in ("1  整理素材", "2  确认方案", "3  生成与审核"):
            self.steps.addTab(caption)
        self.steps.setExpanding(False)
        self.steps.setUsesScrollButtons(False)
        self.steps.currentChanged.connect(self.change_stage)
        body.addWidget(self.steps)
        top = QHBoxLayout()
        top.addWidget(label("参考爆款方案"))
        self.saved_reference = compact_combo()
        self.saved_reference.currentIndexChanged.connect(self.select_reference)
        top.addWidget(self.saved_reference, 1)
        top.addWidget(button("刷新", self.reload_references))
        # top.addWidget(button("高级参数 / Prompt", self.advanced))
        # 2026-10-14：本次修改原因：高级参数按钮跟随方案状态启停，避免可点击却无任何反馈。
        self.advanced_button = button("高级参数 / Prompt", self.advanced)
        top.addWidget(self.advanced_button)
        top.addWidget(button("加工记录", self.history_dialog))
        # body.addLayout(top)
        # 2026-10-14：本次修改原因：审核阶段收起参考与参数栏，把空间留给结果对照。
        self.reference_bar = QWidget()
        self.reference_bar.setLayout(top)
        body.addWidget(self.reference_bar)
        # self.instruction = QPlainTextEdit()
        # 2026-10-14：本次修改原因：本次加工要求按内容增高，粘贴与草稿恢复使用相同行为。
        self.instruction = AutoHeightTextEdit()
        self.instruction.setPlaceholderText("本次加工要求，例如：统一浅色背景，保留尺寸图，三种颜色分别处理，标题使用英文。")
        # self.instruction.setFixedHeight(62)
        # 2026-10-14：本次修改原因：常用要求保持简洁高度，较长 Prompt 可滚动或在高级参数中编辑。
        # self.instruction.setFixedHeight(46)
        # 2026-10-14：本次修改原因：撤下固定 46 像素高度，避免长 Prompt 显示不全。
        # 高度由 AutoHeightTextEdit 根据可见换行自动计算，超过八行保留滚动。
        # self.instruction.textChanged.connect(self.options_changed)
        # 2026-10-14：本次修改原因：说明 Prompt 与处理范围分别设置，避免输入要求后误以为全部图片已选中。
        self.instruction.setToolTip("Prompt 说明如何处理；请在图片下选择调整或重做，或使用本组批量操作选择范围。")
        self.instruction.textChanged.connect(self.options_changed)
        body.addWidget(self.instruction)
        self.stage_hint = label("", "hint", True)
        body.addWidget(self.stage_hint)
        self.group_tabs = QTabBar()
        self.group_tabs.setExpanding(False)
        self.group_tabs.setUsesScrollButtons(False)
        for caption in GROUPS.values():
            self.group_tabs.addTab(caption)
        self.group_tabs.currentChanged.connect(self.change_group)
        body.addWidget(self.group_tabs)
        toolbar = QHBoxLayout()
        self.bulk = compact_combo()
        self.bulk.addItem("本组批量操作…", "")
        # self.bulk.setMaximumWidth(205)
        # 2026-10-14：本次修改原因：批量操作保持可点击的固定宽度，不被工具栏留白压成零。
        self.bulk.setFixedWidth(180)
        self.bulk.currentIndexChanged.connect(self.bulk_action)
        toolbar.addWidget(self.bulk)
        self.add_button = button("补充图片", self.add_image)
        toolbar.addWidget(self.add_button)
        self.plan_button = button("AI 建议加工方案", self.suggest)
        toolbar.addWidget(self.plan_button)
        self.preview_button = button("最终商品预览", self.final_preview)
        toolbar.addWidget(self.preview_button)
        toolbar.addStretch()
        self.reset_button = button("按当前商品新建方案", self.reset_plan)
        toolbar.addWidget(self.reset_button)
        body.addLayout(toolbar)
        self.cards = CardGrid()
        self.scroller = scroll_content(self.cards)
        # self.scroller.verticalScrollBar().valueChanged.connect(self.load_visible)
        # 2026-10-14：本次修改原因：滚动条在布局变化时也会发信号，统一排队后再判断图片可见范围，避免同步读取中间几何。
        self.scroller.verticalScrollBar().valueChanged.connect(lambda _: self.preview_timer.start(0))
        self.text_body = QWidget()
        self.text_layout = QVBoxLayout(self.text_body)
        self.text_layout.setContentsMargins(4, 4, 4, 4)
        self.text_layout.setSpacing(12)
        self.text_scroll = scroll_content(self.text_body)
        body.addWidget(self.scroller, 1)
        body.addWidget(self.text_scroll, 1)
        root.addWidget(self.controls, 1)
        # 2026-10-14：本次修改原因：生成及审核阶段提前显示本机图片尚未托管，避免应用后才发现无法回传。
        self.media_notice = label("", "warning", True)
        self.media_notice.hide()
        # self.media_notice.setToolTip("自动托管尚未接入。请先上传图片到图床或对象存储，在商品编辑页替换对应图片链接，再保存审核。")
        # 2026-10-14：本次修改原因：提示与已接通的图床上传一致。
        self.media_notice.setToolTip("保存并审核后，同步 ERP 时自动托管实际采用的本机图并使用新公网链接。设置 → 图床维护配置；未采用候选不上传。")
        root.addWidget(self.media_notice)
        self.summary_label = label("", "hint", True)
        root.addWidget(self.summary_label)
        self.status = label("先整理素材，也可以让 AI 建议加工方案；打开页面不会调用模型。", "hint", True)
        self.status.setMaximumHeight(38)
        root.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        root.addWidget(self.progress)
        footer = QHBoxLayout()
        self.save_draft_button = button("保存加工草稿", self.save_draft)
        footer.addWidget(self.save_draft_button)
        self.models_label = label("", "hint")
        self.models_label.setMinimumWidth(0)
        self.models_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.models_label, 1)
        self.pause_button = button("完成当前项后暂停", self.pause)
        self.pause_button.hide()
        footer.addWidget(self.pause_button)
        self.continue_button = button("继续未完成", lambda: self.generate(resume=True))
        footer.addWidget(self.continue_button)
        self.primary = button("确认素材与要求", self.primary_action, primary=True)
        footer.addWidget(self.primary)
        root.addLayout(footer)
        self.shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.shortcut.activated.connect(self.save_draft)

    @property
    def stage(self):
        return self.draft["stage"] if self.draft else 0

    @property
    def pending(self):
        return bool(self.draft and not self.draft.get("applied") and any(row["versions"] for row in self.draft["rows"]))

    @property
    def group(self):
        return list(GROUPS)[max(0, self.group_tabs.currentIndex())]

    def message(self, text):
        self.status.setText(text)
        self.status.setToolTip(text)

    def find_row(self, identifier):
        return next((row for row in self.draft["rows"] if row["id"] == identifier), None) if self.draft else None

    def set_product(self, product):
        if self.busy:
            return
        self.product = deepcopy(product)
        if self.draft is None:
            try:
                self.draft = self.processing.load(product["id"])
                self._restored = self.draft is not None
            except (ValueError, OSError) as error:
                self._store_error = str(error)
            self.draft = self.draft or new_draft(product)
            # if self.draft.get("applied") and relevant(product) == relevant(self.draft["base"]):
            # 2026-10-14：本次修改原因：商品只有实际保存了应用结果才保持已应用锁定；放弃商品编辑后重新打开仍可审核加工草稿。
            if self.draft.get("applied") and relevant(product) != relevant(self.draft.get("applied_snapshot", self.draft["base"])):
                self.draft["applied"] = False
                self.message("上次应用未保存到商品，已恢复加工结果，请重新核对。")
            elif self._restored:
                self.message("已恢复加工草稿，包括方案、版本选择和任务进度。")
            self._rendering = True
            self.instruction.setPlainText(self.draft["options"]["instruction"])
            self.steps.setCurrentIndex(self.stage)
            self.group_tabs.setCurrentIndex(self.draft.get("group", 0))
            self._rendering = False
        # self.reload_references()
        # self.render()
        # if self._store_error:
        # 2026-10-14：本次修改原因：再次进入 AI 页时按已更新的商品开始可编辑的新一轮，已应用方案归档，不让已应用标记长期锁死页面。
        if self.draft.get("applied") and not self._store_error:
            self.start_next_round()
        self.reload_references()
        self.render()
        if self._store_error:
            self.message(self._store_error)
        elif not self.draft.get("applied") and relevant(product) != relevant(self.draft["base"]):
            self.message("商品草稿已改变。旧候选保留，应用会检查冲突；继续生成前请按当前商品新建方案。")

    def focus_target(self, field, address="", locator=None):
        if self._restored:
            return
        self.group_tabs.setCurrentIndex(list(GROUPS).index(field) if field in GROUPS else 0)

    def changed(self):
        if self._rendering or self.draft is None:
            return
        self.input_dirty = True
        self.summary_label.setText(summary(self.draft) + " · 加工草稿未保存")

    def options_changed(self):
        if self._rendering or not self.draft:
            return
        self.draft["options"]["instruction"] = self.instruction.toPlainText()
        self.changed()
        if self.pending:
            self.message("要求已修改，旧版本保持原样；按方案生成或局部重做后生效。")

    def change_stage(self, index):
        if self._rendering or not self.draft:
            return
        self.draft["stage"] = index
        self.changed()
        self.render()

    def change_group(self, index):
        if self._rendering or not self.draft:
            return
        self.draft["group"] = index
        self.render()

    def action_combo(self, row):
        combo = compact_combo()
        allowed = ["keep", "rewrite"] if row["group"] == "text" else (["keep", "adjust", "remake"] if row["group"] == "sku" else ["keep", "adjust", "remake", "omit"])
        if not row["original"] and row["group"] != "text":
            allowed = ["new", "omit"] if row["group"] != "sku" else ["keep", "remake"]
        for key in allowed:
            combo.addItem(ACTIONS[key], key)
        # combo.setCurrentIndex(max(0, combo.findData(row["action"])))
        # 2026-10-14：本次修改原因：在图片处理选项中说明哪些操作会调用模型。
        combo.setToolTip("保留：不生成；调整：基于原图修改；重做：重新设计图片。选好后点击开始生成。")
        combo.setCurrentIndex(max(0, combo.findData(row["action"])))
        return combo

    def version_combo(self, row):
        combo = compact_combo()
        combo.addItem("保留原内容" if row["group"] == "text" else ("保留原图" if row["original"] else "暂不添加"), "original")
        if row["group"] in {"images", "detail_images"}:
            combo.addItem("不采用这张图", "omit")
        for index, version in enumerate(row["versions"]):
            combo.addItem(f"生成版本 {index + 1}", version["id"])
        combo.setCurrentIndex(max(0, combo.findData(row["choice"])))
        return combo

    def row_status(self, row):
        tasks = [task for task in self.draft["queue"] if task["row_id"] == row["id"] and task["state"] != "superseded"]
        if any(task["state"] == "running" for task in tasks):
            return "正在生成…"
        failed = [task for task in tasks if task["state"] == "failed"]
        if failed:
            return "失败：" + failed[-1]["error"]
        if any(task["state"] == "waiting" for task in tasks):
            return "等待处理" + (f" · 已有 {len(row['versions'])} 个版本" if row["versions"] else "")
        if self.stage == 2:
            if not final_value(row):
                return "最终不添加此项"
            return "最终采用生成版本" if row["approved"] and chosen_version(row) else "最终保留原内容"
        return f"已有 {len(row['versions'])} 个版本" if row["versions"] else (f"绑定 {len(row['bindings'])} 个规格" if row["bindings"] else ACTIONS[row["action"]])

    # def render(self):
    # 2026-10-14：本次修改原因：共用审核内容判断，保留无需生成即可审核的操作。
    # 2026-10-14：本次修改原因：区分空方案与可审核的排序、删除、改稿和已有版本，避免零任务误跳转。
    def has_review_content(self, draft=None):
        candidate = self.draft if draft is None else draft
        if not candidate or candidate.get("applied"):
            return False
        if any(row["versions"] for row in candidate["rows"]):
            return True
        try:
            return bool(compose_changes(candidate))
        except ValueError:
            # 2026-10-14：本次修改原因：不完整的采用选择仍需审核修正，不能让提示渲染阻断页面操作。
            return True

    # 2026-10-14：本次修改原因：区分尚未采用的本机候选与最终选中的本机图，不把生成成功显示为可直接回传。
    def refresh_media_notice(self):
        rows = [row for row in self.draft["rows"] if row["group"] != "text"]
        selected = {final_value(row) for row in rows
                    if isinstance(final_value(row), str) and final_value(row).startswith("file:")}
        candidates = {version["value"]["uri"] for row in rows for version in row["versions"]
                      if version["value"]["uri"].startswith("file:")}
        if selected:
            # text = f"最终素材含 {len(selected)} 张本机图片：可应用和保存；回传前须托管并替换为 HTTP/HTTPS 链接，自动托管尚未接入。"
            # 2026-10-14：本次修改原因：采用本机图可直接进入保存和同步链路。
            text = f"最终素材含 {len(selected)} 张本机图片：应用、保存并审核后，同步 ERP 时自动托管并替换为新 HTTP/HTTPS 链接；配置在设置 → 图床。"
        elif candidates:
            # text = f"已生成 {len(candidates)} 张本机候选图，尚未采用；采用后回传前须先托管，当前未自动上传。"
            # 2026-10-14：本次修改原因：未采用候选不自动上传。
            text = f"已生成 {len(candidates)} 张本机候选图，尚未采用；未采用不上传，采用并保存审核后在同步 ERP 时自动托管。"
        else:
            text = ""
        self.media_notice.setText(text)
        self.media_notice.setVisible(bool(text))

    def render(self):
        if not self.draft:
            return
        self._rendering = True
        self.steps.setCurrentIndex(self.stage)
        for index, (group, caption) in enumerate(GROUPS.items()):
            count = sum(row["group"] == group for row in self.draft["rows"])
            self.group_tabs.setTabText(index, f"{caption}  {count}")
        hints = [
            "检查全部图片与规格绑定；可按组设置保留、调整或重做。拖动图片标题可调序。",
            # "确认每张图的用途、主体素材与要求。可让 AI 建议方案，也可直接按手动计划生成。",
            # 2026-10-14：本次修改原因：明确第二步选择范围与启动生成的操作顺序。
            "先在图片下选择调整 / 重做，或用本组批量操作；文案选择改写。填写 Prompt 后点击开始生成，自动进入第三步。",
            "每个位置只采用一个版本；未采用的生成图不会上架。核对整组顺序后应用到商品草稿。",
        ]
        # self.stage_hint.setText(self.draft.get("plan_summary")[:180] if self.stage == 1 and self.draft.get("plan_summary") else hints[self.stage])
        # 2026-10-14：本次修改原因：方案摘要不覆盖操作说明，空审核页提示回到第二步启动任务。
        review_ready = self.has_review_content()
        hint = hints[self.stage]
        if self.stage == 1 and self.draft.get("plan_summary"):
            hint += "\n方案摘要：" + self.draft["plan_summary"][:180]
        elif self.stage == 2 and not review_ready and not self.busy:
            hint = "切换到本页不会开始生成。请回到第二步，为图片选择调整 / 重做，再点击开始生成。"
        self.stage_hint.setText(hint)
        # self.stage_hint.setToolTip(self.draft.get("plan_summary") or hints[self.stage])
        # 2026-10-14：本次修改原因：审核页集中展示候选；阶段说明与 Prompt 按需呈现。
        # self.stage_hint.setToolTip(self.draft.get("plan_summary") or hints[self.stage])
        # self.stage_hint.setVisible(self.stage == 1)
        # 2026-10-14：本次修改原因：在没有审核内容时显示生成入口说明。
        self.stage_hint.setToolTip(hint)
        self.stage_hint.setVisible(self.stage == 1 or self.stage == 2 and not review_ready and not self.busy)
        self.steps.setToolTip(hints[self.stage])
        self.reference_bar.setVisible(self.stage != 2)
        self.instruction.setVisible(self.stage != 2)
        self.bulk.clear()
        self.bulk.addItem("本组批量操作…", "")
        options = [("保留原内容", "keep"), ("改写本组文案", "rewrite")] if self.group == "text" else [("保留本组原图", "keep"), ("调整本组图片", "adjust"), ("重做本组图片", "remake")]
        if self.stage == 2:
            options = [("采用本组所选版本", "approve"), ("全部保留原内容", "original")]
        for caption, key in options:
            self.bulk.addItem(caption, key)
        self.add_button.setVisible(self.group in {"images", "detail_images"} and self.stage != 2)
        self.plan_button.setVisible(self.stage != 2)
        self.preview_button.setVisible(self.stage == 2)
        # self.primary.setText(("确认素材与要求", "按方案生成", "应用所选结果")[self.stage])
        # 2026-10-14：本次修改原因：已完成方案提供明确的继续加工入口，避免只显示禁用的阶段按钮。
        completed = bool(self.draft.get("applied"))
        # self.primary.setText("继续加工当前商品" if completed else ("确认素材与要求", "按方案生成", "应用所选结果")[self.stage])
        # 2026-10-14：本次修改原因：生成按钮显示全部分组选中的处理项数，排序或不采用可直接进入审核。
        selected_count = sum(row["action"] in GENERATE for row in self.draft["rows"])
        generate_caption = f"开始生成（{selected_count} 项）" if selected_count or not review_ready else "进入审核（无需生成）"
        self.primary.setText("继续加工当前商品" if completed else ("确认素材与要求", generate_caption, "应用所选结果")[self.stage])
        self.primary.setToolTip("处理所有分组中已选的调整、重做、新图及改写任务；保留项不生成。" if self.stage == 1 else "")
        self.reset_button.setText("继续加工当前商品" if completed else "按当前商品新建方案")
        unfinished = any(task["state"] in {"waiting", "failed", "running"} for task in self.draft["queue"])
        self.continue_button.setVisible(self.stage == 2 and unfinished and not self.draft.get("applied"))
        # 2026-10-14：本次修改原因：失败与暂停采用不同按钮文案，明确下一步且不重复生成成功版本。
        has_failed = any(task["state"] == "failed" for task in self.draft["queue"])
        self.continue_button.setText("重试失败任务" if has_failed else "继续未完成")
        self.continue_button.setToolTip(
            "重试失败任务并继续尚未完成的任务；已成功版本不会重复生成。"
            if has_failed else "继续处理尚未完成的任务；已成功版本不会重复生成。"
        )
        locked = self.busy or bool(self.draft.get("applied")) or bool(self._store_error)
        # for control in (self.primary, self.bulk, self.add_button, self.plan_button, self.instruction, self.saved_reference):
        #     control.setEnabled(not locked)
        # 2026-10-14：本次修改原因：已应用方案禁止重复覆盖，但主操作继续可用以开始下一轮；高级参数禁用状态与实际行为一致。
        for control in (self.bulk, self.add_button, self.plan_button, self.instruction, self.saved_reference, self.advanced_button):
            control.setEnabled(not locked)
        self.primary.setEnabled(not self.busy and not self._store_error)
        self.reset_button.setEnabled(not self.busy and not self._store_error)
        self.continue_button.setEnabled(not locked)
        # self.summary_label.setText(summary(self.draft) + (" · 已应用，商品尚需保存" if self.draft.get("applied") else (" · 加工草稿未保存" if self.input_dirty else "")))
        # 2026-10-14：本次修改原因：完成状态同时提示继续加工和商品保存去向，避免用户误以为页面卡住。
        self.summary_label.setText(summary(self.draft) + (" · 本轮已应用，可继续加工；商品请在手动修改页保存" if completed else (" · 加工草稿未保存" if self.input_dirty else "")))
        # 2026-10-14：本次修改原因：版本选择、采用及移除后同步更新本机素材回传状态。
        self.refresh_media_notice()
        self.models_label.setText(model_summary(self.service))
        self.models_label.setToolTip(self.models_label.text() + "\n模型统一在设置 → AI 模型中管理")
        position = self.scroller.verticalScrollBar().value()
        text_position = self.text_scroll.verticalScrollBar().value()
        self.scroller.setVisible(self.group != "text")
        self.text_scroll.setVisible(self.group == "text")
        if self.group == "text":
            self.render_text()
        else:
            members = [row for row in self.draft["rows"] if row["group"] == self.group]
            cards = [ImageCard(self, row, index) for index, row in enumerate(members)]
            for card in cards:
                card.setEnabled(not locked)
            if not cards:
                empty = label("此组暂无图片。可补充图片任务，或保留当前商品内容。", "empty", True)
                cards = [empty]
            self.cards.set_cards(cards)
        self.scroller.verticalScrollBar().setValue(position)
        self.text_scroll.verticalScrollBar().setValue(text_position)
        self._rendering = False
        # QTimer.singleShot(0, self.load_visible)
        # 2026-10-14：本次修改原因：页面计时器自动遵守控件生命周期。
        self.preview_timer.start(0)

    # def load_visible(self):
    #     if self.group == "text" or not self.scroller.isVisible():
    #         return
    #     viewport = self.scroller.viewport()
    # 2026-10-14：本次修改原因：批量卡片完成排布后再判断可见范围，防止首次布局把所有卡片误判为屏内。
    def load_visible(self):
        if self._rendering or self.group == "text" or not self.scroller.isVisible():
            return
        # self.cards.grid.activate()
        # viewport = self.scroller.viewport()
        # 2026-10-14：本次修改原因：滚动区首次排布会暂时压缩所有卡片；等待内容高度达到布局最小高度后才加载屏内缩略图。
        self.cards.grid.activate()
        if self.cards.height() < self.cards.minimumSizeHint().height():
            self.preview_timer.start(0)
            return
        viewport = self.scroller.viewport()
        for card in self.cards.cards:
            if isinstance(card, ImageCard) and not card.preview_loaded:
                point = card.mapTo(viewport, QPoint(0, 0))
                if point.y() < viewport.height() and point.y() + card.height() > 0:
                    card.preview_loaded = True
                    card.preview.set_url(card.preview_address)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # QTimer.singleShot(0, self.load_visible)
        # 2026-10-14：本次修改原因：页面计时器自动遵守控件生命周期。
        self.preview_timer.start(0)

    def render_text(self):
        while self.text_layout.count():
            item = self.text_layout.takeAt(0)
            if item.widget():
                # item.widget().deleteLater()
                # 2026-10-14：本次修改原因：重绘文案卡片先隐藏旧控件，避免延迟销毁期间覆盖新内容。
                item.widget().hide()
                item.widget().deleteLater()
        for row in (row for row in self.draft["rows"] if row["group"] == "text"):
            frame = QFrame()
            frame.setObjectName("aiTextCard")
            layout = QVBoxLayout(frame)
            heading = QHBoxLayout()
            heading.addWidget(label(row["purpose"] + ("（HTML）" if row["field"] == "description_html" else ""), "panelTitle"))
            heading.addStretch()
            selector = self.version_combo(row) if self.stage == 2 else self.action_combo(row)
            selector.setMinimumWidth(180)
            if self.stage == 2:
                selector.currentIndexChanged.connect(lambda _, r=row, control=selector: self.choose(r["id"], control.currentData()))
            else:
                selector.currentIndexChanged.connect(lambda _, r=row, control=selector: self.set_action(r["id"], control.currentData()))
            heading.addWidget(selector)
            layout.addLayout(heading)
            original = QPlainTextEdit(row["original"])
            original.setReadOnly(True)
            original.setFixedHeight(85)
            if self.stage == 2:
                layout.addWidget(Panel("原内容", original))
                version = chosen_version(row)
                editor = QPlainTextEdit(version["value"] if version else row["original"])
                editor.setReadOnly(not bool(version))
                editor.setMinimumHeight(115)
                editor.textChanged.connect(lambda r=row, control=editor: self.edit_text(r["id"], control.toPlainText()))
                layout.addWidget(editor)
                controls = QHBoxLayout()
                adopt = QCheckBox("采用此版本")
                adopt.setChecked(bool(version and row["approved"]))
                adopt.setEnabled(bool(version))
                adopt.toggled.connect(lambda checked, r=row: self.approve(r["id"], checked))
                controls.addWidget(adopt)
                controls.addStretch()
                controls.addWidget(button("修改要求 / 重做", lambda _, r=row: self.redo_text(r["id"])))
                layout.addLayout(controls)
            else:
                layout.addWidget(original)
                # prompt = QLineEdit(row["instruction"])
                # prompt.setPlaceholderText("此字段的具体要求，可选")
                # prompt.textEdited.connect(lambda value, r=row: self.edit_row_prompt(r["id"], value))
                # 2026-10-14：本次修改原因：字段 Prompt 支持换行、自动增高与长文滚动，保留光标和输入。
                prompt = AutoHeightTextEdit(row["instruction"])
                prompt.setObjectName("rowPrompt")
                prompt.setPlaceholderText("此字段的具体要求，可选")
                prompt.textChanged.connect(lambda r=row, control=prompt: self.edit_row_prompt(r["id"], control.toPlainText()))
                layout.addWidget(prompt)
            state = label(self.row_status(row), "hint", True)
            state.setToolTip(state.text())
            layout.addWidget(state)
            frame.setEnabled(not self.busy and not self.draft.get("applied"))
            self.text_layout.addWidget(frame)
        self.text_layout.addStretch()

    def set_action(self, identifier, action):
        if self._rendering or self.busy:
            return
        row = self.find_row(identifier)
        row["action"], row["approved"] = action, False
        row["choice"] = "omit" if action == "omit" else "original"
        self.changed()
        self.render()

    def choose(self, identifier, choice):
        if self._rendering or self.busy:
            return
        row = self.find_row(identifier)
        row["choice"], row["approved"] = choice, False
        if choice == "omit":
            row["action"] = "omit"
        elif row["action"] == "omit":
            row["action"] = "keep" if choice == "original" else "remake"
        self.changed()
        self.render()

    def approve(self, identifier, checked):
        if self._rendering or self.busy:
            return
        self.find_row(identifier)["approved"] = bool(checked)
        self.changed()
        self.render()

    def edit_row_prompt(self, identifier, text):
        self.find_row(identifier)["instruction"] = text
        self.changed()

    def edit_text(self, identifier, text):
        if self._rendering or self.busy:
            return
        version = chosen_version(self.find_row(identifier))
        if version:
            version["value"] = text
            self.changed()

    def bulk_action(self):
        if self._rendering or self.busy:
            return
        action = self.bulk.currentData()
        if not action:
            return
        for row in (row for row in self.draft["rows"] if row["group"] == self.group):
            if action == "approve":
                row["approved"] = bool(chosen_version(row)) and row["action"] != "omit"
            elif action == "original":
                row.update(choice="original", approved=False, action="keep" if row["original"] or row["group"] in {"sku", "text"} else "omit")
            else:
                row.update(action=action, choice="original", approved=False)
        self.changed()
        self.render()

    def reorder(self, source, target):
        if self.busy or self.draft.get("applied"):
            return
        row, other = self.find_row(source), self.find_row(target)
        if not row or not other or row["group"] != other["group"] or row["group"] not in {"images", "detail_images"}:
            return
        self.draft["rows"].remove(row)
        self.draft["rows"].insert(self.draft["rows"].index(other), row)
        self.changed()
        self.render()

    def reload_references(self):
        if self.busy:
            return
        try:
            rows = self.store.list()
        except (ValueError, OSError) as error:
            self.message(str(error))
            return
        self.reference_rows = {row["id"]: row for row in rows}
        self.saved_reference.blockSignals(True)
        self.saved_reference.clear()
        self.saved_reference.addItem("不选方案 / 使用自定义 Prompt", "")
        for row in rows:
            self.saved_reference.addItem(row["name"], row["id"])
        current = self.draft["options"]["reference_id"] if self.draft else ""
        self.saved_reference.setCurrentIndex(max(0, self.saved_reference.findData(current)))
        self.saved_reference.blockSignals(False)

    def select_reference(self):
        if self._rendering or not self.draft:
            return
        identifier = self.saved_reference.currentData() or ""
        row = getattr(self, "reference_rows", {}).get(identifier)
        options = self.draft["options"]
        if row and options["reference_prompt"] and QMessageBox.question(self, "更换参考方案", "用所选方案替换当前参考 Prompt？本次加工要求保留。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            self.reload_references()
            return
        options["reference_id"] = identifier
        if row:
            options["reference_prompt"] = row["prompt"]
            self.message("已复制参考方案文字，可在高级参数中查看或编辑；不会自动发送方案图片。")
        else:
            self.message("保留当前自定义 Prompt；如需清空，请打开高级参数。")
        self.changed()

    def advanced(self):
        if self.busy or not self.draft or self.draft.get("applied"):
            return
        options = deepcopy(self.draft["options"])
        dialog = QDialog(self)
        dialog.setWindowTitle("本次加工参数")
        dialog.resize(660, 650)
        root = QVBoxLayout(dialog)
        contents = QWidget()
        form = QFormLayout(contents)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow(label(model_summary(self.service) + "\n模型配置与当前模型统一在设置 → AI 模型中管理。", "hint", True))
        language, size = QComboBox(), QComboBox()
        for control, choices, current in ((language, ["English", "中文", "Deutsch", "Français", "日本語", "Español"], options["language"]),
                                          (size, ["1024x1024", "1536x1024", "1024x1536", "2048x2048"], options["size"])):
            control.setEditable(True)
            control.addItems(choices)
            control.setCurrentText(current)
        count = QSpinBox()
        count.setRange(1, 4)
        count.setValue(options["count"])
        vision = QCheckBox("制定方案与写文案时结合商品图片")
        vision.setChecked(options["vision"])
        # reference = QPlainTextEdit(options["reference_prompt"])
        # reference.setMinimumHeight(140)
        # 2026-10-14：本次修改原因：参考、方案与单图 Prompt 随文本及可用宽度增高。
        reference = AutoHeightTextEdit(options["reference_prompt"], minimum_lines=3, maximum_lines=12)
        refs = QPlainTextEdit("\n".join(options["reference_images"]))
        refs.setPlaceholderText("临时风格参考图地址，每行一张；可不填。")
        refs.setFixedHeight(80)
        form.addRow("目标语言", language)
        form.addRow("图片尺寸", size)
        form.addRow("每项生成版本数", count)
        form.addRow(vision)
        form.addRow("参考 Prompt", reference)
        form.addRow("临时参考图", refs)
        upload = button("上传参考图片", lambda: self.upload_to_text(refs))
        form.addRow(upload)
        # plan_text = QPlainTextEdit(self.draft.get("plan_summary", ""))
        # plan_text.setFixedHeight(100)
        # 2026-10-14：本次修改原因：参考、方案与单图 Prompt 随文本及可用宽度增高。
        plan_text = AutoHeightTextEdit(self.draft.get("plan_summary", ""), maximum_lines=12)
        form.addRow("整体方案要求", plan_text)
        root.addWidget(scroll_content(contents), 1)
        root.addWidget(button("保存本次参数", dialog.accept, primary=True))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            options.update(language=language.currentText().strip(), size=size.currentText().strip(), count=count.value(),
                           vision=vision.isChecked(), reference_prompt=reference.toPlainText(),
                           reference_images=list(dict.fromkeys(line.strip() for line in refs.toPlainText().splitlines() if line.strip())))
            self.draft["options"] = options
            self.draft["plan_summary"] = plan_text.toPlainText()
            self.changed()
            self.render()

    def upload_to_text(self, control):
        files, _ = QFileDialog.getOpenFileNames(self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.gif)")
        addresses = control.toPlainText().splitlines()
        try:
            for filename in files:
                addresses.append(self.service.assets.import_file(Path(filename)).uri)
        except (ValueError, OSError) as error:
            self.message(str(error))
        control.setPlainText("\n".join(dict.fromkeys(addresses)))

    def edit_image(self, identifier, new=False):
        original = self.find_row(identifier)
        if not original or self.busy or self.draft.get("applied"):
            return
        row = deepcopy(original)
        dialog = QDialog(self)
        dialog.setWindowTitle(row["purpose"] + " · 素材与版本")
        dialog.resize(820, 710)
        root = QVBoxLayout(dialog)
        content = QWidget()
        layout = QVBoxLayout(content)
        previews = QHBoxLayout()
        version = chosen_version(row)
        for caption, address in (("原图", row["original"]), ("所选生成版本", version["value"]["uri"] if version else "")):
            column = QVBoxLayout()
            # 2026-10-14：本次修改原因：图片对照弹窗也展示本机状态，避免只在主卡片提示。
            if address.startswith("file:"):
                # caption += " · 本机图片，尚未托管"
                # 2026-10-14：本次修改原因：最终预览与实际同步流程保持一致。
                caption += " · 本机图片，同步时自动托管"
            column.addWidget(label(caption, "hint"))
            preview = ImagePreview(self.network, 260)
            preview.setMinimumWidth(0)
            preview.set_url(address)
            column.addWidget(preview)
            previews.addLayout(column, 1)
        layout.addLayout(previews)
        if row["bindings"]:
            layout.addWidget(label("应用范围：" + "；".join(item["caption"] for item in row["bindings"]), "hint", True))
        form = QFormLayout()
        purpose = QLineEdit(row["purpose"])
        action = self.action_combo(row)
        # prompt = QPlainTextEdit(row["instruction"])
        # prompt.setPlaceholderText("例如：保留实物结构和颜色，只调整背景与光线。")
        # prompt.setFixedHeight(90)
        # 2026-10-14：本次修改原因：参考、方案与单图 Prompt 随文本及可用宽度增高。
        prompt = AutoHeightTextEdit(row["instruction"], maximum_lines=12)
        prompt.setObjectName("imagePrompt")
        prompt.setPlaceholderText("例如：保留实物结构和颜色，只调整背景与光线。")
        sources = QPlainTextEdit("\n".join(row["sources"]))
        sources.setFixedHeight(75)
        sources.setPlaceholderText("当前商品主体图地址，每行一张；SKU 请使用对应款式。")
        form.addRow("图片用途", purpose)
        form.addRow("处理方式", action)
        form.addRow("本项要求", prompt)
        form.addRow("主体素材", sources)
        layout.addLayout(form)
        material_row = QHBoxLayout()
        source_combo = compact_combo()
        source_combo.addItem("从当前商品加入素材…", "")
        for item in self.draft["rows"]:
            if item["group"] != "text" and item["original"]:
                source_combo.addItem(item["purpose"], item["original"])
        material_row.addWidget(source_combo, 1)
        def add_source():
            value = source_combo.currentData()
            if value:
                sources.setPlainText("\n".join(dict.fromkeys(sources.toPlainText().splitlines() + [value])))
        material_row.addWidget(button("加入", add_source))
        material_row.addWidget(button("上传主体图", lambda: self.upload_to_text(sources)))
        layout.addLayout(material_row)
        root.addWidget(scroll_content(content), 1)
        foot = QHBoxLayout()
        if len(row["bindings"]) > 1:
            foot.addWidget(button("拆分为独立 SKU 任务", lambda: dialog.done(3)))
        if row["group"] in {"images", "detail_images"}:
            foot.addWidget(button("前移", lambda: dialog.done(4)))
            foot.addWidget(button("后移", lambda: dialog.done(5)))
        foot.addStretch()
        if self.stage == 2:
            foot.addWidget(button("保存要求并重做此图", lambda: dialog.done(2)))
        foot.addWidget(button("保存本项", dialog.accept, primary=True))
        root.addLayout(foot)
        result = dialog.exec()
        if not result:
            if new:
                self.draft["rows"].remove(original)
                self.render()
            return
        row.update(purpose=purpose.text().strip() or row["purpose"], action=action.currentData(), instruction=prompt.toPlainText(),
                   sources=list(dict.fromkeys(line.strip() for line in sources.toPlainText().splitlines() if line.strip())))
        if row["action"] != original["action"]:
            row.update(choice="omit" if row["action"] == "omit" else "original", approved=False)
        self.draft["rows"][self.draft["rows"].index(original)] = row
        if result == 3:
            position = self.draft["rows"].index(row)
            self.draft["rows"].remove(row)
            self.draft["queue"] = [task for task in self.draft["queue"] if task["row_id"] != row["id"]]
            for index, binding in enumerate(row["bindings"]):
                split = deepcopy(row)
                split.update(id=uuid4().hex, bindings=[binding], purpose=binding["caption"])
                self.draft["rows"].insert(position + index, split)
        elif result in (4, 5):
            members = [item for item in self.draft["rows"] if item["group"] == row["group"]]
            index = members.index(row)
            other = index + (-1 if result == 4 else 1)
            if 0 <= other < len(members):
                a, b = self.draft["rows"].index(row), self.draft["rows"].index(members[other])
                self.draft["rows"][a], self.draft["rows"][b] = self.draft["rows"][b], self.draft["rows"][a]
        self.changed()
        self.render()
        if result == 2:
            if row["action"] not in GENERATE:
                row["action"] = "remake"
            self.generate(row_ids=[identifier], redo=True)

    def add_image(self):
        if self.group not in {"images", "detail_images"}:
            return
        row = image_row(self.group, "", "补充图片")
        row["action"] = "new"
        self.draft["rows"].append(row)
        self.edit_image(row["id"], new=True)

    def redo_text(self, identifier):
        row = self.find_row(identifier)
        # prompt, accepted = QInputDialog.getMultiLineText(self, "修改本项要求", row["purpose"], row["instruction"])
        # if accepted:
        #     row.update(instruction=prompt, action="rewrite")
        # 2026-10-14：本次修改原因：重做文案使用可调整大小的 Prompt 窗口，保留历史版本。
        if row is None or self.busy:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("修改本项要求 · " + row["purpose"])
        dialog.resize(680, 420)
        layout = QVBoxLayout(dialog)
        prompt = AutoHeightTextEdit(row["instruction"], maximum_lines=16)
        layout.addWidget(label(row["purpose"], "sectionTitle"))
        layout.addWidget(scroll_content(prompt), 1)
        layout.addWidget(button("按此要求重新生成", dialog.accept, primary=True))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            row.update(instruction=prompt.toPlainText(), action="rewrite")
            self.changed()
            self.generate(row_ids=[identifier], redo=True)

    def require_current(self):
        if self._store_error:
            raise ValueError(self._store_error)
        if relevant(self.product) != relevant(self.draft["base"]):
            raise ValueError("商品草稿已变化，请按当前商品新建方案，再继续生成。")
        if self.draft.get("applied"):
            raise ValueError("此方案已应用，请按当前商品开始新方案。")

    def suggest(self):
        if self.busy:
            return
        try:
            self.require_current()
            request = planning_request(self.service, self.draft)
            if self.pending and QMessageBox.question(self, "重新建议方案", "新方案会重置本次采用选择，已有生成版本保留。继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
                return
            if not self.save_draft(quiet=True):
                return
        except (ValueError, OSError) as error:
            self.message(str(error))
            return
        self.set_busy(True, planning=True)
        self.message("正在分析素材并制定方案；此步不会生成图片。")
        self.hub.submit(lambda report: self.service.generate(request, report), self.plan_finished, self.failed, self.message)

    def plan_finished(self, result):
        self.set_busy(False)
        try:
            if not result.candidates:
                raise ValueError("未返回有效方案，原计划保留。")
            self.draft = accept_plan(self.draft, result.candidates[0])
            self.changed()
            self.save_draft(quiet=True)
            self.message("方案已准备好，请核对每组用途和处理范围，再按方案生成。")
        except (ValueError, TypeError, KeyError) as error:
            self.message(str(error))
        self.render()

    def generate(self, _checked=False, *, row_ids=None, redo=False, resume=False):
        if self.busy:
            return
        try:
            self.require_current()
            # proposed, identifiers = resume_tasks(self.service, self.draft) if resume else prepare_tasks(self.service, self.draft, row_ids, redo)
            # self.processing.save(proposed)
            # 2026-10-14：本次修改原因：全部保留且没有候选或实际修改时保持当前阶段，避免跳入空审核页。
            proposed, identifiers = resume_tasks(self.service, self.draft) if resume else prepare_tasks(self.service, self.draft, row_ids, redo)
            if not identifiers and not self.has_review_content(proposed):
                proposed["stage"] = self.stage
            self.processing.save(proposed)
        except (ValueError, OSError) as error:
            self.message(str(error))
            return
        self.draft, self.input_dirty = proposed, False
        if not identifiers:
            self.render()
            # self.message("当前计划无需新增生成任务，可审核保留项、排序和不采用项。")
            # 2026-10-14：本次修改原因：零任务时解释如何选择处理范围，已有版本或纯排序仍可审核。
            if self.has_review_content():
                self.message("无需新增生成请求，已进入审核；请核对已有版本、图片顺序和不采用项。")
            else:
                self.message("尚未选择生成内容。请把图片下的保留改为调整 / 重做，或使用本组批量操作；输入 Prompt 后点击开始生成。")
            return
        self.pause_flag = Event()
        frozen = deepcopy(self.draft)
        self.set_busy(True)
        self.message(f"准备处理 {len(identifiers)} 项任务；每项完成即保存。")
        self.hub.submit(lambda report: run_tasks(self.service, self.processing, frozen, identifiers, report, self.pause_flag),
                        self.finished, self.failed, self.report)

    def report(self, message):
        try:
            payload = json.loads(message)
            self.draft = payload["draft"]
            self.progress.setRange(0, max(1, payload["total"]))
            self.progress.setValue(payload["completed"])
            self.render()
            self.message(payload["message"])
        except (ValueError, KeyError, TypeError):
            self.message(message)

    def finished(self, draft):
        self.draft, self.input_dirty = draft, False
        self.set_busy(False)
        unfinished = any(task["state"] in {"waiting", "running", "failed"} for task in draft["queue"])
        # self.message("进度已保存，可继续未完成任务；已成功的版本可先审核。" if unfinished else "生成完成，版本和进度已保存。请选择采用的版本，再预览并应用。")
        # 2026-10-14：本次修改原因：无产能与其他失败明确提示重试入口，避免任务结束后误以为页面仍卡住。
        failed = [task for task in draft["queue"] if task["state"] == "failed"]
        capacity = any(
            "没有可用产能" in task.get("error", "") or "暂无可用产能" in task.get("error", "")
            for task in failed
        )
        if capacity:
            self.message("图片服务暂时没有可用产能，任务进度已保存；稍后点击‘重试失败任务’，已成功版本不会重复生成。")
        elif failed:
            self.message("部分任务生成失败，进度已保存。请查看失败项的错误原因，处理后点击‘重试失败任务’；已成功版本可先审核。")
        else:
            self.message(
                "进度已保存，可继续未完成任务；已成功的版本可先审核。"
                if unfinished
                else "生成完成，版本和进度已保存。请选择采用的版本，再预览并应用。"
            )

    def failed(self, message):
        self.set_busy(False)
        self.message("未完成：" + safe_error(self.service, message) + "。已保存的任务可以继续。")

    def set_busy(self, busy, planning=False):
        self.busy = busy
        self.controls.setEnabled(not busy)
        self.save_draft_button.setEnabled(not busy)
        self.primary.setEnabled(not busy)
        self.continue_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0)
        self.pause_button.setVisible(busy and not planning)
        self.pause_button.setEnabled(True)
        self.pause_button.setText("完成当前项后暂停")
        self.busyChanged.emit(busy)
        self.render()

    def pause(self):
        self.pause_flag.set()
        self.pause_button.setEnabled(False)
        self.pause_button.setText("等待当前项完成…")
        self.message("当前请求完成后暂停，已完成结果和剩余任务会保存。")

    # def primary_action(self):
    #     if self.stage == 0:
    # 2026-10-14：本次修改原因：主操作可从已应用记录直接进入下一轮，而不是停留在不可用的阶段流程。
    def primary_action(self):
        if self.draft and self.draft.get("applied"):
            self.start_next_round()
            return
        if self.stage == 0:
            self.steps.setCurrentIndex(1)
        elif self.stage == 1:
            self.generate()
        else:
            self.apply()

    def save_draft(self, _checked=False, *, quiet=False):
        if self.busy or not self.draft:
            return False
        try:
            if self._store_error:
                raise ValueError(self._store_error)
            self.processing.save(self.draft)
            self.input_dirty = False
            self.summary_label.setText(summary(self.draft))
            if not quiet:
                self.message("加工草稿已保存：方案、Prompt、候选编辑、采用选择和进度均可恢复；商品仍需单独保存。")
            return True
        except (ValueError, OSError) as error:
            self.message("加工草稿未保存：" + str(error))
            return False

    def confirm_leave(self):
        if self.busy:
            self.message("请等待当前任务完成或暂停后离开。")
            return False
        if not self.input_dirty:
            return True
        choice = QMessageBox.question(self, "保存加工草稿", "保存本次方案、Prompt、版本选择和候选改稿，下次继续？此操作不会应用或保存商品。",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Save)
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        return self.save_draft(quiet=True) if choice == QMessageBox.StandardButton.Save else True

    # def archive(self):
    # 2026-10-14：本次修改原因：完成方案先归档再原子保存新一轮，保留参考要求和任务参数，以当前商品素材解锁编辑；保存失败时仍保留原方案。
    def start_next_round(self):
        if self.busy or self._store_error or not self.draft:
            return False
        try:
            proposed = new_draft(self.product)
            proposed["options"] = deepcopy(self.draft["options"])
            proposed["group"] = self.draft["group"]
            self.archive()
            self.processing.save(proposed)
        except (ValueError, OSError) as error:
            self.message("下一轮尚未开始：" + str(error) + "。上次方案和结果仍保留，可再次点击继续加工。")
            return False
        self.draft, self.input_dirty, self._restored = proposed, False, False
        self._rendering = True
        self.instruction.setPlainText(proposed["options"]["instruction"])
        self.group_tabs.setCurrentIndex(proposed["group"])
        self._rendering = False
        self.reload_references()
        self.render()
        self.message("可继续加工当前商品。上一轮方案和版本已保留在加工记录中；商品请在手动修改页核对并保存。")
        return True

    def archive(self):
        if self.draft:
            self.service.jobs.save({"id": uuid4().hex, "operation": "product_batch", "product_id": self.draft["product_id"],
                                    "state": "archived", "result": {"draft": deepcopy(self.draft)}})

    # def reset_plan(self):
    #     if self.busy or not self.confirm_leave():
    # 2026-10-14：本次修改原因：已完成方案继续加工时保留参考 Prompt 和参数，并使用当前商品作为新的原始素材。
    def reset_plan(self):
        if self.draft and self.draft.get("applied"):
            self.start_next_round()
            return
        if self.busy or not self.confirm_leave():
            return
        try:
            self.archive()
        except (ValueError, OSError) as error:
            self.message(str(error))
            return
        self.draft = new_draft(self.product)
        self._restored = False
        self._rendering = True
        self.instruction.clear()
        self._rendering = False
        self.changed()
        self.reload_references()
        self.render()
        self.message("已按当前商品重新整理素材；上次方案可在加工记录中查看。")

    def apply(self):
        if self.busy:
            return
        try:
            changes = compose_changes(self.draft)
            if not changes:
                self.message("尚无可应用的修改。请选择生成版本并勾选采用，或调整图片顺序。")
                return
            removed = sum(row["action"] == "omit" for row in self.draft["rows"])
            if removed and QMessageBox.question(self, "确认最终图片组", f"本方案有 {removed} 张图片设为不采用，将从商品草稿中移出。继续应用？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
                return
            # 应用前先保存选择，关闭或异常中断后可以恢复。
            if not self.save_draft(quiet=True):
                return
            self.applyRequested.emit(deepcopy(changes))
        except (ValueError, TypeError, KeyError, OSError) as error:
            self.message("未应用：" + str(error))

    def applied(self, changes, updated=None):
        self.draft["applied"] = True
        self.draft["applied_snapshot"] = deepcopy(updated or self.product)
        self.product = deepcopy(updated or self.product)
        self.changed()
        self.save_draft(quiet=True)
        self.render()
        self.message("已应用到商品草稿，请在手动修改页核对并保存。")

    def history_dialog(self):
        if self.busy or not self.draft:
            return
        jobs = self.service.jobs.list(self.product["id"], "product_batch")
        dialog = QDialog(self)
        dialog.setWindowTitle("商品加工记录")
        dialog.resize(660, 440)
        layout = QVBoxLayout(dialog)
        records = QListWidget()
        for job in jobs:
            item = QListWidgetItem(f"{job.get('updated_at', '')} · {job.get('state', '')}")
            item.setData(Qt.ItemDataRole.UserRole, job["id"])
            records.addItem(item)
        layout.addWidget(records)
        layout.addWidget(label("载入后会保留原商品快照。商品已改变时，应用将核对冲突。", "hint", True))
        layout.addWidget(button("载入所选方案与版本", dialog.accept, primary=True))
        if dialog.exec() != QDialog.DialogCode.Accepted or not records.currentItem():
            return
        if not self.confirm_leave():
            return
        try:
            job = next(item for item in jobs if item["id"] == records.currentItem().data(Qt.ItemDataRole.UserRole))
            restored = validate_draft(deepcopy(job["result"]["draft"]), self.product["id"])
            for task in restored["queue"]:
                if task["state"] == "running":
                    task["state"] = "waiting"
            self.draft = restored
            self._rendering = True
            self.instruction.setPlainText(restored["options"]["instruction"])
            self._rendering = False
            self.changed()
            self.reload_references()
            self.render()
            self.message("已载入历史方案；只有明确应用并保存后才会更改商品。")
        except (ValueError, KeyError, TypeError) as error:
            self.message(str(error))

    def final_preview(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("最终商品预览 · 尚未保存")
        dialog.resize(920, 680)
        root = QVBoxLayout(dialog)
        content = QWidget()
        layout = QVBoxLayout(content)
        for group, caption in GROUPS.items():
            layout.addWidget(label(caption, "sectionTitle"))
            members = [row for row in self.draft["rows"] if row["group"] == group and final_value(row)]
            if group == "text":
                for row in members:
                    layout.addWidget(label(row["purpose"], "panelTitle"))
                    text = QTextBrowser() if row["field"] == "description_html" else QPlainTextEdit(final_value(row))
                    if row["field"] == "description_html":
                        text.setOpenExternalLinks(False)
                        text.setHtml(final_value(row))
                    text.setReadOnly(True)
                    text.setFixedHeight(130)
                    layout.addWidget(text)
            else:
                grid = QGridLayout()
                for index, row in enumerate(members):
                    cell = QWidget()
                    column = QVBoxLayout(cell)
                    caption_text = f"{index + 1}. {row['purpose']}"
                    if row["bindings"]:
                        caption_text += "\n" + "；".join(item["caption"] for item in row["bindings"])
                    # 2026-10-14：本次修改原因：最终商品预览明确标出实际选中的本机素材。
                    if final_value(row).startswith("file:"):
                        # caption_text += "\n本机图片 · 回传前需托管"
                        # 2026-10-14：本次修改原因：最终预览明确同步时自动托管采用的素材。
                        caption_text += "\n本机图片 · 同步时自动托管"
                    column.addWidget(label(caption_text, "hint", True))
                    preview = ImagePreview(self.network, 175)
                    preview.set_url(final_value(row))
                    column.addWidget(preview)
                    grid.addWidget(cell, index // 3, index % 3)
                layout.addLayout(grid)
        root.addWidget(scroll_content(content), 1)
        root.addWidget(button("返回继续审核", dialog.accept))
        dialog.exec()
