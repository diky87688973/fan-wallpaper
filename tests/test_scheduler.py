"""轮播调度：顺序、随机、控制信号与暂停兜底。"""

from __future__ import annotations

import itertools
import time
from pathlib import Path

import pytest

from wallpaper import scheduler as scheduler_module
from wallpaper.scheduler import RotationScheduler


def wait_for(predicate, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def items() -> list[Path]:
    return [Path("1.jpg"), Path("2.jpg"), Path("3.jpg")]


def test_sequential_rotation(items):
    seen = []
    sch = RotationScheduler(lambda: items, lambda p: seen.append(p.name), lambda m: None)
    sch.configure(3600, "sequential")
    try:
        sch.start()
        assert wait_for(lambda: len(seen) >= 1)
        sch.next_now()
        assert wait_for(lambda: len(seen) >= 2)
        assert seen[:2] == ["1.jpg", "2.jpg"]
    finally:
        sch.stop()


def test_stop_terminates_thread(items):
    sch = RotationScheduler(lambda: items, lambda p: None, lambda m: None)
    sch.configure(3600, "sequential")
    sch.start()
    assert wait_for(lambda: sch.running)
    sch.stop()
    assert not sch.running
    assert sch._thread is None


def test_start_is_idempotent(items):
    sch = RotationScheduler(lambda: items, lambda p: None, lambda m: None)
    sch.configure(3600, "sequential")
    try:
        sch.start()
        first = sch._thread
        sch.start()
        assert sch._thread is first
    finally:
        sch.stop()


def test_provider_error_reports_and_keeps_running():
    errors = []

    def broken():
        raise OSError("磁盘掉了")

    sch = RotationScheduler(broken, lambda p: None, errors.append)
    sch.configure(3600, "sequential")
    try:
        sch.start()
        assert wait_for(lambda: errors)
        assert "扫描目录失败" in errors[0]
        assert sch.running
    finally:
        sch.stop()


def test_pause_timeout_resumes_by_itself(items, monkeypatch):
    monkeypatch.setattr(scheduler_module, "PAUSED_TIMEOUT_SECONDS", 0.2)
    seen = []
    sch = RotationScheduler(lambda: items, lambda p: seen.append(p.name), lambda m: None)
    sch.configure(3600, "sequential")
    try:
        sch.start()
        assert wait_for(lambda: len(seen) >= 1)
        sch.pause()
        assert wait_for(lambda: len(seen) >= 2)
        assert not sch._paused
    finally:
        sch.stop()


def test_random_never_repeats_consecutively():
    pool = [Path(f"{i}.jpg") for i in range(5)]
    sch = RotationScheduler(lambda: pool, lambda p: None, lambda m: None)
    sch.configure(1, "random")
    seen = [sch._select().name for _ in range(30)]
    assert all(a != b for a, b in itertools.pairwise(seen))


def test_empty_provider_does_not_fire_tick():
    seen = []
    sch = RotationScheduler(lambda: [], lambda p: seen.append(p.name), lambda m: None)
    sch.configure(3600, "sequential")
    try:
        sch.start()
        time.sleep(0.3)
        assert seen == []
    finally:
        sch.stop()
