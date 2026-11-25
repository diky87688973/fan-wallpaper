"""配置读写。"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_DIR = str(Path.home() / "Pictures" / "壁纸")
ORDERS = ("sequential", "random")
INTERVAL_MIN = 1
INTERVAL_MAX = 1440


def parse_minutes(raw: object, fallback: int) -> int:
    """把界面输入收敛为合法分钟数；非法输入退回 fallback。"""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    return max(INTERVAL_MIN, min(INTERVAL_MAX, value))


@dataclass(frozen=True)
class Config:
    image_dir: str = DEFAULT_DIR
    interval_minutes: int = 5
    order: str = "sequential"
    allow_video: bool = True
    muted: bool = True

    def normalized(self) -> Config:
        return replace(
            self,
            image_dir=(self.image_dir or "").strip().strip('"') or DEFAULT_DIR,
            interval_minutes=parse_minutes(self.interval_minutes, 5),
            order=self.order if self.order in ORDERS else "sequential",
            allow_video=bool(self.allow_video),
            muted=bool(self.muted),
        )

    @property
    def interval_seconds(self) -> int:
        return self.interval_minutes * 60


def load(path: Path = CONFIG_PATH,
         on_error: Callable[[str], None] | None = None) -> Config:
    report = on_error or (lambda message: None)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config()
    except OSError as exc:
        report(f"配置文件读取失败（{path}）：{exc}")
        return Config()
    try:
        raw = json.loads(text)
    except ValueError as exc:
        report(f"配置文件不是合法 JSON（{path}）：{exc}")
        return Config()
    if not isinstance(raw, dict):
        report(f"配置文件顶层不是对象（{path}），已按默认值处理")
        return Config()
    fields = Config.__dataclass_fields__
    return Config(**{k: v for k, v in raw.items() if k in fields}).normalized()


def save(config: Config, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(config.normalized()), ensure_ascii=False, indent=2)
    # 先写同目录临时文件再原子替换：写到一半失败也不会留下截断的 config.json
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(payload, encoding="utf-8")
    os.replace(temp, path)
