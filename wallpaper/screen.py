"""进程 DPI 感知设置。"""

from __future__ import annotations

import contextlib
import ctypes


def enable_dpi_awareness() -> None:
    """让 tkinter 按真实像素布局；两种接口都不可用时保持系统缩放，不阻塞启动。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()
