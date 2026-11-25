"""配置取值收敛与读写落盘。"""

from __future__ import annotations

import json

import pytest

from wallpaper import config as config_module
from wallpaper.config import Config, parse_minutes


@pytest.mark.parametrize(
    ("raw", "fallback", "expected"),
    [
        ("7", 5, 7),
        (12, 5, 12),
        ("abc", 5, 5),
        ("", 5, 5),
        (None, 5, 5),
        ("0", 5, 1),
        ("-3", 5, 1),
        ("99999", 5, 1440),
        ("  9  ", 5, 9),
    ],
)
def test_parse_minutes(raw, fallback, expected):
    assert parse_minutes(raw, fallback) == expected


def test_normalized_fills_defaults_and_clamps():
    cleaned = Config(image_dir="   ", interval_minutes="abc", order="weird").normalized()
    assert cleaned.image_dir == config_module.DEFAULT_DIR
    assert cleaned.interval_minutes == 5
    assert cleaned.order == "sequential"


def test_normalized_strips_wrapping_quotes():
    assert Config(image_dir=' "D:/pics" ').normalized().image_dir == "D:/pics"


def test_load_missing_file_returns_defaults_without_report(tmp_path):
    messages = []
    loaded = config_module.load(tmp_path / "none.json", on_error=messages.append)
    assert loaded == Config()
    assert messages == []


def test_load_broken_json_reports_path_and_falls_back(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{oops", encoding="utf-8")
    messages = []
    assert config_module.load(path, on_error=messages.append) == Config()
    assert len(messages) == 1
    assert str(path) in messages[0]


def test_load_non_object_reports_and_falls_back(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2]", encoding="utf-8")
    messages = []
    assert config_module.load(path, on_error=messages.append) == Config()
    assert len(messages) == 1


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "extra.json"
    path.write_text(json.dumps({"interval_minutes": 8, "legacy": "x"}), encoding="utf-8")
    assert config_module.load(path).interval_minutes == 8


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "cfg.json"
    original = Config(image_dir="D:/pics", interval_minutes=3, order="random",
                      allow_video=False, muted=False)
    config_module.save(original, path)
    assert config_module.load(path) == original


def test_save_leaves_no_temp_file(tmp_path):
    path = tmp_path / "cfg.json"
    config_module.save(Config(), path)
    assert [p.name for p in tmp_path.iterdir()] == ["cfg.json"]
