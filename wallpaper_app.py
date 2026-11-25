"""壁纸轮播：遮盖层显示，不改变壁纸内容；退出时回填原值触发桌面重绘。"""

from __future__ import annotations

import atexit
import ctypes
import importlib.util
import queue
import sys
import tkinter as tk
from ctypes import wintypes
from dataclasses import replace as replace_config
from pathlib import Path
from tkinter import messagebox

REQUIRED_DISTRIBUTIONS = {"PIL": "Pillow", "pystray": "pystray", "webview": "pywebview"}


def _missing_distributions() -> list[str]:
    return [dist for module, dist in REQUIRED_DISTRIBUTIONS.items()
            if importlib.util.find_spec(module) is None]


def _report_fatal(message: str) -> None:
    """用系统消息框报错：此时 tkinter 尚不可用，start.bat 走 pythonw 也没有控制台。"""
    ctypes.windll.user32.MessageBoxW(None, message, "壁纸轮播", 0x00000010)


# 第三方依赖必须在导入前拦下，否则 pythonw 下只会静默退出，用户看到的是双击无反应
_unavailable = _missing_distributions()
if _unavailable:
    _report_fatal("缺少依赖：" + "、".join(_unavailable)
                  + "\n\n请在项目目录运行：\npip install -r requirements.txt")
    raise SystemExit(1)

from wallpaper import config as config_module  # noqa: E402
from wallpaper import media, protocol, screen  # noqa: E402
from wallpaper.backend import WallpaperBackend  # noqa: E402
from wallpaper.scheduler import RotationScheduler  # noqa: E402
from wallpaper.tray import TrayIcon, build_icon  # noqa: E402
from wallpaper.ui import WallpaperUI  # noqa: E402

WATCH_MS = 2000
HIDE_HINT = "已隐藏到托盘，双击图标恢复窗口；托盘「退出」才结束进程。"


