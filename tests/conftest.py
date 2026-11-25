"""测试共用：把项目根加入导入路径，并提供素材目录夹具。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    for name in ("b.JPG", "a.png", "c.mp4", "d.txt", "e.WebM", "f.bmp"):
        (tmp_path / name).write_bytes(b"x")
    return tmp_path
