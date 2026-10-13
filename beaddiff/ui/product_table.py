# 2026-10-13：本次修改原因：移除商品速览后，商品列表集中展示 ERP 风格字段、缩略图及逐行操作，避免大量行控件拖慢列表。
from __future__ import annotations

from collections import OrderedDict, deque
from decimal import Decimal, InvalidOperation

# from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, QUrl, Signal
# 2026-10-13：本次修改原因：商品列表改为 Model/View，代理排序按稳定商品 ID 操作。
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QSettings, QEvent, QPoint, QRect, QRectF, Qt, QTimer, QUrl, Signal
# from PySide6.QtGui import QColor, QPixmap
# 2026-10-13：本次修改原因：明确绘制枚举所属类型，避免缩略图/操作委托依赖实例属性别名。
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
# from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionViewItem, QTableWidget
# 2026-10-13：本次修改原因：统一可见行绘制及状态标签，不创建商品单元格控件。
from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionViewItem, QTableView
from .theme import status_colors, theme_tokens

from ..assets import local_asset_path
from .table_support import CellEditorDelegate


# key、列名、初始宽度、默认是否显示；编号及辅助提示可以按需展开，不压缩主要业务字段。
PRODUCT_COLUMNS = [
    ("selected", "", 40, True),
    ("image", "主图", 76, True),
    ("product", "商品 / 主编号", 340, True),
    ("platform", "平台 / 站点", 94, True),
    ("route", "获取方式", 92, True),
    ("sku", "SKU / 属性", 106, True),
    # ("price", "SKU 售价", 122, True),
    # 2026-10-13：本次修改原因：列名明确展示售价与币种，覆盖原速览中的售价币种字段。
    ("price", "售价 / 币种", 122, True),
    ("materials", "图片 / 视频", 150, False),
    ("review", "审核状态", 88, True),
    ("modified", "修改状态", 88, True),
    ("transfer", "传回 ERP", 92, True),
    ("updated", "更新时间", 110, True),
    ("source_id", "货源 ID", 172, False),
    ("erp_id", "妙手原商品 / 回传 ID", 192, False),
    ("revision", "版本", 70, False),
    ("issues", "检查 / 提示", 230, False),
    ("actions", "操作", 162, True),
]
PRODUCT_COL = {key: index for index, (key, *_rest) in enumerate(PRODUCT_COLUMNS)}
IMAGE_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def price_summary(product) -> tuple[str, str]:
    """只汇总已填写 SKU 售价；货源价格和不同币种不混算。"""
    groups: dict[str, list[Decimal]] = {}
    for sku in product.skus:
        try:
            amount = Decimal(sku.price)
        except (InvalidOperation, ValueError, TypeError):
            continue
        if amount.is_finite() and amount > 0:
            currency = (sku.currency or product.currency or "币种待确认").upper()
            groups.setdefault(currency, []).append(amount)
    lines = []
    for currency, prices in groups.items():
        low, high = min(prices), max(prices)
        values = format(low.normalize(), "f")
        if low != high:
            values += "–" + format(high.normalize(), "f")
        lines.append(values + " " + currency)
    filled = sum(map(len, groups.values()))
    hint = "SKU 售价（未换算币种，不使用货源价代填）\n" + ("\n".join(lines) or "尚未填写有效售价")
    if filled != len(product.skus):
        hint += f"\n有效售价 {filled}/{len(product.skus)} 个 SKU；空值或无效值请到销售属性核对。"
    # text = lines[0] if len(lines) == 1 else ("多币种售价" if lines else "未填写")
    # 2026-10-13：本次修改原因：未填写售价时也展示商品已配置币种，避免移除速览后币种信息消失。
    text = lines[0] if len(lines) == 1 else ("多币种售价" if lines else "未填写\n" + (product.currency or "币种待确认"))
    hint += "\n商品售价币种：" + (product.currency or "待确认")
    return text, hint


