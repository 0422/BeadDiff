# 2026-10-11：本次修改原因：提供妙手开放平台本地凭证、人民币汇率和只读连接测试入口，不要求把密钥发到聊天中。
from __future__ import annotations

# from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget
# 2026-10-13：本次修改原因：汇率从多行文本改为结构化编辑表格，保存协议和原校验方法保持不变。
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit,
    QMessageBox, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget,
)

from ..miaoshou import MiaoshouAdapter
from ..miaoshou_config import API_BASE, MiaoshouConfig, MiaoshouConfigStore
from .widgets import button, card, label
from .table_support import CellEditorDelegate, configure_table, fit_table_rows


# 2026-10-13：本次修改原因：空白汇率行显示填写示例，单元格编辑保持字符串精度，避免浮点控件截断汇率。
class CurrencyRateDelegate(CellEditorDelegate):
    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            editor.setPlaceholderText("如 USD" if index.column() == 0 else "如 7.20")
            if index.column() == 1:
                editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        return editor

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.column() < 2 and not index.data(Qt.ItemDataRole.DisplayRole):
            painter.save()
            painter.setPen(option.palette.color(QPalette.ColorRole.PlaceholderText))
            alignment = Qt.AlignmentFlag.AlignVCenter | (
                Qt.AlignmentFlag.AlignLeft if index.column() == 0 else Qt.AlignmentFlag.AlignRight)
            painter.drawText(option.rect.adjusted(10, 0, -10, 0), alignment,
                             "输入币种" if index.column() == 0 else "输入人民币金额")
            painter.restore()


# 2026-10-13：本次修改原因：新增/移除币种以空白行和行内按钮呈现，仍通过原有币种=汇率文本适配层保存。
class CurrencyRatesEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["币种", "1 单位折合人民币 (CNY)", ""])
        configure_table(self.table, editable=True)
        self.table.setItemDelegate(CurrencyRateDelegate(self.table))
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(2, 48)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                   QAbstractItemView.EditTrigger.EditKeyPressed |
                                   QAbstractItemView.EditTrigger.SelectedClicked)
        self.table.itemChanged.connect(self.row_changed)
        # fit_table_rows(self.table, maximum_rows=5)
        # 2026-10-13：本次修改原因：汇率行随内容展开，避免设置页出现第二根局部纵向滚动条。
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fit_table_rows(self.table, maximum_rows=None)
        layout.addWidget(self.table)

    def append_row(self, code="", value="", *, fixed=False):
        blocked = self.table.blockSignals(True)
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, text in enumerate((code, value)):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (
                Qt.AlignmentFlag.AlignLeft if column == 0 else Qt.AlignmentFlag.AlignRight))
            item.setToolTip("CNY 固定为 1" if fixed else text)
            if fixed:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, column, item)
        remove = QToolButton()
        remove.setText("×")
        remove.setToolTip("移除此币种；点击保存后生效" if not fixed else "CNY 固定为 1")
        remove.setAccessibleName("移除此币种")
        remove.setEnabled(not fixed and bool(code or value))
        remove.clicked.connect(lambda _checked=False, target=remove: self.remove_row(target))
        self.table.setCellWidget(row, 2, remove)
        self.table.blockSignals(blocked)

    def row_changed(self, item):
        row = item.row()
        if row == 0:
            return
        filled = any(self.table.item(row, column).text().strip() for column in (0, 1))
        self.table.cellWidget(row, 2).setEnabled(filled)
        if filled and row == self.table.rowCount() - 1:
            self.append_row()

    def remove_row(self, target):
        for row in range(1, self.table.rowCount() - 1):
            if self.table.cellWidget(row, 2) is target:
                self.table.removeRow(row)
                return

    def setPlainText(self, text):
        blocked = self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.append_row("CNY", "1", fixed=True)
        for line in text.splitlines():
            code, separator, value = line.partition("=")
            if separator and code.strip().upper() != "CNY":
                self.append_row(code.strip(), value.strip())
        self.append_row()
        self.table.blockSignals(blocked)

    def toPlainText(self):
        rows = []
        for row in range(self.table.rowCount()):
            code, value = (self.table.item(row, column).text().strip() for column in (0, 1))
            if code or value:
                rows.append(f"{code}={value}")
        return "\n".join(rows)


