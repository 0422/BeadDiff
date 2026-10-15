# 2026-10-13：本次修改原因：统一浅/深主题、状态标签与控件间距；旧浅色样式注释保留。
# # 2026-10-10：本次修改原因：统一现代电商工作台的配色、间距、表格和表单视觉。
# from PySide6.QtGui import QFont
# from PySide6.QtWidgets import QApplication
#
#
# STYLESHEET = """
# QWidget { font-family: 'Microsoft YaHei UI', 'Microsoft YaHei', 'Segoe UI'; font-size: 13px; color: #243a41; }
# QMainWindow, QDialog { background: #f4f7f9; }
# QWidget#workspace { background: #f4f7f9; }
# QFrame#sidebar { background: #102e31; border: none; }
# QLabel#brand { color: white; font-size: 23px; font-weight: 700; }
# QLabel#brandBadge { background: #33c7b0; color: #102e31; border-radius: 11px; font-size: 17px; font-weight: 800; }
# QLabel#navCaption { color: #7ea2a4; font-size: 11px; }
# QPushButton#navButton { background: transparent; color: #bad0d0; text-align: left; padding: 12px 16px; border: none; border-radius: 8px; font-size: 14px; }
# QPushButton#navButton:hover { background: #1b4143; color: white; }
# QPushButton#navButton:checked { background: #225452; color: #86efdb; font-weight: 600; }
# QLabel#pageTitle { font-size: 26px; font-weight: 700; color: #163438; }
# QLabel#sectionTitle { font-size: 16px; font-weight: 600; color: #163438; }
# QLabel#muted { color: #819198; font-size: 12px; }
# QLabel#hint { color: #668085; font-size: 12px; }
# QLabel#count { font-size: 30px; font-weight: 700; color: #163438; }
# QFrame#card { background: white; border: 1px solid #e3ebee; border-radius: 12px; }
# QFrame#notice { background: #ecf8f5; border: 1px solid #d2ece5; border-radius: 8px; }
# QLabel#noticeText { color: #247663; font-size: 12px; }
# QLabel#warning { background: #fff7e9; color: #946325; border: 1px solid #f1e2c5; border-radius: 7px; padding: 10px; }
# QLabel#empty { color: #84969c; font-size: 14px; padding: 32px; }
# QLabel#imagePreview { background: #f3f7f8; border: 1px solid #e5ecef; border-radius: 9px; color: #90a0a6; }
# QLabel#statusBadge { background: #eaf6f1; color: #248468; border-radius: 10px; padding: 5px 12px; font-size: 12px; }
# QPushButton { background: white; border: 1px solid #dce5e8; border-radius: 7px; padding: 8px 14px; min-height: 18px; }
# QPushButton:hover { background: #f4f8f9; border-color: #a9c5c6; }
# QPushButton:pressed { background: #e9f1f2; }
# QPushButton:disabled { color: #aab7bc; background: #f4f6f7; border-color: #e5ebee; }
# QPushButton#primary { background: #138b78; border-color: #138b78; color: white; font-weight: 600; }
# QPushButton#primary:hover { background: #087b69; border-color: #087b69; }
# QPushButton#primary:disabled { background: #a4cdc4; border-color: #a4cdc4; color: #f5faf9; }
# QPushButton#quiet { background: transparent; color: #148b78; border: none; padding: 6px 8px; }
# QPushButton#filterTab { background: transparent; border: none; color: #758990; padding: 9px 13px; border-radius: 6px; }
# QPushButton#filterTab:checked { background: #e8f5f1; color: #138b78; font-weight: 600; }
# QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox { background: white; border: 1px solid #dce5e8; border-radius: 7px; padding: 8px 10px; selection-background-color: #bde7de; selection-color: #163438; }
# QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #36a893; }
# QLineEdit:read-only { background: #f3f7f8; color: #61777f; }
# QComboBox { min-width: 95px; }
# QComboBox::drop-down { border: none; width: 24px; }
# QComboBox QAbstractItemView { background: white; selection-background-color: #e7f5f0; selection-color: #1c7763; outline: none; }
# QCheckBox { spacing: 8px; }
# QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #c3d2d7; border-radius: 4px; background: white; }
# QCheckBox::indicator:checked { background: #15927e; border-color: #15927e; image: none; }
# QTableWidget { background: white; border: none; gridline-color: #edf2f4; selection-background-color: #eaf5f2; selection-color: #203b3b; alternate-background-color: #fafcfd; outline: none; }
# /* QTableWidget::item { padding: 8px; border-bottom: 1px solid #edf2f4; } */
# /* 2026-10-12：本次修改原因：默认表格行高容纳文字，避免全局大内边距裁掉文字/数字。 */
# QTableWidget::item { padding: 4px 7px; border-bottom: 1px solid #edf2f4; }
# QTableWidget::item:selected { background: #eaf5f2; color: #203b3b; }
# QHeaderView::section { background: #f7f9fb; color: #71848c; border: none; border-bottom: 1px solid #e5ecef; padding: 12px 9px; font-weight: 500; }
# QTableCornerButton::section { background: #f7f9fb; border: none; }
# QTabWidget::pane { background: white; border: 1px solid #e2eaed; border-radius: 8px; top: -1px; }
# QTabBar::tab { background: transparent; padding: 12px 22px; color: #758990; border-bottom: 2px solid transparent; }
# QTabBar::tab:selected { color: #138b78; border-bottom-color: #138b78; font-weight: 600; }
# QScrollArea { background: transparent; border: none; }
# QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
# QScrollBar::handle:vertical { background: #cbd8dd; border-radius: 3px; min-height: 32px; }
# QScrollBar:horizontal { background: transparent; height: 9px; }
# QScrollBar::handle:horizontal { background: #cbd8dd; border-radius: 3px; min-width: 32px; }
# QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
# QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
# QStatusBar { background: white; color: #819198; border-top: 1px solid #e5ecef; }
# /* 2026-10-12：本次修改原因：进度与折叠工具沿用工作台配色，统计卡片紧凑展示。 */
# QStatusBar::item { border: none; }
# QProgressBar { border: none; background: #e4eeeb; border-radius: 5px; text-align: center; color: #174b40; font-size: 10px; }
# QProgressBar::chunk { background: #53b6a0; border-radius: 5px; }
# QToolButton { border: none; background: #edf6f3; color: #247663; padding: 8px; border-radius: 6px; text-align: left; }
# QToolButton:hover { background: #dfefe9; }
# /* 2026-10-13：本次修改原因：滚动表单和速览底板与软件背景一致，避免露出 Qt 默认灰色矩形。 */
# QWidget#editorForm { background: #ffffff; }
# QWidget#inspectorBody { background: #ffffff; }
# QWidget#tableViewport { background: #ffffff; }
# QPushButton#danger { color: #b4473d; border-color: #edd2cf; }
# QPushButton#danger:hover { background: #fff2ef; border-color: #dca29a; }
# QSplitter::handle { background: transparent; width: 12px; }
# QToolTip { background: #163e40; color: white; border: none; padding: 7px; }
# """
#
#
# def apply_theme(application: QApplication) -> None:
#     application.setStyle("Fusion")
#     application.setFont(QFont("Microsoft YaHei UI", 10))
#     application.setStyleSheet(STYLESHEET)
#

