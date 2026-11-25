"""平台接口的可调用性冒烟。

这两个函数依赖 Windows 桌面与 DPI 接口，无法断言具体取值；
只保证在当前平台可调用且不抛异常，作为导入与符号级回归。
"""

from __future__ import annotations

from wallpaper.desktop import find_wallpaper_layer
from wallpaper.screen import enable_dpi_awareness


def test_enable_dpi_awareness_is_idempotent():
    enable_dpi_awareness()
    enable_dpi_awareness()


def test_find_wallpaper_layer_returns_nonnegative_int():
    handle = find_wallpaper_layer()
    assert isinstance(handle, int)
    assert handle >= 0
