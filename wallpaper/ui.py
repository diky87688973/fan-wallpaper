"""界面：目录、间隔、顺序、是否含视频、开始停止。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

from .config import Config, parse_minutes


class WallpaperUI:
    def __init__(self, root: tk.Tk, config: Config) -> None:
        self.root = root
        self.root.title("壁纸轮播")
        self.root.geometry("640x460")
        self.root.minsize(520, 380)
        self._last_interval = config.interval_minutes

        self.on_start = lambda: None
        self.on_stop = lambda: None
        self.on_next = lambda: None
        self.on_config_change = lambda: None

        self.dir_var = tk.StringVar(value=config.image_dir)
        self.interval_var = tk.StringVar(value=str(config.interval_minutes))
        self.order_var = tk.StringVar(value=config.order)
        self.video_var = tk.BooleanVar(value=config.allow_video)
        self.mute_var = tk.BooleanVar(value=config.muted)
        self.count_var = tk.StringVar(value="共 0 项")
        self.status_var = tk.StringVar(value="已停止")

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        row = ttk.Frame(frame)
        row.pack(fill=tk.X)
        ttk.Label(row, text="素材目录").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.dir_var).pack(side=tk.LEFT, fill=tk.X,
                                                       expand=True, padx=6)
        ttk.Button(row, text="浏览", command=self._pick_dir).pack(side=tk.LEFT)

        options = ttk.Frame(frame)
        options.pack(fill=tk.X, pady=8)
        ttk.Label(options, text="间隔(分钟)").pack(side=tk.LEFT)
        ttk.Spinbox(options, from_=1, to=1440, width=6,
                    textvariable=self.interval_var).pack(side=tk.LEFT, padx=6)
        ttk.Label(options, text="顺序").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Combobox(options, width=8, state="readonly", textvariable=self.order_var,
                     values=("sequential", "random")).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(options, text="包含视频", variable=self.video_var).pack(side=tk.LEFT,
                                                                           padx=10)
        ttk.Checkbutton(options, text="视频静音", variable=self.mute_var).pack(side=tk.LEFT)
        ttk.Label(options, textvariable=self.count_var).pack(side=tk.RIGHT)

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=4)
        # 回调要用 lambda 延迟到点击时再取属性，否则装配层后赋值不会生效
        self.start_button = ttk.Button(buttons, text="开始轮播",
                                       command=lambda: self.on_start())
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(buttons, text="停止",
                                      command=lambda: self.on_stop())
        self.stop_button.pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="立即换一张",
                   command=lambda: self.on_next()).pack(side=tk.LEFT)
        ttk.Label(buttons, textvariable=self.status_var).pack(side=tk.RIGHT)

        self.log_text = scrolledtext.ScrolledText(frame, height=14, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        for var in (self.dir_var, self.interval_var, self.order_var, self.video_var,
                    self.mute_var):
            var.trace_add("write", lambda *_: self.on_config_change())

        # 初始未轮播：开始可用、停止置灰
        self.set_running(False)

    def _pick_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.dir_var.get() or None)
        if chosen:
            self.dir_var.set(chosen)

    def read_config(self) -> Config:
        interval = parse_minutes(self.interval_var.get(), self._last_interval)
        self._last_interval = interval
        return Config(
            image_dir=self.dir_var.get(),
            interval_minutes=interval,
            order=self.order_var.get(),
            allow_video=bool(self.video_var.get()),
            muted=bool(self.mute_var.get()),
        ).normalized()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def hide(self) -> None:
        self.root.withdraw()

    def set_icon(self, icon) -> None:
        """icon 是 PIL Image；tk 的 iconphoto 只认 PhotoImage，必须转换并保有引用。"""
        try:
            from PIL import ImageTk

            self._icon_photo = ImageTk.PhotoImage(icon)
            self.root.iconphoto(True, self._icon_photo)
        except Exception as exc:
            self.log(f"图标加载失败：{type(exc).__name__}: {exc}")

    def log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def set_count(self, total: int) -> None:
        self.count_var.set(f"共 {total} 项")

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def set_running(self, running: bool) -> None:
        self.start_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)
