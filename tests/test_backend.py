"""遮盖层后端：进程起停、管道协议与残留清理。

显示进程用替身代替，不启动真实 WebView2；涉及 Win32 的句柄枚举与注册表读取
一律替换为可观察的桩，验证的是本模块自身的分派与失败处理。
"""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from wallpaper import backend as backend_module
from wallpaper.backend import WallpaperBackend


class FakeProcess:
    def __init__(self, lines=(), pid=4321):
        self.pid = pid
        self.stdin = io.StringIO()
        self.stdout = iter(list(lines))
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def kill(self):
        self.returncode = -9


class FakeUser32:
    def __init__(self):
        self.posted = []

    def PostMessageW(self, hwnd, message, wparam, lparam):
        self.posted.append(hwnd)
        return 1


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(backend_module, "cleanup_stale", lambda: 0)
    monkeypatch.setattr(backend_module, "repaint_desktop", lambda: None)
    monkeypatch.setattr(backend_module, "READY_TIMEOUT_SECONDS", 0.5)
    return monkeypatch


def test_own_pids_parses_wmic_output(monkeypatch):
    output = ("CommandLine  ProcessId\n"
              "python.exe -m wallpaper.wallview  777\n"
              "unrelated  888\n")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=output))
    assert backend_module._own_pids() == {777}


def test_own_pids_returns_empty_when_wmic_missing(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no wmic")

    monkeypatch.setattr(subprocess, "run", boom)
    assert backend_module._own_pids() == set()


def test_cleanup_stale_closes_only_own_windows(monkeypatch):
    fake = FakeUser32()
    monkeypatch.setattr(backend_module, "_user32", fake)
    monkeypatch.setattr(backend_module, "find_wallpaper_layer", lambda: 100)
    monkeypatch.setattr(backend_module, "_own_pids", lambda: {42})
    monkeypatch.setattr(backend_module, "_child_pids", lambda layer: [(1, 42), (2, 99)])
    monkeypatch.setattr(backend_module, "repaint_desktop", lambda: None)
    assert backend_module.cleanup_stale() == 1
    assert fake.posted == [1]


def test_cleanup_stale_without_layer(monkeypatch):
    monkeypatch.setattr(backend_module, "find_wallpaper_layer", lambda: 0)
    assert backend_module.cleanup_stale() == 0


def test_cleanup_stale_without_matching_process(monkeypatch):
    monkeypatch.setattr(backend_module, "find_wallpaper_layer", lambda: 100)
    monkeypatch.setattr(backend_module, "_own_pids", lambda: set())
    assert backend_module.cleanup_stale() == 0


def test_repaint_desktop_returns_when_registry_unreadable(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("missing key")

    monkeypatch.setattr(backend_module.winreg, "OpenKey", boom)
    assert backend_module.repaint_desktop() is None


def test_alive_tracks_process_state(isolated):
    backend = WallpaperBackend(lambda name, payload: None)
    assert backend.alive is False
    backend._process = FakeProcess()
    assert backend.alive is True
    backend._process.returncode = 0
    assert backend.alive is False


def test_send_requires_started_process():
    backend = WallpaperBackend(lambda name, payload: None)
    with pytest.raises(RuntimeError, match="未启动"):
        backend._send({"cmd": "quit"})


def test_send_writes_single_json_line(isolated):
    backend = WallpaperBackend(lambda name, payload: None)
    process = FakeProcess()
    backend._process = process
    backend._send({"cmd": "show", "path": "a.jpg"})
    written = process.stdin.getvalue()
    assert json.loads(written) == {"cmd": "show", "path": "a.jpg"}
    assert written.endswith("\n")


def test_start_completes_ready_handshake(isolated, monkeypatch):
    process = FakeProcess(['{"evt":"ready"}'])
    monkeypatch.setattr(backend_module.subprocess, "Popen", lambda *a, **k: process)
    backend = WallpaperBackend(lambda name, payload: None)
    backend.start()
    assert backend.alive is True
    assert backend._process is process


def test_start_raises_when_ready_never_arrives(isolated, monkeypatch):
    monkeypatch.setattr(backend_module.subprocess, "Popen", lambda *a, **k: FakeProcess())
    backend = WallpaperBackend(lambda name, payload: None)
    with pytest.raises(RuntimeError, match="未就绪"):
        backend.start()


def test_start_is_idempotent(isolated, monkeypatch):
    process = FakeProcess(['{"evt":"ready"}'])
    spawns = []

    def fake_popen(*args, **kwargs):
        spawns.append(1)
        return process

    monkeypatch.setattr(backend_module.subprocess, "Popen", fake_popen)
    backend = WallpaperBackend(lambda name, payload: None)
    backend.start()
    backend.start()
    assert len(spawns) == 1


def test_stop_sends_quit_and_clears_process(isolated, monkeypatch):
    process = FakeProcess(['{"evt":"ready"}'])
    monkeypatch.setattr(backend_module.subprocess, "Popen", lambda *a, **k: process)
    backend = WallpaperBackend(lambda name, payload: None)
    backend.start()
    backend.stop()
    assert backend._process is None
    first = json.loads(process.stdin.getvalue().splitlines()[0])
    assert first == {"cmd": "quit"}


def test_stop_without_process_is_noop(isolated):
    backend = WallpaperBackend(lambda name, payload: None)
    backend.stop()
    assert backend._process is None


def test_read_loop_forwards_known_events_and_drops_noise():
    events = []
    backend = WallpaperBackend(lambda name, payload: events.append((name, payload)))
    backend._process = FakeProcess([
        '{"evt":"loaded","path":"a.jpg"}',
        "not json at all",
        '{"evt":"unknown_internal"}',
        '{"evt":"attached","detail":"boom"}',
        '{"evt":"load_error","path":"b.jpg"}',
        '{"evt":"ready"}',
    ])
    backend._read_loop()
    assert ("loaded", "a.jpg") in events
    assert ("error", "挂载桌面失败：boom") in events
    assert ("load_error", "b.jpg") in events
    assert backend._ready.is_set()
    forwarded = [name for name, _ in events]
    assert "unknown_internal" not in forwarded


def test_show_and_set_muted_use_send(isolated, monkeypatch):
    backend = WallpaperBackend(lambda name, payload: None)
    sent = []
    monkeypatch.setattr(backend, "_send", sent.append)
    backend.show("video", Path("x.mp4"), muted=False)
    backend.set_muted(True)
    assert sent[0] == {"cmd": "show", "kind": "video", "path": "x.mp4", "muted": False}
    assert sent[1] == {"cmd": "mute", "value": True}


def test_read_loop_reports_non_protocol_lines_as_stderr():
    events = []
    backend = WallpaperBackend(lambda name, payload: events.append((name, payload)))
    backend._process = FakeProcess([
        "libpng warning: iCCP: cHRM chunk does not match sRGB",
        "[1, 2]",
        '{"evt":"ready"}',
    ])
    backend._read_loop()
    noisy = [payload for name, payload in events if name == "stderr"]
    assert "libpng warning: iCCP: cHRM chunk does not match sRGB" in noisy
    assert "[1, 2]" in noisy
    assert backend._ready.is_set()
