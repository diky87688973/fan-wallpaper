"""显示进程里可独立验证的片段：回环服务的错误处理策略。

客户端加载完素材就断开是常态，这类异常不能刷屏；
真正的故障仍必须打到 stderr，否则又回到"看不见失败原因"。
"""

from __future__ import annotations

import contextlib
import io

from wallpaper.wallview import QuietServer


def _handle(error: BaseException) -> str:
    server = QuietServer.__new__(QuietServer)
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        try:
            raise error
        except type(error):
            server.handle_error(None, ("127.0.0.1", 0))
    return buffer.getvalue()


def test_disconnect_errors_are_silenced():
    for error in (ConnectionAbortedError(10053, "连接被中止"),
                  ConnectionResetError(10054, "连接被重置"),
                  BrokenPipeError(32, "管道断开")):
        assert _handle(error) == ""


def test_other_errors_are_still_reported():
    output = _handle(RuntimeError("真的出错了"))
    assert "RuntimeError" in output
    assert "真的出错了" in output