class WallpaperApp:
    def __init__(self) -> None:
        self._config_errors: list[str] = []
        self.config = config_module.load(on_error=self._config_errors.append)
        self.count = 0
        self._current_name = "尚未切换"
        self._closing = False
        self._hide_hinted = False
        self._status_snapshot: tuple | None = None
        self._events: queue.Queue[tuple[str, str]] = queue.Queue()
        self._actions: queue.Queue[str] = queue.Queue()

        self.root = tk.Tk()
        self.ui = WallpaperUI(self.root, self.config)
        self.ui.set_icon(build_icon(128))
        self.scheduler = RotationScheduler(self._scan, self._rotate, self._report_error)
        self.backend = WallpaperBackend(self._on_backend_event)
        self.tray = TrayIcon(self._actions.put)
        # 任何退出路径都先摸一下托盘，包括异常退出，避免在任务栏留下僵尸图标
        atexit.register(self.tray.stop)

        self.ui.on_start = self.start
        self.ui.on_stop = self.stop
        self.ui.on_next = self.next_now
        self.ui.on_config_change = self._on_config_change
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        for message in self._config_errors:
            self.ui.log(message)
        self._log_scan()
        # 托盘不可用时必须留着主窗口：否则既无窗口也无图标，用户会以为没启动
        if self.tray.start():
            self.root.withdraw()
        else:
            self.ui.log("托盘不可用，窗口保持显示")
        self._push_status()
        self.root.after(100, self._drain)
        self.root.after(400, self._auto_start)
        self.root.after(WATCH_MS, self._watch)

    # ---- 生命周期 ----

    def run(self) -> None:
        self.root.mainloop()

    def _auto_start(self) -> None:
        if self.scheduler.running:
            return
        if self._refresh_count() == 0:
            self.ui.log("目录里没有可用素材，未自动开始")
            return
        self.start()

    def start(self) -> None:
        self._sync_config()
        if self._refresh_count() == 0:
            self._warn("无法开始", "目录里没有可用素材，请先选择目录。")
            return
        try:
            self.backend.start()
        # 显示进程起不来属于环境问题，记日志即可，不在这里重试
        except Exception as exc:
            self.ui.log(f"显示进程启动失败：{exc}")
            return
        self.scheduler.resume()
        # 调度线程起来后会自己先切一张，这里不能再 next_now，否则启动瞬间连切两张
        self.scheduler.start()
        self.ui.set_running(True)
        self.ui.log(f"开始轮播，间隔 {self.config.interval_minutes} 分钟")
        self._push_status()

    def stop(self) -> None:
        self.scheduler.stop()
        self.ui.set_running(False)
        self.ui.log("已停止轮播")
        self._push_status()

    def toggle(self) -> None:
        if self.scheduler.running:
            self.stop()
        else:
            self.start()

    def next_now(self) -> None:
        if self._refresh_count() == 0:
            self._warn("无法切换", "目录里没有可用素材。")
            return
        if not self.scheduler.running:
            self.start()
            return
        self.scheduler.next_now()

    def toggle_video(self) -> None:
        self.config = replace_config(self.config, allow_video=not self.config.allow_video)
        self.ui.video_var.set(self.config.allow_video)
        config_module.save(self.config)
        self._refresh_count()
        self._push_status()
        if self.scheduler.running:
            self.scheduler.next_now()

    def toggle_mute(self) -> None:
        self.config = replace_config(self.config, muted=not self.config.muted)
        self.ui.mute_var.set(self.config.muted)
        config_module.save(self.config)
        self._apply_mute()
        self._push_status()

    def quit(self) -> None:
        self._closing = True
        self.scheduler.stop()
        # 只关遮盖窗口：壁纸内容从未被改过，关掉后由后端回填原值触发重绘
        self.backend.stop()
        self.tray.stop()
        try:
            for job in self.root.tk.call("after", "info"):
                self.root.after_cancel(job)
        # 取消定时回调失败不影响销毁，root 马上就不存在了
        except Exception:
            pass
        self.root.destroy()

    def show_window(self) -> None:
        self.ui.show()

    def hide_window(self) -> None:
        self.ui.hide()
        if not self._hide_hinted:
            self._hide_hinted = True
            self.tray.notify(HIDE_HINT)

    # ---- 内部 ----

    def _scan(self) -> list[Path]:
        directory = self.config.image_dir
        if self.config.allow_video:
            return media.list_media(directory)
        return media.list_images(directory)

    def _rotate(self, item: Path) -> None:
        kind = media.kind_of(item)
        # 视频不看间隔：先停掉计时，等它自己播完（ended）再切
        if kind == "video":
            self.scheduler.pause()
        else:
            self.scheduler.resume()
        self.backend.show(kind, item, self.config.muted)
        self._events.put(("applied", item.name))

    def _report_error(self, message: str) -> None:
        self._events.put(("error", message))

    def _on_backend_event(self, name: str, payload: str) -> None:
        self._events.put((name, payload))
        if name == "ended":
            # 视频播完：解除计时暂停，调度器会立刻切下一张
            self.scheduler.resume()
        elif name == "load_error":
            # 视频没起来就不会有 ended，必须自己接上，否则会停在这里
            self.scheduler.resume()

    def _drain(self) -> None:
        while not self._closing:
            try:
                action = self._actions.get_nowait()
            except queue.Empty:
                break
            self._handle_action(action)
        if self._closing:
            return
        while True:
            try:
                kind, message = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "applied":
                self._current_name = message
                self.ui.log(f"已切换：{message}")
            elif kind == "loaded":
                self.ui.log(f"已上屏：{message}")
            elif kind == "ended":
                self.ui.log(f"视频播完，切下一张：{message}")
            elif kind == "load_error":
                self.ui.log(f"素材加载失败：{message}")
            elif kind in ("page_not_ready", "script_error", "server_error"):
                self.ui.log(f"页面异常：{message or kind}")
            elif kind == protocol.EVT_STDERR:
                self.ui.log(f"显示进程输出：{message}")
            else:
                self.ui.log(f"切换失败：{message}")
        self._push_status()
        self.root.after(100, self._drain)

    def _handle_action(self, action: str) -> None:
        if action == "show":
            self.show_window()
        elif action == "next":
            self.next_now()
        elif action == "toggle":
            self.toggle()
        elif action == "mode":
            self.toggle_video()
        elif action == "mute":
            self.toggle_mute()
        elif action == "quit":
            self.quit()

    def _watch(self) -> None:
        if self._closing:
            return
        if self.scheduler.running and not self.backend.alive:
            self.ui.log("显示进程已退出，正在重启")
            try:
                self.backend.stop()
                self.backend.start()
                self.scheduler.next_now()
            # 重启失败只记录，下一轮 watch 会再试
            except Exception as exc:
                self.ui.log(f"重启失败：{exc}")
        self.root.after(WATCH_MS, self._watch)

    def _apply_mute(self) -> None:
        """把当前静音状态交给显示进程，正在播的视频立即生效。"""
        if not self.backend.alive:
            return
        try:
            self.backend.set_muted(self.config.muted)
        except Exception as exc:
            self.ui.log(f"静音设置未生效：{exc}")
            return
        self.ui.log("视频静音" if self.config.muted else "视频有声")

    def _on_config_change(self) -> None:
        self._sync_config()
        config_module.save(self.config)

    def _sync_config(self) -> None:
        previous_muted = self.config.muted
        updated = self.ui.read_config()
        changed = updated != self.config
        self.config = updated
        self.scheduler.configure(updated.interval_seconds, updated.order)
        if changed:
            self._refresh_count()
            self._push_status()
        if updated.muted != previous_muted:
            self._apply_mute()

    def _refresh_count(self) -> int:
        self.count = len(self._scan())
        self.ui.set_count(self.count)
        return self.count

    def _log_scan(self) -> None:
        total = self._refresh_count()
        if total:
            self.ui.log(f"目录内 {total} 项素材")
        else:
            self.ui.log(f"目录内没有可用素材：{self.config.image_dir}")

    def _push_status(self) -> None:
        running = self.scheduler.running
        snapshot = (running, self.count, self._current_name, self.config.allow_video,
                    self.config.interval_minutes, self.config.muted)
        if snapshot == self._status_snapshot:
            return
        self._status_snapshot = snapshot
        state = "运行中" if running else "已停止"
        self.ui.set_status(f"{state} · {self._current_name} · 共 {self.count} 项")
        self.tray.update(running, self.config.allow_video, self._current_name,
                         self.config.interval_minutes, self.count, self.config.muted)

    def _warn(self, title: str, text: str) -> None:
        self.show_window()
        self.ui.log(text)
        messagebox.showwarning(title, text)


_SINGLE_INSTANCE_MUTEX = "Local\\FanWallpaper-SingleInstance"
_ERROR_ALREADY_EXISTS = 183


def _acquire_single_instance(name: str = _SINGLE_INSTANCE_MUTEX) -> bool:
    """尝试取得单实例所有权。

    两个实例会互相 cleanup_stale 对方的显示窗口，所以只允许一个。
    拿不到系统对象时返回 True：宁可允许多开，也不要拦下正常启动。
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    return True


def main() -> int:
    screen.enable_dpi_awareness()
    if not _acquire_single_instance():
        _report_fatal("壁纸轮播已在运行。\n\n要重启请先在托盘菜单选择「退出」。")
        return 1
    try:
        app = WallpaperApp()
    except Exception as exc:
        _report_fatal(f"启动失败：{type(exc).__name__}: {exc}")
        return 1
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
