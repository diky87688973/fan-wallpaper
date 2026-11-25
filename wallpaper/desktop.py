"""桌面壁纸层定位，主控与显示进程共用同一份实现。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

SPAWN_WORKER_W = 0x052C

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.FindWindowW.restype = wintypes.HWND
_user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR,
                                  wintypes.LPCWSTR]
_user32.FindWindowExW.restype = wintypes.HWND
_user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                        wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                        ctypes.POINTER(ctypes.c_size_t)]
_ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_wallpaper_layer() -> int:
    """返回承载壁纸图标的 WorkerW 句柄，找不到返回 0。

    先向 Progman 发 SPAWN_WORKER_W，让 Explorer 生成独立 WorkerW；
    再找挂着 SHELLDLL_DefView 的顶层窗口，其兄弟 WorkerW 才是壁纸层。
    """
    progman = _user32.FindWindowW("Progman", None)
    if progman:
        result = ctypes.c_size_t(0)
        _user32.SendMessageTimeoutW(progman, SPAWN_WORKER_W, 0, 0, 0, 1000,
                                    ctypes.byref(result))
    found = []

    def cb(top, _):
        if not _user32.FindWindowExW(top, None, "SHELLDLL_DefView", None):
            return True
        sibling = _user32.FindWindowExW(None, top, "WorkerW", None)
        if sibling:
            found.append(int(sibling))
            return False
        return True

    _user32.EnumWindows(_ENUMPROC(cb), 0)
    return found[0] if found else 0
