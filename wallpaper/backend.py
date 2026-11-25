"""遮盖层后端：起停显示进程，转发命令与事件。"""

from __future__ import annotations

import contextlib
import ctypes
import json
import subprocess
import sys
import threading
import winreg
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

from . import protocol
from .desktop import find_wallpaper_layer

READY_TIMEOUT_SECONDS = 25.0
QUIT_TIMEOUT_SECONDS = 1.5
CREATE_NO_WINDOW = 0x08000000

SPI_SETDESK_WALLPAPER = 0x0014
SPIF_SENDCHANGE = 0x02
_WM_CLOSE = 0x0010

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                 wintypes.LPARAM]
_ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _child_pids(parent: int) -> list[tuple[int, int]]:
    rows = []

    def cb(hwnd, _):
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rows.append((int(hwnd), pid.value))
        return True

    _user32.EnumChildWindows(parent, _ENUMPROC(cb), 0)
    return rows


def _own_pids() -> set[int]:
    """命令行里带 wallview 的本程序 python 进程。"""
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe' or name='pythonw.exe'",
             "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, encoding="gbk", errors="ignore", timeout=8,
            check=False,
            # wmic 是控制台程序，不加这个每次启动都会闪一下黑窗
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    pids = set()
    for line in out.stdout.splitlines():
        if "wallview" not in line:
            continue
        parts = line.split()
        if parts and parts[-1].isdigit():
            pids.add(int(parts[-1]))
    return pids


def cleanup_stale() -> int:
    """收掉上次没退干净的遮盖窗口，只认本程序脚本。"""
    layer = find_wallpaper_layer()
    if not layer:
        return 0
    mine = _own_pids()
    if not mine:
        return 0
    targets = [hwnd for hwnd, pid in _child_pids(layer) if pid in mine]
    for hwnd in targets:
        _user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
    if targets:
        repaint_desktop()
    return len(targets)


def repaint_desktop() -> None:
    """让系统把壁纸重新画一遍。

    遮盖窗口销毁后 Explorer 不会自己重绘，画面会停在最后一帧或纯黑。
    实测 InvalidateRect、WM_SETTINGCHANGE、SHChangeNotify 都无法让它重画，
    只有把**当前已经是的壁纸路径**原样交回系统才有效：
    壁纸内容与注册表值均不变，仅触发重绘。

    这是全工程唯一读 WallPaper 注册值并调用系统壁纸接口的位置：
    只读不改，交回系统的就是读到的原值，不存在覆盖用户壁纸的路径。
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            current = str(winreg.QueryValueEx(key, "WallPaper")[0])
    except OSError:
        return
    if not current:
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                            ctypes.c_wchar_p, ctypes.c_uint]
    user32.SystemParametersInfoW.restype = ctypes.c_int
    user32.SystemParametersInfoW(SPI_SETDESK_WALLPAPER, 0, current, SPIF_SENDCHANGE)


def _child_executable() -> str:
    """启动显示进程用的解释器，沿用主控自己的解释器。

    主控经 start.bat 由 pythonw 启动时，这里同样是 pythonw；
    实测事件经管道回报正常，CREATE_NO_WINDOW 保证不会弹控制台。
    """
    return sys.executable


class WallpaperBackend:
    def __init__(self, on_event: Callable[[str, str], None]) -> None:
        self._on_event = on_event
        self._process: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self._process is not None:
            return
        cleanup_stale()
        root = Path(__file__).resolve().parent.parent
        entry = root / "wallpaper" / "wallview.py"
        if not entry.is_file():
            raise RuntimeError(f"找不到显示进程：{entry}")
        # 以模块方式启动：wallview 内部用包内相对导入，cwd 决定 -m 的搜索根
        self._process = subprocess.Popen(
            [_child_executable(), "-m", "wallpaper.wallview"],
            cwd=str(root),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )
        self._ready.clear()
        self._reader = threading.Thread(target=self._read_loop, name="wallview", daemon=True)
        self._reader.start()
        if not self._ready.wait(READY_TIMEOUT_SECONDS):
            raise RuntimeError("显示进程未就绪")

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        # 先关遮盖窗口：窗口还在时重绘是被它盖着的，用户看不到，关掉后桌面
        # 会停在最后一帧，所以必须等窗口真的没了再重绘。
        with contextlib.suppress(OSError, RuntimeError):
            self._send({protocol.CMD: protocol.CMD_QUIT})
        try:
            process.wait(timeout=QUIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            # 窗口没自己退：向壁纸层里属于它的窗口发关闭请求，不结束进程
            for hwnd, pid in _child_pids(find_wallpaper_layer()):
                if pid == process.pid:
                    _user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=QUIT_TIMEOUT_SECONDS)
        self._process = None
        # 窗口没了，这时重绘才会真的画到桌面上
        repaint_desktop()

    def show(self, kind: str, path: Path, muted: bool = True) -> None:
        self._send({
            protocol.CMD: protocol.CMD_SHOW,
            protocol.FIELD_KIND: kind,
            protocol.FIELD_PATH: str(path),
            protocol.FIELD_MUTED: bool(muted),
        })

    def set_muted(self, muted: bool) -> None:
        self._send({protocol.CMD: protocol.CMD_MUTE, protocol.FIELD_VALUE: bool(muted)})

    def _send(self, payload: dict) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise RuntimeError("显示进程未启动")
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            process.stdin.write(line)
            process.stdin.flush()

    def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for raw in process.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except ValueError:
                # 非协议行（第三方库警告、崩溃堆栈）同样转出去，否则失败原因不可见
                self._on_event(protocol.EVT_STDERR, raw)
                continue
            if not isinstance(payload, dict):
                self._on_event(protocol.EVT_STDERR, raw)
                continue
            name = payload.get(protocol.EVT, "")
            if not name:
                continue
            if name == protocol.EVT_READY:
                self._ready.set()
                continue
            if name == protocol.EVT_ATTACHED:
                detail = payload.get(protocol.FIELD_DETAIL)
                if detail:
                    self._on_event("error", f"挂载桌面失败：{detail}")
                continue
            if name in protocol.FORWARD_EVENTS:
                self._on_event(
                    name,
                    payload.get(protocol.FIELD_PATH) or payload.get(protocol.FIELD_DETAIL, ""),
                )
