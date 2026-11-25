"""壁纸显示进程：WebView2 窗口挂到桌面壁纸层，用 img / video 展示素材。

主控通过 stdin 每行一条 JSON 控制：
  {"cmd": "show", "kind": "image|video", "path": "..."}
  {"cmd": "pause"} / {"cmd": "resume"} / {"cmd": "quit"}
"""

from __future__ import annotations

import contextlib
import ctypes
import functools
import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
from ctypes import wintypes
from pathlib import Path

import webview

from . import protocol
from .desktop import find_wallpaper_layer

PAGE = """
<!doctype html>
<html>
<head><meta charset="utf-8">
<style>
  html, body { margin: 0; padding: 0; overflow: hidden; background: #000; }
</style>
</head>
<body>
<script>
  function report(kind, path, detail) {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.on_report(kind, path, detail || '');
    }
  }

  var current = null;

  function build(path, isVideo, muted) {
    var node = document.createElement(isVideo ? 'video' : 'img');
    node.style.cssText =
      'position:fixed;inset:0;width:100vw;height:100vh;object-fit:cover;' +
      'opacity:0;transition:opacity .28s ease;';
    if (isVideo) {
      node.autoplay = true;
      node.muted = muted;
      node.playsInline = true;
      node.onended = function () { report('ended', path); };
    }
    document.body.appendChild(node);
    node.src = path;
    if (isVideo) { node.play().catch(function () {}); }
    return node;
  }

  function whenReady(node, isVideo) {
    return new Promise(function (resolve) {
      var done = false;
      function finish(ok) { if (!done) { done = true; resolve(ok); } }
      node.addEventListener(isVideo ? 'loadeddata' : 'load', function () { finish(true); });
      node.addEventListener('error', function () { finish(false); });
      setTimeout(function () {
        if (isVideo ? node.readyState >= 2 : node.complete) { finish(true); }
      }, 60);
      setTimeout(function () { finish(false); }, 15000);
    });
  }

  function applyMedia(path, isVideo, muted) {
    var incoming = build(path, isVideo, muted);
    return whenReady(incoming, isVideo).then(function (ok) {
      if (!ok) {
        incoming.remove();
        report('load_error', path, isVideo ? 'video' : 'image');
        return false;
      }
      var outgoing = current;
      current = incoming;
      incoming.style.opacity = '1';
      if (outgoing) {
        outgoing.style.opacity = '0';
        setTimeout(function () { outgoing.remove(); }, 320);
      }
      report('loaded', path, isVideo ? 'video' : 'image');
      return true;
    });
  }

  function setMuted(value) {
    if (current && current.tagName === 'VIDEO') { current.muted = value; }
  }
</script>
</body>
</html>
"""

user32 = ctypes.WinDLL("user32", use_last_error=True)
# 64 位下 HWND 是 8 字节，不声明 argtypes 会按 32 位 int 传，句柄被截断
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
user32.SetParent.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_uint32
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint32]
user32.SetWindowLongW.restype = ctypes.c_uint32
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
WS_DECORATION = (0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000
                 | 0x00010000 | 0x00800000 | 0x00400000)
SWP_FRAMECHANGED = 0x0020
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
# SetWindowPos 的 z 序常量本身就是 HWND，负数要按无符号指针值传
HWND_BOTTOM = ctypes.c_void_p(1)
HWND_NOTOPMOST = ctypes.c_void_p(0xFFFFFFFFFFFFFFFE)


class Bridge:
    def __init__(self) -> None:
        self.emit = lambda name, path, detail: None
        self.reveal = lambda: None

    def on_report(self, kind, path, detail):
        # 首张素材上屏后重新定位窗口并确保可见，避免停在 attach 时的旧尺寸
        if kind == protocol.EVT_LOADED:
            self.reveal()
        self.emit(kind, path, detail)
        return True


bridge = Bridge()


