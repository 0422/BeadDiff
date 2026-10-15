# 2026-10-15：本次修改原因：实现持久化的原料选择、AI 设计、人工配方确认、成品图片及 Listing 汇总工作流。
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDialog,QFileDialog,QFormLayout,QHBoxLayout,QLineEdit,QMessageBox,
                               QSpinBox,QTableWidget,QTableWidgetItem,QTabWidget,QVBoxLayout,QWidget)

from ..beads import BeadDesign, MATERIAL_CATEGORY_LABELS, _money
# from ..bead_workflow import (IMAGE_ROLES,design_request,evaluate,image_request,listing_request,make_product,normalize_candidate,
#                              normalize_listing,parse_object,snapshot_key)
# 2026-10-15：本次修改原因：配方版本由交接函数生成，页面无需重复引入计算函数。
from ..bead_workflow import (IMAGE_ROLES,design_request,evaluate,image_request,listing_request,make_product,normalize_candidate,
                             normalize_listing,parse_object)
from .bead_database import scroll_form
from .table_support import configure_table,fit_table_rows
from .widgets import AutoHeightTextEdit,ImagePreview,button,label


class BeadChainPage(QWidget):
    def __init__(self,store,ai_service,ai_hub,parent=None,repository=None,open_product=None,open_erp=None):
        super().__init__(parent)
        self.store,self.ai_service,self.ai_hub,self.repository = store,ai_service,ai_hub,repository
        self.open_product,self.open_erp = open_product,open_erp
        self.design = BeadDesign(); self.materials = []; self.busy = False; self._loading = True; self._dirty = False
        self._active_candidate = ""
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(12)
        # toolbar = QHBoxLayout(); toolbar.addWidget(label("散珠成链","pageTitle")); self.projects = QComboBox(); self.projects.setMinimumWidth(240)
        # 2026-10-15：本次修改原因：侧栏已显示模块名称，成链页面直接展示项目选择和操作，去掉重复页标题。
        toolbar = QHBoxLayout(); self.projects = QComboBox(); self.projects.setMinimumWidth(240)
        toolbar.addWidget(self.projects,1); self.projects.activated.connect(self.load_project)
        # 2026-10-15：本次修改原因：异步任务期间冻结项目操作，防止模型响应写入另一份设计。
        self.project_actions = [button("新建设计",self.new_project),button("复制为新设计",self.duplicate_project),button("版本记录",self.show_history),button("保存草稿",self.save_draft,primary=True)]
        for action in self.project_actions: toolbar.addWidget(action)
        root.addLayout(toolbar)
        self.tabs = QTabWidget(); root.addWidget(self.tabs,1)
        self._build_materials(); self._build_designs(); self._build_listing()
        self.status = label("从数据库勾选原料，然后生成多个设计方向。","hint",True); root.addWidget(self.status)
        self._loading = False; self.refresh(); self._set_editable()

    def _build_materials(self):
        page = QWidget(); layout = QVBoxLayout(page)
        row = QHBoxLayout(); row.addWidget(label("1. 选择原料与设计条件","sectionTitle")); row.addStretch(); row.addWidget(button("刷新原料",self.refresh)); layout.addLayout(row)
        layout.addWidget(label("库存、成本可选。仅确认事实进入商品资料；图片观察可供配色参考。设计和回传不会自动扣减或预留库存。","hint",True))
        # self.table = QTableWidget(0,7); self.table.setHorizontalHeaderLabels(["选用","编号 / 名称","类型","资料 / 观察","可用库存","单位成本","待确认"])
        # 2026-10-15：本次修改原因：数据库撤下原料名称，成链选料统一使用唯一编号和类型识别。
        self.table = QTableWidget(0,7); self.table.setHorizontalHeaderLabels(["选用","编号","类型","资料 / 观察","可用库存","单位成本","待确认"])
        configure_table(self.table,editable=False,multiline=True)
        for col,width in enumerate((55,220,100,280,105,125,220)): self.table.setColumnWidth(col,width)
        self.table.itemChanged.connect(lambda *_:self._changed()); layout.addWidget(self.table,1)
        body = QWidget(); form = QFormLayout(body); form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.title = AutoHeightTextEdit("",minimum_lines=1,maximum_lines=3)
        self.customer = AutoHeightTextEdit("",minimum_lines=1,maximum_lines=3)
        self.region = QLineEdit(); self.target_price = QLineEdit(); self.cost_limit = QLineEdit(); self.cost_currency = QLineEdit("CNY")
        self.mode = QComboBox(); self.mode.addItems(["成品手链","DIY 材料包"])
        self.language = QComboBox(); self.language.addItems(["English","中文","日本語","Deutsch","Français","Español"]); self.language.setEditable(True)
        self.notes = AutoHeightTextEdit("",minimum_lines=3,maximum_lines=8)
        self.notes.setPlaceholderText("可选：风格、配色、目标长度、佩戴场景、节日、组装工艺。未设置时由 AI 提出方向。")
        for title,widget in (("项目名称",self.title),("目标客户（可选）",self.customer),("销售国家 / 地区",self.region),("目标售价区间（参考）",self.target_price),("材料成本上限",self.cost_limit),("成本上限币种",self.cost_currency),("商品形式",self.mode),("Listing 语言",self.language),("补充要求",self.notes)):
            form.addRow(title,widget)
            if isinstance(widget,(QLineEdit,AutoHeightTextEdit)): widget.textChanged.connect(self._changed)
            else: widget.currentTextChanged.connect(self._changed)
        area = scroll_form(body); area.setMinimumHeight(210); layout.addWidget(area,1)
        self.generate_button = button("AI 生成设计方向",self.generate_candidates,primary=True,symbol="analysis"); layout.addWidget(self.generate_button)
        self.tabs.addTab(page,"① 原料与条件")

    def _build_designs(self):
        page = QWidget(); layout = QVBoxLayout(page)
        self.candidates = QTableWidget(0,5); self.candidates.setHorizontalHeaderLabels(["方案","设计与展示建议","材料成本","沿线占长","风险 / 库存"])
        configure_table(self.candidates,editable=False,multiline=True)
        for col,width in enumerate((170,340,160,200,340)): self.candidates.setColumnWidth(col,width)
        self.candidates.itemSelectionChanged.connect(self.select_candidate); layout.addWidget(self.candidates,1)
        layout.addWidget(label("2. 核对顺序与配方","sectionTitle"))
        layout.addWidget(label("“串珠”按行表示从线头开始的顺序；“配件”不参与排列。数量按原料的计量单位填写，线材请按一份裁切线登记。","hint",True))
        self.sequence = QTableWidget(0,3); self.sequence.setHorizontalHeaderLabels(["位置 / 类型","原料","用量"])
        configure_table(self.sequence,editable=False,multiline=True); self.sequence.setColumnWidth(0,150); self.sequence.setColumnWidth(1,420); self.sequence.setColumnWidth(2,130); layout.addWidget(self.sequence,1)
        row = QHBoxLayout()
        for text,callback in (("添加串珠段",lambda:self.add_sequence("sequence")),("添加配件",lambda:self.add_sequence("components")),("上移",lambda:self.move_sequence(-1)),("下移",lambda:self.move_sequence(1)),("移除选中段",self.remove_sequence)):
            row.addWidget(button(text,callback))
        self.sequence_actions = row; layout.addLayout(row)
        self.bom_status = label("选择一个方案后核对配方。","hint",True); layout.addWidget(self.bom_status)
        footer = QHBoxLayout(); self.confirm_bom = QCheckBox("已核对原料、顺序、用量和待补充项，接受打样验证")
        self.confirm_bom.toggled.connect(self._changed); footer.addWidget(self.confirm_bom,1)
        self.lock_button = button("锁定配方",self.lock_bom,primary=True); footer.addWidget(self.lock_button)
        self.unlock_button = button("解锁并重新设计",self.unlock); footer.addWidget(self.unlock_button); layout.addLayout(footer)
        self.tabs.addTab(page,"② 方案与配方")

    def _build_listing(self):
        body = QWidget(); layout = QVBoxLayout(body)
        row = QHBoxLayout(); row.addWidget(label("3. 图片与 Listing 参考","sectionTitle")); row.addStretch()
        self.listing_button = button("AI 起草 Listing",self.generate_listing,primary=True); row.addWidget(self.listing_button); layout.addLayout(row)
        self.listing_title = AutoHeightTextEdit("",minimum_lines=2,maximum_lines=5)
        self.bullets = AutoHeightTextEdit("",minimum_lines=4,maximum_lines=10)
        self.description = AutoHeightTextEdit("",minimum_lines=5,maximum_lines=15)
        self.purposes = AutoHeightTextEdit("主图：白底展示完整手链\n细节图：珠子表面与配色\n佩戴概念图：呈现整体效果\nSKU 图：仅展示当前款式",minimum_lines=4,maximum_lines=10)
        form = QFormLayout(); form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for title,control in (("标题",self.listing_title),("卖点（每行一条）",self.bullets),("商品介绍 HTML",self.description),("图片用途（每行一张）",self.purposes)):
            form.addRow(title,control); control.textChanged.connect(self._listing_changed)
        layout.addLayout(form)
        row = QHBoxLayout(); self.image_button = button("生成上述用途图片",self.generate_images,symbol="analysis"); row.addWidget(self.image_button)
        self.upload_button = button("上传打样 / 成品图片",self.upload_images); row.addWidget(self.upload_button)
        row.addStretch(); layout.addLayout(row)
        # 2026-10-15：本次修改原因：采用图片必须指定 ERP 用途，主图顺序和 SKU 图片由用户确认。
        self.images = QTableWidget(0,4); self.images.setHorizontalHeaderLabels(["采用","回传位置","用途 / 来源","素材"]); configure_table(self.images,editable=False,multiline=True)
        for col,width in enumerate((65,165,350,360)): self.images.setColumnWidth(col,width)
        self.images.itemChanged.connect(self._image_changed); self.images.itemSelectionChanged.connect(self.show_image)
        self.preview = ImagePreview(QNetworkAccessManager(self),220)
        layout.addWidget(self.images); fit_table_rows(self.images,maximum_rows=4); layout.addWidget(self.preview)
        image_actions = QHBoxLayout()
        self.image_actions = [button("图片上移",lambda:self.move_image(-1)),button("图片下移",lambda:self.move_image(1)),button("移除候选图",self.remove_image)]
        for action in self.image_actions: image_actions.addWidget(action)
        image_actions.addStretch(); layout.addLayout(image_actions)
        self.image_review = QCheckBox("已逐张核对采用图中的原料、数量、顺序及当前 SKU，并确认文案和成品 / DIY 形式一致")
        self.image_review.toggled.connect(self._changed); layout.addWidget(self.image_review)
        self.listing_warnings = label("AI 图片为设计概念图，打样后的实物图可以在这里上传替换；每次只生成当前填写的用途。","hint",True); layout.addWidget(self.listing_warnings)
        economics = QFormLayout(); self.sale_price = QLineEdit(); self.sale_price.setPlaceholderText("可留空，在商品编辑页确认售价")
        self.sale_currency = QLineEdit("USD"); economics.addRow("当前 SKU 售价",self.sale_price); economics.addRow("销售币种",self.sale_currency); layout.addLayout(economics)
        self.sale_price.textChanged.connect(self._changed); self.sale_currency.textChanged.connect(self._changed)
        footer = QHBoxLayout(); self.publish_button = button("汇总至回传 ERP",self.publish,primary=True); footer.addWidget(self.publish_button)
        self.edit_product_button = button("打开商品编辑",self.edit_product); footer.addWidget(self.edit_product_button); footer.addStretch(); layout.addLayout(footer)
        self.tabs.addTab(scroll_form(body),"③ 图片与 Listing")

    def _changed(self,*_args):
        if not self._loading: self._dirty = True

    def _listing_changed(self,*_args):
        if not self._loading:
            self.image_review.setChecked(False)
            self._changed()

    def selected_materials(self):
        return [item for row,item in enumerate(self.materials) if self.table.item(row,0) and self.table.item(row,0).checkState() == Qt.CheckState.Checked]

    def _requirements(self):
        return {"customer":self.customer.toPlainText().strip(),"region":self.region.text().strip(),"price":self.target_price.text().strip(),
                "cost_limit":self.cost_limit.text().strip(),"cost_currency":self.cost_currency.text().strip().upper(),"mode":self.mode.currentText(),"language":self.language.currentText(),"notes":self.notes.toPlainText().strip()}

    def refresh(self,*_args):
        if self.busy: return
        selected = {item.id for item in self.selected_materials()} if self.materials else set(self.design.material_ids)
        self._loading = True; self.materials = self.store.list_materials(); self.table.setRowCount(len(self.materials))
        for row,item in enumerate(self.materials):
            check = QTableWidgetItem(); check.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsUserCheckable); check.setCheckState(Qt.CheckState.Checked if item.id in selected else Qt.CheckState.Unchecked)
            # values = [check,QTableWidgetItem(item.code+"\n"+item.name),QTableWidgetItem(MATERIAL_CATEGORY_LABELS.get(item.category,item.category)),QTableWidgetItem("；".join(k+"："+v for k,v in item.facts.items()) or "未填写"),QTableWidgetItem(str(item.available_quantity) if item.track_inventory else "未知"),QTableWidgetItem(item.unit_cost+" "+item.currency if item.unit_cost else "未知"),QTableWidgetItem("、".join(k for k,state in item.fact_statuses.items() if state != "confirmed" and (item.facts.get(k) or item.observations.get(k))) or "无")]
            # 2026-10-15：本次修改原因：原料编号独立显示，移除名称形成的多余空行，类型由相邻列展示。
            values = [check,QTableWidgetItem(item.code),QTableWidgetItem(MATERIAL_CATEGORY_LABELS.get(item.category,item.category)),QTableWidgetItem("；".join(k+"："+v for k,v in item.facts.items()) or "未填写"),QTableWidgetItem(str(item.available_quantity) if item.track_inventory else "未知"),QTableWidgetItem(item.unit_cost+" "+item.currency if item.unit_cost else "未知"),QTableWidgetItem("、".join(k for k,state in item.fact_statuses.items() if state != "confirmed" and (item.facts.get(k) or item.observations.get(k))) or "无")]
            for col,cell in enumerate(values): cell.setToolTip(cell.text()); self.table.setItem(row,col,cell)
        self._refresh_projects(); self._loading = False

    def _refresh_projects(self):
        self.projects.blockSignals(True); self.projects.clear(); self.projects.addItem("新设计（未保存）","")
        for design in self.store.designs(): self.projects.addItem(f"{design.title or design.id[:8]} · v{design.revision}",design.id)
        self.projects.setCurrentIndex(max(0,self.projects.findData(self.design.id))); self.projects.blockSignals(False)

    def _persist(self):
        self.store.save_design(self.design,expected_revision=self.design.revision if self.design.id else None); self._dirty = False; self._refresh_projects(); self._set_editable()

    def _sync_inputs(self):
        ids = [item.id for item in self.selected_materials()]; requirements = self._requirements()
        changed = set(ids) != set(self.design.material_ids) or requirements != self.design.requirements
        if changed and self.design.locked_bom: raise ValueError("原料或条件已变化，请先解锁配方")
        if changed:
            self.design.material_ids = ids; self.design.requirements = requirements
            self.design.material_snapshot = {}; self.design.candidates = []; self.design.selected_candidate_id = ""; self._active_candidate = ""
            self._show_candidates(); self.sequence.setRowCount(0)
        self.design.title = self.title.toPlainText().strip()
        self._sync_candidate(); self._sync_listing()

    def _candidate(self):
        return next((c for c in self.design.candidates if c["id"] == self._active_candidate),None)

    def save_draft(self):
        if self.busy: return False
        try:
            self._sync_inputs(); self._persist(); self.status.setText(f"设计已保存 · v{self.design.revision}"); return True
        except (ValueError,OSError,sqlite3.Error) as error: QMessageBox.warning(self,"保存失败",str(error)); return False

    def can_leave(self):
        if self.busy: QMessageBox.information(self,"设计任务正在进行","请等待任务完成后切换页面。"); return False
        if not self._dirty: return True
        answer = QMessageBox.question(self,"保存设计","当前设计有未保存内容，是否保存？",QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel: return False
        if answer == QMessageBox.StandardButton.Save: return self.save_draft()
        # self._dirty = False; return True
        # 2026-10-15：本次修改原因：放弃修改真正恢复持久化版本，返回工作区时不残留已放弃的输入。
        saved = self.store.design(self.design.id) if self.design.id else None
        self._load(saved or BeadDesign())
        return True

    def open_project(self, design_id):
        """从 ERP 商品进入来源设计，同时保护当前正在编辑的项目。"""
        if self.design.id == design_id: return not self.busy
        if not self.can_leave(): return False
        design = self.store.design(design_id)
        if not design:
            QMessageBox.information(self,"来源设计不存在","该商品仍保留原料及配方快照，请检查本机数据目录。")
            return False
        self._load(design)
        return True

    def load_project(self,index):
        target = self.projects.itemData(index)
        if target == self.design.id: return
        if not self.can_leave(): self._refresh_projects(); return
        design = self.store.design(target) if target else BeadDesign()
        if design: self._load(design)

    def new_project(self):
        if self.can_leave(): self._load(BeadDesign())

    def duplicate_project(self):
        if not self.save_draft(): return
        design = deepcopy(self.design); design.id = ""; design.revision = 1; design.created_at = ""; design.updated_at = ""
        design.title += "（副本）"; design.listing_product_id = ""; design.locked_bom = []; design.locked_material_revisions = {}; design.listing = {}; design.state = "draft"
        self._load(design); self._dirty = True

    def _load(self,design):
        self._loading = True; self.design = design; self._active_candidate = design.selected_candidate_id or (design.candidates[0]["id"] if design.candidates else "")
        self.title.setPlainText(design.title); req = design.requirements
        self.customer.setPlainText(req.get("customer","")); self.region.setText(req.get("region","")); self.target_price.setText(req.get("price","")); self.cost_limit.setText(req.get("cost_limit","")); self.cost_currency.setText(req.get("cost_currency","CNY"))
        self.mode.setCurrentText(req.get("mode","成品手链")); self.language.setCurrentText(req.get("language","English")); self.notes.setPlainText(req.get("notes",""))
        self.materials = []; self.refresh(); self._loading = True
        self._show_candidates(); self._show_sequence(); self.confirm_bom.setChecked(bool(design.locked_bom)); self._show_listing()
        self._loading = False; self._dirty = False; self._set_editable(); self.status.setText(f"已打开：{design.title or '新设计'}")

    def _run(self,request,done):
        if self.busy: return
        self.busy = True; self.tabs.setEnabled(False); self.projects.setEnabled(False); self.status.setText("正在调用已配置模型…")
        for action in self.project_actions: action.setEnabled(False)
        def completed(result):
            self.busy = False; self.tabs.setEnabled(True); self.projects.setEnabled(True)
            for action in self.project_actions: action.setEnabled(True)
            try: done(result)
            except (ValueError,KeyError,IndexError,TypeError,OSError,sqlite3.Error) as error: self.status.setText("结果未采用："+str(error))
            self._set_editable()
        def failed(message):
            self.busy = False; self.tabs.setEnabled(True); self.projects.setEnabled(True); self._set_editable(); self.status.setText("生成失败，已有草稿保留："+str(message))
            for action in self.project_actions: action.setEnabled(True)
        self.ai_hub.submit(lambda progress:self.ai_service.generate(request,progress),completed,failed,lambda message:self.status.setText(message))

    def generate_candidates(self):
        try:
            self._sync_inputs()
            if self.design.locked_bom: raise ValueError("请先解锁配方")
            materials = self.selected_materials()
            if not materials: raise ValueError("请先勾选散珠和所需配件")
            if len(materials) > 24: raise ValueError("单次设计最多选 24 种原料，请缩小设计范围")
            if self.design.requirements["cost_limit"] and _money(self.design.requirements["cost_limit"]) is None: raise ValueError("成本上限必须为非负数字或留空")
            self.design.material_snapshot = {item.id:item.snapshot() for item in materials}; self._persist()
            self._run(design_request(self.design,materials),self._designs_generated)
        except (ValueError,OSError,sqlite3.Error) as error: QMessageBox.warning(self,"无法生成设计",str(error))

    def _designs_generated(self,result):
        value = parse_object(result.candidates[0]); rows = value.get("designs")
        if not isinstance(rows,list) or not 1 <= len(rows) <= 6: raise ValueError("模型应返回 1～6 个设计方案")
        candidates = [normalize_candidate(row,set(self.design.material_ids)) for row in rows]
        for candidate in candidates: evaluate(candidate,{item.id:item for item in self.materials},self.design.requirements)
        self.design.candidates = candidates; self.design.state = "candidates"; self._active_candidate = candidates[0]["id"]
        self.design.selected_candidate_id = self._active_candidate
        self._persist(); self._show_candidates(); self._show_sequence(); self.tabs.setCurrentIndex(1); self.status.setText("设计方向已留档，请核对排列和配方。")

    def _show_candidates(self):
        self.candidates.blockSignals(True); self.candidates.setRowCount(len(self.design.candidates))
        material_map = {item.id:item for item in self.materials}
        for row,candidate in enumerate(self.design.candidates):
            try:
                check = evaluate(candidate,material_map,self.design.requirements); cost,length,warnings = check["cost"],check["length"],check["stock"]+"\n"+"；".join(check["warnings"])
            except (ValueError,KeyError,TypeError) as error: cost,length,warnings = "待核对","待核对",str(error)
            for col,value in enumerate((candidate["name"],candidate.get("rationale",""),cost,length,warnings)):
                cell = QTableWidgetItem(value); cell.setToolTip(value); self.candidates.setItem(row,col,cell)
            if candidate["id"] == self._active_candidate: self.candidates.selectRow(row)
        self.candidates.blockSignals(False)

    def select_candidate(self):
        row = self.candidates.currentRow()
        if not 0 <= row < len(self.design.candidates): return
        target = self.design.candidates[row]["id"]
        if self.design.locked_bom and target != self.design.selected_candidate_id:
            self._show_candidates(); self.status.setText("请先解锁配方后再更换方案。"); return
        self._sync_candidate(); self._active_candidate = target; self._show_sequence(); self.confirm_bom.setChecked(bool(self.design.locked_bom))
        if not self.design.locked_bom:
            self.design.selected_candidate_id = target; self._changed()

    def _sequence_values(self):
        result = {"sequence":[],"components":[]}
        for row in range(self.sequence.rowCount()):
            kind = self.sequence.item(row,0).data(Qt.ItemDataRole.UserRole)
            result[kind].append({"material_id":self.sequence.cellWidget(row,1).currentData(),"quantity":self.sequence.cellWidget(row,2).value()})
        return result

    def _sync_candidate(self):
        candidate = self._candidate()
        # if candidate and self.sequence.rowCount() and not self.design.locked_bom: candidate.update(self._sequence_values())
        # 2026-10-15：本次修改原因：移除最后一行也同步为空配方，不能继续使用已移除的旧排列。
        if candidate and not self.design.locked_bom: candidate.update(self._sequence_values())

    def _show_sequence(self):
        self.sequence.setRowCount(0); candidate = self._candidate()
        if not candidate: return
        for kind in ("sequence","components"):
            for line in candidate.get(kind,[]): self._add_sequence_row(kind,line)
        self._update_evaluation()

    def _add_sequence_row(self,kind,line):
        row = self.sequence.rowCount(); self.sequence.insertRow(row)
        title = QTableWidgetItem(("串珠段 " if kind == "sequence" else "配件 ")+str(row+1)); title.setData(Qt.ItemDataRole.UserRole,kind); self.sequence.setItem(row,0,title)
        material = QComboBox()
        for item in self.materials:
            # if item.id in self.design.material_ids: material.addItem(item.code+" · "+item.name,item.id)
            # 2026-10-15：本次修改原因：配方选料下拉框使用编号和类型，保证不填写原料名称也能辨识选项。
            if item.id in self.design.material_ids: material.addItem(item.code+" · "+MATERIAL_CATEGORY_LABELS.get(item.category,item.category),item.id)
        material.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        material.setMinimumContentsLength(12); material.setMinimumWidth(0)
        material.setCurrentIndex(material.findData(line.get("material_id")))
        qty = QSpinBox(); qty.setRange(1,1000); qty.setValue(line.get("quantity",1)); self.sequence.setCellWidget(row,1,material); self.sequence.setCellWidget(row,2,qty)
        material.currentIndexChanged.connect(self._sequence_changed); qty.valueChanged.connect(self._sequence_changed)
        material.setEnabled(not self.design.locked_bom); qty.setEnabled(not self.design.locked_bom)

    def _sequence_changed(self,*_args):
        self._sync_candidate(); self.confirm_bom.setChecked(False); self._changed(); self._update_evaluation()

    def add_sequence(self,kind):
        if self.design.locked_bom or not self._candidate(): return
        # self._add_sequence_row(kind,{"material_id":self.design.material_ids[0],"quantity":1}); self._sequence_changed()
        # 2026-10-15：本次修改原因：已有配件时新增串珠段仍保持分组顺序，使上下移操作与可见排列一致。
        self._add_sequence_row(kind,{"material_id":self.design.material_ids[0],"quantity":1})
        self._sequence_changed(); self._show_sequence()
        row = len(self._candidate()["sequence"])-1 if kind == "sequence" else self.sequence.rowCount()-1
        self.sequence.selectRow(row)

    def move_sequence(self,step):
        if self.design.locked_bom: return
        row = self.sequence.currentRow(); target = row+step
        if row < 0 or not 0 <= target < self.sequence.rowCount(): return
        self._sync_candidate(); candidate = self._candidate(); rows = [(kind,line) for kind in ("sequence","components") for line in candidate[kind]]
        if rows[row][0] != rows[target][0]: return
        rows[row],rows[target] = rows[target],rows[row]
        for kind in ("sequence","components"): candidate[kind] = [line for key,line in rows if key == kind]
        self._show_sequence(); self.sequence.selectRow(target); self.confirm_bom.setChecked(False); self._changed()

    def remove_sequence(self):
        if not self.design.locked_bom and self.sequence.currentRow() >= 0: self.sequence.removeRow(self.sequence.currentRow()); self._sequence_changed()

    def _update_evaluation(self):
        candidate = self._candidate()
        if not candidate: return
        try:
            check = evaluate(candidate,{item.id:item for item in self.materials},self._requirements())
            self.bom_status.setText(f"材料成本：{check['cost']} · {check['length']} · {check['stock']}\n"+"；".join(check["warnings"]))
        except (ValueError,KeyError) as error: self.bom_status.setText(str(error))

    def lock_bom(self):
        try:
            self._sync_inputs(); candidate = self._candidate()
            if not candidate: raise ValueError("请先选择一个设计方案")
            if not self.confirm_bom.isChecked(): raise ValueError("请先核对配方并勾选确认")
            normalized = normalize_candidate(candidate,set(self.design.material_ids)); normalized["id"] = candidate["id"]; candidate.update(normalized)
            current = {item_id:self.store.material(item_id) for item_id in self.design.material_ids}
            if any(not item or item.revision != self.design.material_snapshot.get(item_id,{}).get("revision") for item_id,item in current.items()): raise ValueError("原料资料在生成后发生变化，请刷新并重新生成方案")
            check = evaluate(candidate,current,self.design.requirements)
            blockers = [warning for warning in check["warnings"] if "库存不足" in warning or "超过设定上限" in warning or (self.design.requirements.get("cost_limit") and "无法校验成本上限" in warning)]
            for line in check["bom"]:
                item = current[line["material_id"]]
                if any(state == "conflict" for state in item.fact_statuses.values()): blockers.append(item.code+" 存在资料冲突，请先在数据库中核实")
            if blockers: raise ValueError("\n".join(blockers))
            self.design.selected_candidate_id = candidate["id"]; self.design.locked_bom = check["bom"]
            self.design.locked_material_revisions = {key:item.revision for key,item in current.items()}; self.design.state = "bom_locked"; self._persist(); self._show_sequence(); self.tabs.setCurrentIndex(2); self.status.setText("配方已锁定，可生成 Listing 和成品概念图。")
        except (ValueError,OSError,sqlite3.Error) as error: QMessageBox.warning(self,"无法锁定配方",str(error))

    def unlock(self):
        if self.design.listing_product_id: QMessageBox.information(self,"设计已汇总","请复制为新设计修改配方，已汇总商品保留原配方快照。"); return
        if QMessageBox.question(self,"解锁配方","解锁会清空本项目的 Listing 和图片采用结果，历史版本仍可查看。继续？") != QMessageBox.StandardButton.Yes: return
        self.design.locked_bom = []; self.design.locked_material_revisions = {}; self.design.listing = {}; self.design.state = "candidates"; self.confirm_bom.setChecked(False)
        try: self._persist(); self._show_sequence(); self._show_listing(); self._set_editable()
        except (ValueError,sqlite3.Error) as error: QMessageBox.warning(self,"无法解锁",str(error))

    def _check_lock(self):
        if not self.design.locked_bom: raise ValueError("请先锁定配方")
        for item_id,revision in self.design.locked_material_revisions.items():
            item = self.store.material(item_id)
            if not item or item.state == "archived" or item.revision != revision: raise ValueError("锁定后的原料资料已变更，请解锁并重新核对配方")

    def generate_listing(self):
        try:
            self._check_lock(); self._sync_listing(); self._persist()
            if self.design.listing.get("title") and QMessageBox.question(self,"重新起草 Listing","生成成功后将替换当前文案，图片和历史记录保留。继续？") != QMessageBox.StandardButton.Yes: return
            self._run(listing_request(self.design),self._listing_generated)
        except (ValueError,sqlite3.Error) as error: QMessageBox.warning(self,"无法起草 Listing",str(error))

    def _listing_generated(self,result):
        listing = normalize_listing(parse_object(result.candidates[0])); listing["images"] = self.design.listing.get("images",[])
        self.design.listing = listing; self.design.state = "listing"; self._persist(); self._show_listing(); self.status.setText("Listing 参考已留档，请核实文案并生成或上传图片。")

    def _sync_listing(self):
        if not self.design.locked_bom: return
        self.design.listing.update({"title":self.listing_title.toPlainText().strip(),"bullets":[x.strip() for x in self.bullets.toPlainText().splitlines() if x.strip()],"description_html":self.description.toPlainText(),"image_briefs":[x.strip() for x in self.purposes.toPlainText().splitlines() if x.strip()],"images_confirmed":self.image_review.isChecked(),"price":self.sale_price.text().strip(),"currency":self.sale_currency.text().strip().upper()})

    def _show_listing(self):
        self._loading = True; value = self.design.listing
        self.listing_title.setPlainText(value.get("title","")); self.bullets.setPlainText("\n".join(value.get("bullets",[]))); self.description.setPlainText(value.get("description_html",""))
        self.purposes.setPlainText("\n".join(value.get("image_briefs") or ["主图：白底展示完整手链","细节图：珠子表面与配色","佩戴概念图：呈现整体效果","SKU 图：仅展示当前款式"]))
        self.sale_price.setText(value.get("price","")); self.sale_currency.setText(value.get("currency","USD")); self.image_review.setChecked(value.get("images_confirmed",False))
        self.listing_warnings.setText("；".join(str(x) for x in value.get("warnings",[]))+"\n生成图为概念展示，请核对配方与 SKU，打样后可上传实物图。")
        self._show_images(); self._loading = False

    def generate_images(self):
        try:
            self._check_lock(); self._sync_listing(); purposes = self.design.listing["image_briefs"]
            if not 1 <= len(purposes) <= 8: raise ValueError("请填写 1～8 个图片用途，每行一张")
            self._persist(); self._run(image_request(self.design,purposes),self._images_generated)
        except (ValueError,sqlite3.Error) as error: QMessageBox.warning(self,"无法生成图片",str(error))

    def _images_generated(self,result):
        images = self.design.listing.setdefault("images",[])
        for asset,purpose in zip(result.assets,result.purposes):
            role = "sku" if "SKU" in purpose.upper() else ("main" if "主图" in purpose else "detail")
            images.append({"uri":asset.uri,"purpose":purpose,"selected":False,"origin":"AI 概念图","role":role})
        self.design.listing["images_confirmed"] = False; self._persist(); self._show_listing()
        self.status.setText(f"已保存 {len(result.assets)} 张图片。"+("失败用途请单独填入后重试："+"；".join(result.errors) if result.errors else "请预览后勾选采用图并人工核对。"))

    def upload_images(self):
        try:
            self._check_lock(); self._sync_listing()
            paths,_ = QFileDialog.getOpenFileNames(self,"上传成品 / 打样图片","","图片 (*.png *.jpg *.jpeg *.webp)")
            for path in paths:
                uri = self.ai_service.assets.import_file(Path(path)).uri
                rows = self.design.listing.setdefault("images",[])
                rows.append({"uri":uri,"purpose":"打样 / 成品图片","selected":False,"origin":"用户上传","role":"main_sku" if not rows else "detail"})
            if paths: self.design.listing["images_confirmed"] = False; self._persist(); self._show_listing()
        except (ValueError,OSError,sqlite3.Error) as error: QMessageBox.warning(self,"无法导入成品图片",str(error))

    def _show_images(self):
        self.images.blockSignals(True); rows = self.design.listing.get("images",[]); self.images.setRowCount(len(rows))
        for row,value in enumerate(rows):
            if "role" not in value: value["role"] = "main_sku" if row == 0 else "main"
            check = QTableWidgetItem(); check.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsUserCheckable); check.setCheckState(Qt.CheckState.Checked if value.get("selected") else Qt.CheckState.Unchecked); self.images.setItem(row,0,check)
            role = QComboBox()
            for key,text in IMAGE_ROLES.items(): role.addItem(text,key)
            role.setCurrentIndex(max(0,role.findData(value["role"]))); self.images.setCellWidget(row,1,role)
            role.currentIndexChanged.connect(lambda _index,r=row:self._image_role_changed(r))
            for col,text in ((2,value["purpose"]+" · "+value["origin"]),(3,value["uri"])): cell = QTableWidgetItem(text); cell.setToolTip(text); self.images.setItem(row,col,cell)
        self.images.blockSignals(False)
        if rows: self.images.selectRow(0)
        else: self.preview.set_url("")

    def _image_changed(self,item):
        if self._loading or item.column() != 0: return
        self.design.listing["images"][item.row()]["selected"] = item.checkState() == Qt.CheckState.Checked; self.image_review.setChecked(False); self._changed()

    def _image_role_changed(self,row):
        if self._loading: return
        self.design.listing["images"][row]["role"] = self.images.cellWidget(row,1).currentData()
        self.image_review.setChecked(False); self._changed()

    def move_image(self,step):
        row = self.images.currentRow(); rows = self.design.listing.get("images",[]); target = row+step
        if self.design.listing_product_id or row < 0 or not 0 <= target < len(rows): return
        rows[row],rows[target] = rows[target],rows[row]
        self.image_review.setChecked(False); self._changed(); self._show_images(); self.images.selectRow(target)

    def remove_image(self):
        row = self.images.currentRow(); rows = self.design.listing.get("images",[])
        if self.design.listing_product_id or not 0 <= row < len(rows): return
        rows.pop(row); self.image_review.setChecked(False); self._changed(); self._show_images()

    def show_image(self):
        row = self.images.currentRow(); rows = self.design.listing.get("images",[])
        self.preview.set_url(rows[row]["uri"] if 0 <= row < len(rows) else "")

    def publish(self):
        try:
            if self.design.listing_product_id:
                if self.open_erp: self.open_erp(self.design.listing_product_id)
                return
            self._check_lock(); self._sync_listing(); self._persist()
            product = make_product(self.design,self.sale_price.text().strip(),self.sale_currency.text().strip().upper())
            saved = self.repository.create_design_product(product); self.design.listing_product_id = saved.id; self.design.state = "published"; self._persist()
            self.status.setText("商品已汇总至回传 ERP；请确认售价、图片和文案后审核，再执行回传。")
            if self.open_erp: self.open_erp(saved.id)
        except (ValueError,OSError,sqlite3.Error) as error: QMessageBox.warning(self,"无法汇总商品",str(error))

    def edit_product(self):
        if self.design.listing_product_id and self.open_product: self.open_product(self.design.listing_product_id)
        else: QMessageBox.information(self,"尚未汇总商品","请先完成配方、Listing 和图片核对，再汇总商品。")

    def show_history(self):
        if self.busy or not self.design.id: return
        dialog = QDialog(self); dialog.setWindowTitle("设计版本记录"); dialog.resize(900,680); layout = QVBoxLayout(dialog)
        text = AutoHeightTextEdit(json.dumps(self.store.versions(self.design.id),ensure_ascii=False,indent=2),minimum_lines=20,maximum_lines=30); text.setReadOnly(True)
        layout.addWidget(scroll_form(text),1); layout.addWidget(button("关闭",dialog.accept)); dialog.exec()

    def _set_editable(self):
        locked = bool(self.design.locked_bom); published = bool(self.design.listing_product_id)
        self.table.setEnabled(not locked); self.generate_button.setEnabled(not locked)
        for widget in (self.customer,self.region,self.target_price,self.cost_limit,self.cost_currency,self.mode,self.language,self.notes): widget.setEnabled(not locked)
        self.lock_button.setEnabled(not locked); self.unlock_button.setEnabled(locked and not published); self.confirm_bom.setEnabled(not locked)
        for index in range(self.sequence_actions.count()): self.sequence_actions.itemAt(index).widget().setEnabled(not locked)
        for widget in (self.listing_button,self.image_button,self.upload_button,self.listing_title,self.bullets,self.description,self.purposes,self.images,self.image_review,self.sale_price,self.sale_currency): widget.setEnabled(locked and not published)
        for action in self.image_actions: action.setEnabled(locked and not published)
        self.publish_button.setText("打开回传 ERP 中的商品" if published else "汇总至回传 ERP"); self.publish_button.setEnabled(locked)
        self.edit_product_button.setEnabled(published)
