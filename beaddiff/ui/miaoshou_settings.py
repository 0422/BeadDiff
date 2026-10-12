# 2026-10-11：本次修改原因：提供妙手开放平台本地凭证、人民币汇率和只读连接测试入口，不要求把密钥发到聊天中。
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget

from ..miaoshou import MiaoshouAdapter
from ..miaoshou_config import API_BASE, MiaoshouConfig, MiaoshouConfigStore
from .widgets import button, card, label


class MiaoshouSettingsPage(QWidget):
    def __init__(self, store: MiaoshouConfigStore, adapter: MiaoshouAdapter, runner, changed, parent=None):
        super().__init__(parent)
        self.store, self.adapter, self.runner, self.changed = store, adapter, runner, changed
        self.busy = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        contents = QVBoxLayout(body)
        frame, layout = card()
        layout.addWidget(label("妙手开放平台 · 公共采集箱", "sectionTitle"))
        layout.addWidget(label("这里填写妙手开放平台为你的账号分配的 AppKey/AppSecret；Apifox 文档密码不能用于调用接口。", "hint", True))
        form = QFormLayout()
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
        form.addRow("AppSecret", self.secret)
        form.addRow("请求超时", self.timeout)
        layout.addLayout(form)
        layout.addWidget(label("人工确认的人民币汇率", "sectionTitle"))
        layout.addWidget(label("每行填 币种=1单位该币种对应的人民币金额，例如 USD=7.20。CNY 固定为 1；未填的币种不会自动换算。", "hint", True))
        self.rates = QPlainTextEdit()
        self.rates.setPlaceholderText("CNY=1\nUSD=请填写你确认的汇率")
        self.rates.setMaximumHeight(110)
        layout.addWidget(self.rates)
        self.status = label("", "hint", True)
        layout.addWidget(self.status)
        layout.addWidget(label(f"凭证单独保存于 {store.path}，已忽略 Git；该文件是本地明文文件。", "muted", True))
        actions = QHBoxLayout()
        self.save_button = button("保存凭证与汇率", self.save, primary=True)
        self.reload_button = button("重新加载", self.reload)
        self.clear_button = button("清空凭证", self.clear)
        self.test_button = button("测试连接（只读）", self.test)
        for item in (self.reload_button, self.clear_button, self.test_button, self.save_button):
            actions.addWidget(item)
        layout.addLayout(actions)
        layout.addWidget(label("连接测试只查询 1 条公共采集箱记录；测试成功不代表已获新增/更新或图片接口权限。回传写入公共采集箱，认领和发布仍在妙手完成。", "hint", True))
        contents.addWidget(frame)
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
        contents.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.refresh()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget in (self.key, self.secret, self.timeout, self.rates, self.save_button,
                       self.reload_button, self.clear_button, self.test_button):
            widget.setEnabled(not busy)
        # 2026-10-12：本次修改原因：回传运行期间不能清除正在使用的图片缓存。
        self.clear_picture_cache_button.setEnabled(not busy)

    def refresh(self) -> None:
        config = self.store.config
        self.key.setText(config.app_key)
        self.secret.setText(config.app_secret)
        self.timeout.setValue(config.timeout)
        self.rates.setPlainText("\n".join(f"{code}={value}" for code, value in sorted(config.cny_rates.items())))
        self.status.setText(self.adapter.unavailable_reason or "凭证已保存。可测试只读连接，再到商品库进行回传。")

    def save(self) -> None:
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
            self.store.save(MiaoshouConfig(self.key.text().strip(), self.secret.text().strip(), self.timeout.value(), rates))
            self.refresh()
            self.changed()
            self.status.setText(self.adapter.unavailable_reason or "已保存到本地文件，下一次回传使用此配置。")
        except (OSError, ValueError) as error:
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
