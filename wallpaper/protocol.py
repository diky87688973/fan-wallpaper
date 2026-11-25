"""主控与显示进程之间的行协议。

两端只允许引用这里的常量，不得各自写字面量：
键名写错不会报错，只会让切换静默失效。
"""

from __future__ import annotations

# 主控 -> 显示进程
CMD = "cmd"
CMD_SHOW = "show"
CMD_MUTE = "mute"
CMD_QUIT = "quit"

FIELD_KIND = "kind"
FIELD_PATH = "path"
FIELD_MUTED = "muted"
FIELD_VALUE = "value"
FIELD_DETAIL = "detail"

KIND_IMAGE = "image"
KIND_VIDEO = "video"

# 显示进程 -> 主控
EVT = "evt"
EVT_READY = "ready"
EVT_ATTACHED = "attached"
EVT_HANDLE = "handle"
EVT_PAGE_READY = "page_ready"
EVT_PAGE_NOT_READY = "page_not_ready"
EVT_LOADED = "loaded"
EVT_LOAD_ERROR = "load_error"
EVT_ENDED = "ended"
EVT_SCRIPT_ERROR = "script_error"
EVT_SERVER_ERROR = "server_error"

# 主控内部事件：显示进程写往 stdout 的非协议行（第三方库警告、崩溃堆栈）
EVT_STDERR = "stderr"

# 主控需要转给界面层的显示进程事件
FORWARD_EVENTS = frozenset({
    EVT_LOADED,
    EVT_LOAD_ERROR,
    EVT_ENDED,
    EVT_PAGE_NOT_READY,
    EVT_SCRIPT_ERROR,
    EVT_SERVER_ERROR,
})