def emit(name: str, path: str = "", detail: str = "") -> None:
    payload = {protocol.EVT: name, protocol.FIELD_PATH: path, protocol.FIELD_DETAIL: detail}
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def attach(hwnd: int) -> str:
    host = find_wallpaper_layer()
    if not host:
        return f"找不到 WorkerW（hwnd={hwnd} 0x{hwnd:X}）"

    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    style_error = ctypes.get_last_error()
    new_style = (style & ~WS_POPUP & ~WS_DECORATION) | WS_CHILD
    style_ret = user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)
    style_set_error = ctypes.get_last_error()

    # 窗口创建时是顶层窗口，已在任务栏登记了按钮；改成子窗口不会撤销它，
    # 必须显式标成工具窗口（并去掉 APPWINDOW），任务栏才会忽略。
    exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    new_exstyle = (exstyle | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    exstyle_ret = user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_exstyle)

    parent_ret = user32.SetParent(hwnd, host)
    parent_error = ctypes.get_last_error()
    actual = user32.GetParent(hwnd)
    if actual != host:
        # 这条失败路径只出现过一次且未能复现，所以把当时全部现场记下来
        return (
            "SetParent 失败\n"
            f"  hwnd={hwnd} (0x{hwnd:X}, {hwnd.bit_length()} bit)  "
            f"host={host} (0x{host:X})\n"
            f"  读回父窗口={actual}\n"
            f"  style {style:#010x} -> {new_style:#010x}"
            f"（SetWindowLongW 返回 {style_ret}，错误码 {style_set_error}，"
            f"读取前错误码 {style_error}）\n"
            f"  exstyle {exstyle:#010x} -> {new_exstyle:#010x}"
            f"（SetWindowLongW 返回 {exstyle_ret}）\n"
            f"  SetParent 返回 {parent_ret}，错误码 {parent_error}"
        )
    # 取消置顶：fullscreen 创建时被设成 TOPMOST，留着就会盖住图标和任务栏。
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    # 压到父窗口 z 序最底，保证它只是底座
    rect = wintypes.RECT()
    user32.GetClientRect(host, ctypes.byref(rect))
    user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0,
                        rect.right - rect.left, rect.bottom - rect.top,
                        SWP_FRAMECHANGED | SWP_NOACTIVATE | SWP_SHOWWINDOW)
    return ""


def place_on_screen(hwnd: int) -> None:
    """把窗口重新压回主屏底部，不改变层级归属。"""
    host = find_wallpaper_layer()
    if not host:
        return
    rect = wintypes.RECT()
    user32.GetClientRect(host, ctypes.byref(rect))
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0,
                        rect.right - rect.left, rect.bottom - rect.top,
                        SWP_FRAMECHANGED | SWP_NOACTIVATE | SWP_SHOWWINDOW)


def window_handle(window):
    native = getattr(window, "native", None)
    for attr in ("Handle", "handle"):
        if native is not None and hasattr(native, attr):
            value = getattr(native, attr)
            return value.ToInt64() if hasattr(value, "ToInt64") else int(value)
    return 0


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


class QuietServer(http.server.ThreadingHTTPServer):
    """回环服务：客户端中途断连是常态，不当异常上报；其余错误照常打。"""

    daemon_threads = True

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


_media = {"server": None, "port": 0, "directory": ""}
_media_lock = threading.Lock()


def serve_dir(directory: str) -> int:
    """按素材目录起回环服务；目录变了才重建。"""
    with _media_lock:
        if _media["port"] and _media["directory"] == directory:
            return _media["port"]
        old = _media["server"]
        if old is not None:
            threading.Thread(target=old.shutdown, daemon=True).start()
        handler = functools.partial(QuietHandler, directory=directory)
        try:
            server = QuietServer(("127.0.0.1", 0), handler)
        except OSError as exc:
            emit(protocol.EVT_SERVER_ERROR, "", str(exc))
            return 0
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _media.update(server=server, port=server.server_address[1], directory=directory)
        return _media["port"]


def to_url(path: str) -> str:
    target = Path(path)
    port = serve_dir(str(target.parent))
    if not port:
        return ""
    return "http://127.0.0.1:%d/%s" % (port, urllib.parse.quote(target.name))


