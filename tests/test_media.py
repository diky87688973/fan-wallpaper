"""素材枚举与类型判定。"""

from __future__ import annotations

from pathlib import Path

from wallpaper import media


def test_list_images_filters_extensions_and_sorts(media_dir):
    assert [p.name for p in media.list_images(str(media_dir))] == ["a.png", "b.JPG", "f.bmp"]


def test_list_media_includes_videos(media_dir):
    listed = [p.name for p in media.list_media(str(media_dir))]
    assert listed == ["a.png", "b.JPG", "c.mp4", "e.WebM", "f.bmp"]


def test_empty_and_missing_directory_return_empty():
    assert media.list_images("") == []
    assert media.list_images("Z:/definitely-missing-dir") == []


def test_kind_of_by_suffix():
    assert media.kind_of(Path("x.MP4")) == "video"
    assert media.kind_of(Path("x.png")) == "image"
    assert media.kind_of(Path("x.unknown")) == "image"


def test_directory_with_media_suffix_is_skipped(tmp_path):
    (tmp_path / "fake.png").mkdir()
    assert media.list_images(str(tmp_path)) == []