from string import Template

# from PySide6.QtCore import QSettings
# from PySide6.QtGui import QColor, QFont, QPalette
# from PySide6.QtWidgets import QApplication
# 2026-10-13：本次修改原因：数字输入框箭头用矢量绘制，统一浅深主题和高 DPI，不增加外部打包资源。
# from PySide6.QtCore import QSettings, QPointF, Qt
# from PySide6.QtGui import QColor, QFont, QPalette, QPainter, QPolygonF
# from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleFactory
# 2026-10-13：本次修改原因：统一下拉菜单的列表绘制和箭头，数字输入撤下增减按钮；只调整全局控件呈现。
from PySide6.QtCore import QEvent, QObject, QSettings, QPointF, Qt
# 2026-10-13：本次修改原因：展开下拉列表时标明当前选项，只同步列表高亮，不改变控件值。
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtGui import QColor, QFont, QPalette, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QComboBox, QFrame,
    QListView, QProxyStyle, QStyle, QStyleFactory, QStyledItemDelegate,
    QStyleOptionViewItem, QWidget,
)
# 2026-10-13：本次修改原因：数字输入保留正常编辑区布局，增减按钮继续由现有 QSS 隐藏。
from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox


TOKENS = {
    "light": dict(window="#F5F7F9", surface="#FFFFFF", alternate="#F8FAFC",
                  text="#172B35", muted="#526975", border="#D9E2E7",
                  accent="#0F766E", accent_hover="#115E59", accent_text="#FFFFFF",
                  selected="#D9F2ED", hover="#ECF6F3", disabled="#6E7D85",
                  # danger="#B42318", danger_bg="#FFF0EE", sidebar="#102E31"),
                  # 2026-10-13：本次修改原因：上下增减按钮采用独立底色，与输入内容明确分区。
                  # danger="#B42318", danger_bg="#FFF0EE", sidebar="#102E31", stepper="#E9EFF3"),
                  # 2026-10-13：本次修改原因：侧栏改为参考图的柔和浅色，与内容块通过留白区分；保留单一品牌主色。
                  danger="#B42318", danger_bg="#FFF0EE", sidebar="#E5EDF6", sidebar_end="#E1E8F4",
                  nav_selected="#FFFFFF", nav_hover="#D9E5F0", stepper="#E9EFF3"),
    "dark": dict(window="#11191D", surface="#1B252A", alternate="#202D33",
                 text="#E8F0F2", muted="#A7B8BE", border="#455B66",
                 accent="#42B8A5", accent_hover="#67CBB9", accent_text="#102E31",
                 selected="#214A45", hover="#253A3E", disabled="#8C9FA8",
                 # danger="#FDA29B", danger_bg="#492727", sidebar="#0D181C"),
                 # danger="#FDA29B", danger_bg="#492727", sidebar="#0D181C", stepper="#33454F"),
                 danger="#FDA29B", danger_bg="#492727", sidebar="#18242D", sidebar_end="#1C2934",
                 nav_selected="#2A413F", nav_hover="#25353D", stepper="#33454F"),
}

