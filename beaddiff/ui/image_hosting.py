# 2026-10-14：本次修改原因：提供图床配置和已托管素材管理入口，AI 候选图不在生成阶段自动上传。
from __future__ import annotations

from pathlib import Path

import httpx

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView,
    QFileDialog, QLabel, QLineEdit, QMessageBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..assets import local_asset_path
from ..image_hosting import GitHubImageHosting, ImageHostingConfig, ImageHostingStore
from .ai_runner import TaskHub
from .table_support import configure_table
from .widgets import button, card, label


class ImageHostingConfigPage(QWidget):
    def __init__(self, store: ImageHostingStore, hosting: GitHubImageHosting, hub: TaskHub, parent=None):
        super().__init__(parent)
        self.store, self.hosting, self.hub = store, hosting, hub
        self.checking = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        frame, contents = card()
        contents.addWidget(label("图床配置", "sectionTitle"))
        contents.addWidget(label("AI 生成图只保存在本机；点击同步到 ERP 时，系统才会按最终商品快照上传并替换公网链接。", "hint", True))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.enabled = QCheckBox("启用 GitHub + jsDelivr")
        self.enabled.setToolTip("启用后，含 file: 本机图片的商品才能同步到 ERP。")
        form.addRow("状态", self.enabled)
        self.provider = QComboBox()
        self.provider.addItem("GitHub + jsDelivr", "github")
        self.provider.setEnabled(False)
        form.addRow("提供方", self.provider)
        self.owner = QLineEdit()
        self.owner.setPlaceholderText("GitHub 用户名或组织名")
        form.addRow("用户名", self.owner)
        self.repository = QLineEdit()
        self.repository.setPlaceholderText("公开仓库名称，例如 erp-images")
        form.addRow("仓库", self.repository)
        self.branch = QLineEdit()
        self.branch.setPlaceholderText("main")
        form.addRow("分支", self.branch)
        self.base_path = QLineEdit()
        self.base_path.setPlaceholderText("beaddiff-images")
        form.addRow("图片目录", self.base_path)
        token_row = QHBoxLayout()
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("只保存在本机配置文件，不会写入日志")
        token_row.addWidget(self.token, 1)
        self.show_token = QCheckBox("显示")
        self.show_token.toggled.connect(lambda checked: self.token.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        token_row.addWidget(self.show_token)
        form.addRow("Token", token_row)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 120)
        self.timeout.setSuffix(" 秒")
        form.addRow("网络超时", self.timeout)
        contents.addLayout(form)
        actions = QHBoxLayout()
        # actions.addWidget(button("保存配置", self.save, primary=True))
        # 2026-10-14：本次修改原因：明确忽略 clicked 的布尔参数，避免关键字配置参数被信号传参干扰。
        actions.addWidget(button("保存配置", lambda _checked=False: self.save(), primary=True))
        self.test_button = button("测试连接", self.test_connection)
        actions.addWidget(self.test_button)
        # 2026-10-14：本次修改原因：配置被外部修改时可直接重新读取，不要求重启软件。
        actions.addWidget(button("重新读取", self.reload_from_disk))
        actions.addStretch()
        contents.addLayout(actions)
        self.config_status = label("", "hint", True)
        contents.addWidget(self.config_status)
        layout.addWidget(frame)
        layout.addWidget(label("准备工作：GitHub 仓库必须为 Public；Token 需要有向该仓库写入 Contents 的权限。生产环境建议后续切换到 OSS/COS 等对象存储。", "hint", True))
        layout.addStretch()
        self.reload()

    def reload(self) -> None:
        config = self.store.config
        self.enabled.setChecked(config.enabled)
        self.owner.setText(config.owner)
        self.repository.setText(config.repository)
        self.branch.setText(config.branch)
        self.base_path.setText(config.base_path)
        self.token.setText(config.token)
        self.timeout.setValue(config.timeout)
        # 2026-10-14：本次修改原因：配置缺项与文件损坏均在原设置页解释，用户可修复后保存。
        self.config_status.setText(self.store.error or "\n".join(config.problems()))

    def reload_from_disk(self) -> None:
        self.store.reload()
        self.reload()

    def _value(self) -> ImageHostingConfig:
        return ImageHostingConfig(
            enabled=self.enabled.isChecked(), provider=str(self.provider.currentData()),
            owner=self.owner.text().strip(), repository=self.repository.text().strip(),
            branch=self.branch.text().strip() or "main", base_path=self.base_path.text().strip() or "beaddiff-images",
            token=self.token.text().strip(), timeout=self.timeout.value(),
        )

    # def save(self) -> bool:
    # 2026-10-14：本次修改原因：测试连接时静默保存，避免测试前先弹“保存成功”打断流程。
    def save(self, *, notify: bool = True) -> bool:
        try:
            # self.store.save(self._value())
            # 2026-10-14：本次修改原因：损坏配置经用户确认后备份重建，正常配置仍防止覆盖外部改动。
            if self.store.error:
                answer = QMessageBox.question(self, "重建图床配置", "原配置文件无法读取。是否备份原文件，并按当前填写内容重建？")
                if answer != QMessageBox.StandardButton.Yes:
                    return False
                self.store.recover(self._value())
            else:
                self.store.save(self._value())
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "保存失败", str(error))
            return False
        self.config_status.setText("配置已保存。")
        if notify:
            QMessageBox.information(self, "已保存", "图床配置已保存；同步 ERP 时会按需上传本机图片。")
        return True

    def test_connection(self) -> None:
        if self.checking:
            return
        # if not self.save():
        if not self.save(notify=False):
            return
        self.checking = True
        self.test_button.setEnabled(False)
        self.test_button.setText("测试中…")
        # self.hub.submit(self.hosting.test_connection, self._test_done, self._test_failed)
        # 2026-10-14：本次修改原因：TaskHub 的工作函数接收进度回调，避免测试连接直接抛 TypeError。
        self.hub.submit(lambda _progress: self.hosting.test_connection(), self._test_done, self._test_failed)

    def _test_done(self, _value=None) -> None:
        self.checking = False
        self.test_button.setEnabled(True)
        self.test_button.setText("测试连接")
        # QMessageBox.information(self, "连接成功", "已成功访问 GitHub 仓库。")
        # 2026-10-14：本次修改原因：空仓库测试通过时说明目录在首次上传创建，并区分可读检查与写入验证。
        message = _value if isinstance(_value, str) else "已成功访问 GitHub 仓库。"
        QMessageBox.information(self, "连接成功", message + "\n本次未上传文件；Contents 写入权限将在实际上传时验证。")

    def _test_failed(self, message: str) -> None:
        self.checking = False
        self.test_button.setEnabled(True)
        self.test_button.setText("测试连接")
        QMessageBox.warning(self, "连接失败", message)


