"""托盘图标与菜单。"""

from __future__ import annotations

import contextlib
import threading

from PIL import Image, ImageDraw

try:
    import pystray
except ImportError:  # pystray 缺失时 start 返回 False，由装配层提示
    pystray = None


def build_icon(size: int) -> Image.Image:
    """一个向右的播放三角，透明背景，深浅任务栏都能看清。"""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(1, size // 6)
    points = [
        (margin, margin),
        (margin, size - margin),
        (size - margin, size // 2),
    ]
    # 先画中灰轮廓再加上浅色内芯，深底浅底都能分辨
    draw.polygon(points, fill=(132, 146, 166, 255))
    inset = max(1, size // 14)
    inner = [
        (margin + inset * 2, margin + inset),
        (margin + inset * 2, size - margin - inset),
        (size - margin - inset, size // 2),
    ]
    draw.polygon(inner, fill=(244, 248, 255, 255))
    return image


class TrayIcon:
    def __init__(self, post) -> None:
        self._post = post
        self._icon = None
        self._thread = None
        self._running = False
        self._video = True
        self._muted = True

    def start(self) -> bool:
        if pystray is None:
            return False
        try:
            menu = pystray.Menu(
                pystray.MenuItem("显示主窗口", lambda: self._post("show"), default=True),
                pystray.MenuItem("立即换一张", lambda: self._post("next")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    lambda _: "停止轮播" if self._running else "开始轮播",
                    lambda: self._post("toggle"),
                ),
                pystray.MenuItem("包含视频", lambda: self._post("mode"),
                                 checked=lambda _: self._video),
                pystray.MenuItem(
                    lambda _: "关闭声音" if not self._muted else "打开声音",
                    lambda: self._post("mute"),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", lambda: self._post("quit")),
            )
            self._icon = pystray.Icon("wallpaper", build_icon(64), "壁纸轮播", menu)
            self._thread = threading.Thread(target=self._icon.run, daemon=True, name="tray")
            self._thread.start()
        except Exception:
            # 托盘是可选能力，不能拖垮主程序；交由装配层提示并保留主窗口
            self._icon = None
            return False
        return True

    def stop(self) -> None:
        if self._icon is not None:
            # 停止失败不影响退出流程，句柄照样丢弃
            with contextlib.suppress(Exception):
                self._icon.stop()
            self._icon = None

    def notify(self, message: str) -> None:
        if self._icon is not None:
            # 通知失败不影响业务，托盘菜单仍能显示状态
            with contextlib.suppress(Exception):
                self._icon.notify(message, "壁纸轮播")

    def update(self, running: bool, dynamic: bool, current: str, minutes: int,
               total: int, muted: bool = True) -> None:
        self._running = running
        self._video = dynamic
        self._muted = muted
        if self._icon is None:
            return
        state = "运行中" if running else "已停止"
        sound = "静音" if muted else "有声"
        self._icon.title = (f"{state} · {current} · 间隔 {minutes} 分钟 · 共 {total} 项"
                            f" · {sound}")
        # 菜单刷新失败不影响业务状态，下次状态变化会再试
        with contextlib.suppress(Exception):
            self._icon.update_menu()