QSS = Template("""
QWidget { color: $text; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog, QWidget#workspace { background: $window; }
/* QFrame#sidebar { background: $sidebar; border: none; } */
/* QLabel#brand { color: #FFFFFF; font-size: 23px; font-weight: 700; } */
/* QLabel#brandBadge { background: #86EFDB; color: #102E31; border-radius: 10px; font-size: 17px; font-weight: 800; } */
/* QLabel#navCaption { color: #AEC7C7; font-size: 11px; } */
/* QPushButton#navButton { background: transparent; color: #D1E0E0; text-align: left; padding: 12px 14px; border: none; border-radius: 8px; } */
/* QPushButton#navButton:hover { background: #1B4143; color: #FFFFFF; } */
/* QPushButton#navButton:checked { background: #225452; color: #ABF5E5; font-weight: 600; } */
/* 2026-10-13：本次修改原因：导航改为浅色层次和紧凑选中块，去除深色侧栏及多余说明；深色主题使用对应 Token。 */
QWidget#desktopShell { background: $window; }
/* QFrame#sidebar { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 $sidebar,stop:1 $sidebar_end); border: none; border-radius: 10px; } */
/* 2026-10-13：本次修改原因：侧栏顶到头，圆角统一由整窗外轮廓负责，避免侧栏右上出现内凹圆角和顶部空隙。 */
QFrame#sidebar { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 $sidebar,stop:1 $sidebar_end); border: none; border-radius: 0px; }
QWidget#workspaceColumn { background: $window; }
QLabel#brand { color: $text; font-size: 23px; font-weight: 700; }
QLabel#brandBadge { background: $accent; color: $accent_text; border-radius: 10px; font-size: 16px; font-weight: 700; }
QLabel#navCaption { color: $muted; font-size: 11px; }
QPushButton#navButton { background: transparent; color: $text; text-align: left; padding: 11px 12px; border: none; border-radius: 8px; }
QPushButton#navButton:hover { background: $nav_hover; }
QPushButton#navButton:checked { background: $nav_selected; color: $accent; font-weight: 600; }
/* 2026-10-14：本次修改原因：底部日志、设置和回收站只显示居中的图标，避免继承文字导航左对齐内边距。 */
QPushButton#navButton[iconOnly="true"] { text-align: center; padding: 0px; }
/* 2026-10-13：本次修改原因：顶部只显示标准窗口操作，背景融入工作区，不再重复软件名称与图标。 */
QFrame#windowBar { background: $window; border: none; }
QToolButton#windowControl, QToolButton#windowClose { background: transparent; border: none; border-radius: 4px; padding: 0px; margin: 0px; }
QToolButton#windowControl:hover { background: $border; }
QToolButton#windowControl:pressed { background: $selected; }
QToolButton#windowClose:hover, QToolButton#windowClose:pressed { background: #C42B1C; }
/* 2026-10-13：本次修改原因：列表来源用紧凑分段按钮切换，对应获取入口紧邻显示，避免堆叠多个更多菜单。 */
QFrame#sourceSwitch { background: $alternate; border: 1px solid $border; border-radius: 8px; }
QPushButton#sourceTab { background: transparent; color: $muted; border: none; border-radius: 6px; padding: 7px 12px; min-height: 18px; }
QPushButton#sourceTab:hover { background: $hover; color: $text; }
QPushButton#sourceTab:checked { background: $selected; color: $accent; font-weight: 600; }
QLabel#pageTitle { font-size: 25px; font-weight: 700; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; }
QLabel#count { font-size: 26px; font-weight: 700; }
/* 2026-10-13：本次修改原因：顶部统计紧凑并排，主操作高度统一，减少装饰性大卡片。 */
QFrame#metricChip { background: $surface; border: 1px solid $border; border-radius: 8px; }
QLabel#metricValue { font-size: 16px; font-weight: 700; }
QLabel#hint, QLabel#muted { color: $muted; font-size: 12px; }
QFrame#card, QWidget#panel { background: $surface; border: 1px solid $border; border-radius: 10px; }
QWidget#panel QLabel { border: none; }
/* 2026-10-13：本次修改原因：设置左右各保留一层圆角边框，内部配置用留白分组，避免卡片和标签容器描边叠加。 */
QFrame#settingsContentFrame { background: $surface; border: 1px solid $border; border-radius: 10px; }
/* QFrame#settingsContentFrame QFrame#card { background: transparent; border: none; border-radius: 0px; } */
/* 2026-10-13：本次修改原因：各自保存生效的配置重新用独立圆角卡片分组；外层滚动整页，避免只滚动一块。 */
QFrame#settingsContentFrame QFrame#card { background: $surface; border: 1px solid $border; border-radius: 10px; }
QFrame#settingsContentFrame QTabWidget::pane { background: transparent; border: none; }
QListWidget#settingsNavigation { background: transparent; border: none; padding: 0px; }
QListWidget#settingsNavigation::item { padding: 11px 12px; margin: 2px 0px; border: none; border-radius: 8px; }
QListWidget#settingsNavigation::item:hover { background: $hover; }
QListWidget#settingsNavigation::item:selected { background: $selected; color: $accent; font-weight: 600; }
QFrame#notice { background: $hover; border: 1px solid $border; border-radius: 8px; }
QLabel#noticeText { color: $accent; font-size: 12px; }
QLabel#warning { background: $danger_bg; color: $danger; border: 1px solid $border; border-radius: 8px; padding: 10px; }
QLabel#empty { color: $muted; font-size: 14px; padding: 24px; }
QLabel#imagePreview { background: $alternate; border: 1px solid $border; border-radius: 8px; color: $muted; }
QLabel#statusBadge { background: $selected; color: $text; border-radius: 8px; padding: 5px 10px; }
QPushButton { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 8px 12px; min-height: 18px; }
QPushButton:hover { background: $hover; border-color: $accent; }
QPushButton:pressed { background: $selected; }
QPushButton:focus { border: 1px solid $accent; }
QPushButton:disabled { color: $disabled; background: $alternate; border-color: $border; }
QPushButton#primary { background: $accent; border-color: $accent; color: $accent_text; font-weight: 600; }
QPushButton#primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#primary:pressed { background: $accent_hover; }
QPushButton#primary:disabled { background: $alternate; border-color: $border; color: $disabled; }
QPushButton[compact="true"], QToolButton[compact="true"] { padding: 7px 9px; }
QPushButton#quiet { background: transparent; color: $accent; border: 1px solid transparent; padding: 6px 8px; }
QPushButton#quiet:hover { background: $hover; }
QPushButton#danger { color: $danger; border-color: $danger; }
QPushButton#danger:hover, QPushButton#danger:pressed { background: $danger_bg; }
/* 2026-10-15：本次修改原因：原料图片空状态使用居中加号和虚线圆角上传框，图片操作收至预览右上角，颜色跟随主题。 */
QPushButton#materialUpload { background: $alternate; border: 2px dashed $border; border-radius: 10px; padding: 0px; min-height: 0px; }
QPushButton#materialUpload:hover, QPushButton#materialUpload:focus { background: $hover; border-color: $accent; }
QPushButton#materialUpload:pressed { background: $selected; border-color: $accent; }
QLabel#materialUploadPlus { background: transparent; color: $accent; font-size: 38px; }
QLabel#materialUploadCaption { background: transparent; color: $muted; font-size: 13px; }
QPushButton#materialImageAction { background: $surface; color: $text; border: 1px solid $border; border-radius: 7px; padding: 0px; min-height: 0px; min-width: 0px; font-size: 22px; }
QPushButton#materialImageAction:hover, QPushButton#materialImageAction:focus { background: $hover; color: $accent; border-color: $accent; }
QPushButton#materialImageAction:pressed { background: $selected; }
QPushButton#materialImageAction[removeImage="true"]:hover, QPushButton#materialImageAction[removeImage="true"]:focus { background: $danger_bg; color: $danger; border-color: $danger; }
/* 2026-10-15：本次修改原因：原料图片底部轮播使用紧凑箭头及清晰的缩略图选中边框，配色沿用浅深主题。 */
QPushButton#materialPhotoNav { background: $surface; color: $text; border: 1px solid $border; border-radius: 7px; padding: 0px; min-height: 0px; min-width: 0px; font-size: 22px; }
QPushButton#materialPhotoNav:hover, QPushButton#materialPhotoNav:focus { background: $hover; color: $accent; border-color: $accent; }
QPushButton#materialPhotoNav:pressed { background: $selected; }
QPushButton#materialPhotoNav:disabled { background: $surface; color: $disabled; border-color: $border; }
QPushButton#filterTab { background: transparent; border: none; color: $muted; padding: 8px 12px; }
QPushButton#filterTab:hover { background: $hover; }
QPushButton#filterTab:checked { background: $selected; color: $text; font-weight: 600; }
/* QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 8px 10px; selection-background-color: $selected; selection-color: $text; } */
/* QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: $accent; } */
/* 2026-10-13：本次修改原因：为全部数字输入控件划分清楚的输入区与增减区，保留原范围、键盘和滚轮操作。 */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 8px 10px; selection-background-color: $selected; selection-color: $text; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: $accent; }
/* QSpinBox, QDoubleSpinBox { padding: 6px 36px 6px 10px; min-height: 24px; } */
/* 2026-10-13：本次修改原因：数字输入使用完整的输入区域，不保留右侧箭头或增减色块。 */
QSpinBox, QDoubleSpinBox { padding: 8px 10px; min-height: 18px; }
/* QSpinBox QLineEdit, QDoubleSpinBox QLineEdit { border: none; border-radius: 0px; padding: 0px; background: transparent; } */
/* 2026-10-13：本次修改原因：恢复数字框文字可见宽度后，内层编辑区保持与普通输入框一致的横向留白。 */
QSpinBox QLineEdit, QDoubleSpinBox QLineEdit { border: none; border-radius: 0px; padding: 0px 10px; background: transparent; }
/* QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 28px; background: $stepper; border-left: 1px solid $border; border-bottom: 1px solid $border; border-top-right-radius: 7px; } */
/* QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 28px; background: $stepper; border-left: 1px solid $border; border-bottom-right-radius: 7px; } */
/* QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: $hover; } */
/* QSpinBox::up-button:pressed, QSpinBox::down-button:pressed, QDoubleSpinBox::up-button:pressed, QDoubleSpinBox::down-button:pressed { background: $selected; } */
/* QSpinBox::up-button:disabled, QSpinBox::down-button:disabled, QDoubleSpinBox::up-button:disabled, QDoubleSpinBox::down-button:disabled { background: $alternate; } */
/* QSpinBox::up-arrow, QSpinBox::down-arrow, QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow { width: 10px; height: 6px; } */
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; height: 0px; border: none; background: transparent; }
QLineEdit:read-only { background: $alternate; color: $muted; }
/* QLineEdit[cellEditor="true"] { padding: 2px 5px; min-height: 0px; border-radius: 3px; border: 1px solid $accent; } */
/* 2026-10-15：本次修改原因：表格内多行资料输入沿用单行编辑器的主题边框和紧凑留白。 */
QLineEdit[cellEditor="true"], QPlainTextEdit[cellEditor="true"] { padding: 2px 5px; min-height: 0px; border-radius: 3px; border: 1px solid $accent; }
/* QComboBox::drop-down { border: none; width: 24px; } */
/* 2026-10-13：本次修改原因：下拉输入与展开列表统一圆角、行高和留白，不沿用系统菜单的凹凸边框。 */
QComboBox { padding: 8px 34px 8px 12px; min-height: 18px; }
QComboBox::drop-down { border: none; width: 28px; background: transparent; }
QComboBox::down-arrow { image: none; width: 0px; height: 0px; }
/* 2026-10-15：本次修改原因：原料来源和状态列撤下多余右侧留白，箭头仅占右侧 22px，缩窄列宽后仍有足够文字空间。 */
QComboBox[materialFactChoice="true"] { padding: 8px 0px 8px 6px; min-width: 0px; }
QComboBox[materialFactChoice="true"]::drop-down { subcontrol-origin: border; subcontrol-position: center right; width: 22px; }
/* QFrame#comboPopupFrame { background: $surface; border: 1px solid $border; border-radius: 10px; } */
/* QListView#comboPopupList { background: transparent; border: none; padding: 2px; outline: none; } */
/* 2026-10-13：本次修改原因：修复下拉窗口透明导致文字透出并重叠；边框由不透明列表自身绘制，不依赖透明弹出容器。 */
QFrame#comboPopupFrame { background: $surface; border: none; border-radius: 0px; }
QComboBox QAbstractItemView, QListView#comboPopupList { background: $surface; color: $text; border: 1px solid $border; border-radius: 6px; padding: 4px; outline: none; selection-background-color: $selected; selection-color: $text; }
QComboBox QAbstractItemView::item, QListView#comboPopupList::item { min-height: 20px; padding: 5px 10px; border: none; border-radius: 4px; }
QComboBox QAbstractItemView::item:hover, QListView#comboPopupList::item:hover { background: $hover; }
QComboBox QAbstractItemView::item:selected, QListView#comboPopupList::item:selected { background: $selected; color: $text; }
QComboBox QAbstractItemView::item:disabled, QListView#comboPopupList::item:disabled { color: $disabled; background: $surface; }
QWidget#comboChevron { background: transparent; border: none; }
/* QComboBox QAbstractItemView, QListWidget { background: $surface; color: $text; selection-background-color: $selected; selection-color: $text; border: 1px solid $border; outline: none; } */
QListWidget { background: $surface; color: $text; selection-background-color: $selected; selection-color: $text; border: 1px solid $border; outline: none; }
QListWidget::item { padding: 8px; }
/* 2026-10-15：本次修改原因：底部缩略图片带使用透明底色与紧凑留白，当前图片即使失焦也保留清晰高亮。 */
QListWidget#materialPhotoThumbnails { background: transparent; border: none; padding: 0px; }
QListWidget#materialPhotoThumbnails::item { padding: 4px; border: 2px solid transparent; border-radius: 7px; }
QListWidget#materialPhotoThumbnails::item:hover { background: $hover; border-color: $border; }
QListWidget#materialPhotoThumbnails::item:selected { background: $selected; color: $text; border-color: $accent; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QTableView, QTableWidget { background: $surface; border: 1px solid $border; border-radius: 8px; alternate-background-color: $alternate; selection-background-color: $selected; selection-color: $text; gridline-color: $border; outline: none; }
/* 2026-10-13：本次修改原因：主工作区表格和只读回执已被圆角分区包围，取消重复的内层边框，保留表头与行分隔。 */
QTableView[embeddedTable="true"], QTableWidget[embeddedTable="true"] { border: none; border-radius: 0px; }
/* 2026-10-15：本次修改原因：数据库原料列表使用独立的 2px 圆角外框，避免表格内部控件遮挡边界。 */
QFrame#databaseListFrame { background: $surface; border: 2px solid $border; border-radius: 10px; }
/* 2026-10-15：本次修改原因：原料弹窗的图片区和资料表分别使用清晰的圆角外框，沿用浅深主题配色。 */
QFrame#materialImageFrame, QFrame#materialFactsFrame { background: $surface; border: 2px solid $border; border-radius: 10px; }
QFrame#materialImageFrame QLabel#imagePreview { border: none; }
/* 2026-10-15：本次修改原因：表格边缘入口平时融入背景，悬停或键盘聚焦时显示加号和新增区域。 */
QToolButton#tableEdgeAdd { background: transparent; color: transparent; border: 1px solid transparent; border-radius: 5px; padding: 0px; min-width: 0px; min-height: 0px; font-size: 19px; }
QToolButton#tableEdgeAdd[edgeActive="true"], QToolButton#tableEdgeAdd:hover, QToolButton#tableEdgeAdd:focus { background: $selected; color: $accent; border: 1px dashed $accent; }
QToolButton#tableEdgeAdd:pressed { background: $hover; color: $accent; }
QPlainTextEdit[embeddedViewer="true"] { border: none; border-radius: 0px; padding: 6px; }
QTableView::item, QTableWidget::item { padding: 4px 7px; border: none; border-bottom: 1px solid $border; }
QTableView::item:hover, QTableWidget::item:hover { background: $hover; }
QTableView::item:selected, QTableWidget::item:selected { background: $selected; color: $text; }
QHeaderView { background: $surface; }
QHeaderView::section { background: $alternate; color: $muted; border: none; border-bottom: 1px solid $border; padding: 8px; font-weight: 600; }
QHeaderView#rowNumbers::section { background: $surface; padding: 4px; }
QTableCornerButton::section { background: $alternate; border: none; }
QTabWidget::pane { background: $surface; border: 1px solid $border; border-radius: 8px; }
QTabBar::tab { background: transparent; padding: 10px 15px; color: $muted; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: $accent; border-bottom-color: $accent; font-weight: 600; }
/* 2026-10-13：本次修改原因：AI 模型分类使用独立圆角标签，下方当前分类内容统一圆角区，不改变分类与操作。 */
QTabWidget#modelTabs::pane, QFrame#settingsContentFrame QTabWidget#modelTabs::pane { background: $surface; border: 1px solid $border; border-radius: 10px; }
QTabBar#modelTypeTabs::tab { background: $surface; color: $muted; border: 1px solid $border; border-radius: 8px; padding: 9px 18px; margin: 0px 8px 10px 0px; }
QTabBar#modelTypeTabs::tab:hover { background: $hover; }
QTabBar#modelTypeTabs::tab:selected { background: $selected; color: $accent; border: 1px solid $accent; font-weight: 600; }
/* 2026-10-13：本次修改原因：日志一级标签强调分类，去掉容器重复描边，内层来源筛选沿用紧凑按钮。 */
QTabWidget#logTabs::pane { border: none; background: transparent; }
QTabBar#logTypeTabs::tab { font-size: 14px; padding: 10px 22px; }
QTabBar#logTypeTabs::tab:hover { background: $hover; }
QTabBar#logTypeTabs::tab:selected { color: $accent; background: $selected; border-bottom-color: $accent; }
/* 2026-10-13：本次修改原因：商品编辑模式以紧凑分段控件呈现，沿用当前主题与焦点反馈。 */
QTabBar#editorModeTabs::tab { background: $surface; color: $muted; padding: 8px 16px; border: 1px solid $border; border-radius: 6px; margin-left: 4px; }
QTabBar#editorModeTabs::tab:hover { background: $hover; }
QTabBar#editorModeTabs::tab:selected { background: $selected; color: $accent; border-color: $accent; }
QTabBar#editorModeTabs::tab:disabled { color: $muted; background: $alternate; }
/* 2026-10-14：本次修改原因：整商品阶段标签和缩略图卡片复用浅深主题，提高素材清单与审核的可辨识性。 */
QTabBar#processingSteps::tab { background: $surface; border: 1px solid $border; border-radius: 6px; padding: 7px 16px; margin-right: 8px; }
QTabBar#processingSteps::tab:selected { color: $accent; background: $selected; border-color: $accent; }
QFrame#aiImageCard, QFrame#aiTextCard { background: $surface; border: 1px solid $border; border-radius: 9px; }
QFrame#aiImageCard:hover { border-color: $accent; }
QTextBrowser { background: $surface; border: 1px solid $border; border-radius: 7px; padding: 8px; }


QScrollArea { background: transparent; border: none; }
/* 2026-10-13：本次修改原因：设置滚动底板透明，与外层圆角卡片保持同一背景，避免突兀的灰色内层矩形。 */
QWidget#settingsBody { background: transparent; }
QWidget#editorForm, QWidget#tableViewport { background: $surface; }
/* 2026-10-13：本次修改原因：按需展开的 AI 工作区使用单层卡片边界，与编辑表单清楚分区。 */
QWidget#aiWorkspace { background: $surface; border: 1px solid $border; border-radius: 10px; }
QScrollBar:vertical { background: $alternate; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: $alternate; height: 10px; margin: 2px; }
/* QScrollBar::handle { background: $border; border-radius: 4px; min-height: 24px; min-width: 24px; } */
/* QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; } */
/* 2026-10-13：本次修改原因：滚动柄最小尺寸按方向设置，避免 10px 轨道被 24px 横向/纵向尺寸挤压变形。 */
QScrollBar::handle:vertical { background: $border; border-radius: 3px; min-height: 28px; }
QScrollBar::handle:horizontal { background: $border; border-radius: 3px; min-width: 28px; }
QScrollBar::handle:hover, QScrollBar::handle:pressed { background: $muted; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; border: none; background: transparent; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; border: none; background: transparent; }
QScrollBar::up-arrow, QScrollBar::down-arrow, QScrollBar::left-arrow, QScrollBar::right-arrow { width: 0px; height: 0px; background: transparent; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
/* 2026-10-13：本次修改原因：表格/文本框的横纵滚动交汇处使用主题底色，消除系统灰色凸起方块。 */
QAbstractScrollArea::corner { background: $surface; border: none; }
QStatusBar { background: $surface; color: $muted; border-top: 1px solid $border; }
QStatusBar::item { border: none; }
QProgressBar { border: 1px solid $border; background: $alternate; border-radius: 6px; text-align: center; color: $text; }
QProgressBar::chunk { background: $accent; border-radius: 5px; }
QToolButton { border: 1px solid $border; background: $surface; color: $text; padding: 6px; border-radius: 6px; }
QToolButton:hover { background: $hover; }
QToolButton:disabled { color: $disabled; }
/* QSplitter::handle { background: $border; } */
/* 2026-10-13：本次修改原因：区域之间常态仅显示留白，鼠标经过再高亮拖拽，减少横竖装饰线。 */
QSplitter::handle { background: transparent; }
QSplitter::handle:hover, QSplitter::handle:pressed { background: $accent; }
/* 2026-10-15：本次修改原因：原料弹窗的图片与资料分隔条始终透明，拖动调宽时不再显示深绿色长条。 */
QSplitter#materialDetailsSplitter::handle, QSplitter#materialDetailsSplitter::handle:hover, QSplitter#materialDetailsSplitter::handle:pressed { background: transparent; }
QMenu { background: $surface; color: $text; border: 1px solid $border; padding: 5px; }
QMenu::item { padding: 7px 14px; }
QMenu::item:selected { background: $selected; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 7px; }
""")