class ImageHostingPage(QWidget):
    def __init__(self, store: ImageHostingStore, hosting: GitHubImageHosting, hub: TaskHub, parent=None):
        super().__init__(parent)
        self.store, self.hosting, self.hub = store, hosting, hub
        self.pending = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        heading.addWidget(label("图床", "pageTitle"))
        heading.addWidget(label("已采用或手动上传的图片", "muted"))
        heading.addStretch()
        heading.addWidget(button("打开图床设置", self.open_settings))
        # 2026-10-14：本次修改原因：运营人员可主动托管本机图片并复制直链，无需先绑定商品。
        heading.addWidget(button("上传图片", self.upload_file, primary=True))
        heading.addWidget(button("刷新", self.refresh))
        layout.addLayout(heading)
        layout.addWidget(label("AI 候选图不会自动上传。应用到商品后，只有同步 ERP 时才会托管最终商品快照中的本机图片。", "hint", True))
        self.status = label("", "hint", True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["图片", "本机素材", "公网链接", "状态", "操作"])
        configure_table(self.table, editable=False, multiline=True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(76)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 86)
        self.table.setColumnWidth(3, 100)
        # self.table.setColumnWidth(4, 170)
        self.table.setColumnWidth(4, 220)
        layout.addWidget(self.table, 1)

    def open_settings(self) -> None:
        window = self.window()
        if hasattr(window, "open_settings"):
            window.open_settings(getattr(window, "SETTINGS_HOSTING", 4))

    def refresh(self) -> None:
        # 2026-10-14：本次修改原因：显式保留缓存错误，不依赖界面旧提示内容判断是否读取失败。
        cache_error = ""
        try:
            records = self.store.records()
        except ValueError as error:
            # 2026-10-14：本次修改原因：缓存损坏时保持页面可操作，并明确提示用户处理本机缓存文件。
            records = []
            # self.status.setText(str(error))
            cache_error = str(error)
        self.table.setRowCount(0)
        for record in records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            source = str(record.get("source_uri", ""))
            public = str(record.get("public_url", ""))
            preview = QLabel("无预览")
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setFixedSize(72, 62)
            path = local_asset_path(source)
            if path:
                # 2026-10-14：本次修改原因：按缩略图尺寸解码大图，避免图床列表因全尺寸图片占满内存。
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                if reader.size().isValid():
                    reader.setScaledSize(reader.size().scaled(QSize(68, 58), Qt.AspectRatioMode.KeepAspectRatio))
                pixmap = QPixmap.fromImage(reader.read())
                if not pixmap.isNull():
                    preview.setPixmap(pixmap.scaled(68, 58, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
            self.table.setCellWidget(row, 0, preview)
            source_item = QTableWidgetItem(source)
            source_item.setToolTip(source)
            self.table.setItem(row, 1, source_item)
            public_item = QTableWidgetItem(public)
            public_item.setToolTip(public)
            self.table.setItem(row, 2, public_item)
            # self.table.setItem(row, 3, QTableWidgetItem("已托管" if public else "待处理"))
            # 2026-10-14：本次修改原因：状态来自持久记录，失败和中断任务可直接在图床页重试。
            state = str(record.get("status", "pending"))
            status_item = QTableWidgetItem({"ready": "已托管", "pending": "待重试", "failed": "失败"}.get(state, "待重试"))
            status_item.setToolTip(str(record.get("last_error", "")) or str(record.get("provider_key", "")))
            self.table.setItem(row, 3, status_item)
            actions = QWidget()
            action_layout = QHBoxLayout(actions)
            action_layout.setContentsMargins(4, 2, 4, 2)
            # 2026-10-14：本次修改原因：异步回调只持有 URL，不引用刷新后已销毁的表格单元格。
            copy = button("复制", lambda _checked=False, value=public: QApplication.clipboard().setText(value))
            # check = button("检测", lambda _checked=False, value=public: self.check_url(value))
            check = button("检测", lambda _checked=False, value=public, saved=record: self.check_url(value, saved))
            retry = button("重试", lambda _checked=False, value=source: self.retry(value))
            copy.setEnabled(bool(public) and state == "ready")
            check.setEnabled(bool(public))
            retry.setEnabled(local_asset_path(source) is not None)
            retry.setToolTip("按当前图床配置重试，内容相同的已有文件会复用。")
            action_layout.addWidget(copy)
            action_layout.addWidget(check)
            action_layout.addWidget(retry)
            self.table.setCellWidget(row, 4, actions)
        # if records or not self.status.text().startswith("图床缓存读取失败"):
        #     self.status.setText(f"共 {len(records)} 张已托管图片；失败任务可在同步 ERP 时重试。")
        ready = sum(record.get("status") == "ready" for record in records)
        self.status.setText(cache_error or f"共 {len(records)} 条记录，已托管 {ready} 张，待重试 {len(records) - ready} 张。")

    # def check_url(self, url: str, target: QTableWidgetItem | None) -> None:
    # 2026-10-14：本次修改原因：回调按链接重新定位当前表格行，刷新页面后也不会操作失效对象。
    # def check_url(self, url: str) -> None:
    # 2026-10-14：本次修改原因：公网检测更新持久状态，页面刷新后不会丢失检测结果。
    def check_url(self, url: str, record: dict | None = None) -> None:
        if not url:
            return
        if self.pending:
            return
        self.pending = True
        self.status.setText("正在检测公网链接…")
        # self.hub.submit(lambda: self._head(url), lambda _value: self._check_done(target),
        #                 lambda message: self._check_failed(message, target))
        # self.hub.submit(lambda _progress: self._head(url), lambda _value: self._check_done(url), ...)
        self.hub.submit(lambda _progress: self.hosting.verify_record(record) if record else self._head(url), lambda _value: self._check_done(url),
                        lambda message: self._check_failed(message, url))

    @staticmethod
    def _head(url: str) -> None:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            response = client.head(url)
            if response.status_code in {405, 501}:
                response = client.get(url, headers={"Range": "bytes=0-32"})
            response.raise_for_status()
            if not response.headers.get("content-type", "").lower().startswith(("image/", "application/octet-stream")):
                raise ValueError("链接返回的内容不是图片。")

    def _set_status(self, url: str, status: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 2)
            if item and item.text() == url:
                self.table.item(row, 3).setText(status)

    # def _check_done(self, target: QTableWidgetItem | None) -> None:
    def _check_done(self, url: str) -> None:
        self.pending = False
        self.refresh()
        self._set_status(url, "可访问")
        self.status.setText("公网链接可访问。")

    # def _check_failed(self, message: str, target: QTableWidgetItem | None) -> None:
    def _check_failed(self, message: str, url: str) -> None:
        self.pending = False
        self.refresh()
        self._set_status(url, "不可访问")
        self.status.setText("公网链接不可访问，可点击重试。")
        QMessageBox.warning(self, "检测失败", message)

    def retry(self, source: str) -> None:
        if self.pending or not source:
            return
        self.pending = True
        # self.status.setText("正在验证图床链接…")
        self.status.setText("正在重试托管并验证公网链接…")
        # self.hub.submit(lambda: self.hosting.ensure_public(source), lambda _value: self._retry_done(),
        #                 self._retry_failed)
        self.hub.submit(lambda _progress: self.hosting.ensure_public(source, verify_cached=True), lambda _value: self._retry_done(),
                        self._retry_failed)

    # 2026-10-14：本次修改原因：独立图床页允许主动导入并上传图片，失败不会写进商品草稿。
    def upload_file(self) -> None:
        if self.pending:
            return
        filename, _filter = QFileDialog.getOpenFileName(self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.gif)")
        if not filename:
            return
        self.pending = True
        self.status.setText("正在导入并上传图片…")
        def work(_progress):
            asset = self.hosting.assets.import_file(Path(filename))
            return self.hosting.ensure_public(asset.uri)
        self.hub.submit(work, self._upload_done, self._retry_failed)

    def _upload_done(self, url: str) -> None:
        self.pending = False
        self.refresh()
        QApplication.clipboard().setText(url)
        self.status.setText("图片已托管，公网链接已复制。")

    def _retry_done(self) -> None:
        self.pending = False
        self.refresh()

    def _retry_failed(self, message: str) -> None:
        self.pending = False
        # 2026-10-14：本次修改原因：上传失败后立即展示留下的失败记录，无需用户手动刷新。
        self.refresh()
        self.status.setText("图床托管失败，请检查设置或稍后重试。")
        QMessageBox.warning(self, "托管失败", message)
