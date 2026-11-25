"""托盘图标构建与控制分支。

pystray 用替身代替，不创建真实托盘图标；验证的是构建结果与本模块的降级行为。
"""

from __future__ import annotations

from wallpaper import tray as tray_module
from wallpaper.tray import TrayIcon, build_icon


class FakeIcon:
    def __init__(self, *args, **kwargs):
        self.title = ""
        self.stopped = False
        self.notified = []
        self.menu_updates = 0

    def run(self):
        return None

    def stop(self):
        self.stopped = True

    def notify(self, message, title):
        self.notified.append((message, title))

    def update_menu(self):
        self.menu_updates += 1


class FakePystray:
    SEPARATOR = "-"
    Icon = FakeIcon

    class Menu:
        SEPARATOR = "-"

        def __init__(self, *items):
            self.items = items

    class MenuItem:
        def __init__(self, *args, **kwargs):
            self.args = args


class BoomPystray:
    SEPARATOR = "-"

    class Menu:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("托盘初始化失败")


def test_build_icon_has_transparent_corners():
    image = build_icon(64)
    assert image.size == (64, 64)
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((32, 32))[3] > 0


def test_build_icon_tolerates_tiny_size():
    image = build_icon(4)
    assert image.size == (4, 4)


def test_start_returns_false_without_pystray(monkeypatch):
    monkeypatch.setattr(tray_module, "pystray", None)
    assert TrayIcon(lambda action: None).start() is False


def test_start_returns_false_when_construction_fails(monkeypatch):
    monkeypatch.setattr(tray_module, "pystray", BoomPystray)
    assert TrayIcon(lambda action: None).start() is False


def test_start_then_stop_with_fake_pystray(monkeypatch):
    monkeypatch.setattr(tray_module, "pystray", FakePystray)
    tray = TrayIcon(lambda action: None)
    assert tray.start() is True
    assert tray._icon is not None
    tray.stop()
    assert tray._icon is None


def test_icon_operations_are_safe_before_start(monkeypatch):
    monkeypatch.setattr(tray_module, "pystray", None)
    tray = TrayIcon(lambda action: None)
    tray.stop()
    tray.notify("提示")
    tray.update(True, True, "当前", 5, 3, muted=False)
    assert tray._icon is None


def test_update_publishes_state_to_icon(monkeypatch):
    monkeypatch.setattr(tray_module, "pystray", FakePystray)
    tray = TrayIcon(lambda action: None)
    tray.start()
    icon = tray._icon
    tray.update(True, False, "1.jpg", 5, 3, muted=False)
    assert "运行中" in icon.title
    assert "1.jpg" in icon.title
    assert "有声" in icon.title
    assert "共 3 项" in icon.title
    assert icon.menu_updates >= 1
    tray.notify("已隐藏")
    assert icon.notified == [("已隐藏", "壁纸轮播")]
    tray.stop()
    assert icon.stopped is True


def test_update_when_stopped_shows_stopped_state(monkeypatch):
    monkeypatch.setattr(tray_module, "pystray", FakePystray)
    tray = TrayIcon(lambda action: None)
    tray.start()
    tray.update(False, True, "尚未切换", 10, 0, muted=True)
    assert "已停止" in tray._icon.title
    assert "静音" in tray._icon.title
    tray.stop()