# 状态只负责显示；不映射或修改业务状态值。
def status_colors(text: str, category: str = "") -> tuple[str, str]:
    if any(word in text for word in ("失败", "解析失败")):
        return "#FEE2E2", "#991B1B"
    if any(word in text for word in ("未知", "待核对", "未发送", "待完善", "待审核", "待补充")):
        return "#FEF3C7", "#92400E"
    if category == "modified" and text == "已修改":
        return "#DBEAFE", "#1E3A8A"
    if text == "已审核":
        return "#DCFCE7", "#166534"
    if text in ("已传", "发送成功", "成功"):
        return "#CCFBF1", "#115E59"
    if text in ("需重传", "回传中", "发送中"):
        return "#DBEAFE", "#1E3A8A"
    return "#F1F5F9", "#475569"


def theme_tokens():
    app = QApplication.instance()
    name = app.property("beaddiffTheme") if app else "light"
    return TOKENS.get(name, TOKENS["light"])


# 2026-10-13：本次修改原因：用户要求撤下数字增减按钮，原箭头代理绘制注释保留。
# class ClearSpinStyle(QProxyStyle):
#     def drawPrimitive(self, element, option, painter, widget=None):
#         up = QStyle.PrimitiveElement.PE_IndicatorSpinUp
#         down = QStyle.PrimitiveElement.PE_IndicatorSpinDown
#         if element not in (up, down):
#             return super().drawPrimitive(element, option, painter, widget)
#         tokens = theme_tokens()
#         enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
#         rect = option.rect
#         cx, cy = rect.center().x() + 0.5, rect.center().y() + 0.5
#         half_width = max(1.0, min(4.5, (rect.width() - 2) / 2))
#         half_height = max(1.0, min(2.5, (rect.height() - 1) / 2))
#         direction = 1 if element == up else -1
#         triangle = QPolygonF([
#             QPointF(cx - half_width, cy + direction * half_height),
#             QPointF(cx + half_width, cy + direction * half_height),
#             QPointF(cx, cy - direction * half_height),
#         ])
#         painter.save()
#         painter.setRenderHint(QPainter.RenderHint.Antialiasing)
#         painter.setPen(Qt.PenStyle.NoPen)
#         painter.setBrush(QColor(tokens["text" if enabled else "disabled"]))
#         painter.drawPolygon(triangle)
#         painter.restore()