# 2026-10-13：本次修改原因：保留旧表格类供对照，运行时使用轻量 Model/View 和现有操作回调。
# class ProductTable(QTableWidget):
#     def __init__(self):
#         super().__init__(0, len(PRODUCT_COLUMNS))
#         self.setHorizontalHeaderLabels([title for _key, title, _width, _visible in PRODUCT_COLUMNS])
# 
#     def fit_title(self) -> None:
#         # 标题保持可读宽度；空间不足时横向滚动，避免其他列挤成半截文字。
#         column = PRODUCT_COL["product"]
#         remaining = sum(self.columnWidth(index) for index in range(self.columnCount())
#                         if index != column and not self.isColumnHidden(index))
#         self.setColumnWidth(column, max(340, self.viewport().width() - remaining))
# 
#     def resizeEvent(self, event) -> None:
#         super().resizeEvent(event)
#         if self.horizontalHeader().sectionResizeMode(PRODUCT_COL["product"]) == QHeaderView.ResizeMode.Interactive:
#             self.fit_title()

SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 2


class ProductModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(PRODUCT_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return PRODUCT_COLUMNS[section][1] if orientation == Qt.Orientation.Horizontal else section + 1
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key = PRODUCT_COLUMNS[index.column()][0]
        if role == Qt.ItemDataRole.UserRole:
            return row["id"]
        if role == IMAGE_ROLE:
            return row.get("image_url", "") if key == "image" else None
        if role == Qt.ItemDataRole.CheckStateRole and key == "selected":
            return Qt.CheckState.Checked if row["checked"] else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            return row["values"].get(key, "")
        if role == Qt.ItemDataRole.ToolTipRole:
            return row["hints"].get(key, row["values"].get(key, ""))
        if role == SORT_ROLE:
            return row.get("sort", {}).get(key, row["values"].get(key, ""))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if key in {"route", "review", "modified", "transfer", "revision"}:
                return Qt.AlignmentFlag.AlignCenter
            if key == "price":
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.isValid() and index.column() == PRODUCT_COL["selected"]:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != PRODUCT_COL["selected"] or role != Qt.ItemDataRole.CheckStateRole:
            return False
        checked = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        if self.rows[index.row()]["checked"] != checked:
            self.rows[index.row()]["checked"] = checked
            self.dataChanged.emit(index, index, [int(role)])
        return True

    def replace_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


class ProductCell:
    """只读单元格适配；保留原工具栏、完整查看和批量勾选回调，行号按显示顺序。"""
    def __init__(self, table, row, column):
        self.table, self._row, self._column = table, row, column

    def row(self):
        return self._row

    def column(self):
        return self._column

    def index(self):
        return self.table.model().index(self._row, self._column)

    def text(self):
        return self.index().data(Qt.ItemDataRole.DisplayRole) or ""

    def data(self, role):
        return self.index().data(role)

    def flags(self):
        return self.index().flags()

    def toolTip(self):
        return self.index().data(Qt.ItemDataRole.ToolTipRole) or ""

    def setToolTip(self, text):
        source = self.table.proxy.mapToSource(self.index())
        self.table.source_model.rows[source.row()]["hints"][PRODUCT_COLUMNS[source.column()][0]] = text

    def checkState(self):
        return self.index().data(Qt.ItemDataRole.CheckStateRole) or Qt.CheckState.Unchecked

    def setCheckState(self, value):
        self.table.model().setData(self.index(), value, Qt.ItemDataRole.CheckStateRole)


class ProductTable(QTableView):
    itemChanged = Signal(object)
    itemSelectionChanged = Signal()
    itemDoubleClicked = Signal(object)

    def __init__(self):
        super().__init__()
        self.source_model = ProductModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.source_model)
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setDynamicSortFilter(True)
        self.setModel(self.proxy)
        self.source_model.dataChanged.connect(self._changed)
        self.selectionModel().currentChanged.connect(lambda *_: self.itemSelectionChanged.emit())
        self.doubleClicked.connect(lambda index: self.itemDoubleClicked.emit(self.item(index.row(), index.column())))
        self.hover_row = -1
        self.viewport().setMouseTracking(True)
        self.width_settings = QSettings("BeadDiff", "BeadDiff")
        self.width_timer = QTimer(self)
        self.width_timer.setSingleShot(True)
        self.width_timer.setInterval(250)
        self.width_timer.timeout.connect(self.save_widths)
        self.horizontalHeader().sectionResized.connect(lambda *_: self.width_timer.start())

    def set_rows(self, rows):
        self.source_model.replace_rows(rows)
        self.hover_row = -1

    def _changed(self, top_left, bottom_right, roles):
        if int(Qt.ItemDataRole.CheckStateRole) in roles:
            index = self.proxy.mapFromSource(top_left)
            self.itemChanged.emit(self.item(index.row(), index.column()))

    def rowCount(self):
        return self.proxy.rowCount()

    def columnCount(self):
        return self.proxy.columnCount()

    def item(self, row, column):
        if 0 <= row < self.rowCount() and 0 <= column < self.columnCount():
            return ProductCell(self, row, column)
        return None

    def itemAt(self, position):
        index = self.indexAt(position)
        return self.item(index.row(), index.column()) if index.isValid() else None

    def currentRow(self):
        return self.currentIndex().row()

    def setCurrentCell(self, row, column):
        self.setCurrentIndex(self.model().index(row, column))

    def fit_title(self):
        # 手动列宽优先；只在恢复默认列时使用建议宽度。
        column = PRODUCT_COL["product"]
        remaining = sum(self.columnWidth(index) for index in range(self.columnCount())
                        if index != column and not self.isColumnHidden(index))
        self.setColumnWidth(column, max(340, self.viewport().width() - remaining))

    def restore_widths(self):
        widths = self.width_settings.value("ui/products/column_widths_v1", {})
        if isinstance(widths, dict):
            for key, width in widths.items():
                if key in PRODUCT_COL and isinstance(width, int):
                    self.setColumnWidth(PRODUCT_COL[key], max(40, min(1200, width)))

    def save_widths(self):
        self.width_settings.setValue("ui/products/column_widths_v1",
            {key: self.columnWidth(index) for index, (key, *_rest) in enumerate(PRODUCT_COLUMNS)})

    def viewportEvent(self, event):
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.Leave):
            row = self.indexAt(event.position().toPoint()).row() if event.type() == QEvent.Type.MouseMove else -1
            if row != self.hover_row:
                for target in (self.hover_row, row):
                    if target >= 0:
                        self.viewport().update(QRect(0, self.rowViewportPosition(target), self.viewport().width(), self.rowHeight(target)))
                self.hover_row = row
        return super().viewportEvent(event)

    # 2026-10-13：本次修改原因：滚动时清除旧悬停行，避免原位置状态遗留到另一条商品。
    def scrollContentsBy(self, dx, dy):
        self.hover_row = -1
        super().scrollContentsBy(dx, dy)