def main() -> int:
    # 浏览器默认禁止非静音自动播放，放开后音量开关才真正有效。
    # 后半段关闭 Chromium 的后台与遮挡节流：壁纸窗口永远被其他窗口盖在上面，
    # 默认策略会把被遮挡的窗口当成后台，直接把视频挂起。
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = " ".join((
        "--autoplay-policy=no-user-gesture-required",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--disable-background-media-suspend",
        "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling",
    ))
    # 主控用 UTF-8 写管道，这里必须按 UTF-8 读；
    # 否则中文路径会被按系统默认编码解码，路径直接错位、文件找不到。
    # stderr 同样要设：它会被合并进 stdout 由主控按 UTF-8 解码，
    # 不设就会把系统代码页的中文变成乱码。
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    bridge.emit = emit
    window = webview.create_window(
        "wallpage", html=PAGE, frameless=True, fullscreen=True,
        easy_drag=False, background_color="#000000", js_api=bridge,
    )

    state = {"ready": False, "pending": None, "hwnd": 0}
    lock = threading.Lock()
    shown = {"done": False}

    def reveal() -> None:
        """首张就绪后确保窗口仍在原位、仍可见。"""
        with lock:
            if shown["done"] or not state["hwnd"]:
                return
            shown["done"] = True
            hwnd = state["hwnd"]
        place_on_screen(hwnd)

    bridge.reveal = reveal

    def dispatch(script: str) -> None:
        with lock:
            if not state["ready"]:
                state["pending"] = script
                return
        try:
            window.evaluate_js(script)
        except Exception as exc:
            emit(protocol.EVT_SCRIPT_ERROR, "", str(exc))

    def wait_page_ready() -> None:
        for _ in range(60):
            try:
                if window.evaluate_js("typeof applyMedia === 'function'"):
                    with lock:
                        state["ready"] = True
                        pending = state["pending"]
                        state["pending"] = None
                    emit(protocol.EVT_PAGE_READY)
                    if pending:
                        dispatch(pending)
                    return
            except Exception:
                pass
            time.sleep(0.2)
        emit(protocol.EVT_PAGE_NOT_READY)

    def serve() -> None:
        hwnd = 0
        for _ in range(30):
            time.sleep(0.2)
            hwnd = window_handle(window)
            if hwnd:
                break
        with lock:
            state["hwnd"] = hwnd
        emit(protocol.EVT_HANDLE, "", str(hwnd))
        if hwnd:
            emit(protocol.EVT_ATTACHED, "", attach(hwnd))
        wait_page_ready()
        emit(protocol.EVT_READY)

    def watch() -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                command = json.loads(line)
            except ValueError:
                continue
            name = command.get(protocol.CMD)
            if name == protocol.CMD_QUIT:
                def teardown() -> None:
                    with contextlib.suppress(Exception):
                        window.destroy()
                    time.sleep(0.3)
                    os._exit(0)

                threading.Thread(target=teardown, daemon=True).start()
                return
            if name == protocol.CMD_SHOW:
                if not shown["done"]:
                    # 首张：给一个兜底，万一加载事件没回来也要显示
                    threading.Timer(4.0, reveal).start()
                script = "applyMedia(%s, %s, %s)" % (
                    json.dumps(to_url(command.get(protocol.FIELD_PATH, ""))),
                    "true" if command.get(protocol.FIELD_KIND) == protocol.KIND_VIDEO else "false",
                    "true" if command.get(protocol.FIELD_MUTED, True) else "false",
                )
                dispatch(script)
            elif name == protocol.CMD_MUTE:
                dispatch("setMuted(%s)"
                         % ("true" if command.get(protocol.FIELD_VALUE) else "false"))

    threading.Thread(target=serve, daemon=True).start()
    threading.Thread(target=watch, daemon=True).start()
    webview.start(gui="edgechromium")
    return 0


if __name__ == "__main__":
    sys.exit(main())
