"""素材枚举与类型判定，只读文件名，不解码内容。"""

from __future__ import annotations

from pathlib import Path

IMAGE_EXT = frozenset(
    {".jpg", ".jpeg", ".jfif", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
)
VIDEO_EXT = frozenset({".mp4", ".webm", ".mov", ".mkv", ".avi"})


def kind_of(path: Path) -> str:
    return "video" if path.suffix.lower() in VIDEO_EXT else "image"


def _list(directory: str, extensions: frozenset[str]) -> list[Path]:
    if not directory:
        return []
    root = Path(directory)
    try:
        if not root.is_dir():
            return []
        entries = list(root.iterdir())
    except OSError:
        return []
    picked = []
    for entry in entries:
        if entry.suffix.lower() not in extensions:
            continue
        try:
            if entry.is_file():
                picked.append(entry)
        except OSError:
            continue
    return sorted(picked, key=lambda item: item.name.lower())


def list_images(directory: str) -> list[Path]:
    return _list(directory, IMAGE_EXT)


def list_media(directory: str) -> list[Path]:
    return _list(directory, IMAGE_EXT | VIDEO_EXT)
