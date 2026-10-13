# 2026-10-13：本次修改原因：界面静态资源统一定位；数据、凭证和数据库仍使用原有数据目录。
from pathlib import Path
import sys


def resource_path(relative: str) -> Path:
    """只用于随程序分发的QSS/图标；当前主题和SVG内嵌，不需要额外打包数据。"""
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    return root / relative
