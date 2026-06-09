"""Tests for AppConfig persistence."""
from __future__ import annotations

from pathlib import Path

import pytest

from apple_music_tui import config as config_mod
from apple_music_tui.config import AppConfig, load_config


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config module (and the pydantic json source) at a temp file."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)
    monkeypatch.setitem(AppConfig.model_config, "json_file", str(cfg_file))
    return cfg_file


class TestLoadConfig:
    def test_missing_file_uses_defaults(self, config_file: Path) -> None:
        config = load_config()
        assert config.theme == "textual-dark"

    def test_corrupt_json_falls_back_to_defaults(self, config_file: Path) -> None:
        config_file.write_text("{not valid json", encoding="utf-8")
        config = load_config()
        assert config.theme == "textual-dark"

    def test_save_load_roundtrip(self, config_file: Path) -> None:
        config = load_config()
        config.theme = "amber-terminal"
        config.save()
        assert config_file.exists()
        assert load_config().theme == "amber-terminal"
