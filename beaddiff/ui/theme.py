# 2026-10-10：本次修改原因：统一现代电商工作台的配色、间距、表格和表单视觉。
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


STYLESHEET = """
QWidget { font-family: 'Microsoft YaHei UI', 'Microsoft YaHei', 'Segoe UI'; font-size: 13px; color: #243a41; }
QMainWindow, QDialog { background: #f4f7f9; }
QWidget#workspace { background: #f4f7f9; }
QFrame#sidebar { background: #102e31; border: none; }
QLabel#brand { color: white; font-size: 23px; font-weight: 700; }
QLabel#brandBadge { background: #33c7b0; color: #102e31; border-radius: 11px; font-size: 17px; font-weight: 800; }
QLabel#navCaption { color: #7ea2a4; font-size: 11px; }
QPushButton#navButton { background: transparent; color: #bad0d0; text-align: left; padding: 12px 16px; border: none; border-radius: 8px; font-size: 14px; }
QPushButton#navButton:hover { background: #1b4143; color: white; }
QPushButton#navButton:checked { background: #225452; color: #86efdb; font-weight: 600; }
QLabel#pageTitle { font-size: 26px; font-weight: 700; color: #163438; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; color: #163438; }
QLabel#muted { color: #819198; font-size: 12px; }
QLabel#hint { color: #668085; font-size: 12px; }
QLabel#count { font-size: 30px; font-weight: 700; color: #163438; }
QFrame#card { background: white; border: 1px solid #e3ebee; border-radius: 12px; }
QFrame#notice { background: #ecf8f5; border: 1px solid #d2ece5; border-radius: 8px; }
QLabel#noticeText { color: #247663; font-size: 12px; }
QLabel#warning { background: #fff7e9; color: #946325; border: 1px solid #f1e2c5; border-radius: 7px; padding: 10px; }
QLabel#empty { color: #84969c; font-size: 14px; padding: 32px; }
QLabel#imagePreview { background: #f3f7f8; border: 1px solid #e5ecef; border-radius: 9px; color: #90a0a6; }
QLabel#statusBadge { background: #eaf6f1; color: #248468; border-radius: 10px; padding: 5px 12px; font-size: 12px; }
QPushButton { background: white; border: 1px solid #dce5e8; border-radius: 7px; padding: 8px 14px; min-height: 18px; }
QPushButton:hover { background: #f4f8f9; border-color: #a9c5c6; }
QPushButton:pressed { background: #e9f1f2; }
QPushButton:disabled { color: #aab7bc; background: #f4f6f7; border-color: #e5ebee; }
QPushButton#primary { background: #138b78; border-color: #138b78; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #087b69; border-color: #087b69; }
QPushButton#primary:disabled { background: #a4cdc4; border-color: #a4cdc4; color: #f5faf9; }
QPushButton#quiet { background: transparent; color: #148b78; border: none; padding: 6px 8px; }
QPushButton#filterTab { background: transparent; border: none; color: #758990; padding: 9px 13px; border-radius: 6px; }
QPushButton#filterTab:checked { background: #e8f5f1; color: #138b78; font-weight: 600; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox { background: white; border: 1px solid #dce5e8; border-radius: 7px; padding: 8px 10px; selection-background-color: #bde7de; selection-color: #163438; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #36a893; }
QLineEdit:read-only { background: #f3f7f8; color: #61777f; }
QComboBox { min-width: 95px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #e7f5f0; selection-color: #1c7763; outline: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #c3d2d7; border-radius: 4px; background: white; }
QCheckBox::indicator:checked { background: #15927e; border-color: #15927e; image: none; }
QTableWidget { background: white; border: none; gridline-color: #edf2f4; selection-background-color: #eaf5f2; selection-color: #203b3b; alternate-background-color: #fafcfd; outline: none; }
QTableWidget::item { padding: 8px; border-bottom: 1px solid #edf2f4; }
QTableWidget::item:selected { background: #eaf5f2; color: #203b3b; }
QHeaderView::section { background: #f7f9fb; color: #71848c; border: none; border-bottom: 1px solid #e5ecef; padding: 12px 9px; font-weight: 500; }
QTableCornerButton::section { background: #f7f9fb; border: none; }
QTabWidget::pane { background: white; border: 1px solid #e2eaed; border-radius: 8px; top: -1px; }
QTabBar::tab { background: transparent; padding: 12px 22px; color: #758990; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #138b78; border-bottom-color: #138b78; font-weight: 600; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #cbd8dd; border-radius: 3px; min-height: 32px; }
QScrollBar:horizontal { background: transparent; height: 9px; }
QScrollBar::handle:horizontal { background: #cbd8dd; border-radius: 3px; min-width: 32px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QStatusBar { background: white; color: #819198; border-top: 1px solid #e5ecef; }
QSplitter::handle { background: transparent; width: 12px; }
QToolTip { background: #163e40; color: white; border: none; padding: 7px; }
"""


def apply_theme(application: QApplication) -> None:
    application.setStyle("Fusion")
    application.setFont(QFont("Microsoft YaHei UI", 10))
    application.setStyleSheet(STYLESHEET)