# 2026-10-13：本次修改原因：下拉控件使用清晰的矢量展开标识，不依赖系统小箭头或新增图片资源。
class ComboChevron(QWidget):
    def __init__(self, combo):
        super().__init__(combo)
        self.setObjectName("comboChevron")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event):
        tokens = theme_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(tokens["muted" if self.isEnabled() else "disabled"]),
                            1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        center = self.rect().center()
        painter.drawPolyline(QPolygonF([
            QPointF(center.x() - 4, center.y() - 2),
            QPointF(center.x(), center.y() + 2),
            QPointF(center.x() + 4, center.y() - 2),
        ]))


# 2026-10-13：本次修改原因：停用自绘选项，改用 Qt 标准委托配合紧凑 QSS，避免双重行距和丢失背景。
# class ComboPopupDelegate(QStyledItemDelegate):
#     def sizeHint(self, option, index):
#         size = super().sizeHint(option, index)
#         size.setHeight(max(38, option.fontMetrics.height() + 18))
#         return size
#
#     def paint(self, painter, option, index):
#         tokens = theme_tokens()
#         adjusted = QStyleOptionViewItem(option)
#         self.initStyleOption(adjusted, index)
#         active = bool(option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver))
#         painter.save()
#         if active and index.flags() & Qt.ItemFlag.ItemIsEnabled:
#             painter.setRenderHint(QPainter.RenderHint.Antialiasing)
#             painter.setPen(Qt.PenStyle.NoPen)
#             painter.setBrush(QColor(tokens["selected" if option.state & QStyle.StateFlag.State_Selected else "hover"]))
#             painter.drawRoundedRect(option.rect.adjusted(2, 1, -2, -1), 7, 7)
#         adjusted.rect = option.rect.adjusted(10, 0, -10, 0)
#         adjusted.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_HasFocus)
#         super().paint(painter, adjusted, index)
#         painter.restore()


