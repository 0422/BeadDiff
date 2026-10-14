# 2026-10-14：本次修改原因：设置集中维护白底图类目、整套任务与建档预设，加工页复用当前模型。
from dataclasses import replace
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QScrollArea, QSpinBox, QVBoxLayout, QWidget
from ..listing import ListingDefaults
from .widgets import AutoHeightTextEdit, button, card, label

class ListingSettingsPage(QScrollArea):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWidgetResizable(True)
        body = QWidget()
        root = QVBoxLayout(body)
        try:
            self.defaults = store.get()
            error = ''
        except (ValueError, OSError) as exception:
            self.defaults, error = ListingDefaults(), str(exception)
        self.fields = {}
        for title, pairs in (
            ('生成方案', (('category', '产品类目'), ('language', '目标语言'))),
            ('建档预设（每件商品均可修改）', (('code_prefix', '主编号前缀'), ('spec1', '默认规格1'), ('currency', '售价 / 货源币种'),
             ('price', 'SKU 售价'), ('supply_price', '独立货源价'), ('stock', '库存'), ('weight', '包裹及 SKU 重量 KG'), ('dimensions', '包装及 SKU 尺寸 CM')))):
            frame, layout = card()
            layout.addWidget(label(title, 'sectionTitle'))
            form = QFormLayout()
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for key, caption in pairs:
                editor = QLineEdit(getattr(self.defaults, key))
                self.fields[key] = editor
                if key == 'category':
                    editor.setPlaceholderText('例如：首饰配件 / 手工串珠；用于生成，发布类目在妙手确认')
                form.addRow(caption, editor)
            if title == '生成方案':
                self.main_count, self.detail_count = QSpinBox(), QSpinBox()
                self.main_count.setRange(1, 15)
                self.detail_count.setRange(1, 12)
                self.main_count.setValue(self.defaults.main_count)
                self.detail_count.setValue(self.defaults.detail_count)
                form.addRow('主图 / 轮播目标数量', self.main_count)
                form.addRow('详情图目标数量', self.detail_count)
                self.instruction = AutoHeightTextEdit(self.defaults.instruction)
                form.addRow('整套生成要求（Prompt）', self.instruction)
                layout.addWidget(label('上传后自动生成标题、简述、详情正文、主图、详情图和默认 SKU 图。主体图多于目标数量时全部纳入审核。', 'hint', True))
            else:
                layout.addWidget(label('这些数值用于建档，不代表实测信息。默认库存为 0；审核前请核对售价、货源成本及物流信息。非 CNY 币种需在设置 → 妙手 ERP 配置汇率。', 'hint', True))
            layout.addLayout(form)
            root.addWidget(frame)
        self.status = label(error, 'warning', True)
        root.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button('保存白底图配置', self.save, primary=True))
        root.addLayout(actions)
        root.addStretch()
        self.setWidget(body)

    def save(self):
        values = {key: control.text().strip() for key, control in self.fields.items()}
        values['currency'] = values['currency'].upper()
        defaults = replace(self.defaults, **values, main_count=self.main_count.value(), detail_count=self.detail_count.value(),
                           instruction=self.instruction.toPlainText().strip())
        try:
            self.store.save(defaults)
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            QMessageBox.warning(self, '白底图配置未保存', str(error))
            return
        self.defaults = defaults
        self.status.setText('已保存。下次上传白底图时生效；当前商品和已有方案保持原值。')
