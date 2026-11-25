"""轮播调度：到点才向 provider 要一次目录内容，不缓存列表。"""

from __future__ import annotations

import random
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

# 视频靠 ended 事件解除暂停；事件丢失时以这个上限兜底，避免轮播永久停摆
PAUSED_TIMEOUT_SECONDS = 600.0


class RotationScheduler:
    def __init__(
        self,
        provider: Callable[[], Sequence[Path]],
        on_tick: Callable[[Path], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._provider = provider
        self._on_tick = on_tick
        self._on_error = on_error or (lambda message: None)
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self._interval = 300
        self._random = False
        self._index = -1
        self._last = ""
        self._pending = False
        self._paused = False
        self._stopped = True

    def configure(self, interval_seconds: int, order: str) -> None:
        with self._cond:
            self._interval = max(1, int(interval_seconds))
            self._random = order == "random"
            self._cond.notify()

    def start(self) -> None:
        with self._cond:
            if not self._stopped:
                return
            self._stopped = False
            self._thread = threading.Thread(target=self._run, name="rotation", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._cond:
            if self._stopped:
                return
            self._stopped = True
            self._cond.notify()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def next_now(self) -> None:
        with self._cond:
            self._pending = True
            self._cond.notify()

    def pause(self) -> None:
        with self._cond:
            if self._paused:
                return
            self._paused = True
            self._cond.notify()

    def resume(self) -> None:
        with self._cond:
            if not self._paused:
                return
            self._paused = False
            self._cond.notify()

    @property
    def running(self) -> bool:
        with self._cond:
            return not self._stopped

    def _select(self) -> Path | None:
        try:
            items = list(self._provider())
        # provider 由装配层提供，任何异常都不应打死调度线程；已交 on_error 留痕
        except Exception as exc:
            self._on_error(f"扫描目录失败：{exc}")
            return None
        if not items:
            return None
        if self._random:
            pool = [item for item in items if str(item) != self._last] or items
            choice = random.choice(pool)
        else:
            self._index = (self._index + 1) % len(items)
            choice = items[self._index]
        self._last = str(choice)
        return choice

    def _wait_next(self, interval: int) -> bool:
        while True:
            if self._stopped:
                return False
            if self._pending:
                self._pending = False
                return True
            if self._paused:
                # 超时未收到 resume 视为播放已终止，主动解除暂停继续轮播
                if not self._cond.wait(timeout=PAUSED_TIMEOUT_SECONDS):
                    self._paused = False
                    return True
                # 暂停解除就立即切下一张：视频播完靠这个信号驱动
                if not self._paused:
                    return True
                continue
            if self._cond.wait(timeout=interval):
                interval = self._interval
                continue
            return not self._stopped

    def _run(self) -> None:
        while True:
            with self._cond:
                if self._stopped:
                    return
                item = self._select()
                interval = self._interval
            if item is not None:
                try:
                    self._on_tick(item)
                # 单张素材失败不能终止轮播；已交 on_error 留痕
                except Exception as exc:
                    self._on_error(f"{item.name}：{exc}")
            with self._cond:
                if not self._wait_next(interval):
                    return