# 2026-10-13：本次修改原因：全应用的下拉框使用同一列表样式；数字框只撤下按钮，原范围、值类型及校验不变。
class InterfaceStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, returnData)

    def polish(self, target):
        result = super().polish(target)
        if isinstance(target, QAbstractSpinBox):
            # target.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            # 2026-10-13：本次修改原因：Qt 在带 padding 的 QSS 下使用 NoButtons 会把数字编辑区压成 1 像素；保留布局模式，按钮宽高仍为零。
            target.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows
                                    if isinstance(target, (QSpinBox, QDoubleSpinBox))
                                    else QAbstractSpinBox.ButtonSymbols.NoButtons)
        elif isinstance(target, QComboBox):
            # if not target.property("beaddiffComboStyled"):
            #     target.setProperty("beaddiffComboStyled", True)
            # 2026-10-13：本次修改原因：所有下拉框采用修正后的同一呈现，包括可编辑框及后创建的对话框。
            if not target.property("beaddiffComboStyledV2"):
                target.setProperty("beaddiffComboStyledV2", True)
                view = QListView(target)
                view.setObjectName("comboPopupList")
                view.setFrameShape(QFrame.Shape.NoFrame)
                view.setUniformItemSizes(True)
                # view.setSpacing(2)
                # 2026-10-13：本次修改原因：取消额外的行间距，选项仅由统一 QSS 的紧凑留白决定高度。
                view.setSpacing(0)
                view.setMouseTracking(True)
                view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                # view.setItemDelegate(ComboPopupDelegate(view))
                target.setView(view)
                # 2026-10-13：本次修改原因：在绑定列表后设置委托，防止 Qt 切换视图时恢复默认菜单绘制。
                # view.setItemDelegate(ComboPopupDelegate(view))
                view.setItemDelegate(QStyledItemDelegate(view))
                target.setMaxVisibleItems(12)
                popup = view.window()
                popup.setObjectName("comboPopupFrame")
                # popup.setWindowFlags(popup.windowFlags() | Qt.WindowType.FramelessWindowHint |
                #                      Qt.WindowType.NoDropShadowWindowHint)
                # popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                # popup.setContentsMargins(5, 5, 5, 5)
                # 2026-10-13：本次修改原因：保留 Qt 原生 Popup 定位、关闭与焦点机制，背景强制不透明，修复下方内容透出。
                popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
                popup.setAutoFillBackground(True)
                popup.setContentsMargins(0, 0, 0, 0)
                view.viewport().setAutoFillBackground(True)
                if isinstance(popup, QFrame):
                    popup.setFrameShape(QFrame.Shape.NoFrame)
                # target._beaddiff_chevron = ComboChevron(target)
                if not getattr(target, "_beaddiff_chevron", None):
                    target._beaddiff_chevron = ComboChevron(target)
            target.installEventFilter(self)
            # 2026-10-13：本次修改原因：首次展开与切换主题后统一高亮当前选项，保留 Qt 的弹出窗口和选择机制。
            popup = target.view().window()
            # popup._beaddiff_combo = target
            # 2026-10-13：本次修改原因：使用 Qt 动态属性保存所属下拉框，避免临时 Python 窗口包装对象释放后丢失引用。
            popup.setProperty("beaddiffComboOwner", target)
            popup.installEventFilter(self)
            self.position_chevron(target)
        return result

    @staticmethod
    def position_chevron(combo):
        chevron = getattr(combo, "_beaddiff_chevron", None)
        if chevron:
            # chevron.setGeometry(max(0, combo.width() - 30), 1, 24, max(0, combo.height() - 2))
            # 2026-10-15：本次修改原因：原料选择列的矢量箭头与紧凑展开区对齐，避免箭头占据文字空间。
            if combo.property("materialFactChoice"):
                chevron.setGeometry(max(0, combo.width() - 23), 1, 22, max(0, combo.height() - 2))
            else:
                chevron.setGeometry(max(0, combo.width() - 30), 1, 24, max(0, combo.height() - 2))
            chevron.show()
            chevron.raise_()
            chevron.update()

    def eventFilter(self, target, event):
        # 2026-10-13：本次修改原因：Qt 弹出窗口显示后补齐当前行高亮，避免首次打开时无法辨认正在使用的选项。
        if event.type() == QEvent.Type.Show and target.objectName() == "comboPopupFrame":
            # combo = getattr(target, "_beaddiff_combo", None)
            # 2026-10-13：本次修改原因：从弹出窗口的 Qt 属性读取所属控件，保证首次展开与主题切换均能高亮。
            combo = target.property("beaddiffComboOwner")
            if combo is not None:
                index = combo.model().index(combo.currentIndex(), combo.modelColumn(), combo.rootModelIndex())
                if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEnabled:
                    combo.view().selectionModel().setCurrentIndex(
                        index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        if isinstance(target, QComboBox) and event.type() in (
                QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.EnabledChange,
                QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self.position_chevron(target)
        return super().eventFilter(target, event)


def apply_theme(application: QApplication, name: str | None = None) -> None:
    settings = QSettings("BeadDiff", "BeadDiff")
    name = name or settings.value("ui/theme", "light")
    if name not in TOKENS:
        name = "light"
    tokens = TOKENS[name]
    application.setProperty("beaddiffTheme", name)
    # application.setStyle("Fusion")
    # 2026-10-13：本次修改原因：代理样式只增强数字增减箭头，其他控件继续使用原 Fusion 风格。
    # application.setStyle(ClearSpinStyle(QStyleFactory.create("Fusion")))
    # 2026-10-13：本次修改原因：统一现代下拉框及手动数字输入，替代已撤下的增减箭头绘制。
    # application.setStyle(InterfaceStyle(QStyleFactory.create("Fusion")))
    # 2026-10-14：本次修改原因：浅深主题仅更新配色和样式表，复用应用代理样式，避免已有组合框在反复替换样式时失效。
    if not getattr(application, "_beaddiff_interface_style", None):
        style = InterfaceStyle(QStyleFactory.create("Fusion"))
        application.setStyle(style)
        application._beaddiff_interface_style = style
    application.setFont(QFont("Microsoft YaHei UI", 10))
    palette = QPalette()
    roles = {"Window": "window", "WindowText": "text", "Base": "surface",
             "AlternateBase": "alternate", "Text": "text", "Button": "surface",
             "ButtonText": "text", "Highlight": "selected", "HighlightedText": "text",
             "ToolTipBase": "surface", "ToolTipText": "text", "PlaceholderText": "muted"}
    for role, token in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(tokens[token]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(tokens["disabled"]))
    application.setPalette(palette)
    application.setStyleSheet(QSS.substitute(tokens))
    settings.setValue("ui/theme", name)