class ProductRowDelegate(CellEditorDelegate):
    def paint(self, painter, option, index):
        adjusted = QStyleOptionViewItem(option)
        if index.row() == self.parent().hover_row:
            adjusted.state |= QStyle.StateFlag.State_MouseOver
        super().paint(painter, adjusted, index)


class StatusBadgeDelegate(ProductRowDelegate):
    def paint(self, painter, option, index):
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        if index.row() == self.parent().hover_row:
            background.state |= QStyle.StateFlag.State_MouseOver
        self.parent().style().drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, self.parent())
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        key = PRODUCT_COLUMNS[index.column()][0]
        bg, fg = status_colors(text, key)
        width = min(option.rect.width() - 10, option.fontMetrics.horizontalAdvance(text) + 16)
        rect = QRectF(option.rect.center().x() - width / 2, option.rect.center().y() - 14, width, 28)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(QColor(fg))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class ProductThumbnailDelegate(CellEditorDelegate):
    """仅为绘制到的行加载图片，限制并发与缓存，不给每行创建 QLabel。"""
    def __init__(self, table, network):
        super().__init__(table)
        self.table, self.network = table, network
        self.cache: OrderedDict[str, QPixmap | None] = OrderedDict()
        self.pending = deque()
        self.queued: set[str] = set()
        self.replies: dict[QNetworkReply, tuple[str, bytearray]] = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._load_pending)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        address = index.data(IMAGE_ROLE) or ""
        size = min(56, option.rect.width() - 14, option.rect.height() - 14)
        rect = QRect(option.rect.center().x() - size // 2, option.rect.center().y() - size // 2, size, size)
        painter.save()
        # painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        # painter.setBrush(QColor("#f2f6f7"))
        # 2026-10-13：本次修改原因：主图占位随主题切换。
        painter.setBrush(QColor(theme_tokens()["alternate"]))
        painter.drawRoundedRect(QRectF(rect), 5, 5)
        if address in self.cache and self.cache[address] is not None:
            pixmap = self.cache[address].scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(rect.center().x() - pixmap.width() // 2,
                               rect.center().y() - pixmap.height() // 2, pixmap)
            self.cache.move_to_end(address)
        else:
            # painter.setPen(QColor("#8b9da4"))
            painter.setPen(QColor(theme_tokens()["muted"]))
            font = painter.font()
            font.setPixelSize(11)
            painter.setFont(font)
            text = "无主图" if not address else ("未加载" if address in self.cache else "加载中")
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            if address and address not in self.cache and address not in self.queued:
                self.pending.append(address)
                self.queued.add(address)
                self.timer.start(0)
        painter.restore()

    def _remember(self, address, pixmap) -> None:
        self.cache[address] = pixmap
        self.cache.move_to_end(address)
        while len(self.cache) > 200:
            self.cache.popitem(last=False)
        self.queued.discard(address)
        # self.table.viewport().update()
        # 2026-10-13：本次修改原因：图片返回仅刷新可见且引用该图片的单元格，避免整表重绘。
        first = max(0, self.table.rowAt(0))
        last = self.table.rowAt(self.table.viewport().height() - 1)
        last = self.table.rowCount() - 1 if last < 0 else last
        for row in range(first, last + 1):
            index = self.table.model().index(row, PRODUCT_COL["image"])
            if index.data(IMAGE_ROLE) == address:
                self.table.viewport().update(self.table.visualRect(index))

    def _load_pending(self) -> None:
        while self.pending and len(self.replies) < 3:
            address = self.pending.popleft()
            local = local_asset_path(address)
            if local:
                pixmap = QPixmap(str(local))
                self._remember(address, pixmap.scaled(112, 112, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation) if not pixmap.isNull() else None)
                continue
            url = QUrl(address)
            if url.scheme() not in {"http", "https"} or not url.host():
                self._remember(address, None)
                continue
            request = QNetworkRequest(url)
            request.setTransferTimeout(8000)
            request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                                 QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
            reply = self.network.get(request)
            reply.setParent(self)
            self.replies[reply] = (address, bytearray())
            reply.readyRead.connect(lambda reply=reply: self._read(reply))
            reply.finished.connect(lambda reply=reply: self._finish(reply))

    def _read(self, reply) -> None:
        entry = self.replies.get(reply)
        if entry:
            entry[1].extend(bytes(reply.readAll()))
            if len(entry[1]) > 8 * 1024 * 1024:
                reply.abort()

    def _finish(self, reply) -> None:
        self._read(reply)
        entry = self.replies.pop(reply, None)
        if entry:
            address, raw = entry
            pixmap = QPixmap()
            loaded = (len(raw) <= 8 * 1024 * 1024 and reply.error() == QNetworkReply.NetworkError.NoError
                      and pixmap.loadFromData(bytes(raw)))
            self._remember(address, pixmap.scaled(112, 112, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation) if loaded else None)
        reply.deleteLater()
        self.timer.start(0)


class ProductActionsDelegate(CellEditorDelegate):
    editRequested = Signal(str)
    moreRequested = Signal(str, QPoint)

    def __init__(self, table):
        super().__init__(table)
        self.table = table
        self.busy = False

    @staticmethod
    def buttons(rect):
        width = max(74, rect.width() - 68)
        height = min(34, rect.height() - 16)
        edit = QRect(rect.left() + 8, rect.center().y() - height // 2, width, height)
        more = QRect(edit.right() + 7, edit.top(), 46, height)
        return edit, more

    def paint(self, painter, option, index):
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        self.table.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, self.table)
        painter.save()
        # painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 2026-10-13：本次修改原因：行内操作与主题保持一致，任务锁仍由现有调度决定。
        tokens = theme_tokens()
        for rect, text, color in zip(self.buttons(option.rect), ("编辑 / AI", "更多"), (tokens["accent"], tokens["muted"])):
            painter.setPen(Qt.PenStyle.NoPen)
            # painter.setBrush(QColor("#eaf5f1" if text == "编辑 / AI" else "#f0f4f6"))
            painter.setBrush(QColor(tokens["selected"] if text == "编辑 / AI" else tokens["alternate"]))
            painter.drawRoundedRect(QRectF(rect), 5, 5)
            # painter.setPen(QColor("#aab7bc" if self.busy else color))
            painter.setPen(QColor(tokens["disabled"] if self.busy else color))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if (event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.Left
                and not self.busy):
            edit, more = self.buttons(option.rect)
            point = event.position().toPoint()
            identity = index.data(Qt.ItemDataRole.UserRole)
            if edit.contains(point):
                self.editRequested.emit(identity)
                return True
            if more.contains(point):
                self.moreRequested.emit(identity, self.table.viewport().mapToGlobal(point))
                return True
        return False
