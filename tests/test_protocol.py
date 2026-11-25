"""跨进程协议：常量值即线上格式，两端必须引用同一份定义。"""

from __future__ import annotations

import json
from pathlib import Path

from wallpaper import protocol, wallview
from wallpaper.backend import WallpaperBackend


def test_values_are_the_wire_contract():
    assert protocol.CMD == "cmd"
    assert protocol.EVT == "evt"
    assert protocol.FIELD_PATH == "path"
    assert protocol.FIELD_MUTED == "muted"
    assert protocol.FIELD_DETAIL == "detail"
    assert protocol.CMD_QUIT == "quit"
    assert protocol.EVT_READY == "ready"


def test_forward_events_skip_internal_ones():
    for internal in (protocol.EVT_HANDLE, protocol.EVT_PAGE_READY, protocol.EVT_READY):
        assert internal not in protocol.FORWARD_EVENTS
    for forwarded in (protocol.EVT_LOADED, protocol.EVT_ENDED, protocol.EVT_LOAD_ERROR):
        assert forwarded in protocol.FORWARD_EVENTS


def test_backend_command_uses_protocol_keys(monkeypatch):
    backend = WallpaperBackend(lambda name, payload: None)
    sent = []
    monkeypatch.setattr(backend, "_send", sent.append)
    backend.show("video", Path("x.mp4"), muted=True)
    backend.set_muted(False)
    assert set(sent[0]) == {protocol.CMD, protocol.FIELD_KIND,
                            protocol.FIELD_PATH, protocol.FIELD_MUTED}
    assert sent[0][protocol.CMD] == protocol.CMD_SHOW
    assert set(sent[1]) == {protocol.CMD, protocol.FIELD_VALUE}


def test_wallview_emit_uses_protocol_keys(capsys):
    wallview.emit(protocol.EVT_LOADED, "a.jpg", "image")
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload == {
        protocol.EVT: protocol.EVT_LOADED,
        protocol.FIELD_PATH: "a.jpg",
        protocol.FIELD_DETAIL: "image",
    }