class MiaoshouSettingsPage(QWidget):
    def __init__(self, store: MiaoshouConfigStore, adapter: MiaoshouAdapter, runner, changed, parent=None):
        super().__init__(parent)
        self.store, self.adapter, self.runner, self.changed = store, adapter, runner, changed
        self.busy = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        # scroll = QScrollArea()
        # scroll.setWidgetResizable(True)
        # 2026-10-13：本次修改原因：取消凭证区域独立滚动，外层 ERP 页面统一滚动全部设置卡片。
        body = QWidget()
        contents = QVBoxLayout(body)
        contents.setContentsMargins(0, 0, 0, 0)
        contents.setSpacing(16)
        frame, layout = card()
        # 2026-10-13：本次修改原因：开发平台凭证和汇率各自独立成卡片，分别提交各自配置。
        self.credentials_card = frame
        layout.addWidget(label("妙手开放平台 · 公共采集箱", "sectionTitle"))
        layout.addWidget(label("这里填写妙手开放平台为你的账号分配的 AppKey/AppSecret；Apifox 文档密码不能用于调用接口。", "hint", True))
        form = QFormLayout()
        # 2026-10-13：本次修改原因：凭证表单统一字段间距和伸展方式，与写回设置保持一致。
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.url = QLineEdit(API_BASE)
        self.url.setReadOnly(True)
        self.key = QLineEdit()
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 120)
        self.timeout.setSuffix(" 秒")
        form.addRow("官方 API 地址", self.url)
        form.addRow("AppKey", self.key)
        # form.addRow("AppSecret", self.secret)
        # 2026-10-13：本次修改原因：密钥默认掩码，允许用户核对输入，仅改变显示状态。
        from PySide6.QtWidgets import QCheckBox
        secret_row = QHBoxLayout()
        secret_row.addWidget(self.secret, 1)
        show_secret = QCheckBox("显示")
        show_secret.toggled.connect(lambda checked: self.secret.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        secret_row.addWidget(show_secret)
        form.addRow("AppSecret", secret_row)
        form.addRow("请求超时", self.timeout)
        layout.addLayout(form)
        # layout.addWidget(label("人工确认的人民币汇率", "sectionTitle"))
        # layout.addWidget(label("每行填 币种=1单位该币种对应的人民币金额，例如 USD=7.20。CNY 固定为 1；未填的币种不会自动换算。", "hint", True))
        # self.rates = QPlainTextEdit()
        # self.rates.setPlaceholderText("CNY=1\nUSD=请填写你确认的汇率")
        # self.rates.setMaximumHeight(110)
        # 2026-10-13：本次修改原因：用币种/金额两列替代文本语法，保留人工确认、CNY 固定值及原配置校验。
        # layout.addWidget(label("双击单元格填写你确认的汇率，例如 USD → 7.20。末尾空白行可添加币种，× 可移除；保存后生效。CNY 固定为 1。", "hint", True))
        self.rates = CurrencyRatesEditor()
        # layout.addWidget(self.rates)
        self.status = label("", "hint", True)
        layout.addWidget(self.status)
        layout.addWidget(label(f"凭证单独保存于 {store.path}，已忽略 Git；该文件是本地明文文件。", "muted", True))
        actions = QHBoxLayout()
        # self.save_button = button("保存凭证与汇率", self.save, primary=True)
        # 2026-10-13：本次修改原因：凭证卡片右下角独立保存，汇率未提交的输入不会被一并保存或重置。
        self.save_button = button("保存接口配置", self.save_credentials, primary=True)
        self.reload_button = button("重新加载", self.reload)
        self.clear_button = button("清空凭证", self.clear)
        self.test_button = button("测试连接（只读）", self.test)
        # for item in (self.reload_button, self.clear_button, self.test_button, self.save_button):
        for item in (self.reload_button, self.clear_button, self.test_button):
            actions.addWidget(item)
        actions.addStretch()
        actions.addWidget(self.save_button)
        layout.addWidget(label("连接测试只查询 1 条公共采集箱记录；测试成功不代表已获新增/更新或图片接口权限。回传写入公共采集箱，认领和发布仍在妙手完成。", "hint", True))
        layout.addLayout(actions)
        contents.addWidget(frame)
        # 2026-10-13：本次修改原因：汇率单独用圆角边框分隔，状态和保存按钮都归属本组。
        self.rates_card, rates_layout = card()
        rates_layout.addWidget(label("人工确认的人民币汇率", "sectionTitle"))
        rates_layout.addWidget(label("双击单元格填写汇率，例如 USD → 7.20。末尾空白行可添加币种，× 可移除；保存后生效。CNY 固定为 1。", "hint", True))
        rates_layout.addWidget(self.rates)
        self.rates_status = label("", "hint", True)
        self.rates_status.setToolTip(str(store.path))
        rates_layout.addWidget(self.rates_status)
        rates_actions = QHBoxLayout()
        rates_actions.addStretch()
        self.save_rates_button = button("保存汇率", self.save_rates, primary=True)
        rates_actions.addWidget(self.save_rates_button)
        rates_layout.addLayout(rates_actions)
        contents.addWidget(self.rates_card)
        # 2026-10-12：本次修改原因：说明上传缓存自动复用，并给远端图片已删除或同地址图片内容改变提供恢复入口。
        cache_frame, cache_layout = card()
        cache_layout.addWidget(label("图片上传缓存", "sectionTitle"))
        cache_layout.addWidget(label("每张图片成功转存后自动保存，同一账号和图片链接再次回传时复用；中途失败和重启后仍可继续使用。", "hint", True))
        cache_layout.addWidget(label("如果已在妙手删除图片，或替换了同一链接的图片内容，请清除当前账号缓存后重新上传。清除缓存不会释放妙手图片空间容量。", "muted", True))
        self.clear_picture_cache_button = button("清除当前账号图片缓存", self.clear_picture_cache)
        cache_actions = QHBoxLayout()
        cache_actions.addWidget(self.clear_picture_cache_button)
        cache_actions.addStretch()
        cache_layout.addLayout(cache_actions)
        contents.addWidget(cache_frame)
        # contents.addStretch()
        # scroll.setWidget(body)
        # outer.addWidget(scroll)
        # 2026-10-13：本次修改原因：各配置分区保留自己的动作按钮，使用外层单一滚动条。
        outer.addWidget(body)
        self.refresh()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        # 2026-10-13：本次修改原因：任务期间按钮反馈忙碌状态，查询及权限验证保持只读。
        self.test_button.setText("正在处理…" if busy else "测试连接（只读）")
        # for widget in (self.key, self.secret, self.timeout, self.rates, self.save_button,
        #                self.reload_button, self.clear_button, self.test_button):
        # 2026-10-13：本次修改原因：独立汇率保存按钮仍遵守原任务锁，处理期间不能修改配置。
        for widget in (self.key, self.secret, self.timeout, self.rates, self.save_button,
                       self.save_rates_button, self.reload_button, self.clear_button, self.test_button):
            widget.setEnabled(not busy)
        # 2026-10-12：本次修改原因：回传运行期间不能清除正在使用的图片缓存。
        self.clear_picture_cache_button.setEnabled(not busy)

    def refresh(self) -> None:
        config = self.store.config
        self.key.setText(config.app_key)
        self.secret.setText(config.app_secret)
        self.timeout.setValue(config.timeout)
        self.rates.setPlainText("\n".join(f"{code}={value}" for code, value in sorted(config.cny_rates.items())))
        # self.status.setText(self.adapter.unavailable_reason or "凭证已保存。可测试只读连接，再到商品库进行回传。")
        # 2026-10-12：本次修改原因：设置提示指向同步和商品加工的完整接口流程。
        self.status.setText(self.adapter.unavailable_reason or "凭证已保存。先测试只读连接，再同步采集箱或在商品加工回传。")
        # 2026-10-13：本次修改原因：加载反馈分别显示在对应配置卡片中。
        self.rates_status.setText("修改后点击右下角“保存汇率”生效。")

    # 2026-10-13：本次修改原因：原合并保存入口注释保留，拆为两个分区提交，沿用原配置文件及校验。
    # def save(self) -> None:
    #     if self.busy:
    #         return
    #     try:
    #         rates = {"CNY": "1"}
    #         seen = set()
    #         for line in self.rates.toPlainText().splitlines():
    #             if not line.strip():
    #                 continue
    #             parts = line.split("=")
    #             if len(parts) != 2:
    #                 raise ValueError("汇率每行应为 币种=汇率，例如 USD=7.20。")
    #             code, value = (part.strip() for part in parts)
    #             code = code.upper()
    #             if code in seen:
    #                 raise ValueError("汇率币种不能重复。")
    #             seen.add(code)
    #             rates[code] = value
    #         self.store.save(MiaoshouConfig(self.key.text().strip(), self.secret.text().strip(), self.timeout.value(), rates))
    #         self.refresh()
    #         self.changed()
    #         self.status.setText(self.adapter.unavailable_reason or "已保存到本地文件，下一次回传使用此配置。")
    #     except (OSError, ValueError) as error:
    #         QMessageBox.warning(self, "保存失败", str(error))

    # 2026-10-13：本次修改原因：只提交开发平台字段，合并已保存汇率，不读取或清空汇率草稿。
    def save_credentials(self) -> None:
        if self.busy:
            return
        try:
            saved = self.store.get()
            self.store.save(MiaoshouConfig(self.key.text().strip(), self.secret.text().strip(),
                                           self.timeout.value(), saved.cny_rates))
            self.changed()
            self.status.setText("接口配置已保存到本地文件。" + (self.adapter.unavailable_reason or "下一次接口请求使用此配置。"))
        except (OSError, ValueError) as error:
            self.status.setText("接口配置保存失败：" + str(error))
            QMessageBox.warning(self, "保存失败", str(error))

    # 2026-10-13：本次修改原因：沿用原汇率解析与文件校验，只提交汇率，保留已保存的凭证和请求超时。
    def save_rates(self) -> None:
        if self.busy:
            return
        try:
            rates = {"CNY": "1"}
            seen = set()
            for line in self.rates.toPlainText().splitlines():
                if not line.strip():
                    continue
                parts = line.split("=")
                if len(parts) != 2:
                    raise ValueError("汇率每行应为 币种=汇率，例如 USD=7.20。")
                code, value = (part.strip() for part in parts)
                code = code.upper()
                if code in seen:
                    raise ValueError("汇率币种不能重复。")
                seen.add(code)
                rates[code] = value
            saved = self.store.get()
            self.store.save(MiaoshouConfig(saved.app_key, saved.app_secret, saved.timeout, rates))
            self.rates.setPlainText("\n".join(f"{code}={value}" for code, value in sorted(rates.items())))
            self.changed()
            self.rates_status.setText("汇率已保存到本地文件，下一次回传使用此配置。")
        except (OSError, ValueError) as error:
            self.rates_status.setText("汇率保存失败：" + str(error))
            QMessageBox.warning(self, "保存失败", str(error))

    def reload(self) -> None:
        if not self.busy:
            self.store.reload()
            self.refresh()
            self.changed()

    def clear(self) -> None:
        if self.busy:
            return
        if QMessageBox.question(self, "清空本地凭证", "清空此文件中的 AppKey/AppSecret？汇率保留。",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            config = self.store.get()
            self.store.save(MiaoshouConfig(timeout=config.timeout, cny_rates=config.cny_rates))
            self.refresh()
            self.changed()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "清空失败", str(error))

    def test(self) -> None:
        if self.busy:
            return
        if self.adapter.unavailable_reason:
            QMessageBox.information(self, "请先保存配置", self.adapter.unavailable_reason)
            return
        client = self.adapter.client()
        self.status.setText("正在查询公共采集箱连接…（使用已保存的凭证）")
        self.runner(lambda: client.list_products(size=1),
                    lambda result: self.status.setText(f"只读连接成功，公共采集箱共 {result.get('total', '未知')} 条商品。"))

    # 2026-10-12：本次修改原因：用户确认后在后台清除当前已保存 AppKey 的本地映射，不删除妙手图片或其他账号缓存。
    def clear_picture_cache(self) -> None:
        if self.busy:
            return
        try:
            account_id = self.store.get().account_id
            if not account_id:
                raise ValueError("请先保存需要清除图片缓存的 AppKey。")
        except ValueError as error:
            QMessageBox.information(self, "请先保存配置", str(error))
            return
        if QMessageBox.question(self, "清除本地图片上传缓存",
                                "清除当前已保存账号的本地上传记录？妙手图片和本地商品都会保留；后续回传可能需要重新上传图片。",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.status.setText("正在清除当前账号的本地图片缓存…")
        self.runner(lambda: self.adapter.clear_picture_cache(account_id),
                    lambda count: self.status.setText(f"已清除当前账号 {count} 条本地图片缓存。妙手图片和商品数据已保留。"))
