"""装配层的单实例守卫。

两个实例会互相 cleanup_stale 对方的显示窗口，所以启动前必须先拿到命名互斥量。
"""

from __future__ import annotations

import uuid

import wallpaper_app


def _name() -> str:
    return f"Local\\FanWallpaper-test-{uuid.uuid4()}"


def test_second_acquire_is_rejected():
    name = _name()
    assert wallpaper_app._acquire_single_instance(name) is True
    assert wallpaper_app._acquire_single_instance(name) is False


def test_distinct_names_do_not_collide():
    assert wallpaper_app._acquire_single_instance(_name()) is True
    assert wallpaper_app._acquire_single_instance(_name()) is True
